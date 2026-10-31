"""Targeted cover letter generation (SPEC N100-F01).

Generates a cover letter from approved evidence only.  No invented facts,
no auto-send.  Deterministic, local, no network.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Iterable


@dataclass
class CoverLetter:
    recipient: str = ""
    subject: str = ""
    body: str = ""
    language: str = "fr"
    evidence_used: list[str] = field(default_factory=list)
    missing_evidence: list[str] = field(default_factory=list)


def build_cover_letter(
    *,
    candidate_name: str,
    target_role: str,
    company: str,
    evidence: Iterable[str],
    language: str = "fr",
    tone: str = "formal",
) -> CoverLetter:
    evidence = [e for e in (evidence or []) if str(e).strip()]
    letter = CoverLetter(recipient=company, subject=f"Candidature — {target_role}", language=language)

    if not evidence:
        letter.body = (
            f"Madame, Monsieur,\n\n"
            f"Je me permets de vous adresser ma candidature pour le poste de {target_role} "
            f"au sein de {company}.\n\n"
            f"[À COMPLÉTER : ajouter des faits approuvés du profil.]\n\n"
            f"Cordialement,\n{candidate_name}"
        )
        letter.missing_evidence.append("aucune preuve fournie")
        return letter

    # Build body from approved evidence only.
    bullets = "\n".join(f"- {e}" for e in evidence)
    letter.body = (
        f"Madame, Monsieur,\n\n"
        f"Je me permets de vous adresser ma candidature pour le poste de {target_role} "
        f"au sein de {company}.\n\n"
        f"Mon profil s'appuie sur les éléments suivants :\n{bullets}\n\n"
        f"Je serais ravi(e) d'échanger avec vous.\n\n"
        f"Cordialement,\n{candidate_name}"
    )
    letter.evidence_used = list(evidence)
    return letter


def to_dict(letter: CoverLetter) -> dict[str, Any]:
    return asdict(letter)