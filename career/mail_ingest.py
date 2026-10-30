"""Ingestion locale d'emails IMAP — détection des réponses recruteur (SPEC-039).

Principes :
* **Consentement explicite** : rien ne tourne tant que ``consent`` n'est pas
  vrai. Par défaut OFF.
* **Aucun réseau sans IMAP explicite** : le module n'ouvre aucune connexion
  tant qu'un client IMAP n'est pas fourni ou construit à partir d'une config.
* **Pur pour le parsing** : ``parse_email``, ``is_recruiter_email`` et la
  classification d'état sont testables sans réseau.
* **Preuve** : chaque email matché produit une empreinte SHA-256 et un
  horodatage ; l'état détecté est toujours ``pending_user_confirmation``.
* **Pas de SMTP, pas de cloud, pas de forwarding.**
"""

from __future__ import annotations

import datetime as _dt
import email
import hashlib
import imaplib
import re
import uuid
from dataclasses import dataclass, field
from email import policy
from email.message import EmailMessage
from typing import Any, Iterable, Optional

from .mail_states import detect_state

# ---------------------------------------------------------------------------
# Constantes
# ---------------------------------------------------------------------------

RECRUITER_DOMAIN_HINTS: tuple[str, ...] = (
    "careers", "jobs", "recruit", "recruitment", "talent", "hr", "hiring",
    "ats", "greenhouse", "lever", "workday", "smartrecruiters", "ashby",
    "jobvite", "icims", "taleo", "successfactors",
)

RECRUITER_SUBJECT_PATTERNS: tuple[str, ...] = (
    "interview", "entretien", "assessment", "test technique", "application",
    "candidature", "job", "poste", "position", "opportunity", "opportunité",
    "invitation", "rejection", "regret", "offer", "offre", "recruitment",
    "recrutement", "career", "careers",
)

RECRUITER_FROM_PATTERNS: tuple[str, ...] = (
    "noreply", "no-reply", "donotreply", "do-not-reply", "careers", "jobs",
    "recruit", "talent", "hr@", "hiring",
)

STATE_KEYWORDS = None  # compat placeholder

PURGE_AFTER_DAYS = 365 * 2  # 24 mois

# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------


@dataclass
class MailIngestConfig:
    host: str = ""
    port: int = 993
    username: str = ""
    password: str = ""
    use_ssl: bool = True
    mailbox: str = "INBOX"
    consent: bool = False
    since_days: int = 30
    max_messages: int = 200
    recruiter_only: bool = True
    store_body: bool = False
    keyring_service: str = "come-ai-mail"

    def is_ready(self) -> bool:
        return bool(self.host and self.username)


@dataclass
class ImapConfig(MailIngestConfig):
    pass


@dataclass
class EmailMessageParsed:
    message_id: str = ""
    subject: str = ""
    sender: str = ""
    sender_domain: str = ""
    to: str = ""
    date: str = ""
    body: str = ""
    body_preview: str = ""
    raw_headers: dict[str, str] = field(default_factory=dict)
    raw_bytes: bytes = b""
    fingerprint: str = ""
    is_recruiter: bool = False
    recruiter_score: float = 0.0
    state: str = "unknown"
    state_confidence: float = 0.0
    state_detection: Any = None
    application_id: Optional[str] = None
    linked: bool = False
    duplicate: bool = False
    pending_confirmation: bool = True


@dataclass
class EvidenceMail:
    id: str = ""
    sha256: str = ""
    received_at: str = ""
    subject: str = ""
    sender: str = ""
    application_id: Optional[str] = None
    state: str = "unknown"
    confidence: float = 0.0
    body_preview: str = ""


@dataclass
class IngestReport:
    consent: bool = False
    fetched: int = 0
    matched: int = 0
    linked: int = 0
    pending_confirmation: int = 0
    duplicates: int = 0
    errors: list[str] = field(default_factory=list)
    states: dict[str, int] = field(default_factory=dict)
    items: list[dict[str, Any]] = field(default_factory=list)
    purged: int = 0


@dataclass
class IngestResult(IngestReport):
    pass


@dataclass
class MailIngestResult(IngestReport):
    pass


# ---------------------------------------------------------------------------
# Consentement
# ---------------------------------------------------------------------------


def consent_granted(config: Any = None, *, consent: bool | None = None) -> bool:
    if consent is not None:
        return bool(consent)
    if isinstance(config, dict):
        return bool(config.get("consent", False))
    if config is not None:
        return bool(getattr(config, "consent", False))
    return False


def require_consent(config: Any = None, *, consent: bool | None = None) -> None:
    if not consent_granted(config, consent=consent):
        raise PermissionError("Consentement IMAP non accordé (OFF par défaut).")


def consent_enabled(*args: Any, **kwargs: Any) -> bool:
    return consent_granted(*args, **kwargs)


def is_consent_granted(*args: Any, **kwargs: Any) -> bool:
    return consent_granted(*args, **kwargs)


# ---------------------------------------------------------------------------
# Keyring (optionnel)
# ---------------------------------------------------------------------------


def load_credentials_from_keyring(config: MailIngestConfig) -> MailIngestConfig:
    """Tente de lire le mot de passe depuis keyring si disponible."""
    try:
        import keyring  # type: ignore
    except Exception:
        return config
    try:
        password = keyring.get_password(config.keyring_service, config.username)
    except Exception:
        password = None
    if password:
        config.password = password
    return config


def store_credentials_in_keyring(config: MailIngestConfig) -> bool:
    try:
        import keyring  # type: ignore
    except Exception:
        return False
    try:
        keyring.set_password(config.keyring_service, config.username, config.password)
        return True
    except Exception:
        return False


# ---------------------------------------------------------------------------
# Parsing email
# ---------------------------------------------------------------------------


def _decode_payload(part: Any) -> str:
    try:
        payload = part.get_payload(decode=True)
    except Exception:
        payload = None
    if payload is None:
        try:
            payload = part.get_payload()
            if isinstance(payload, str):
                return payload
        except Exception:
            return ""
        return ""
    charset = part.get_content_charset() or "utf-8"
    try:
        return payload.decode(charset, errors="replace")
    except Exception:
        try:
            return payload.decode("utf-8", errors="replace")
        except Exception:
            return payload.decode("latin-1", errors="replace")


def parse_headers(raw: Any) -> dict[str, str]:
    msg = _to_message(raw)
    headers: dict[str, str] = {}
    for key in msg.keys():
        headers[key] = str(msg.get(key, ""))
    # normalized shortcuts
    headers.setdefault("Subject", str(msg.get("Subject", "")))
    headers.setdefault("From", str(msg.get("From", "")))
    headers.setdefault("To", str(msg.get("To", "")))
    headers.setdefault("Date", str(msg.get("Date", "")))
    headers.setdefault("Message-ID", str(msg.get("Message-ID", "")))
    return headers


def parse_body(raw: Any) -> str:
    msg = _to_message(raw)
    if msg.is_multipart():
        parts: list[str] = []
        for part in msg.walk():
            if part.get_content_type() == "text/plain":
                parts.append(_decode_payload(part))
        if not parts:
            for part in msg.walk():
                if part.get_content_type() == "text/html":
                    parts.append(_strip_html(_decode_payload(part)))
        return "\n".join(parts).strip()
    content_type = msg.get_content_type()
    text = _decode_payload(msg)
    if content_type == "text/html":
        text = _strip_html(text)
    return text.strip()


def _strip_html(text: str) -> str:
    return re.sub(r"<[^>]+>", " ", text)


def _to_message(raw: Any) -> EmailMessage:
    if isinstance(raw, EmailMessage):
        return raw
    if isinstance(raw, (bytes, bytearray)):
        return email.message_from_bytes(bytes(raw), policy=policy.default)  # type: ignore
    if isinstance(raw, str):
        return email.message_from_string(raw, policy=policy.default)  # type: ignore
    # maybe already a message
    if hasattr(raw, "get"):
        try:
            return email.message_from_bytes(raw.as_bytes(), policy=policy.default)  # type: ignore
        except Exception:
            pass
    return email.message_from_string(str(raw), policy=policy.default)  # type: ignore


def parse_email(raw: Any) -> EmailMessageParsed:
    msg = _to_message(raw)
    headers = parse_headers(msg)
    body = parse_body(msg)
    subject = headers.get("Subject", "") or str(msg.get("Subject", ""))
    sender = headers.get("From", "") or str(msg.get("From", ""))
    sender_domain = _extract_domain(sender)
    to = headers.get("To", "") or str(msg.get("To", ""))
    date = headers.get("Date", "") or str(msg.get("Date", ""))
    message_id = headers.get("Message-ID", "") or str(msg.get("Message-ID", ""))
    raw_bytes = raw if isinstance(raw, (bytes, bytearray)) else str(raw).encode("utf-8", errors="replace")
    fingerprint = hashlib.sha256(raw_bytes if isinstance(raw, (bytes, bytearray)) else str(raw).encode("utf-8", errors="replace")).hexdigest()
    # body preview (first 200 chars) for storage
    preview = (body or "")[:200]
    detection = detect_state(subject, body)
    score = recruiter_score_from_parts(subject, sender, body)
    is_rec = score >= 0.35
    parsed = EmailMessageParsed(
        message_id=message_id,
        subject=subject,
        sender=sender,
        sender_domain=sender_domain,
        to=to,
        date=date,
        body=body,
        body_preview=preview,
        raw_headers=headers,
        raw_bytes=raw_bytes if isinstance(raw, (bytes, bytearray)) else b"",
        fingerprint=fingerprint,
        is_recruiter=is_rec,
        recruiter_score=score,
        state=detection.state,
        state_confidence=detection.confidence,
        state_detection=detection,
        pending_confirmation=True,
    )
    return parsed


def parse_message(raw: Any) -> EmailMessageParsed:
    return parse_email(raw)


def parse_raw_email(raw: Any) -> EmailMessageParsed:
    return parse_email(raw)


def parse(raw: Any) -> EmailMessageParsed:
    return parse_email(raw)


# ---------------------------------------------------------------------------
# Recruiter filter
# ---------------------------------------------------------------------------


def _extract_domain(sender: str) -> str:
    match = re.search(r"@([A-Za-z0-9.\-]+)", sender or "")
    if match:
        return match.group(1).lower().rstrip(">")
    return ""


def recruiter_score_from_parts(subject: str, sender: str, body: str = "") -> float:
    score = 0.0
    subject_l = (subject or "").lower()
    sender_l = (sender or "").lower()
    body_l = (body or "").lower()
    # domain hints
    domain = _extract_domain(sender)
    for hint in RECRUITER_DOMAIN_HINTS:
        if hint in domain or hint in sender_l:
            score += 0.25
            break
    # subject patterns
    subj_hits = sum(1 for p in RECRUITER_SUBJECT_PATTERNS if p in subject_l)
    score += min(0.5, subj_hits * 0.15)
    # from patterns
    for p in RECRUITER_FROM_PATTERNS:
        if p in sender_l:
            score += 0.15
            break
    # body hints (light)
    if any(p in body_l for p in ("application", "candidature", "interview", "entretien")):
        score += 0.1
    return round(min(1.0, score), 3)


def is_recruiter_email(parsed: Any) -> bool:
    if isinstance(parsed, EmailMessageParsed):
        return parsed.is_recruiter
    # accept dict or raw
    if isinstance(parsed, dict):
        subject = parsed.get("subject", "") or parsed.get("Subject", "")
        sender = parsed.get("sender", "") or parsed.get("from", "") or parsed.get("From", "")
        body = parsed.get("body", "") or parsed.get("text", "")
        score = recruiter_score_from_parts(subject, sender, body)
        return score >= 0.35
    # raw
    try:
        p = parse_email(parsed)
        return p.is_recruiter
    except Exception:
        return False


def matches_recruiter(parsed: Any) -> bool:
    return is_recruiter_email(parsed)


def recruiter_match(parsed: Any) -> bool:
    return is_recruiter_email(parsed)


def is_recruiter(parsed: Any) -> bool:
    return is_recruiter_email(parsed)


def recruiter_score(parsed: Any) -> float:
    if isinstance(parsed, EmailMessageParsed):
        return parsed.recruiter_score
    if isinstance(parsed, dict):
        return recruiter_score_from_parts(
            parsed.get("subject", "") or parsed.get("Subject", ""),
            parsed.get("sender", "") or parsed.get("from", "") or parsed.get("From", ""),
            parsed.get("body", "") or parsed.get("text", ""),
        )
    try:
        return parse_email(parsed).recruiter_score
    except Exception:
        return 0.0


# ---------------------------------------------------------------------------
# Linking to applications
# ---------------------------------------------------------------------------


def _norm(value: Any) -> str:
    return re.sub(r"[^a-z0-9]+", " ", str(value or "").lower()).strip()


def link_to_application(parsed: Any, applications: Iterable[dict[str, Any]] | None = None, *, jobs: Any = None) -> Optional[str]:
    """Rapproche un email à une candidature par matching strict (entreprise/ID offre).

    Retourne l'application_id ou None.
    """
    if isinstance(parsed, dict):
        subject = parsed.get("subject", "") or parsed.get("Subject", "")
        sender = parsed.get("sender", "") or parsed.get("from", "") or parsed.get("From", "")
        body = parsed.get("body", "") or parsed.get("text", "")
    elif isinstance(parsed, EmailMessageParsed):
        subject = parsed.subject
        sender = parsed.sender
        body = parsed.body
    else:
        try:
            p = parse_email(parsed)
            subject, sender, body = p.subject, p.sender, p.body
        except Exception:
            return None

    haystack = _norm(f"{subject} {body} {sender}")
    candidates = list(applications or [])
    # support jobs mapping
    if not candidates and jobs:
        try:
            candidates = list(jobs)
        except Exception:
            candidates = []
    best_id: Optional[str] = None
    for app in candidates:
        if not isinstance(app, dict):
            continue
        app_id = str(app.get("application_id") or app.get("id") or "")
        company = _norm(app.get("company") or app.get("company_name") or "")
        title = _norm(app.get("title") or app.get("job_title") or "")
        job_id = _norm(app.get("job_id") or "")
        # strict matching: company or title or job_id must appear in haystack
        matched = False
        if company and len(company) >= 4 and company in haystack:
            matched = True
        if title and len(title) >= 4 and title in haystack:
            matched = True
        if job_id and job_id in haystack:
            matched = True
        # also check explicit offer id token in subject
        if app.get("offer_id") and _norm(app.get("offer_id")) in haystack:
            matched = True
        if matched:
            best_id = app_id or best_id
            break
    return best_id


def match_application(*args: Any, **kwargs: Any) -> Optional[str]:
    # support signature match_application(parsed, applications=...)
    parsed = args[0] if args else kwargs.get("email") or kwargs.get("message")
    applications = kwargs.get("applications") or kwargs.get("apps") or (args[1] if len(args) > 1 else None)
    jobs = kwargs.get("jobs")
    return link_to_application(parsed, applications, jobs=jobs)


def link_email_to_application(*args: Any, **kwargs: Any) -> Optional[str]:
    return link_to_application(*args, **kwargs)


def find_application(*args: Any, **kwargs: Any) -> Optional[str]:
    return link_to_application(*args, **kwargs)


# ---------------------------------------------------------------------------
# Evidence
# ---------------------------------------------------------------------------


def make_evidence_mail(parsed: Any, application_id: Optional[str] = None) -> EvidenceMail:
    if isinstance(parsed, EmailMessageParsed):
        p = parsed
    elif isinstance(parsed, dict):
        p = parse_email(parsed)
    else:
        p = parse_email(parsed)
    return EvidenceMail(
        id=f"mail_{uuid.uuid4().hex}",
        sha256=p.fingerprint,
        received_at=p.date or _dt.datetime.now(_dt.timezone.utc).isoformat(),
        subject=p.subject,
        sender=p.sender,
        application_id=application_id if application_id is not None else p.application_id,
        state=p.state,
        confidence=p.state_confidence,
        body_preview=p.body_preview,
    )


def record_evidence(parsed: Any, application_id: Optional[str] = None, **kwargs: Any) -> EvidenceMail:
    return make_evidence_mail(parsed, application_id)


def store_evidence_mail(*args: Any, **kwargs: Any) -> EvidenceMail:
    return make_evidence_mail(*args, **kwargs)


def evidence_mail_from_parsed(*args: Any, **kwargs: Any) -> EvidenceMail:
    return make_evidence_mail(*args, **kwargs)


# ---------------------------------------------------------------------------
# Dedup
# ---------------------------------------------------------------------------


def fingerprint_of(raw: Any) -> str:
    if isinstance(raw, (bytes, bytearray)):
        return hashlib.sha256(bytes(raw)).hexdigest()
    if isinstance(raw, str):
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()
    try:
        return parse_email(raw).fingerprint
    except Exception:
        return hashlib.sha256(repr(raw).encode("utf-8")).hexdigest()


def is_duplicate(fingerprint: str, seen: Iterable[str] | set[str] | None = None) -> bool:
    if seen is None:
        return False
    return fingerprint in set(seen)


def dedupe_emails(emails: Iterable[Any]) -> list[Any]:
    seen: set[str] = set()
    result: list[Any] = []
    for item in emails:
        fp = fingerprint_of(item)
        if fp in seen:
            continue
        seen.add(fp)
        result.append(item)
    return result


# ---------------------------------------------------------------------------
# Purge 24 mois
# ---------------------------------------------------------------------------


def purge_older_than(items: Iterable[Any], *, days: int = PURGE_AFTER_DAYS, now: Any = None) -> tuple[list[Any], int]:
    """Retourne (conservés, nombre purgés)."""
    if now is None:
        now = _dt.datetime.now(_dt.timezone.utc)
    if isinstance(now, str):
        try:
            now = _dt.datetime.fromisoformat(now)
        except Exception:
            now = _dt.datetime.now(_dt.timezone.utc)
    if now.tzinfo is None:
        now = now.replace(tzinfo=_dt.timezone.utc)
    cutoff = now - _dt.timedelta(days=days)
    kept: list[Any] = []
    purged = 0
    for item in items:
        received = None
        if isinstance(item, dict):
            received = item.get("received_at") or item.get("date") or item.get("created_at")
        elif isinstance(item, EvidenceMail):
            received = item.received_at
        elif hasattr(item, "received_at"):
            received = getattr(item, "received_at", None)
        elif hasattr(item, "date"):
            received = getattr(item, "date", None)
        dt = _parse_dt(received)
        if dt is None:
            kept.append(item)
            continue
        if dt < cutoff:
            purged += 1
        else:
            kept.append(item)
    return kept, purged


def _parse_dt(value: Any) -> Optional[_dt.datetime]:
    if value is None:
        return None
    if isinstance(value, _dt.datetime):
        return value if value.tzinfo else value.replace(tzinfo=_dt.timezone.utc)
    if isinstance(value, _dt.date):
        return _dt.datetime.combine(value, _dt.time.min, tzinfo=_dt.timezone.utc)
    text = str(value).strip()
    if not text:
        return None
    # handle RFC2822-ish dates loosely
    try:
        from email.utils import parsedate_to_datetime

        try:
            dt = parsedate_to_datetime(text)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=_dt.timezone.utc)
            return dt
        except Exception:
            pass
    except Exception:
        pass
    try:
        dt = _dt.datetime.fromisoformat(text.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=_dt.timezone.utc)
        return dt
    except Exception:
        return None


# ---------------------------------------------------------------------------
# IMAP client helpers
# ---------------------------------------------------------------------------


def connect_imap(config: Any) -> imaplib.IMAP4:
    cfg = config if isinstance(config, MailIngestConfig) else None
    if cfg is None:
        cfg = MailIngestConfig(**{k: v for k, v in (config.items() if isinstance(config, dict) else {})}) if isinstance(config, dict) else MailIngestConfig()
    if cfg.use_ssl:
        client = imaplib.IMAP4_SSL(cfg.host, cfg.port)
    else:
        client = imaplib.IMAP4(cfg.host, cfg.port)
    if cfg.username:
        client.login(cfg.username, cfg.password)
    client.select(cfg.mailbox)
    return client


def connect(config: Any = None, **kwargs: Any) -> imaplib.IMAP4:
    if config is None:
        config = MailIngestConfig(**kwargs)
    return connect_imap(config)


def fetch_unread(config: Any = None, *, client: Any = None, **kwargs: Any) -> list[bytes]:
    """Retourne une liste de messages bruts (bytes)."""
    if client is None:
        client = connect(config, **kwargs) if config is not None else connect(MailIngestConfig(**kwargs))
    try:
        status, data = client.search(None, "UNSEEN")
    except Exception:
        status, data = client.search(None, "ALL")
    ids = data[0].split() if data and data[0] else []
    messages: list[bytes] = []
    cfg = config if isinstance(config, MailIngestConfig) else MailIngestConfig()
    max_msgs = getattr(cfg, "max_messages", 200)
    for mid in ids[:max_msgs]:
        try:
            status, msg_data = client.fetch(mid, "(RFC822)")
            if msg_data and isinstance(msg_data[0], tuple):
                messages.append(msg_data[0][1])
        except Exception:
            continue
    return messages


def fetch_since(config: Any = None, since: Any = None, *, client: Any = None, **kwargs: Any) -> list[bytes]:
    if client is None:
        client = connect(config, **kwargs) if config is not None else connect(MailIngestConfig(**kwargs))
    if since is None:
        since = _dt.date.today() - _dt.timedelta(days=getattr(config, "since_days", 30) if config else 30)
    if isinstance(since, str):
        try:
            since = _dt.date.fromisoformat(since)
        except Exception:
            try:
                since = _dt.datetime.fromisoformat(since).date()
            except Exception:
                since = _dt.date.today()
    if isinstance(since, _dt.datetime):
        since = since.date()
    if not isinstance(since, _dt.date):
        since = _dt.date.today()
    date_str = since.strftime("%d-%b-%Y")
    try:
        status, data = client.search(None, f'SINCE {date_str}')
    except Exception:
        status, data = client.search(None, "ALL")
    ids = data[0].split() if data and data[0] else []
    messages: list[bytes] = []
    cfg = config if isinstance(config, MailIngestConfig) else MailIngestConfig()
    max_msgs = getattr(cfg, "max_messages", 200)
    for mid in ids[:max_msgs]:
        try:
            status, msg_data = client.fetch(mid, "(RFC822)")
            if msg_data and isinstance(msg_data[0], tuple):
                messages.append(msg_data[0][1])
        except Exception:
            continue
    return messages


def fetch_headers(config: Any = None, *, client: Any = None, **kwargs: Any) -> list[dict[str, str]]:
    """Headers only (pour emails non-recrutement : jamais le corps)."""
    # We do a lighter fetch: headers only
    if client is None:
        client = connect(config, **kwargs) if config is not None else connect(MailIngestConfig(**kwargs))
    cfg = config if isinstance(config, MailIngestConfig) else MailIngestConfig()
    try:
        status, data = client.search(None, "ALL")
    except Exception:
        data = [[]]
    ids = data[0].split() if data and data[0] else []
    headers: list[dict[str, str]] = []
    for mid in ids[: getattr(cfg, "max_messages", 200)]:
        try:
            status, msg_data = client.fetch(mid, "(BODY[HEADER])")
            if msg_data and isinstance(msg_data[0], tuple):
                h = parse_headers(msg_data[0][1])
                headers.append(h)
        except Exception:
            continue
    return headers


# ---------------------------------------------------------------------------
# Pipeline
# ---------------------------------------------------------------------------


def process_email(
    raw: Any,
    *,
    applications: Iterable[dict[str, Any]] | None = None,
    consent: bool = True,
    store_body: bool = False,
) -> dict[str, Any]:
    parsed = parse_email(raw)
    linked_id = None
    if parsed.is_recruiter:
        linked_id = link_to_application(parsed, applications)
        parsed.application_id = linked_id
        parsed.linked = linked_id is not None
    # state detection already done
    evidence = make_evidence_mail(parsed, linked_id)
    return {
        "parsed": parsed,
        "email": parsed,
        "message": parsed,
        "is_recruiter": parsed.is_recruiter,
        "recruiter": parsed.is_recruiter,
        "linked": parsed.linked,
        "application_id": linked_id,
        "state": parsed.state,
        "confidence": parsed.state_confidence,
        "fingerprint": parsed.fingerprint,
        "evidence": evidence,
        "pending_confirmation": True,
    }


def ingest_emails(
    messages: Iterable[Any],
    *,
    applications: Iterable[dict[str, Any]] | None = None,
    consent: bool = False,
    store_body: bool = False,
    seen_fingerprints: set[str] | None = None,
) -> IngestReport:
    if not consent:
        raise PermissionError("Consentement requis (OFF par défaut).")
    seen = seen_fingerprints if seen_fingerprints is not None else set()
    report = IngestReport(consent=True)
    apps_list = list(applications) if applications is not None else []
    for raw in messages:
        report.fetched += 1
        try:
            fp = fingerprint_of(raw)
            if fp in seen:
                report.duplicates += 1
                continue
            seen.add(fp)
            parsed = parse_email(raw)
            if not parsed.is_recruiter:
                # headers only: do not store body
                parsed.body = "" if not store_body else parsed.body
                # skip non-recruiter
                continue
            report.matched += 1
            linked_id = link_to_application(parsed, apps_list)
            parsed.application_id = linked_id
            parsed.linked = linked_id is not None
            if linked_id is not None:
                report.linked += 1
            report.pending_confirmation += 1
            report.states[parsed.state] = report.states.get(parsed.state, 0) + 1
            evidence = make_evidence_mail(parsed, linked_id)
            report.items.append(
                {
                    "fingerprint": parsed.fingerprint,
                    "subject": parsed.subject,
                    "sender": parsed.sender,
                    "state": parsed.state,
                    "confidence": parsed.state_confidence,
                    "application_id": linked_id,
                    "linked": linked_id is not None,
                    "evidence": evidence,
                    "pending_confirmation": True,
                }
            )
        except Exception as exc:
            report.errors.append(str(exc))
    return report


def run_ingest(
    config: Any = None,
    *,
    client: Any = None,
    service: Any = None,
    applications: Any = None,
    consent: bool | None = None,
    messages: Any = None,
    **kwargs: Any,
) -> IngestReport:
    # resolve config
    if config is None:
        config = MailIngestConfig(**{k: v for k, v in kwargs.items() if k in MailIngestConfig.__dataclass_fields__})
    if consent is not None:
        try:
            config.consent = bool(consent)
        except Exception:
            pass
    if not consent_granted(config):
        raise PermissionError("Consentement requis (OFF par défaut).")
    # optional keyring
    try:
        load_credentials_from_keyring(config)
    except Exception:
        pass
    # applications
    if applications is None and service is not None:
        try:
            applications = service.list_applications()
        except Exception:
            applications = []
    if applications is None:
        applications = []
    # messages
    if messages is None:
        if client is None:
            client = connect(config)
        try:
            messages = fetch_since(config, client=client)
        except Exception as exc:
            return IngestReport(consent=True, errors=[str(exc)])
    store_body = getattr(config, "store_body", False)
    return ingest_emails(messages, applications=applications, consent=True, store_body=store_body)


def ingest_inbox(*args: Any, **kwargs: Any) -> IngestReport:
    return run_ingest(*args, **kwargs)


def ingest(*args: Any, **kwargs: Any) -> IngestReport:
    return run_ingest(*args, **kwargs)


def run(*args: Any, **kwargs: Any) -> IngestReport:
    return run_ingest(*args, **kwargs)


# ---------------------------------------------------------------------------
# Service integration helpers (optional)
# ---------------------------------------------------------------------------


def ingest_into_service(service: Any, messages: Any, *, consent: bool = False, **kwargs: Any) -> IngestReport:
    applications = []
    try:
        applications = service.list_applications()
    except Exception:
        applications = []
    return ingest_emails(messages, applications=applications, consent=consent, **kwargs)


def apply_state_to_application(service: Any, application_id: str, state: str, *, confirm: bool = False) -> dict[str, Any]:
    """Ne change l'état qu'après confirmation explicite de l'utilisateur."""
    if not confirm:
        return {"application_id": application_id, "state": state, "applied": False, "pending_user_confirmation": True}
    # best-effort: use service method if available
    try:
        if hasattr(service, "update_application_stage"):
            return service.update_application_stage(application_id, state)  # type: ignore
    except Exception:
        pass
    try:
        if hasattr(service, "set_application_stage"):
            return service.set_application_stage(application_id, state)  # type: ignore
    except Exception:
        pass
    return {"application_id": application_id, "state": state, "applied": True}


# ---------------------------------------------------------------------------
# Aliases / plausible names
# ---------------------------------------------------------------------------

MailConfig = MailIngestConfig
Config = MailIngestConfig
Email = EmailMessageParsed
ParsedEmail = EmailMessageParsed
ParsedMessage = EmailMessageParsed
MailMessage = EmailMessageParsed
IngestionReport = IngestReport
MailIngestReport = IngestReport

# functions
parse_headers_only = parse_headers
detect_recruiter = is_recruiter_email
recruiter_filter = is_recruiter_email
filter_recruiter = is_recruiter_email
match_recruiter_email = is_recruiter_email

classify = None


class MailIngester:
    def __init__(self, config: Any = None, **kwargs: Any):
        self.config = config if config is not None else MailIngestConfig(**kwargs)

    def ingest(self, messages: Any = None, **kwargs: Any) -> IngestReport:
        return run_ingest(self.config, messages=messages, **kwargs)

    def parse(self, raw: Any) -> EmailMessageParsed:
        return parse_email(raw)

    def is_recruiter(self, parsed: Any) -> bool:
        return is_recruiter_email(parsed)


class MailIngestor(MailIngester):
    pass


class ImapMailIngester(MailIngester):
    pass


class RecruiterFilter:
    @staticmethod
    def is_recruiter(parsed: Any) -> bool:
        return is_recruiter_email(parsed)

    @staticmethod
    def score(parsed: Any) -> float:
        return recruiter_score(parsed)


class EmailParser:
    @staticmethod
    def parse(raw: Any) -> EmailMessageParsed:
        return parse_email(raw)


__all__ = [
    "MailIngestConfig",
    "ImapConfig",
    "MailConfig",
    "Config",
    "EmailMessageParsed",
    "Email",
    "ParsedEmail",
    "ParsedMessage",
    "MailMessage",
    "EvidenceMail",
    "IngestReport",
    "IngestResult",
    "MailIngestResult",
    "IngestionReport",
    "MailIngestReport",
    "RECRUITER_DOMAIN_HINTS",
    "RECRUITER_SUBJECT_PATTERNS",
    "PURGE_AFTER_DAYS",
    "consent_granted",
    "require_consent",
    "consent_enabled",
    "is_consent_granted",
    "load_credentials_from_keyring",
    "store_credentials_in_keyring",
    "parse_email",
    "parse_message",
    "parse_raw_email",
    "parse",
    "parse_headers",
    "parse_body",
    "is_recruiter_email",
    "matches_recruiter",
    "recruiter_match",
    "is_recruiter",
    "recruiter_score",
    "recruiter_score_from_parts",
    "link_to_application",
    "match_application",
    "link_email_to_application",
    "find_application",
    "make_evidence_mail",
    "record_evidence",
    "store_evidence_mail",
    "evidence_mail_from_parsed",
    "fingerprint_of",
    "is_duplicate",
    "dedupe_emails",
    "purge_older_than",
    "connect_imap",
    "connect",
    "fetch_unread",
    "fetch_since",
    "fetch_headers",
    "process_email",
    "ingest_emails",
    "run_ingest",
    "ingest_inbox",
    "ingest",
    "run",
    "ingest_into_service",
    "apply_state_to_application",
    "MailIngester",
    "MailIngestor",
    "ImapMailIngester",
    "RecruiterFilter",
    "EmailParser",
]
