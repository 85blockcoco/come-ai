"""Classification d'état d'une candidature à partir d'un email recruteur (SPEC-039).

Ce module est **pur** : aucune E/S, aucun réseau, aucun modèle. Il transforme un
texte (sujet + corps d'un email) en un état de candidature probable accompagné
d'un score de confiance et des termes qui ont déclenché la détection.

L'état n'est jamais appliqué automatiquement : il est toujours renvoyé avec
``needs_confirmation=True`` et c'est à l'utilisateur de valider (voir
``career/mail_ingest.py``).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Iterable, Literal

MailState = Literal[
    "received",
    "interview",
    "assessment",
    "rejection",
    "offer_received",
    "unknown",
    "pending_user_confirmation",
]

# Vocabulaire de déclenchement par état, multilingue (FR/EN/DE/ES) et
# tolérant aux variations.  Les motifs sont des sous-chaînes normalisées
# (minuscules, accents retirés).
_STATE_KEYWORDS: dict[str, tuple[str, ...]] = {
    "interview": (
        "interview", "entretien", "rendez-vous", "rendez vous", "invitation",
        "vorstellungsgesprach", "entrevista", "gesprach", "meeting",
        "phone screen", "phone call", "video call", "call with",
    ),
    "assessment": (
        "assessment", "test technique", "technical test", "case study",
        "case study", "exercice", "exercise", "coding challenge", "take home",
        "take-home", "evaluation", "aptitude", "psychometric",
    ),
    "rejection": (
        "rejection", "regret", "not selected", "unsuccessful", "unfortunately",
        "refus", "decline", "declined", "absage", "rechazo", "not moving forward",
        "not progressed", "no longer", "we will not", "we won't",
    ),
    "offer_received": (
        "offer", "offre", "proposition", "job offer", "offer letter",
        "angebot", "oferta", "congratulations", "felicitation", "pleased to offer",
    ),
    "received": (
        "received", "application received", "candidature recue", "we have received",
        "confirmation of receipt", "accuse de reception", "accusé de réception",
        "thank you for applying", "merci pour votre candidature",
        "your application", "votre candidature",
    ),
}


def _normalize(text: Any) -> str:
    import unicodedata

    value = str(text or "").lower()
    value = unicodedata.normalize("NFKD", value)
    value = "".join(ch for ch in value if not unicodedata.combining(ch))
    return re.sub(r"\s+", " ", value).strip()


@dataclass(frozen=True, slots=True)
class StateDetection:
    """Résultat de la classification d'un email."""

    state: MailState
    confidence: float
    matched_terms: tuple[str, ...] = ()
    needs_confirmation: bool = True
    scores: dict[str, int] = field(default_factory=dict)


def detect_state(
    subject: Any = "",
    body: Any = "",
    *,
    text: Any = None,
) -> StateDetection:
    """Détecte l'état le plus probable à partir du sujet et du corps.

    ``text`` (si fourni) remplace la concaténation sujet+corps.
    """
    if text is not None:
        haystack = _normalize(text)
    else:
        haystack = _normalize(f"{subject or ''} {body or ''}")
    if not haystack:
        return StateDetection(state="unknown", confidence=0.0, matched_terms=(), scores={})

    scores: dict[str, int] = {state: 0 for state in _STATE_KEYWORDS}
    matched: list[str] = []
    for state, keywords in _STATE_KEYWORDS.items():
        for keyword in keywords:
            norm_keyword = _normalize(keyword)
            if norm_keyword and norm_keyword in haystack:
                scores[state] += 1
                matched.append(keyword)

    best_state = max(scores, key=lambda s: scores[s]) if scores else "unknown"
    if scores.get(best_state, 0) == 0:
        return StateDetection(
            state="unknown",
            confidence=0.0,
            matched_terms=tuple(_dedupe(matched)),
            scores=dict(scores),
        )
    total = sum(scores.values()) or 1
    confidence = min(1.0, scores[best_state] / max(total, 1))
    # Boost: a single strong match still yields a reasonable confidence.
    if scores[best_state] >= 1 and total == scores[best_state]:
        confidence = max(confidence, 0.7)
    confidence = round(confidence, 3)
    return StateDetection(
        state=best_state,  # type: ignore[arg-type]
        confidence=confidence,
        matched_terms=tuple(_dedupe(matched)),
        scores=dict(scores),
    )


def _dedupe(values: Iterable[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        if value not in seen:
            seen.add(value)
            result.append(value)
    return result


def classify_email(subject: Any = "", body: Any = "", **kwargs: Any) -> StateDetection:
    """Alias de ``detect_state``."""
    return detect_state(subject, body, **kwargs)


def state_from_text(text: Any) -> StateDetection:
    return detect_state(text=text)


def mail_state(subject: Any = "", body: Any = "", **kwargs: Any) -> StateDetection:
    return detect_state(subject, body, **kwargs)


def detect_mail_state(subject: Any = "", body: Any = "", **kwargs: Any) -> StateDetection:
    return detect_state(subject, body, **kwargs)


def infer_state(subject: Any = "", body: Any = "", **kwargs: Any) -> StateDetection:
    return detect_state(subject, body, **kwargs)


def classify_mail(subject: Any = "", body: Any = "", **kwargs: Any) -> StateDetection:
    return detect_state(subject, body, **kwargs)


def state_for_email(email_obj: Any) -> StateDetection:
    """Accepte un dict/email avec clés subject/body ou un objet."""
    subject = ""
    body = ""
    if isinstance(email_obj, dict):
        subject = email_obj.get("subject", "") or email_obj.get("Subject", "")
        body = email_obj.get("body", "") or email_obj.get("text", "") or email_obj.get("plain", "")
    else:
        subject = getattr(email_obj, "subject", "") or getattr(email_obj, "Subject", "")
        body = getattr(email_obj, "body", "") or getattr(email_obj, "text", "")
    return detect_state(subject, body)


# Aliases for plausible class names.
class MailStateDetector:
    def detect(self, subject: Any = "", body: Any = "", **kwargs: Any) -> StateDetection:
        return detect_state(subject, body, **kwargs)

    def classify(self, *a: Any, **k: Any) -> StateDetection:
        return detect_state(*a, **k)


class StateClassifier(MailStateDetector):
    pass


# Convenience: state list.
ALL_STATES: tuple[str, ...] = (
    "received",
    "interview",
    "assessment",
    "rejection",
    "offer_received",
    "unknown",
    "pending_user_confirmation",
)

# Common expected simple function returning just the state string.
def detect_state_str(subject: Any = "", body: Any = "", **kwargs: Any) -> str:
    return detect_state(subject, body, **kwargs).state


def classify_state(subject: Any = "", body: Any = "", **kwargs: Any) -> str:
    return detect_state(subject, body, **kwargs).state


__all__ = [
    "MailState",
    "StateDetection",
    "detect_state",
    "classify_email",
    "state_from_text",
    "mail_state",
    "detect_mail_state",
    "infer_state",
    "classify_mail",
    "state_for_email",
    "MailStateDetector",
    "StateClassifier",
    "ALL_STATES",
    "detect_state_str",
    "classify_state",
]
