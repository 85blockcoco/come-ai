"""Cover letter templates by sector (N100-F08).

Templates are structural: they affect wording focus only.  Facts are never
invented — the caller supplies approved evidence.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

TEMPLATES = ("finance", "consulting", "tech", "default")

_FOCUS = {
    "finance": "rigueur analytique et intérêt pour les marchés",
    "consulting": "capacité de résolution de problèmes et travail en équipe",
    "tech": "curiosité technique et goût du concret",
    "default": "motivation et sérieux démontrés",
}


@dataclass
class LetterTemplate:
    template_id: str
    focus: str
    requires: list[str] = field(default_factory=list)


def describe_template(template_id: str) -> LetterTemplate:
    tid = template_id if template_id in TEMPLATES else "default"
    return LetterTemplate(template_id=tid, focus=_FOCUS[tid])


def pick_letter_template(text: str) -> LetterTemplate:
    t = (text or "").lower()
    scores = {k: 0 for k in _FOCUS}
    kws = {
        "finance": ["finance", "banque", "asset", "m&a", "trading", "audit", "investment"],
        "consulting": ["consulting", "conseil", "strategy", "stratégie", "advisory"],
        "tech": ["tech", "software", "data", "develop", "code", "ingénier"],
    }
    for key, words in kws.items():
        for w in words:
            if w in t:
                scores[key] += 1
    best = max(scores, key=scores.get)
    if scores[best] == 0:
        return describe_template("default")
    return describe_template(best)


def to_dict(t: LetterTemplate) -> dict[str, Any]:
    return asdict(t)
