"""Claim-level audit for application documents (SPEC-042 / CVBOOST-77).

Splits a document into sentence-level claims and labels each one against a set
of approved evidence items:

    supported | inflated | out_of_context | invented | unverifiable

No probabilistic AI: deterministic rules + lexicon only.
"""

from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass, field
from typing import Iterable

# Exaggeration lexicon (versioned, editable by the user).  Each entry maps a
# term to a minimum evidence requirement expressed as a keyword that must be
# present in the approved evidence for the claim to be "supported".
EXAGGERATION_TERMS: dict[str, str] = {
    "expert": "years",
    "senior": "years",
    "lead": "years",
    "master": "certification",
    "guru": "years",
}

# ATS keyword-stuffing threshold: same keyword repeated more than this many
# times in a single document triggers a "stuffing" flag.
ATS_STUFFING_THRESHOLD = 3


@dataclass
class Claim:
    text: str
    label: str  # supported | inflated | out_of_context | invented | unverifiable
    evidence: list[str] = field(default_factory=list)
    missing: str | None = None
    suggestion: str | None = None


@dataclass
class ClaimReport:
    claims: list[Claim]
    score: float
    summary: dict[str, int]


def _split_sentences(text: str) -> list[str]:
    if not text:
        return []
    # Split on sentence terminators, keep non-empty.
    parts = re.split(r"(?<=[.!?])\s+", text.strip())
    out = [p.strip() for p in parts if p.strip()]
    if not out and text.strip():
        out = [text.strip()]
    return out


def _has_evidence(claim: str, evidence: Iterable[str]) -> bool:
    cl = claim.lower()
    for ev in evidence:
        evl = str(ev).lower()
        # A claim is "supported" if a substantial token of the evidence appears.
        tokens = [t for t in re.findall(r"[a-zà-ÿ]{4,}", evl) if t not in {"avec", "pour", "dans"}]
        if any(tok in cl for tok in tokens[:6]):
            return True
    return False


def _is_inflated(claim: str) -> bool:
    cl = claim.lower()
    for term in EXAGGERATION_TERMS:
        if re.search(r"\b" + re.escape(term) + r"\b", cl):
            return True
    return False


def _is_out_of_context(claim: str, evidence: Iterable[str]) -> bool:
    # A numeric claim (e.g. "increased sales by 40%") is out of context if
    # the number cannot be traced to any evidence item.
    numbers = re.findall(r"\d+(?:[.,]\d+)?%?", claim)
    if not numbers:
        return False
    ev_text = " ".join(str(e) for e in evidence).lower()
    for num in numbers:
        if num not in ev_text:
            return True
    return False


def check_claims(document: str, evidence: Iterable[str] | None = None) -> ClaimReport:
    evidence = list(evidence or [])
    sentences = _split_sentences(document)
    claims: list[Claim] = []
    counts: dict[str, int] = {
        "supported": 0, "inflated": 0, "out_of_context": 0,
        "invented": 0, "unverifiable": 0,
    }
    for sent in sentences:
        ev_for_claim = [e for e in evidence if _has_evidence(sent, [e])]
        if not evidence:
            label = "unverifiable"
            missing = "aucune preuve fournie"
            suggestion = "Fournir une preuve approuvée pour ce fait."
        elif _has_evidence(sent, evidence):
            if _is_inflated(sent):
                label = "inflated"
                missing = "terme exagéré non appuyé par les preuves"
                suggestion = "Reformuler sans terme exagéré ou ajouter la preuve correspondante."
            elif _is_out_of_context(sent, evidence):
                label = "out_of_context"
                missing = "chiffre/contexte non traçable"
                suggestion = "Resituer le chiffre dans son contexte d'origine."
            else:
                label = "supported"
                missing = None
                suggestion = None
        else:
            # No matching evidence: invented if it asserts a fact, else unverifiable.
            if re.search(r"\b(j'ai|je suis|j'ai réalisé|managed|led|built|created)\b", sent.lower()):
                label = "invented"
                missing = "aucune preuve pour ce fait affirmé"
                suggestion = "S'appuyer sur les faits déjà approuvés ou retirer l'affirmation."
            else:
                label = "unverifiable"
                missing = "preuve non trouvée"
                suggestion = "Ajouter une preuve ou reformuler."
        claims.append(Claim(text=sent, label=label, evidence=ev_for_claim, missing=missing, suggestion=suggestion))
        counts[label] += 1

    total = len(claims) or 1
    supported = counts["supported"]
    score = round(100.0 * supported / total, 1)
    # Penalize exaggerations.
    score = max(0.0, score - 5.0 * counts["inflated"] - 10.0 * counts["invented"])
    return ClaimReport(claims=claims, score=score, summary=counts)


def ats_keyword_stuffing(text: str, threshold: int = ATS_STUFFING_THRESHOLD) -> list[str]:
    """Return keywords repeated more than ``threshold`` times."""
    tokens = re.findall(r"[a-zà-ÿ]{4,}", (text or "").lower())
    c = Counter(tokens)
    return [w for w, n in c.items() if n > threshold]