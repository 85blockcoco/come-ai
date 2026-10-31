"""J-1 interview briefing generator (SPEC-037).

Aggregates company facts, probable questions (from faq_mining), STAR worksheets,
admin blockers and CV sections to reread into a single :class:`BriefingDoc`.
Deterministic, local, no network.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Iterable


@dataclass
class BriefingDoc:
    application_id: str
    company_facts: list[str] = field(default_factory=list)
    top_questions: list[str] = field(default_factory=list)
    star_ready: list[str] = field(default_factory=list)
    admin_blockers: list[str] = field(default_factory=list)
    cv_section_reread: list[str] = field(default_factory=list)
    incomplete_sections: list[str] = field(default_factory=list)


def build_j1_briefing(
    application_id: str,
    *,
    company_facts: Iterable[str] | None = None,
    top_questions: Iterable[str] | None = None,
    star_worksheets: Iterable[dict[str, Any]] | None = None,
    admin_blockers: Iterable[str] | None = None,
    cv_sections: Iterable[str] | None = None,
    star_completeness_threshold: float = 0.8,
) -> BriefingDoc:
    company_facts = list(company_facts or [])
    top_questions = list(top_questions or [])
    star_worksheets = list(star_worksheets or [])
    admin_blockers = list(admin_blockers or [])
    cv_sections = list(cv_sections or [])

    # STAR worksheets with completeness >= threshold are "ready".
    star_ready: list[str] = []
    incomplete: list[str] = []
    for ws in star_worksheets:
        if not isinstance(ws, dict):
            continue
        name = str(ws.get("name") or ws.get("title") or ws.get("id") or "worksheet")
        completeness = float(ws.get("completeness", 0.0) or 0.0)
        if completeness >= star_completeness_threshold:
            star_ready.append(name)
        else:
            incomplete.append(name)

    doc = BriefingDoc(
        application_id=application_id,
        company_facts=company_facts,
        top_questions=top_questions,
        star_ready=star_ready,
        admin_blockers=admin_blockers,
        cv_section_reread=cv_sections,
        incomplete_sections=incomplete,
    )
    # If worksheets empty, mark explicitly (never hide).
    if not star_worksheets:
        if "STAR worksheets" not in doc.incomplete_sections:
            doc.incomplete_sections.append("STAR worksheets")
    return doc


def to_dict(doc: BriefingDoc) -> dict[str, Any]:
    return asdict(doc)