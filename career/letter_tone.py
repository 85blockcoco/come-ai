"""Tone adaptation for cover letters (SPEC-022).

Supported tones: formel, direct, startup, corporate.
"""

from __future__ import annotations

from typing import Any

TONES: tuple[str, ...] = ("formel", "direct", "startup", "corporate")


def normalize_tone(value: Any) -> str:
    text = str(value or "").strip().lower()
    aliases = {
        "formal": "formel",
        "formelle": "formel",
        "directe": "direct",
        "startuppy": "startup",
        "corporate": "corporate",
        "banque": "corporate",
        "bank": "corporate",
    }
    text = aliases.get(text, text)
    if text not in TONES:
        return "formel"
    return text


def tone_salutation(tone: str) -> str:
    tone = normalize_tone(tone)
    return {
        "formel": "Madame, Monsieur,",
        "direct": "Bonjour,",
        "startup": "Hello,",
        "corporate": "Dear Hiring Committee,",
    }[tone]


def tone_closing_line(tone: str) -> str:
    tone = normalize_tone(tone)
    return {
        "formel": "Je vous prie d'agréer, Madame, Monsieur, l'expression de mes salutations distinguées.",
        "direct": "Au plaisir d'échanger avec vous.",
        "startup": "Au plaisir de builder ensemble.",
        "corporate": "I remain at your disposal for any further discussion.",
    }[tone]


def adapt_text(text: str, tone: str) -> str:
    """Lightweight tone adaptation (no invention)."""
    tone = normalize_tone(tone)
    base = str(text or "").strip()
    if not base:
        return base
    if tone == "direct":
        return base.replace("Je suis vivement intéressé(e)", "Je postule pour")
    if tone == "startup":
        return base.replace("Mes expériences démontrent", "J'ai shippé")
    if tone == "corporate":
        return base.replace("Je suis vivement intéressé(e)", "I am keenly interested")
    return base


def apply_tone_to_paragraphs(paragraphs: list[Any], tone: str) -> list[Any]:
    tone = normalize_tone(tone)
    out = []
    for p in paragraphs or []:
        text = getattr(p, "text", None)
        if text is None and isinstance(p, dict):
            text = p.get("text", "")
        new_text = adapt_text(str(text or ""), tone)
        if hasattr(p, "text"):
            p.text = new_text
            out.append(p)
        elif isinstance(p, dict):
            new_p = dict(p)
            new_p["text"] = new_text
            out.append(new_p)
        else:
            out.append(p)
    return out


def tone_for_company(company: str | None = None) -> str:
    # heuristic: banks/finance -> corporate
    c = str(company or "").lower()
    if any(k in c for k in ("bank", "banque", "finance", "capital", "asset")):
        return "corporate"
    return "formel"


__all__ = [
    "TONES",
    "normalize_tone",
    "tone_salutation",
    "tone_closing_line",
    "adapt_text",
    "apply_tone_to_paragraphs",
    "tone_for_company",
]


# Compatibility aliases
apply_tone = apply_tone_to_paragraphs
adapt = adapt_text
