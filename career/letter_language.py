"""Multilingual cover letter rendering with tone variants (N100-F02, N100-F03).

Letters are rendered from structured facts only — no translation of invented
content, no auto-send.  Deterministic, local, no network.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Iterable

LETTER_LANGS = ("fr", "en", "de", "es")
TONES = ("formal", "dynamic", "concise")

_GREETINGS = {"fr": "Madame, Monsieur,", "en": "Dear Sir or Madam,", "de": "Sehr geehrte Damen und Herren,", "es": "Estimados señores,"}

_CLOSINGS = {
    "fr": "Cordialement,",
    "en": "Yours sincerely,",
    "de": "Mit freundlichen Grüßen,",
    "es": "Atentamente,",
}

_OPENERS = {
    "fr": "Je me permets de vous adresser ma candidature pour le poste de {role} au sein de {company}.",
    "en": "I am writing to apply for the position of {role} at {company}.",
    "de": "hiermit bewerbe ich mich um die Stelle als {role} bei {company}.",
    "es": "Me dirijo a ustedes para postular al puesto de {role} en {company}.",
}

_EVIDENCE_INTRO = {
    "fr": "Mon profil s'appuie sur les éléments suivants :",
    "en": "My profile is based on the following facts:",
    "de": "Mein Profil stützt sich auf folgende Fakten:",
    "es": "Mi perfil se basa en los siguientes hechos:",
}

_TONE_SUFFIX = {
    "fr": {
        "formal": "",
        "dynamic": "\n\nJe suis disponible pour un échange dès cette semaine.",
        "concise": "",
    },
    "en": {
        "formal": "",
        "dynamic": "\n\nI am available for a call this week.",
        "concise": "",
    },
    "de": {"formal": "", "dynamic": "\n\nIch stehe für ein Gespräch diese Woche zur Verfügung.", "concise": ""},
    "es": {"formal": "", "dynamic": "\n\nEstoy disponible para una conversación esta semana.", "concise": ""},
}


@dataclass
class MultilingualLetter:
    candidate_name: str = ""
    role: str = ""
    company: str = ""
    language: str = "fr"
    tone: str = "formal"
    evidence: list[str] = field(default_factory=list)
    body: str = ""
    warnings: list[str] = field(default_factory=list)


def render_multilingual_letter(
    *,
    candidate_name: str = "",
    role: str = "",
    company: str = "",
    evidence: Iterable[str] = (),
    language: str = "fr",
    tone: str = "formal",
) -> MultilingualLetter:
    out = MultilingualLetter(
        candidate_name=candidate_name, role=role, company=company,
        evidence=[str(e) for e in (evidence or []) if str(e).strip()],
    )
    lang = (language or "fr").lower()
    if lang not in LETTER_LANGS:
        out.warnings.append(f"langue non supportée: {lang}")
        lang = "fr"
    t = (tone or "formal").lower()
    if t not in TONES:
        out.warnings.append(f"ton non supporté: {t}")
        t = "formal"
    out.language, out.tone = lang, t

    name = (candidate_name or "").strip()
    role_txt = (role or "").strip() or "—"
    company_txt = (company or "").strip()
    opener = _OPENERS[lang].format(role=role_txt, company=company_txt or "[ENTREPRISE]")
    if not company_txt:
        out.warnings.append("entreprise manquante")
    if not role_txt or role_txt == "—":
        out.warnings.append("rôle manquant")

    lines = [_GREETINGS[lang], "", opener]
    if out.evidence:
        lines += ["", _EVIDENCE_INTRO[lang], *(f"- {e}" for e in out.evidence)]
    else:
        placeholder = {
            "fr": "[À COMPLÉTER : ajouter des faits approuvés du profil.]",
            "en": "[TO COMPLETE: add approved facts from the profile.]",
            "de": "[AUSZUFÜLLEN: genehmigte Fakten hinzufügen.]",
            "es": "[POR COMPLETAR: añadir hechos aprobados del perfil.]",
        }
        lines += ["", placeholder[lang]]
    if t != "concise":
        lines.append(_TONE_SUFFIX[lang][t])
    lines += ["", _CLOSINGS[lang], name if name else "[NOM]"]
    out.body = "\n".join(lines).strip("\n")
    return out


def to_dict(l: MultilingualLetter) -> dict[str, Any]:
    return asdict(l)
