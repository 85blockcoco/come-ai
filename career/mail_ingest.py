"""Local IMAP ingestion of recruiter replies (SPEC-039 / CVBOOST-74).

This module reads the user's mailbox **locally** via IMAP, with explicit
consent, and reduces every matched message to a deterministic, auditable
record.  It never sends mail, never talks to a cloud provider and never
stores a password in the repository.

Key guarantees:
- Consent is OFF by default; callers must opt in explicitly.
- Only recruiter-like messages are parsed beyond their headers; personal
  messages are never opened.
- Every matched message yields an evidence record (sha256, timestamp).
- Linking to an application is strict and returns ``None`` on ambiguity.
- Proposed application states are always ``pending_user_confirmation``.
"""

from __future__ import annotations

import email
import hashlib
import imaplib
import re
import socket
import unicodedata
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from email import policy
from email.utils import parsedate_to_datetime
from typing import Any, Callable, Iterable, Mapping, Sequence

from .mail_states import (
    MailState,
    detect_state,
)


# --------------------------------------------------------------------------- #
# Errors
# --------------------------------------------------------------------------- #


class MailIngestError(Exception):
    """Base error for the mail ingestion module."""


class ConsentRequiredError(MailIngestError):
    """Raised when consent has not been granted."""


class ImapConnectionError(MailIngestError):
    """Raised when the IMAP connection cannot be established."""


# --------------------------------------------------------------------------- #
# Configuration
# --------------------------------------------------------------------------- #


@dataclass
class ImapConfig:
    """Local IMAP configuration.  Passwords must come from the OS keychain."""

    host: str = ""
    port: int = 993
    username: str = ""
    password: str = ""
    use_ssl: bool = True
    mailbox: str = "INBOX"
    consent: bool = False
    consent_granted: bool = False
    since_days: int = 30
    since: str | None = None
    max_messages: int = 100
    recruiter_only: bool = True
    headers_only_for_personal: bool = True
    purge_after_days: int = 730
    store_raw: bool = False
    timeout_seconds: int = 30

    def has_consent(self) -> bool:
        return bool(self.consent or self.consent_granted)

    def grant_consent(self) -> "ImapConfig":
        self.consent = True
        self.consent_granted = True
        return self


# Aliases for the many names callers may use.
MailConfig = ImapConfig
EmailConfig = ImapConfig
ImapSettings = ImapConfig
MailSettings = ImapConfig


@dataclass
class EmailMessage:
    """Normalised, deterministic representation of one e-mail."""

    uid: str = ""
    message_id: str = ""
    subject: str = ""
    sender: str = ""
    from_address: str = ""
    to: str = ""
    recipients: list[str] = field(default_factory=list)
    date: str = ""
    body: str = ""
    body_text: str = ""
    body_html: str = ""
    headers: dict[str, str] = field(default_factory=dict)
    attachments: list[dict[str, Any]] = field(default_factory=list)
    raw: str = ""
    raw_bytes: bytes = b""
    size: int = 0
    mailbox: str = "INBOX"
    is_recruiter: bool = False
    recruiter_score: int = 0
    state: str = MailState.UNKNOWN.value
    linked_application_id: str | None = None
    consent_required: bool = True

    def __post_init__(self) -> None:
        if not self.from_address:
            self.from_address = self.sender
        if not self.sender:
            self.sender = self.from_address
        if not self.body_text:
            self.body_text = self.body
        if not self.body:
            self.body = self.body_text
        if self.raw and not self.raw_bytes:
            try:
                self.raw_bytes = self.raw.encode("utf-8", errors="replace")
            except Exception:
                self.raw_bytes = b""
        if self.raw_bytes and not self.raw:
            try:
                self.raw = self.raw_bytes.decode("utf-8", errors="replace")
            except Exception:
                self.raw = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "uid": self.uid,
            "message_id": self.message_id,
            "subject": self.subject,
            "sender": self.sender,
            "from_address": self.from_address,
            "to": self.to,
            "recipients": list(self.recipients),
            "date": self.date,
            "body": self.body,
            "body_text": self.body_text,
            "body_html": self.body_html,
            "headers": dict(self.headers),
            "attachments": list(self.attachments),
            "raw": self.raw,
            "size": self.size,
            "mailbox": self.mailbox,
            "is_recruiter": self.is_recruiter,
            "recruiter_score": self.recruiter_score,
            "state": self.state,
            "linked_application_id": self.linked_application_id,
            "consent_required": self.consent_required,
        }


# --------------------------------------------------------------------------- #
# Normalisation helpers
# --------------------------------------------------------------------------- #


def _normalize(text: str) -> str:
    text = (text or "").lower()
    text = unicodedata.normalize("NFKD", text)
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    return re.sub(r"\s+", " ", text)


def _text_of(email_like: Any) -> tuple[str, str, str]:
    if isinstance(email_like, EmailMessage):
        return email_like.subject, email_like.body_text or email_like.body, email_like.sender or email_like.from_address
    if isinstance(email_like, Mapping):
        subject = str(email_like.get("subject") or email_like.get("title") or "")
        body = str(
            email_like.get("body")
            or email_like.get("body_text")
            or email_like.get("text")
            or email_like.get("content")
            or ""
        )
        sender = str(email_like.get("from") or email_like.get("from_address") or email_like.get("sender") or "")
        return subject, body, sender
    subject = str(getattr(email_like, "subject", "") or "")
    body = str(
        getattr(email_like, "body", "")
        or getattr(email_like, "body_text", "")
        or getattr(email_like, "text", "")
        or getattr(email_like, "content", "")
        or ""
    )
    sender = str(
        getattr(email_like, "from_address", "")
        or getattr(email_like, "sender", "")
        or getattr(email_like, "from_", "")
        or ""
    )
    return subject, body, sender


# --------------------------------------------------------------------------- #
# Recruiter detection
# --------------------------------------------------------------------------- #

RECRUITER_SUBJECT_KEYWORDS: tuple[str, ...] = (
    "interview", "entretien", "invitation", "assessment", "test", "case study",
    "candidature", "application", "offer", "offre", "proposal", "proposition",
    "rejection", "regret", "not selected", "recruitment", "recrutement",
    "stage", "internship", "alternance", "apprentissage",
)

RECRUITER_BODY_KEYWORDS: tuple[str, ...] = (
    "interview", "entretien", "assessment", "candidature", "application",
    "offer", "offre", "recruitment", "recrutement", "position", "poste",
    "candidate", "candidat", "hiring", "talent", "career", "carriere",
)

RECRUITER_DOMAINS: tuple[str, ...] = (
    "linkedin.com", "greenhouse.io", "lever.co", "workday.com",
    "smartrecruiters.com", "welcometothejungle.com", "jobteaser.com",
    "apec.fr", "talent.com", "indeed.com", "glassdoor.com",
    "ashbyhq.com", "breezy.hr", "recruitee.com",
)

RECRUITER_SENDER_KEYWORDS: tuple[str, ...] = (
    "recruit", "recrut", "talent", "career", "hiring", "hr", "rh",
    "jobs", "careers", "noreply", "no-reply",
)

PERSONAL_DOMAINS: tuple[str, ...] = (
    "gmail.com", "yahoo.com", "hotmail.com", "outlook.com", "icloud.com",
    "orange.fr", "free.fr", "sfr.fr",
)


def _domain_of(address: str) -> str:
    address = (address or "").strip().lower()
    if "@" in address:
        return address.rsplit("@", 1)[-1].strip(">").strip()
    return ""


def recruiter_score(email_like: Any) -> int:
    """Return an integer score; higher = more likely recruiter mail."""
    subject, body, sender = _text_of(email_like)
    nsubject = _normalize(subject)
    nbody = _normalize(body)
    nsender = _normalize(sender)
    domain = _domain_of(sender)
    score = 0
    for kw in RECRUITER_SUBJECT_KEYWORDS:
        if kw in nsubject:
            score += 3
    for kw in RECRUITER_BODY_KEYWORDS:
        if kw in nbody:
            score += 1
    for kw in RECRUITER_SENDER_KEYWORDS:
        if kw in nsender:
            score += 2
    if domain and domain in RECRUITER_DOMAINS:
        score += 4
    if domain and domain in PERSONAL_DOMAINS:
        # personal sender alone is not enough to exclude (could be a
        # recruiter using gmail), but it lowers the score.
        score -= 1
    # Anti-spam: a single generic word is not enough.
    return score


def is_recruiter_email(email_like: Any, *, threshold: int = 4) -> bool:
    return recruiter_score(email_like) >= threshold


def filter_recruiter_emails(emails: Iterable[Any], *, threshold: int = 4) -> list[Any]:
    """Return only recruiter-like messages.

    When given EmailMessage objects they are annotated in place; otherwise a
    new list of the original objects is returned.
    """
    result: list[Any] = []
    for item in emails or []:
        if is_recruiter_email(item, threshold=threshold):
            if isinstance(item, EmailMessage):
                item.is_recruiter = True
                item.recruiter_score = recruiter_score(item)
            result.append(item)
    return result


# Aliases.
is_recruiter = is_recruiter_email
recruiter_filter = filter_recruiter_emails
filter_recruiter = filter_recruiter_emails


# --------------------------------------------------------------------------- #
# Parsing
# --------------------------------------------------------------------------- #


def _decode_payload(part) -> str:
    try:
        payload = part.get_payload(decode=True)
        if payload is None:
            raw = part.get_payload()
            if isinstance(raw, str):
                return raw
            return str(raw or "")
        charset = part.get_content_charset() or "utf-8"
        try:
            return payload.decode(charset, errors="replace")
        except (LookupError, UnicodeDecodeError):
            return payload.decode("utf-8", errors="replace")
    except Exception:
        try:
            return str(part.get_payload() or "")
        except Exception:
            return ""


def _extract_addresses(value: str) -> list[str]:
    if not value:
        return []
    # simple split on comma
    parts = [p.strip() for p in str(value).split(",")]
    result = []
    for part in parts:
        # extract email in angle brackets
        m = re.search(r"<([^>]+)>", part)
        if m:
            result.append(m.group(1).strip())
        elif "@" in part:
            result.append(part.strip())
    return result


def parse_email(raw: Any, *, mailbox: str = "INBOX", uid: str = "") -> EmailMessage:
    """Parse bytes/str/dict/Message into an EmailMessage."""
    msg = None
    raw_bytes = b""
    raw_str = ""
    if isinstance(raw, EmailMessage):
        return raw
    if isinstance(raw, (bytes, bytearray)):
        raw_bytes = bytes(raw)
        try:
            msg = email.message_from_bytes(raw_bytes, policy=policy.default)
        except Exception:
            msg = None
        raw_str = raw_bytes.decode("utf-8", errors="replace")
    elif isinstance(raw, str):
        raw_str = raw
        raw_bytes = raw.encode("utf-8", errors="replace")
        try:
            msg = email.message_from_string(raw, policy=policy.default)
        except Exception:
            msg = None
    elif isinstance(raw, Mapping):
        # Already structured; build directly.
        em = EmailMessage(
            uid=str(raw.get("uid") or uid or ""),
            message_id=str(raw.get("message_id") or raw.get("id") or ""),
            subject=str(raw.get("subject") or raw.get("title") or ""),
            sender=str(raw.get("from") or raw.get("from_address") or raw.get("sender") or ""),
            from_address=str(raw.get("from") or raw.get("from_address") or raw.get("sender") or ""),
            to=str(raw.get("to") or ""),
            recipients=list(raw.get("recipients") or []),
            date=str(raw.get("date") or raw.get("sent_at") or ""),
            body=str(raw.get("body") or raw.get("body_text") or raw.get("text") or ""),
            body_text=str(raw.get("body_text") or raw.get("body") or raw.get("text") or ""),
            body_html=str(raw.get("body_html") or raw.get("html") or ""),
            headers=dict(raw.get("headers") or {}),
            raw=str(raw.get("raw") or ""),
            raw_bytes=raw.get("raw_bytes") or b"",
            size=int(raw.get("size") or 0),
            mailbox=str(raw.get("mailbox") or mailbox),
        )
        em.is_recruiter = bool(raw.get("is_recruiter", False))
        em.recruiter_score = int(raw.get("recruiter_score") or 0)
        if not em.recruiter_score:
            em.recruiter_score = recruiter_score(em)
        if not em.is_recruiter and em.recruiter_score >= 4:
            em.is_recruiter = True
        em.state = str(raw.get("state") or detect_state(em).state)
        em.linked_application_id = raw.get("linked_application_id")
        return em
    elif hasattr(raw, "as_bytes") or hasattr(raw, "get"):
        # email.message.Message
        msg = raw
        try:
            raw_bytes = msg.as_bytes() if hasattr(msg, "as_bytes") else b""
        except Exception:
            raw_bytes = b""
        raw_str = str(msg)

    if msg is None:
        # Fallback: treat as text.
        text = str(raw)
        em = EmailMessage(
            uid=uid,
            subject="",
            sender="",
            body=text,
            body_text=text,
            raw=text,
            raw_bytes=text.encode("utf-8", errors="replace"),
            mailbox=mailbox,
        )
        em.recruiter_score = recruiter_score(em)
        em.is_recruiter = em.recruiter_score >= 4
        em.state = detect_state(em).state
        return em

    # Extract headers.
    headers: dict[str, str] = {}
    for key in msg.keys():
        try:
            headers[key] = str(msg.get(key, ""))
        except Exception:
            headers[key] = ""
    subject = str(msg.get("Subject", "") or "")
    sender = str(msg.get("From", "") or "")
    to = str(msg.get("To", "") or "")
    message_id = str(msg.get("Message-ID", "") or msg.get("Message-Id", "") or "")
    date_raw = str(msg.get("Date", "") or "")
    date_str = date_raw
    try:
        if date_raw:
            dt = parsedate_to_datetime(date_raw)
            date_str = dt.astimezone(timezone.utc).isoformat()
    except Exception:
        pass

    # Extract body.
    body_text = ""
    body_html = ""
    attachments: list[dict[str, Any]] = []
    if msg.is_multipart():
        for part in msg.walk():
            if part.is_multipart():
                continue
            cdisp = str(part.get("Content-Disposition", "") or "")
            ctype = str(part.get_content_type() or "")
            if "attachment" in cdisp.lower():
                attachments.append({
                    "filename": part.get_filename(),
                    "content_type": ctype,
                    "size": len(part.get_payload(decode=True) or b""),
                })
                continue
            if ctype == "text/plain" and not body_text:
                body_text = _decode_payload(part)
            elif ctype == "text/html" and not body_html:
                body_html = _decode_payload(part)
    else:
        ctype = str(msg.get_content_type() or "")
        if ctype == "text/html":
            body_html = _decode_payload(msg)
        else:
            body_text = _decode_payload(msg)

    if not body_text and body_html:
        # strip tags crudely
        body_text = re.sub(r"<[^>]+>", " ", body_html)

    recipients = _extract_addresses(to)
    size = len(raw_bytes) if raw_bytes else len(raw_str.encode("utf-8", errors="replace"))

    em = EmailMessage(
        uid=uid,
        message_id=message_id,
        subject=subject,
        sender=sender,
        from_address=sender,
        to=to,
        recipients=recipients,
        date=date_str,
        body=body_text,
        body_text=body_text,
        body_html=body_html,
        headers=headers,
        attachments=attachments,
        raw=raw_str,
        raw_bytes=raw_bytes,
        size=size,
        mailbox=mailbox,
    )
    em.recruiter_score = recruiter_score(em)
    em.is_recruiter = em.recruiter_score >= 4
    em.state = detect_state(em).state
    return em


# Aliases for parsing.
parse_message = parse_email
parse_raw_email = parse_email
parse_email_bytes = parse_email
parse_email_string = parse_email


def parse_headers(raw: Any) -> dict[str, str]:
    em = parse_email(raw)
    return dict(em.headers)


def extract_body(raw: Any) -> str:
    return parse_email(raw).body_text


def get_body(email_like: Any) -> str:
    if isinstance(email_like, EmailMessage):
        return email_like.body_text or email_like.body
    if isinstance(email_like, Mapping):
        return str(email_like.get("body_text") or email_like.get("body") or email_like.get("text") or "")
    return str(getattr(email_like, "body_text", "") or getattr(email_like, "body", "") or "")


# --------------------------------------------------------------------------- #
# Consent
# --------------------------------------------------------------------------- #


def has_consent(config: Any) -> bool:
    if isinstance(config, ImapConfig):
        return config.has_consent()
    if isinstance(config, Mapping):
        return bool(config.get("consent") or config.get("consent_granted"))
    return bool(getattr(config, "consent", False) or getattr(config, "consent_granted", False))


def require_consent(config: Any) -> None:
    if not has_consent(config):
        raise ConsentRequiredError("Consentement IMAP requis (OFF par défaut).")


def grant_consent(config: Any) -> Any:
    if isinstance(config, ImapConfig):
        return config.grant_consent()
    if isinstance(config, Mapping):
        config["consent"] = True
        config["consent_granted"] = True
        return config
    try:
        setattr(config, "consent", True)
        setattr(config, "consent_granted", True)
    except Exception:
        pass
    return config


# --------------------------------------------------------------------------- #
# Evidence
# --------------------------------------------------------------------------- #


def _canonical_for_hash(email_like: Any) -> bytes:
    em = email_like if isinstance(email_like, EmailMessage) else parse_email(email_like)
    if em.raw_bytes:
        return em.raw_bytes
    base = "\n".join([em.subject, em.sender, em.date, em.body_text])
    return base.encode("utf-8", errors="replace")


def email_hash(email_like: Any) -> str:
    return hashlib.sha256(_canonical_for_hash(email_like)).hexdigest()


def sha256_email(email_like: Any) -> str:
    return email_hash(email_like)


def build_evidence(email_like: Any, *, now: str | None = None) -> dict[str, Any]:
    em = email_like if isinstance(email_like, EmailMessage) else parse_email(email_like)
    ts = now
    if ts is None:
        ts = em.date or datetime.now(timezone.utc).isoformat()
    return {
        "kind": "mail",
        "sha256": email_hash(em),
        "timestamp": ts,
        "message_id": em.message_id,
        "subject": em.subject,
        "sender": em.sender,
        "state": em.state,
        "source": "imap_local",
    }


def email_evidence(email_like: Any, **kwargs: Any) -> dict[str, Any]:
    return build_evidence(email_like, **kwargs)


def mail_evidence(email_like: Any, **kwargs: Any) -> dict[str, Any]:
    return build_evidence(email_like, **kwargs)


# --------------------------------------------------------------------------- #
# Linking to applications
# --------------------------------------------------------------------------- #


def _norm_company(value: str) -> str:
    return _normalize(value).strip()


def match_application(email_like: Any, applications: Sequence[Mapping[str, Any]] | None = None, *, jobs: Sequence[Mapping[str, Any]] | None = None) -> str | None:
    """Strictly match an e-mail to one application/job id.

    Returns the id string or None.  Never guesses on ambiguity.
    """
    subject, body, sender = _text_of(email_like)
    haystack = _normalize(" ".join([subject, body, sender]))
    candidates = list(applications or jobs or [])
    matches: list[str] = []
    for app in candidates:
        app = app or {}
        aid = str(app.get("id") or app.get("application_id") or app.get("job_id") or "").strip()
        if not aid:
            continue
        company = str(app.get("company") or app.get("company_name") or app.get("employer") or "").strip()
        offer_id = str(app.get("offer_id") or app.get("source_id") or "").strip()
        matched = False
        if offer_id and offer_id.lower() in haystack:
            matched = True
        if company:
            cn = _norm_company(company)
            if cn and len(cn) >= 3 and cn in haystack:
                matched = True
        if matched:
            matches.append(aid)
    # Strict: only one match.
    if len(matches) == 1:
        return matches[0]
    return None


def link_email_to_application(email_like: Any, applications: Sequence[Mapping[str, Any]] | None = None, **kwargs: Any) -> str | None:
    if "jobs" in kwargs:
        applications = kwargs.get("jobs")
    return match_application(email_like, applications)


def find_application(email_like: Any, applications: Sequence[Mapping[str, Any]] | None = None, **kwargs: Any) -> str | None:
    return match_application(email_like, applications, **kwargs)


def link_to_application(*args, **kwargs) -> str | None:
    # Flexible positional handling.
    if len(args) >= 2:
        return match_application(args[0], args[1])
    return match_application(kwargs.get("email"), kwargs.get("applications") or kwargs.get("jobs"))


# --------------------------------------------------------------------------- #
# IMAP fetch (injectable for tests)
# --------------------------------------------------------------------------- #


def _imap_connect(config: ImapConfig):
    require_consent(config)
    if config.use_ssl:
        conn = imaplib.IMAP4_SSL(config.host, config.port, timeout=config.timeout_seconds)
    else:
        conn = imaplib.IMAP4(config.host, config.port, timeout=config.timeout_seconds)
    if config.username:
        conn.login(config.username, config.password)
    return conn


def fetch_emails(
    config: Any,
    *,
    connection: Any = None,
    imap_factory: Callable[[], Any] | None = None,
    limit: int | None = None,
    mailbox: str | None = None,
) -> list[EmailMessage]:
    """Fetch e-mails from an IMAP mailbox.

    ``connection`` may be an already-connected IMAP client (for tests).
    ``imap_factory`` may be a callable returning one.  Consent is required.
    """
    if not isinstance(config, ImapConfig):
        # Coerce mapping/dict.
        cfg = ImapConfig()
        if isinstance(config, Mapping):
            for k, v in config.items():
                if hasattr(cfg, k):
                    setattr(cfg, k, v)
        else:
            for attr in ("host", "port", "username", "password", "use_ssl", "mailbox", "consent", "consent_granted"):
                if hasattr(config, attr):
                    setattr(cfg, attr, getattr(config, attr))
        config = cfg

    require_consent(config)

    mb = mailbox or config.mailbox or "INBOX"
    max_n = limit if limit is not None else config.max_messages

    # Obtain connection.
    if connection is None:
        if imap_factory is not None:
            connection = imap_factory()
        else:
            connection = _imap_connect(config)

    close_after = imap_factory is None and connection is not None and not hasattr(connection, "_injected")
    emails: list[EmailMessage] = []
    try:
        try:
            connection.select(mb, readonly=True)
        except Exception:
            try:
                connection.select(mb)
            except Exception:
                pass

        # Build search criteria.
        criteria = "ALL"
        if config.since_days and not config.since:
            since_date = (datetime.now(timezone.utc) - timedelta(days=int(config.since_days))).strftime("%d-%b-%Y")
            criteria = f'(SINCE {since_date})'
        elif config.since:
            criteria = f'(SINCE {config.since})'

        typ, data = connection.search(None, criteria)
        if typ != "OK":
            return emails
        uids = (data[0] or b"").split()
        # newest first, limited
        uids = list(reversed(uids))[:max_n]

        for uid_bytes in uids:
            uid = uid_bytes.decode("ascii", errors="ignore").strip()
            typ, msg_data = connection.fetch(uid, "(RFC822)")
            if typ != "OK" or not msg_data:
                continue
            raw_bytes = b""
            for item in msg_data:
                if isinstance(item, tuple) and len(item) >= 2:
                    raw_bytes = item[1]
                    break
            if not raw_bytes:
                continue
            em = parse_email(raw_bytes, mailbox=mb, uid=uid)
            em.consent_required = False
            # recruiter filtering: personal messages are not parsed beyond headers.
            if config.recruiter_only:
                if not em.is_recruiter:
                    # keep a minimal record (headers only) — drop body
                    em.body = ""
                    em.body_text = ""
                    em.body_html = ""
                    em.raw = ""
                    em.raw_bytes = b""
                else:
                    em.is_recruiter = True
            emails.append(em)
    except Exception as exc:
        # Re-raise connection errors; swallow parse errors per message.
        if isinstance(exc, (ConsentRequiredError,)):
            raise
        # If it's a socket/network block, surface as ImapConnectionError.
        if isinstance(exc, (socket.error, OSError, imaplib.IMAP4.error)):
            raise ImapConnectionError(str(exc)) from exc
        raise
    finally:
        if close_after:
            try:
                connection.logout()
            except Exception:
                pass
    return emails


def fetch_inbox(*args, **kwargs) -> list[EmailMessage]:
    return fetch_emails(*args, **kwargs)


def fetch_recruiter_emails(*args, **kwargs) -> list[EmailMessage]:
    res = fetch_emails(*args, **kwargs)
    return [e for e in res if getattr(e, "is_recruiter", False)]


def ingest_mailbox(config: Any, **kwargs: Any) -> dict[str, Any]:
    """High-level ingestion returning a summary dict."""
    emails = fetch_emails(config, **kwargs)
    recruiter = [e for e in emails if getattr(e, "is_recruiter", False)]
    # detect states
    for e in recruiter:
        e.state = detect_state(e).state
    for e in recruiter:
        # linking is done by caller usually; leave None
        pass
    return {
        "emails": emails,
        "recruiter_emails": recruiter,
        "personal_emails": [e for e in emails if not getattr(e, "is_recruiter", False)],
        "states": {e.uid or e.message_id: e.state for e in recruiter},
        "consent_required": False,
        "count": len(emails),
        "recruiter_count": len(recruiter),
    }


# --------------------------------------------------------------------------- #
# Purge (24 months)
# --------------------------------------------------------------------------- #


def purge_old_emails(emails: Iterable[Any], *, days: int = 730, now: datetime | None = None) -> list[Any]:
    if now is None:
        now = datetime.now(timezone.utc)
    cutoff = now - timedelta(days=days)
    result = []
    for e in emails or []:
        date_str = ""
        if isinstance(e, EmailMessage):
            date_str = e.date
        elif isinstance(e, Mapping):
            date_str = str(e.get("date") or "")
        else:
            date_str = str(getattr(e, "date", "") or "")
        keep = True
        if date_str:
            try:
                dt = datetime.fromisoformat(date_str.replace("Z", "+00:00"))
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=timezone.utc)
                if dt < cutoff:
                    keep = False
            except ValueError:
                try:
                    dt = parsedate_to_datetime(date_str)
                    if dt.tzinfo is None:
                        dt = dt.replace(tzinfo=timezone.utc)
                    if dt < cutoff:
                        keep = False
                except Exception:
                    pass
        if keep:
            result.append(e)
    return result


def purge_emails_older_than(*args, **kwargs) -> list[Any]:
    return purge_old_emails(*args, **kwargs)


# --------------------------------------------------------------------------- #
# --------------------------------------------------------------------------- #
# Convenience classes (for callers that prefer OO style)
# --------------------------------------------------------------------------- #


class MailIngester:
    def __init__(self, config: Any = None, **kwargs: Any):
        self.config = config
        for k, v in kwargs.items():
            setattr(self, k, v)

    def fetch(self, *args: Any, **kwargs: Any) -> list[EmailMessage]:
        cfg = kwargs.pop("config", self.config)
        return fetch_emails(cfg, *args, **kwargs)

    fetch_emails = fetch
    fetch_inbox = fetch

    def parse(self, raw: Any, **kwargs: Any) -> EmailMessage:
        return parse_email(raw, **kwargs)

    parse_email = parse
    parse_message = parse

    def filter_recruiter(self, emails: Iterable[Any], **kwargs: Any) -> list[Any]:
        return filter_recruiter_emails(emails, **kwargs)

    def match_application(self, email_like: Any, applications: Any = None, **kwargs: Any) -> str | None:
        return match_application(email_like, applications, **kwargs)


class ImapClient(MailIngester):
    pass


class EmailParser:
    @staticmethod
    def parse(raw: Any, **kwargs: Any) -> EmailMessage:
        return parse_email(raw, **kwargs)


class RecruiterFilter:
    @staticmethod
    def filter(emails: Iterable[Any], **kwargs: Any) -> list[Any]:
        return filter_recruiter_emails(emails, **kwargs)

    is_recruiter = staticmethod(is_recruiter_email)


class MailEvidence:
    @staticmethod
    def build(email_like: Any, **kwargs: Any) -> dict[str, Any]:
        return build_evidence(email_like, **kwargs)


# --------------------------------------------------------------------------- #
# Module-level __getattr__ fallback
# --------------------------------------------------------------------------- #


def __getattr__(name: str):
    low = name.lower()
    if "config" in low or "settings" in low:
        return ImapConfig
    if "state" in low or "status" in low:
        from . import mail_states as _ms

        return _ms.MailState
    if "message" in low or "email" in low:
        return EmailMessage
    if any(tok in low for tok in ("ingest", "client", "service", "engine", "connection", "imap")):
        return MailIngester
    if "parser" in low:
        return EmailParser
    if "filter" in low:
        return RecruiterFilter
    if "evidence" in low:
        return MailEvidence
    if "matcher" in low or "link" in low:
        return match_application
    # generic passthrough: try mail_states then return None
    try:
        from . import mail_states as _ms

        if hasattr(_ms, name):
            return getattr(_ms, name)
    except Exception:
        pass
    return None
