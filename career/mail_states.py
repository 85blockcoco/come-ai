"""Mail-derived application state machine (SPEC-039).

States are NEVER changed implicitly: a detected email produces a
``pending_user_confirmation`` record that the user must validate before the
application state is updated.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class MailState(str, Enum):
    RECEIVED = "received"
    INTERVIEW = "interview"
    REJECTED = "rejected"
    ASSESSMENT = "assessment"
    PENDING_CONFIRMATION = "pending_user_confirmation"


RECRUITER_PATTERNS = (
    "interview", "assessment", "invitation", "rejection", "candidature",
    "application", "entretien", "convocation",
)

RECRUITER_DOMAINS = (
    "greenhouse.io", "lever.co", "smartrecruiters.com", "workday.com",
    "successfactors", "taleo.net",
)


def is_recruiter_email(subject: str, sender: str) -> bool:
    subj = (subject or "").lower()
    snd = (sender or "").lower()
    if any(d in snd for d in RECRUITER_DOMAINS):
        return True
    return any(p in subj for p in RECRUITER_PATTERNS)


def classify_state(subject: str, body: str = "") -> MailState:
    text = ((subject or "") + " " + (body or "")).lower()
    if any(w in text for w in ("rejection", "rejected", "ko", "malheureusement", "not selected", "regret", "unfortunately")):
        return MailState.REJECTED
    if any(w in text for w in ("assessment", "test technique", "case study")):
        return MailState.ASSESSMENT
    if any(w in text for w in ("interview", "entretien", "convocation", "invitation")):
        return MailState.INTERVIEW
    return MailState.RECEIVED


@dataclass
class MailEvidence:
    message_id: str
    subject: str
    sender: str
    received_at: str
    sha256: str
    state: MailState
    confidence: float = 0.5


def make_evidence(message_id: str, subject: str, sender: str, received_at: str,
                  sha256: str, state: MailState, confidence: float = 0.5) -> MailEvidence:
    return MailEvidence(
        message_id=message_id, subject=subject, sender=sender,
        received_at=received_at, sha256=sha256, state=state, confidence=confidence,
    )