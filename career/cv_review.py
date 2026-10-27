"""Evidence-backed CV review workspace (SPEC-004).

The targeted CV generator exists (SK-11) but nothing let the person read what
the generator actually changed, prove it, and refuse it.  This module is the
pure core of that review workspace:

* every adaptation of the CV is one :class:`ReviewBlock` (source wording,
  proposed wording, proof, decision);
* the difference between the two is computed locally with
  :mod:`difflib` — no model, no network;
* the export is gated: a critical block (``experiences``, ``skills``) that is
  still undecided without proof, or that still carries an unfilled proof
  marker, blocks the DOCX export.

Everything in this module is a pure function of its arguments: no clock, no
filesystem, no randomness, no network.  The timestamp and the identifier are
injected by the caller so the same inputs always produce the same workspace.

Vocabulary note: the five sections required by the specification
(``experiences``, ``skills``, ``education``, ``projects``, ``languages``) are
implemented, plus ``certifications`` because the targeted variants emit a
certification section (the local profile has no certification field, so that
section only ever holds a placeholder).  The extra value is documented in the
mission report and never blocks the export on its own.
"""

from __future__ import annotations

import difflib
import re
import unicodedata
from dataclasses import dataclass, replace
from typing import Any, Iterable, Literal, Mapping, Sequence

from career.application_studio import (
    PLACEHOLDER_MARKER,
    SECTION_FIELDS,
    SUMMARY_HEADING,
    KitGap,
    KitSection,
    plan_kit_gaps,
    plan_kit_sections,
    plan_kit_summary,
    variant_text,
)
from career.cv_fit import CoverageResult
from career.cv_variants import CVVariant


ReviewSection = Literal[
    "experiences",
    "skills",
    "education",
    "projects",
    "languages",
    "certifications",
]
ReviewStatus = Literal["pending", "accepted", "rejected", "modified", "verified"]
DiffKind = Literal["equal", "insert", "delete"]

#: Sections whose content decides the export.
CRITICAL_SECTIONS: tuple[str, ...] = ("experiences", "skills")
#: Statuses the person can set from the interface.
USER_DECISION_STATUSES: tuple[str, ...] = ("accepted", "rejected", "modified", "pending")
#: Statuses that mean "the person (or the direct proof) has settled this block".
DECIDED_STATUSES: tuple[str, ...] = ("verified", "accepted", "modified", "rejected")
#: Profile field → review section.
SECTION_BY_FIELD: dict[str, str] = {
    "experience": "experiences",
    "skills": "skills",
    "education": "education",
    "projects": "projects",
    "languages": "languages",
    "certifications": "certifications",
}
DEFAULT_SECTION = "experiences"
#: Requirement wording (canonical CV section names) → review section.
SECTION_BY_REQUIREMENT: dict[str, str] = {
    "experience": "experiences",
    "experiences": "experiences",
    "formation": "education",
    "education": "education",
    "competences": "skills",
    "skills": "skills",
    "langues": "languages",
    "languages": "languages",
    "projets": "projects",
    "projects": "projects",
    "certifications": "certifications",
}
#: A marker is a bracketed note that carries at least one letter: "[2024]" is
#: a date, "[AJOUTER PREUVE CHIFFRÉE]" is a proof still to be added.
PLACEHOLDER_PATTERN = re.compile(r"\[[^\[\]\n]*[^\W\d_][^\[\]\n]*\]")
#: Longest wording a decision may quote back to the server (the reviewed
#: proposal).  A profile line can be several thousand characters long, so the
#: limit has to stay well above the length of a profile field.
REVIEWED_TEXT_LIMIT = 20_000
_TOKEN_PATTERN = re.compile(r"\S+\s*")


@dataclass(frozen=True, slots=True)
class EvidenceRef:
    """One exact citation backing a proposed line.

    ``source`` names the local field the quote comes from, ``quote`` is the
    verbatim excerpt and ``offset`` is its position inside that field, so the
    reader can locate the proof without trusting the wording around it.
    """

    source: str
    quote: str
    offset: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {"source": self.source, "quote": self.quote, "offset": self.offset}


@dataclass(frozen=True, slots=True)
class DiffSegment:
    """One fragment of the word-level difference between two texts."""

    kind: DiffKind
    text: str

    def to_dict(self) -> dict[str, Any]:
        return {"kind": self.kind, "text": self.text}


@dataclass(frozen=True, slots=True)
class ReviewHeader:
    """The factual header of the CV (name, contacts, graduation)."""

    display_name: str = ""
    contact_line: str = ""
    education_line: str = ""


@dataclass(frozen=True, slots=True)
class ReviewBlock:
    """One reviewable unit of the targeted CV."""

    block_id: str
    section: ReviewSection
    source_text: str
    proposed_text: str
    status: ReviewStatus
    evidence: list[EvidenceRef] | None
    placeholder_reason: str | None
    user_text: str | None
    decided_at: str | None
    decided_by: str
    heading: str = ""
    index: int = 0
    label: str = ""

    @property
    def critical(self) -> bool:
        return self.section in CRITICAL_SECTIONS

    @property
    def resolved(self) -> bool:
        return self.status in DECIDED_STATUSES

    @property
    def title(self) -> str:
        """Short label used by the interface and by the export messages."""

        return self.label or self.heading or self.block_id


@dataclass(frozen=True, slots=True)
class ReviewWorkspace:
    """The complete review state for one application and one CV variant."""

    application_id: str
    job_id: str
    variant_id: str
    language: str
    blocks: list[ReviewBlock]
    created_at: str
    updated_at: str
    header: ReviewHeader = ReviewHeader()
    source_document: str = ""
    invalidated_blocks: list[str] | None = None


@dataclass(frozen=True, slots=True)
class ReviewEvent:
    """One immutable entry of the decision history.

    The event carries the wording that was read when the decision was taken,
    so the history alone is enough to replay the decisions and to prove that
    a decision always applied to the exact text the person saw.
    """

    event_id: str
    application_id: str
    block_id: str
    from_status: str
    to_status: str
    user_text: str
    decided_at: str
    decided_by: str
    sequence: int
    variant_id: str = ""
    proposed_text: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "event_id": self.event_id,
            "application_id": self.application_id,
            "block_id": self.block_id,
            "from_status": self.from_status,
            "to_status": self.to_status,
            "user_text": self.user_text,
            "decided_at": self.decided_at,
            "decided_by": self.decided_by,
            "sequence": self.sequence,
            "variant_id": self.variant_id,
            "proposed_text": self.proposed_text,
        }


# ---------------------------------------------------------------------------
# Pure helpers
# ---------------------------------------------------------------------------


def _text(value: Any, limit: int = 12_000) -> str:
    return str(value or "").replace("\x00", "").strip()[:limit]


def _normalized(value: Any) -> str:
    """Case-folded and accent-free text, used to match section names."""

    decomposed = unicodedata.normalize("NFKD", str(value or "").casefold())
    return "".join(character for character in decomposed if not unicodedata.combining(character)).strip()


def _slug(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", _normalized(value)).strip("-")
    return slug or "block"


def _offset_of(value: Any, needle: str) -> int:
    """Position of ``needle`` inside the source field, 0 when not found."""

    haystack = str(value or "")
    if not needle:
        return 0
    offset = haystack.find(needle)
    return offset if offset >= 0 else 0


def contains_placeholder(text: str) -> bool:
    """Tell whether a text still carries an unfilled proof marker."""

    return bool(PLACEHOLDER_PATTERN.search(text or ""))


def effective_text(block: ReviewBlock) -> str:
    """The wording this block contributes to the exported CV.

    Only a settled block may carry an adaptation: a pending or rejected block
    falls back to the source wording, so no unreviewed proposal can reach the
    export.
    """

    if block.status == "modified" and block.user_text is not None:
        return block.user_text
    if block.status in ("accepted", "verified"):
        return block.proposed_text
    return block.source_text


def evidence_state(block: ReviewBlock) -> str:
    """Badge of the proof behind a block: verified, to_verify, placeholder."""

    if block.placeholder_reason and contains_placeholder(effective_text(block)):
        return "placeholder"
    if block.status == "pending":
        return "to_verify"
    if block.evidence:
        return "verified"
    return "decided"


def diff_segments(source: str, proposed: str) -> list[DiffSegment]:
    """Word-level difference between the source and the proposed wording.

    ``difflib.SequenceMatcher`` compares word tokens (words keep their
    trailing space) so the reader sees the exact fragments that changed
    instead of a whole-line replacement.
    """

    left = _TOKEN_PATTERN.findall(source or "")
    right = _TOKEN_PATTERN.findall(proposed or "")
    segments: list[DiffSegment] = []
    matcher = difflib.SequenceMatcher(a=left, b=right, autojunk=False)
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag == "equal":
            segments.append(DiffSegment("equal", "".join(left[i1:i2])))
        elif tag == "delete":
            segments.append(DiffSegment("delete", "".join(left[i1:i2])))
        elif tag == "insert":
            segments.append(DiffSegment("insert", "".join(right[j1:j2])))
        else:
            segments.append(DiffSegment("delete", "".join(left[i1:i2])))
            segments.append(DiffSegment("insert", "".join(right[j1:j2])))
    return _merge_segments(segments)


def _merge_segments(segments: Iterable[DiffSegment]) -> list[DiffSegment]:
    merged: list[DiffSegment] = []
    for segment in segments:
        if not segment.text:
            continue
        if merged and merged[-1].kind == segment.kind:
            merged[-1] = DiffSegment(segment.kind, merged[-1].text + segment.text)
        else:
            merged.append(segment)
    return merged


def _header_from_profile(profile: Mapping[str, Any]) -> ReviewHeader:
    contacts = " · ".join(
        part
        for part in (
            _text(profile.get("contact_email"), 320),
            _text(profile.get("contact_phone"), 80),
            _text(profile.get("linkedin_url"), 500),
        )
        if part
    )
    return ReviewHeader(
        display_name=_text(profile.get("display_name"), 160),
        contact_line=contacts,
        education_line=_text(profile.get("education"), 1_000),
    )


def _section_kind(section: KitSection) -> str:
    return SECTION_BY_FIELD.get(section.field, DEFAULT_SECTION)


def _verified_status(line: str, rendered: str, variant: CVVariant) -> ReviewStatus:
    """A proposal that only re-spells the proven line is auto-verified.

    The variant adapter is deterministic and orthographic (en-GB vs en-US
    spellings), so the proof stays valid.  Any other transformation would
    leave the block pending and force an explicit decision.
    """

    if rendered == variant_text(line, variant):
        return "verified"
    return "pending"


# ---------------------------------------------------------------------------
# Workspace construction
# ---------------------------------------------------------------------------


def build_workspace(
    application_id: str,
    *,
    job: Mapping[str, Any] | None = None,
    job_id: str = "",
    variant: CVVariant | None = None,
    language: str = "fr",
    profile: Mapping[str, Any] | None = None,
    coverage: CoverageResult | None = None,
    created_at: str = "",
    source_document: str = "",
) -> ReviewWorkspace:
    """Build the review workspace of one application.

    Pure: the same offer, profile, variant and coverage always produce the
    same blocks, in the same order, with the same identifiers.  The caller
    injects the timestamp so the result never depends on a clock.
    """

    profile_data = dict(profile or {})
    job_data = dict(job or {})
    blocks: list[ReviewBlock] = []

    if variant is not None:
        blocks.extend(_summary_block(job_data, profile_data, variant))
        for section in plan_kit_sections(profile_data, variant):
            blocks.extend(_section_blocks(section, profile_data, variant))
        gaps = plan_kit_gaps(coverage) if coverage is not None else []
        for gap in gaps:
            blocks.append(_gap_block(gap, variant))
    blocks = _unique_block_ids(blocks)

    return ReviewWorkspace(
        application_id=_text(application_id, 80),
        job_id=_text(job_id, 80),
        variant_id=variant.id if variant is not None else "",
        language=_text(language, 16) or "fr",
        blocks=blocks,
        created_at=created_at,
        updated_at=created_at,
        header=_header_from_profile(profile_data),
        source_document=_text(source_document, 200),
        invalidated_blocks=[],
    )


def _summary_block(
    job: Mapping[str, Any], profile: Mapping[str, Any], variant: CVVariant
) -> list[ReviewBlock]:
    """The generated professional summary, reviewed like any other block."""

    summary = plan_kit_summary(job, profile, variant)
    if summary.placeholder:
        return [
            ReviewBlock(
                block_id="summary",
                section="skills",
                heading=summary.heading,
                source_text="",
                proposed_text=summary.text,
                status="pending",
                evidence=None,
                placeholder_reason=(
                    "Aucune compétence enregistrée dans le profil : le résumé doit être écrit ou refusé."
                ),
                user_text=None,
                decided_at=None,
                decided_by="",
                index=0,
                label="Résumé professionnel",
            )
        ]
    return [
        ReviewBlock(
            block_id="summary",
            section="skills",
            heading=summary.heading,
            source_text=summary.source_text,
            proposed_text=summary.text,
            status="pending",
            evidence=[
                EvidenceRef(
                    source="profile.skills",
                    quote=summary.source_text,
                    offset=_offset_of(profile.get("skills"), summary.source_text),
                )
            ],
            placeholder_reason=None,
            user_text=None,
            decided_at=None,
            decided_by="",
            index=0,
            label="Résumé professionnel",
        )
    ]


def _section_blocks(
    section: KitSection, profile: Mapping[str, Any], variant: CVVariant
) -> list[ReviewBlock]:
    """One block per planned line, plus one block for an empty section."""

    kind = _section_kind(section)
    if section.placeholder:
        return [
            ReviewBlock(
                block_id=_slug(f"{kind}:{section.heading}:placeholder"),
                section=kind,
                heading=section.heading,
                source_text="",
                proposed_text=PLACEHOLDER_MARKER,
                status="pending",
                evidence=None,
                placeholder_reason=(
                    f"Aucune ligne enregistrée dans le profil pour la section « {section.heading} »."
                ),
                user_text=None,
                decided_at=None,
                decided_by="",
                index=0,
                label=f"{section.heading} — section vide",
            )
        ]
    blocks: list[ReviewBlock] = []
    field_value = profile.get(section.field)
    for index, (line, rendered) in enumerate(zip(section.lines, section.rendered)):
        blocks.append(
            ReviewBlock(
                block_id=_slug(f"{kind}:{section.heading}:{index}"),
                section=kind,
                heading=section.heading,
                source_text=line,
                proposed_text=rendered,
                status=_verified_status(line, rendered, variant),
                evidence=[
                    EvidenceRef(
                        source=f"profile.{section.field}",
                        quote=line,
                        offset=_offset_of(field_value, line),
                    )
                ],
                placeholder_reason=None,
                user_text=None,
                decided_at=None,
                decided_by="",
                index=index,
                label=section.heading,
            )
        )
    return blocks


def _gap_section(gap: KitGap) -> str:
    """Section a requirement gap belongs to, from its canonical wording."""

    return SECTION_BY_REQUIREMENT.get(_normalized(gap.requirement), DEFAULT_SECTION)


def _gap_heading(gap: KitGap, variant: CVVariant) -> str:
    """Heading of the variant where the requirement would belong."""

    kind = _gap_section(gap)
    for heading in variant.section_order:
        if SECTION_BY_FIELD.get(SECTION_FIELDS.get(heading.casefold(), ""), "") == kind:
            return heading
    return "Exigences de l'offre"


def _gap_block(gap: KitGap, variant: CVVariant) -> ReviewBlock:
    """One offer requirement that has no supporting profile evidence."""

    kind = _gap_section(gap)
    return ReviewBlock(
        block_id=_slug(f"requirement:{gap.requirement}"),
        section=kind,
        heading=_gap_heading(gap, variant),
        source_text="",
        proposed_text=gap.text,
        status="pending",
        evidence=None,
        placeholder_reason=(
            f"Exigence {gap.requirement_type} sans preuve dans le profil : « {gap.requirement} »."
        ),
        user_text=None,
        decided_at=None,
        decided_by="",
        index=0,
        label=f"Exigence : {gap.requirement}",
    )


def _unique_block_ids(blocks: list[ReviewBlock]) -> list[ReviewBlock]:
    """Guarantee one identifier per block, so a decision targets one block."""

    seen: set[str] = set()
    unique: list[ReviewBlock] = []
    for block in blocks:
        block_id = block.block_id
        suffix = 2
        while block_id in seen:
            block_id = f"{block.block_id}-{suffix}"
            suffix += 1
        seen.add(block_id)
        unique.append(block if block_id == block.block_id else replace(block, block_id=block_id))
    return unique


# ---------------------------------------------------------------------------
# Decisions
# ---------------------------------------------------------------------------


def find_block(workspace: ReviewWorkspace, block_id: str) -> ReviewBlock | None:
    for block in workspace.blocks:
        if block.block_id == block_id:
            return block
    return None


def apply_decision(
    workspace: ReviewWorkspace,
    block_id: str,
    status: str,
    *,
    user_text: str = "",
    decided_at: str = "",
    decided_by: str = "user",
) -> ReviewWorkspace:
    """Return a new workspace with one decision applied.

    Pure: the input workspace is never mutated, so a rejected decision can be
    replayed from the stored history without side effects.
    """

    if status not in USER_DECISION_STATUSES:
        raise ValueError(f"Statut de décision inconnu : {status}")
    if status == "modified" and not _text(user_text, 4_000):
        raise ValueError("Un bloc modifié doit porter le texte validé par la personne.")
    blocks: list[ReviewBlock] = []
    found = False
    for block in workspace.blocks:
        if block.block_id != block_id:
            blocks.append(block)
            continue
        found = True
        blocks.append(
            replace(
                block,
                status=status,  # type: ignore[arg-type]
                user_text=_text(user_text, 4_000) if status == "modified" else None,
                decided_at=decided_at or None,
                decided_by=decided_by if decided_at else block.decided_by,
            )
        )
    if not found:
        raise KeyError(block_id)
    return replace(
        workspace,
        blocks=blocks,
        updated_at=decided_at or workspace.updated_at,
    )


def merge_decisions(
    fresh: ReviewWorkspace, saved: ReviewWorkspace | None
) -> tuple[ReviewWorkspace, list[str]]:
    """Replay the stored decisions onto a freshly built workspace.

    A decision is only replayed when the proposed wording did not change in
    the meantime: a decision always applies to the exact text the person
    read.  A block whose proposal changed goes back to ``pending`` and is
    reported as invalidated.
    """

    if saved is None:
        return fresh, []
    previous_by_id = {block.block_id: block for block in saved.blocks}
    blocks: list[ReviewBlock] = []
    invalidated: list[str] = []
    for block in fresh.blocks:
        previous = previous_by_id.get(block.block_id)
        if previous is None or previous.status == "pending":
            blocks.append(block)
            continue
        if previous.proposed_text != block.proposed_text:
            invalidated.append(block.block_id)
            blocks.append(block)
            continue
        blocks.append(
            replace(
                block,
                status=previous.status,
                user_text=previous.user_text,
                decided_at=previous.decided_at,
                decided_by=previous.decided_by,
            )
        )
    return replace(fresh, blocks=blocks, invalidated_blocks=invalidated), invalidated


def replay_events(
    fresh: ReviewWorkspace, events: Sequence[ReviewEvent]
) -> tuple[ReviewWorkspace, list[str]]:
    """Rebuild the decisions from the immutable history.

    The history is the source of truth: when the state file is missing or
    unreadable, the decisions are replayed from the recorded events.  An
    event is applied only when it carries a valid status and the exact
    wording that was read: an event whose wording no longer matches the
    current proposal is ignored, exactly like a stale state.
    """

    blocks = list(fresh.blocks)
    invalidated: list[str] = []
    for event in events:
        if event.variant_id and event.variant_id != fresh.variant_id:
            continue
        if event.to_status not in USER_DECISION_STATUSES:
            # Only a person can decide: a system status in the history is
            # ignored rather than trusted.
            continue
        index = next(
            (position for position, block in enumerate(blocks) if block.block_id == event.block_id),
            None,
        )
        if index is None:
            continue
        block = blocks[index]
        if event.proposed_text != block.proposed_text:
            if block.block_id not in invalidated:
                invalidated.append(block.block_id)
            blocks[index] = replace(block, status="pending", user_text=None)
            continue
        blocks[index] = replace(
            block,
            status=event.to_status,  # type: ignore[arg-type]
            user_text=event.user_text or None,
            decided_at=event.decided_at or None,
            decided_by=event.decided_by or "user",
        )
        # A block decided again is not an invalidated block any more.
        if block.block_id in invalidated:
            invalidated.remove(block.block_id)
    return replace(fresh, blocks=blocks, invalidated_blocks=invalidated), invalidated


# ---------------------------------------------------------------------------
# Export gate
# ---------------------------------------------------------------------------


def header_placeholders(workspace: ReviewWorkspace) -> list[str]:
    """Header lines that still carry an unfilled proof marker."""

    header = workspace.header
    lines = [
        ("le nom", header.display_name),
        ("les coordonnées", header.contact_line),
        ("la formation", header.education_line),
    ]
    return [f"{label} : {value}" for label, value in lines if contains_placeholder(value)]


def can_export(workspace: ReviewWorkspace) -> tuple[bool, list[str]]:
    """Tell whether the reviewed CV may be exported, and why not.

    Blocked while a critical block is still undecided, blocked when the
    wording that would be exported still carries an unfilled proof marker
    (header included), and blocked when there is nothing to export at all.

    A critical block is undecided while its status is ``pending``: the proof
    does not replace the decision, because the wording of the summary or of a
    requirement is the person's call.  A block that carries a direct proof is
    auto-verified at build time, so it never stays pending on its own.

    A rejected block is settled: the source wording is exported, so no
    unreviewed adaptation reaches the document.
    """

    blockers: list[str] = []
    if not workspace.blocks:
        return (False, ["Aucune proposition de CV à exporter pour cette candidature."])
    for block in workspace.blocks:
        if not block.critical:
            continue
        if block.status == "pending":
            blockers.append(
                f"« {block.title} » : bloc critique en attente de décision, à trancher avant l'export."
            )
            continue
        if contains_placeholder(effective_text(block)):
            blockers.append(
                f"« {block.title} » : une preuve à compléter est encore présente dans le texte validé."
            )
    for line in header_placeholders(workspace):
        blockers.append(f"En-tête du CV : {line}.")
    return (not blockers, blockers)


def export_warnings(workspace: ReviewWorkspace) -> list[str]:
    """Non-blocking notices for the exported document."""

    warnings: list[str] = []
    for block in workspace.blocks:
        if block.status == "pending" and not block.critical:
            warnings.append(
                f"« {block.title} » : bloc non critique non tranché, la formulation source est exportée."
            )
        if block.placeholder_reason and not block.critical:
            warnings.append(f"« {block.title} » : {block.placeholder_reason}")
    return warnings


def review_progress(workspace: ReviewWorkspace) -> dict[str, Any]:
    """Counters of the review: how many critical blocks are settled."""

    critical = [block for block in workspace.blocks if block.critical]
    validated = [block for block in critical if block.resolved]
    pending = [block for block in critical if block.status == "pending"]
    return {
        "blocks_total": len(workspace.blocks),
        "critical_total": len(critical),
        "critical_validated": len(validated),
        "critical_pending": len(pending),
        "placeholders_total": sum(1 for block in workspace.blocks if block.placeholder_reason),
        "pct": round(100 * len(validated) / len(critical)) if critical else 100,
    }


def render_workspace_markdown(workspace: ReviewWorkspace) -> str:
    """Render the reviewed CV as the Markdown subset the DOCX writer accepts.

    Only settled wording reaches the document, and a wording that still
    carries a proof marker is dropped: the exported CV never contains an
    unresolved marker.

    Blocks are grouped by heading, in the order the heading first appears,
    so a requirement proof lands in its own section instead of repeating that
    heading at the end of the document.
    """

    parts: list[str] = []
    header = workspace.header
    if header.display_name and not contains_placeholder(header.display_name):
        parts.append(f"# {header.display_name}")
    if header.contact_line and not contains_placeholder(header.contact_line):
        parts.append(header.contact_line)
    if header.education_line and not contains_placeholder(header.education_line):
        parts.append(f"Graduation: {header.education_line}")
    groups: list[tuple[str, list[str]]] = []
    positions: dict[str, int] = {}
    for block in workspace.blocks:
        text = effective_text(block).strip()
        if not text or contains_placeholder(text):
            continue
        if block.heading not in positions:
            positions[block.heading] = len(groups)
            groups.append((block.heading, []))
        groups[positions[block.heading]][1].append(text)
    for heading, lines in groups:
        parts.append(f"## {heading}")
        if heading == SUMMARY_HEADING:
            parts.extend(lines)
        else:
            parts.extend(f"- {line}" for line in lines)
    return "\n\n".join(parts) + "\n"


# ---------------------------------------------------------------------------
# Serialization
# ---------------------------------------------------------------------------


def serialize_block(block: ReviewBlock) -> dict[str, Any]:
    """JSON-ready view of one block, with its word-level difference."""

    return {
        "block_id": block.block_id,
        "section": block.section,
        "heading": block.heading,
        "label": block.title,
        "index": block.index,
        "status": block.status,
        "critical": block.critical,
        "source_text": block.source_text,
        "proposed_text": block.proposed_text,
        "effective_text": effective_text(block),
        "user_text": block.user_text,
        "placeholder_reason": block.placeholder_reason,
        "evidence": [item.to_dict() for item in block.evidence] if block.evidence else None,
        "evidence_state": evidence_state(block),
        "decided_at": block.decided_at,
        "decided_by": block.decided_by,
        "diff": [segment.to_dict() for segment in diff_segments(block.source_text, block.proposed_text)],
    }


def serialize_workspace(
    workspace: ReviewWorkspace,
    *,
    can_export_flag: bool | None = None,
    blockers: Sequence[str] | None = None,
    warnings: Sequence[str] | None = None,
) -> dict[str, Any]:
    """JSON-ready view of the whole workspace, ready for the interface."""

    allowed, reasons = can_export(workspace)
    payload = {
        "application_id": workspace.application_id,
        "job_id": workspace.job_id,
        "variant_id": workspace.variant_id,
        "language": workspace.language,
        "created_at": workspace.created_at,
        "updated_at": workspace.updated_at,
        "source_document": workspace.source_document,
        "header": {
            "display_name": workspace.header.display_name,
            "contact_line": workspace.header.contact_line,
            "education_line": workspace.header.education_line,
        },
        "blocks": [serialize_block(block) for block in workspace.blocks],
        "progress": review_progress(workspace),
        "can_export": allowed if can_export_flag is None else can_export_flag,
        "export_blockers": list(reasons if blockers is None else blockers),
        "warnings": list(warnings if warnings is not None else export_warnings(workspace)),
        "invalidated_blocks": list(workspace.invalidated_blocks or []),
        "checks": [
            "Chaque adaptation est affichée avec sa preuve locale et son statut.",
            "Un bloc critique en attente de décision bloque l'export DOCX.",
            "Aucune décision n'est envoyée ailleurs : tout reste sur ce Mac.",
        ],
    }
    return payload
