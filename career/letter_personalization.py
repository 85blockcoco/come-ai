"""Company personalization for cover letters (N100-F04).

Adds a company-specific paragraph built ONLY from approved facts about the
company.  If no facts are supplied, a placeholder is inserted — never an
invented detail.
"""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass
from typing import Any


_PLACEHOLDER = "[À COMPLÉTER : ajout d'un fait approuvé sur l'entreprise.]"


@dataclass
class PersonalizationResult:
    personalized_body: str
    facts_used: list[str]
    uses_placeholder: bool
    warnings: list[str] = None  # type: ignore[assignment]

    def __post_init__(self) -> None:
        if self.warnings is None:
            self.warnings = []


def personalize_letter(
    body: str,
    *,
    company: str = "",
    company_facts: list[str] | None = None,
    insert_before_closing: bool = True,
) -> PersonalizationResult:
    facts = [str(f).strip() for f in (company_facts or []) if str(f).strip()]
    warnings: list[str] = []
    if not (body or "").strip():
        warnings.append("corps de lettre vide")
    if not (company or "").strip():
        warnings.append("entreprise manquante")
    if not facts:
        warning_tpl = "aucun fait approuvé sur {c}"
        warnings.append(warning_tpl.format(c=(company or "l'entreprise"))) if company else warnings.append("aucun fait approuvé")

    if facts:
        para = f"\n\nVotre société {company or '[ENTREPRISE]'} : " + " ".join(facts) + "\n"
    else:
        para = f"\n\n{_PLACEHOLDER}\n"

    text = body or ""
    if insert_before_closing:
        m = re.search(r"\n(Cordialement|Yours sincerely|Mit freundlich|Atentamente)", text)
        if m:
            text = text[: m.start()] + para + text[m.start() :]
        else:
            text = text + para
    else:
        text = text + para
    return PersonalizationResult(
        personalized_body=text.strip("\n"),
        facts_used=facts,
        uses_placeholder=not facts,
        warnings=warnings,
    )


def to_dict(r: PersonalizationResult) -> dict[str, Any]:
    return asdict(r)
