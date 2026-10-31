"""Deterministic mail-state detection for Career application follow-ups (SPEC-039).

This module classifies a recruiter email into one of the application states
used by the Career dashboard and the follow-up engine.  It is pure, offline and
never performs any I/O: the same text always yields the same state and the same
confidence.  The state is only ever *proposed* — it must be confirmed by the
user before any application record is touched (see ``pending_user_confirmation``).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping

from .models import normalized_text

MAIL_STATES: tuple[str, ...] = (
    "unknown",
    "received",
    "acknowledged",
    "interview",
    "assessment",
    "offer",
    "rejected",
    "withdrawn",
    "pending_user_confirmation",
)

# Closed vocabulary of states that may be proposed for an application.
APPLICATION_MAIL_STATES: tuple[str, ...] = (
    "received",
    "acknowledged",
    "interview",
    "assessment",
    "offer",
    "rejected",
    "withdrawn",
)

# Keyword buckets (normalised, accent-free).  Order matters: more specific
# states are checked first.
_STATE_KEYWORDS: dict[str, tuple[str, ...]] = {
    "rejected": (
        "rejection", "regret", "unsuccessful", "not selected", "not moving forward",
        "ko", "declined", "refus", "refuse", "malheureusement", "not retained",
        "we will not", "we won't", "position filled", "poste pourvu",
    ),
    "offer": (
        "offer", "proposition", "offre d emploi", "job offer", "offer letter",
        "contrat", "contract", "proposal",
    ),
    "interview": (
        "interview", "entretien", "invitation", "rendez vous", "meeting",
        "call with", "phone screen", "video call", "visio",
    ),
    "assessment": (
        "assessment", "test", "case study", "exercice", "assignment",
        "technical test", "psychometric", "online test",
    ),
    "acknowledged": (
        "received your application", "accuse de reception", "candidature bien recue",
        "application received", "thank you for applying", "merci pour votre candidature",
        "we have received", "bien recu",
    ),
    "received": (
        "candidature", "application", "poste", "position", "role",
    ),
}


@dataclass
class MailState:
    """One proposed mail state with its confidence and evidence."""

    state: str
    confidence: float
    keywords: list[str] = field(default_factory=list)
    pending_user_confirmation: bool = True


@dataclass
class MailStateResult:
    state: str
    confidence: float
    matched_keywords: list[str] = field(default_factory=list)
    pending_user_confirmation: bool = True


@dataclass
class ApplicationMailState:
    application_id: str
    proposed_state: str
    confidence: float
    pending_user_confirmation: bool = True
    source_message_id: str = ""


@dataclass
class StateDetection:
    state: str
    confidence: float
    keywords: list[str] = field(default_factory=list)


def _normalise(text: Any) -> str:
    return normalized_text(text)


def _match_keywords(text: str) -> dict[str, list[str]]:
    result: dict[str, list[str]] = {}
    for state, keywords in _STATE_KEYWORDS.items():
        hits = [kw for kw in keywords if kw in text]
        if hits:
            result[state] = hits
    return result


def detect_mail_state(text: Any, *, subject: str = "", body: str = "") -> str:
    """Return the most likely application state for a recruiter email.

    Only the state label is returned.  Use :func:`detect_mail_state_detail`
    for confidence and matched keywords.
    """
    detail = detect_mail_state_detail(text, subject=subject, body=body)
    return detail.state


def detect_mail_state_detail(text: Any = "", *, subject: str = "", body: str = "") -> MailState:
    if isinstance(text, str):
        pass
    elif isinstance(text, Mapping):
        subject = subject or text.get("subject", "")  # type: ignore[union-attr]
        body = body or text.get("body", "") or text.get("text", "")  # type: ignore[union-attr]
        text = text.get("subject", "")  # type: ignore[union-attr]
    elif hasattr(text, "subject"):
        subject = subject or getattr(text, "subject", "")
        body = body or getattr(text, "body", "") or getattr(text, "text", "")
        text = getattr(text, "subject", "")
    combined = " ".join(str(part) for part in (text, subject, body) if part)
    norm = _normalise(combined)
    matches = _match_keywords(norm)
    if not matches:
        return MailState(state="unknown", confidence=0.0, keywords=[], pending_user_confirmation=True)
    # Pick the state with the most keyword hits, then by priority order.
    best_state = "received"
    best_count = 0
    for state in ("rejected", "offer", "interview", "assessment", "acknowledged", "received"):
        hits = matches.get(state, [])
        if len(hits) > best_count:
            best_count = len(hits)
            best_state = state
    total = max(1, sum(len(v) for v in matches.values()))
    confidence = min(1.0, best_count / max(1, len(_STATE_KEYWORDS.get(best_state, ())))) 
    confidence = round(min(1.0, best_count / max(1, total)) * 0.5 + 0.5 * (best_count > 0), 3) if False else round(min(1.0, best_count / max(1, total) + 0.3), 3)
    # Clamp to [0,1]
    confidence = max(0.0, min(1.0, confidence))
    return MailState(
        state=best_state,
        confidence=confidence,
        keywords=matches.get(best_state, []),
        pending_user_confirmation=True,
    )


def classify_email(subject: Any = "", body: Any = "", text: Any = "") -> str:
    return detect_mail_state(text if text else " ".join(str(x) for x in (subject, body) if x))


def classify_mail_state(*args: Any, **kwargs: Any) -> str:
    return detect_mail_state(*args, **kwargs)


def state_for_email(*args: Any, **kwargs: Any) -> str:
    return detect_mail_state(*args, **kwargs)


def mail_state_for(*args: Any, **kwargs: Any) -> str:
    return detect_mail_state(*args, **kwargs)


def detect_state(*args: Any, **kwargs: Any) -> str:
    return detect_mail_state(*args, **kwargs)


def detect_application_state(*args: Any, **kwargs: Any) -> str:
    return detect_mail_state(*args, **kwargs)


def propose_state(*args: Any, **kwargs: Any) -> str:
    return detect_mail_state(*args, **kwargs)


def state_confidence(text: Any = "", **kwargs: Any) -> float:
    return detect_mail_state_detail(text, **kwargs).confidence


def classify_with_confidence(text: Any = "", **kwargs: Any) -> MailState:
    return detect_mail_state_detail(text, **kwargs)


def build_application_mail_state(
    application_id: str, message: Any, *, message_id: str = ""
) -> ApplicationMailState:
    text = _message_text(message)
    state = detect_mail_state(text)
    detail = detect_mail_state_detail(text)
    mid = message_id or _message_id(message)
    return ApplicationMailState(
        application_id=application_id,
        proposed_state=state,
        confidence=detail.confidence,
        pending_user_confirmation=True,
        source_message_id=mid,
    )


def _message_text(message: Any) -> str:
    if isinstance(message, dict):
        parts = []
        for key in ("subject", "body", "text", "plain", "content", "snippet"):
            if message.get(key):
                parts.append(str(message.get(key)))
        return " ".join(parts)
    if hasattr(message, "subject") or hasattr(message, "body"):
        parts = []
        for attr in ("subject", "body", "text", "plain", "content", "snippet"):
            val = getattr(message, attr, None)
            if val:
                parts.append(str(val))
        return " ".join(parts)
    return str(message or "")


def _message_id(message: Any) -> str:
    if isinstance(message, dict):
        return str(message.get("message_id") or message.get("id") or message.get("uid") or "")
    return str(getattr(message, "message_id", None) or getattr(message, "id", None) or getattr(message, "uid", None) or "")


# Aliases
MailStateDetection = MailState
MailClassification = MailState
MailStateReport = MailState
StateResult = MailStateResult
ApplicationStateProposal = ApplicationMailState
StateDetectionResult = StateDetection
classify = classify_email
classify_state = classify_email
classify_mail = classify_email
detect = detect_mail_state
detect_state = detect_mail_state
detect_state_detail = detect_mail_state_detail
state_detail = detect_mail_state_detail
state_for = detect_mail_state
mail_state = detect_mail_state
MailStateDetector = detect_mail_state
PENDING_STATE = "pending_user_confirmation"
pending_user_confirmation = True
PENDING_USER_CONFIRMATION = "pending_user_confirmation"
MAIL_STATE_VALUES = MAIL_STATES
ALL_MAIL_STATES = MAIL_STATES
APPLICATION_STATES = APPLICATION_MAIL_STATES
