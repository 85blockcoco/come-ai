"""Explain advertised education levels without inferring a candidate's degree.

This is a soft search preference, not an eligibility check or an offer filter.
Evidence always refers to a verbatim passage in the supplied offer.
"""

from __future__ import annotations

import re
from typing import Any


_FIELDS = ("role_level", "requirements", "eligibility_requirement", "description_original", "description")
_DESCRIPTION_FIELDS = {"description_original", "description"}
_LEVEL_PATTERNS = {
    "Bachelor / BBA / Bac+3": re.compile(
        r"\bbachelor(?:['’]s)?\b|\bbba\b|\bbac\s*\+\s*3\b|\blicence\b", re.I
    ),
    "Master 1 / Bac+4": re.compile(r"\bmaster\s*(?:1|I)\b|\bm\s*1\b|\bbac\s*\+\s*4\b", re.I),
    "Master 2 / MBA / Bac+5": re.compile(
        r"\bmaster\s*(?:2|II)\b|\bm\s*2\b|\bmba\b|\bbac\s*\+\s*5\b", re.I
    ),
}
_GENERIC_MASTER = re.compile(r"\bmaster(?:['’]s)?\b(?!\s*(?:[12]|II?\b))", re.I)
_EDUCATION = re.compile(
    r"\b(?:degree|diploma|education|qualifications?|university|college|student|students|"
    r"studying|enrolled|pursuing|dipl[oô]me|formation|[ée]tudiant\w*|cursus|titulaire|"
    r"niveau|pr[ée]par\w*|bac\s*\+)\b", re.I
)
_REQUIREMENT = re.compile(
    r"\b(?:required|requires?|requirement|must|minimum|candidate|candidates|eligibility|"
    r"qualification|requis\w*|exig[ée]\w*|recherch\w*|profil|admissib\w*)\b", re.I
)
_ADVANCED = re.compile(r"\b(?:ph\.?d\.?|doctorat|doctoral)\b", re.I)
_ALTERNATIVE = re.compile(r"\b(?:or|ou)\b", re.I)
_CONJUNCTION = re.compile(r"\b(?:and|et|both)\b|&", re.I)
_EXCLUSION = re.compile(r"\b(?:not\s+(?:accepted|eligible|sufficient)|no\s+bachelor|non\s+admis\w*|ne\s+suffit\s+pas)\b", re.I)


def _values(value: Any):
    if isinstance(value, str):
        yield value[:100_000]
    elif isinstance(value, (list, tuple)):
        for part in value[:100]:
            if isinstance(part, str):
                yield part[:100_000]


def _passages(text: str):
    # Split without rewriting text, so every returned passage is an exact substring.
    for part in re.split(r"(?:\r?\n|(?<=[.!?;])\s+|</(?:p|li|div)\s*>)", text, flags=re.I):
        part = part.strip()
        if part:
            yield part


def _generic_master_is_degree(passage: str, field: str) -> bool:
    """Do not read the verb 'master Python' as an academic requirement."""
    return bool(
        re.search(r"\bmaster(?:['’]s)(?:\s+degree)?\b|\bmaster\s+(?:degree|of|en|in)\b", passage, re.I)
        or (_EDUCATION.search(passage) and _GENERIC_MASTER.search(passage))
        or (field not in _DESCRIPTION_FIELDS and re.fullmatch(r"\s*master\s*", passage, re.I))
        or re.search(r"\bmaster\s+(?:required|requis|exig[ée])\b", passage, re.I)
    )


def assess_education_access(job: dict[str, Any], preference: str = "bachelor_m1_then_m2") -> dict[str, Any]:
    """Rank explicit advertised education requirements, never personal admission.

    ``preferred`` means Bachelor or M1 is explicitly accepted; ``consider`` means
    M2 or another explicit advanced level can be considered; ``to_verify`` means
    the advertised level or its combination is unclear. ``outside_preference``
    is reserved for an explicit doctoral-only requirement. Unknown values never
    become a confirmed Bachelor/M1 route. ``any`` makes the preference neutral.
    """
    if preference not in {"bachelor_m1_then_m2", "any"}:
        raise ValueError("Préférence de niveau d’études inconnue.")
    evidence: list[dict[str, str]] = []
    labels: list[str] = []
    decisions: list[str] = []
    for field in _FIELDS:
        for text in _values(job.get(field)):
            for passage in _passages(text):
                found = [label for label, pattern in _LEVEL_PATTERNS.items() if pattern.search(passage)]
                generic = bool(_GENERIC_MASTER.search(passage) and _generic_master_is_degree(passage, field))
                advanced = bool(_ADVANCED.search(passage))
                if not (found or generic or advanced):
                    continue
                # Descriptions need education/requirement context, unlike dedicated fields.
                if field in _DESCRIPTION_FIELDS and not (_EDUCATION.search(passage) or _REQUIREMENT.search(passage)):
                    continue
                # A driving licence is unrelated to the French academic "licence".
                if found == ["Bachelor / BBA / Bac+3"] and re.search(
                    r"\b(?:driving|driver['’]s)\s+licence\b", passage, re.I
                ):
                    continue
                if generic:
                    found.append("Master (niveau non précisé)")
                if advanced:
                    found.append("Doctorat")
                for label in found:
                    if label not in labels:
                        labels.append(label)
                evidence.append({"field": field, "passage": passage})
                low = any(label in found for label in ("Bachelor / BBA / Bac+3", "Master 1 / Bac+4"))
                high = "Master 2 / MBA / Bac+5" in found or advanced
                if _EXCLUSION.search(passage):
                    decisions.append("to_verify")
                elif low and high:
                    # A joint requirement cannot establish access with Bachelor alone.
                    if _ALTERNATIVE.search(passage) and not re.search(r"\bboth\b", passage, re.I):
                        decisions.append("preferred")
                    elif _CONJUNCTION.search(passage):
                        decisions.append("to_verify")
                    else:
                        decisions.append("to_verify")
                elif low:
                    decisions.append("preferred")
                elif "Master 2 / MBA / Bac+5" in found:
                    decisions.append("consider")
                elif advanced:
                    decisions.append("outside_preference")
                else:
                    decisions.append("to_verify")
    if preference == "any":
        status = "consider"
        reason = "Aucune préférence de niveau appliquée ; l’admissibilité personnelle reste à vérifier."
    elif not decisions:
        status = "to_verify"
        reason = "Aucune exigence académique explicite exploitable dans l’offre."
    elif "to_verify" in decisions:
        status = "to_verify"
        reason = "Le niveau demandé ou la combinaison des diplômes doit être vérifié dans les passages cités."
    elif len(set(decisions)) > 1:
        status = "to_verify"
        reason = "Des exigences académiques distinctes doivent être clarifiées ; aucun accès personnel n’est déduit."
    else:
        status = decisions[0]
        reason = {
            "preferred": "Un accès Bachelor ou Master 1 est explicitement mentionné dans l’offre.",
            "consider": "Un niveau Master 2 est explicitement mentionné ; cette offre reste à considérer.",
            "outside_preference": "Une exigence de doctorat est mentionnée ; elle dépasse la préférence Bachelor/M1 puis M2.",
        }[status]
    return {
        "status": status,
        "labels": labels,
        "evidence": evidence,
        "reason": reason,
        "priority_rank": {"preferred": 0, "consider": 1, "to_verify": 2, "outside_preference": 3}[status],
    }
