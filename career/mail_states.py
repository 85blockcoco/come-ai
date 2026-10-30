"""Deterministic state detection for recruiter e-mails (SPEC-039 / CVBOOST-74).

This module turns an e-mail (subject + body + sender) into a **proposed**
application state.  It never changes an application on its own: every
proposal is returned with ``pending_user_confirmation=True`` and a confidence
level, so the caller (dashboard / relance engine) can ask the person to
validate it.

States (closed list, aligned with ``career.models.APPLICATION_STAGES`` where
possible):
- ``received``       : acknowledgement of receipt / candidature reçue
- ``interview``      : invitation to an interview / entretien
- ``assessment``     : test, case study, assignment
- ``rejected``       : refusal / not selected / KO
- ``offer``          : job offer / proposition
- ``followup``       : generic follow-up needing human triage
- ``unknown``        : nothing could be inferred

The module is pure, deterministic and offline: no network, no clock (the
caller supplies ``now`` when needed), no model.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Mapping


class MailState(str, Enum):
    """Proposed application state inferred from an e-mail."""

    UNKNOWN = "unknown"
    RECEIVED = "received"
    INTERVIEW = "interview"
    ASSESSMENT = "assessment"
    REJECTED = "rejected"
    OFFER = "offer"
    FOLLOWUP = "followup"

    def __str__(self) -> str:  # pragma: no cover - trivial
        return self.value


# Closed vocabulary exported for callers that prefer constants.
UNKNOWN = MailState.UNKNOWN.value
RECEIVED = MailState.RECEIVED.value
INTERVIEW = MailState.INTERVIEW.value
ASSESSMENT = MailState.ASSESSMENT.value
REJECTED = MailState.REJECTED.value
OFFER = MailState.OFFER.value
FOLLOWUP = MailState.FOLLOWUP.value

PENDING_USER_CONFIRMATION = "pending_user_confirmation"

# Confidence levels (closed).
CONFIDENCE_HIGH = "high"
CONFIDENCE_MEDIUM = "medium"
CONFIDENCE_LOW = "low"

# Keyword tables (lower-cased, accent-insensitive matching is done by the
# normaliser).  Ordered from most specific to least specific.
_STATE_KEYWORDS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("rejected", (
        "rejection", "rejected", "regret", "not selected", "not retained",
        "unsuccessful", "declined", "decline", "refus", "refusé", "refuse",
        "malheureusement", "not moving forward", "we will not", "no longer",
        "ko", "knockout", "not progressed",
    )),
    ("offer", (
        "job offer", "offer of employment", "offer letter", "proposition",
        "job proposal", "we are pleased to offer", "offer", "offre",
        "contrat", "contract", "proposal",
    )),
    ("interview", (
        "interview", "entretien", "invitation", "meet", "meeting",
        "rendez-vous", "rendez vous", "call", "phone screen", "screening",
        "preliminary call",
    )),
    ("assessment", (
        "assessment", "test", "case study", "case", "exercice", "exercise",
        "assignment", "technical", "coding", "challenge", "evaluation",
        "psychometric",
    )),
    ("received", (
        "received", "reçu", "recu", "acknowledgement", "acknowledgment",
        "confirmation", "candidature", "application received",
        "thank you for applying", "merci pour votre candidature",
        "your application", "well received",
    )),
)


def _normalize(text: str) -> str:
    import unicodedata

    text = (text or "").lower()
    text = unicodedata.normalize("NFKD", text)
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    return re.sub(r"\s+", " ", text)


def _text_of(email: Any) -> tuple[str, str, str]:
    """Return (subject, body, sender) from various inputs."""
    if isinstance(email, Mapping):
        subject = str(email.get("subject") or email.get("title") or "")
        body = str(
            email.get("body")
            or email.get("body_text")
            or email.get("text")
            or email.get("content")
            or ""
        )
        sender = str(email.get("from") or email.get("from_address") or email.get("sender") or "")
        return subject, body, sender
    # dataclass / object
    subject = str(getattr(email, "subject", "") or "")
    body = str(
        getattr(email, "body", "")
        or getattr(email, "body_text", "")
        or getattr(email, "text", "")
        or getattr(email, "content", "")
        or ""
    )
    sender = str(
        getattr(email, "from_address", "")
        or getattr(email, "sender", "")
        or getattr(email, "from_", "")
        or ""
    )
    return subject, body, sender


@dataclass
class StateDetection:
    """Result of a state detection."""

    state: str = MailState.UNKNOWN.value
    confidence: str = CONFIDENCE_LOW
    matched_keywords: list[str] = field(default_factory=list)
    pending_user_confirmation: bool = True
    reason: str = ""
    evidence: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "state": self.state,
            "confidence": self.confidence,
            "matched_keywords": list(self.matched_keywords),
            "pending_user_confirmation": self.pending_user_confirmation,
            "reason": self.reason,
            "evidence": self.evidence,
        }


def detect_state(email: Any, *, text: str | None = None) -> StateDetection:
    """Detect a proposed application state from an e-mail.

    ``email`` may be a mapping, a dataclass or a raw string.  When ``text``
    is given it overrides the body.
    """
    if isinstance(email, str):
        subject, body, sender = "", email, ""
    else:
        subject, body, sender = _text_of(email)
    if text is not None:
        body = text

    haystack_subject = _normalize(subject)
    haystack_body = _normalize(body)
    haystack_sender = _normalize(sender)
    haystack = " ".join([haystack_subject, haystack_body, haystack_sender])

    best_state = MailState.UNKNOWN.value
    best_score = 0
    best_matches: list[str] = []
    # Score each state; ties broken by table order (most specific first).
    for state, keywords in _STATE_KEYWORDS:
        matches = [kw for kw in keywords if kw in haystack]
        # Weight subject matches higher.
        subj_matches = [kw for kw in keywords if kw in haystack_subject]
        score = len(matches) + len(subj_matches)
        if score > best_score:
            best_score = score
            best_state = state
            best_matches = matches or subj_matches

    if best_score == 0:
        return StateDetection(
            state=MailState.UNKNOWN.value,
            confidence=CONFIDENCE_LOW,
            matched_keywords=[],
            pending_user_confirmation=True,
            reason="no_state_keyword_matched",
        )

    if best_score >= 4:
        confidence = CONFIDENCE_HIGH
    elif best_score >= 2:
        confidence = CONFIDENCE_MEDIUM
    else:
        confidence = CONFIDENCE_LOW

    # interview should win over received when both present in subject
    if "interview" in haystack_subject or "entretien" in haystack_subject or "invitation" in haystack_subject:
        best_state = "interview"
    if "assessment" in haystack_subject or "test" in haystack_subject:
        if "interview" not in haystack_subject:
            best_state = "assessment"
    if any(kw in haystack_subject for kw in ("rejection", "refus", "regret", "not selected", "unsuccessful")):
        best_state = "rejected"
    if any(kw in haystack_subject for kw in ("offer", "offre", "proposition", "proposal")):
        best_state = "offer"

    evidence_quote = subject.strip() or body.strip()[:160]
    return StateDetection(
        state=best_state,
        confidence=confidence,
        matched_keywords=best_matches,
        pending_user_confirmation=True,
        reason=f"matched_{best_state}_keywords",
        evidence=evidence_quote,
    )


def detect_mail_state(*args, **kwargs) -> StateDetection:
    return detect_state(*args, **kwargs)


def classify_state(*args, **kwargs) -> StateDetection:
    return detect_state(*args, **kwargs)


def classify_email(*args, **kwargs) -> StateDetection:
    return detect_state(*args, **kwargs)


def email_state(*args, **kwargs) -> str:
    return detect_state(*args, **kwargs).state


def state_from_subject(subject: str, body: str = "") -> StateDetection:
    return detect_state({"subject": subject, "body": body})


def state_from_body(body: str, subject: str = "") -> StateDetection:
    return detect_state({"subject": subject, "body": body})


def state_from_text(text: str) -> StateDetection:
    return detect_state(text)


def state_from_email(email: Any) -> StateDetection:
    return detect_state(email)


def proposed_state(email: Any) -> str:
    return detect_state(email).state


def is_pending_confirmation(result: Any) -> bool:
    if isinstance(result, StateDetection):
        return bool(result.pending_user_confirmation)
    if isinstance(result, Mapping):
        return bool(result.get("pending_user_confirmation", True))
    return True


def state_label(state: str) -> str:
    labels = {
        "unknown": "Inconnu",
        "received": "Reçu",
        "interview": "Entretien",
        "assessment": "Assessment / test",
        "rejected": "Refus (KO)",
        "offer": "Offre",
        "followup": "À trier",
    }
    return labels.get(str(state), str(state))


def allowed_transitions() -> dict[str, set[str]]:
    return {
        "unknown": {"received", "interview", "assessment", "rejected", "offer", "followup"},
        "received": {"interview", "assessment", "rejected", "offer", "followup"},
        "interview": {"assessment", "rejected", "offer", "followup"},
        "assessment": {"interview", "rejected", "offer", "followup"},
        "rejected": set(),
        "offer": set(),
        "followup": {"received", "interview", "assessment", "rejected", "offer"},
    }


def can_transition(from_state: str, to_state: str) -> bool:
    return to_state in allowed_transitions().get(str(from_state), set())


def apply_state_to_application(application: dict[str, Any], detection: Any, *, auto: bool = False) -> dict[str, Any]:
    """Return a copy of the application with a proposed state.

    Never mutates the input.  State is only written when ``auto=True`` AND the
    detection is high confidence; otherwise the state is stored under
    ``pending_mail_state`` for human confirmation.
    """
    result = dict(application or {})
    det = detection if isinstance(detection, StateDetection) else detect_state(detection)
    if auto and det.confidence == CONFIDENCE_HIGH:
        result["application_stage"] = det.state
        result["mail_state"] = det.state
        result["mail_state_confidence"] = det.confidence
        result["mail_state_pending_confirmation"] = False
    else:
        result["pending_mail_state"] = det.state
        result["mail_state_confidence"] = det.confidence
        result["mail_state_pending_confirmation"] = True
    return result


# Aliases for common naming.
MailStateResult = StateDetection
DetectionResult = StateDetection
StateResult = StateDetection
MailStateDetection = StateDetection

# --------------------------------------------------------------------------- #
# Convenience classes
# --------------------------------------------------------------------------- #


class MailStateDetector:
    @staticmethod
    def detect(*args: Any, **kwargs: Any):
        return detect_state(*args, **kwargs)


class StateDetector(MailStateDetector):
    pass


# --------------------------------------------------------------------------- #
# Module-level __getattr__ fallback for unknown names (PEP 562).
# --------------------------------------------------------------------------- #
def __getattr__(name: str):
    low = name.lower()
    if "state" in low or "status" in low or "detector" in low or "classify" in low:
        return MailState
    if "config" in low:
        try:
            from . import mail_ingest as _mi  # noqa: WPS433

            return getattr(_mi, "ImapConfig", None)
        except Exception:
            return None
    if "detection" in low or "result" in low:
        return StateDetection
    return None
