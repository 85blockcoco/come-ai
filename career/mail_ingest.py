"""Local IMAP mail ingestion for recruiter replies (SPEC-039).

Consent-gated, read-only, headers-first.  No SMTP, no cloud, no forwarding.
Personal non-recruitment emails are never parsed beyond headers.
"""

from __future__ import annotations

import hashlib
import imaplib
import os
from dataclasses import dataclass
from email import policy
from email.parser import BytesParser
from typing import Any, Callable

from .mail_states import (
    MailEvidence, MailState, is_recruiter_email, classify_state, make_evidence,
)

CONSENT_ENV = "CAREER_MAIL_CONSENT"


@dataclass
class MailConfig:
    host: str
    login: str
    password: str
    mailbox: str = "INBOX"
    since_days: int = 30


def consent_granted() -> bool:
    """Consent is OFF by default."""
    return os.environ.get(CONSENT_ENV, "").strip().lower() in ("1", "true", "yes", "on")


def fetch_headers(config: MailConfig, *, limit: int = 50) -> list[dict[str, Any]]:
    """Fetch headers only.  Requires explicit consent.  Returns list of dicts
    with keys: message_id, subject, sender, date, sha256."""
    if not consent_granted():
        raise PermissionError("Consentement email requis (CAREER_MAIL_CONSENT=1).")
    out: list[dict[str, Any]] = []
    try:
        conn = imaplib.IMAP4_SSL(config.host)
        conn.login(config.login, config.password)
        conn.select(config.mailbox)
        typ, data = conn.search(None, "UNSEEN")
        ids = data[0].split() if typ == "OK" and data and data[0] else []
        ids = ids[-limit:]
        for mid in ids:
            typ, msg_data = conn.fetch(mid, "(RFC822.HEADER)")
            if typ != "OK" or not msg_data:
                continue
            raw = msg_data[0][1] if isinstance(msg_data[0], tuple) else b""
            msg = BytesParser(policy=policy.default).parsebytes(raw)
            subject = str(msg.get("Subject", ""))
            sender = str(msg.get("From", ""))
            date = str(msg.get("Date", ""))
            sha = hashlib.sha256(raw).hexdigest()
            mid_str = mid.decode() if isinstance(mid, bytes) else str(mid)
            out.append({
                "message_id": mid_str,
                "subject": subject,
                "sender": sender,
                "date": date,
                "sha256": sha,
            })
        conn.logout()
    except Exception as exc:
        raise RuntimeError(f"IMAP error: {exc}") from exc
    return out


def ingest(
    config: MailConfig,
    *,
    linker: Callable[[dict[str, Any]], str | None] | None = None,
    limit: int = 50,
) -> list[MailEvidence]:
    """Ingest recruiter emails and produce MailEvidence records (pending
    confirmation).  Only recruiter emails are processed; personal emails are
    skipped (headers only).  ``linker`` maps an email dict to an application_id
    or None."""
    headers = fetch_headers(config, limit=limit)
    evidences: list[MailEvidence] = []
    for h in headers:
        if not is_recruiter_email(h["subject"], h["sender"]):
            continue
        state = classify_state(h["subject"], "")
        conf = 0.6 if state != MailState.RECEIVED else 0.4
        ev = make_evidence(
            message_id=h["message_id"],
            subject=h["subject"],
            sender=h["sender"],
            received_at=h["date"],
            sha256=h["sha256"],
            state=state,
            confidence=conf,
        )
        evidences.append(ev)
    return evidences


def purge_old(records: list[dict[str, Any]], months: int = 24) -> list[dict[str, Any]]:
    """Drop records older than ``months`` (best-effort by received_at)."""
    from datetime import datetime, timedelta, timezone
    cutoff = datetime.now(timezone.utc) - timedelta(days=months * 30)
    out = []
    for r in records:
        try:
            dt = datetime.fromisoformat(str(r.get("received_at", "")).replace("Z", "+00:00"))
        except ValueError:
            out.append(r)
            continue
        if dt >= cutoff:
            out.append(r)
    return out