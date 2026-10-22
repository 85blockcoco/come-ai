"""Evidence-backed CV review workspace — core models and pure logic.

SPEC-004.  The targeted CV generator (``career.application_studio``) already
produces a proposal; this module turns that proposal into a *reviewable*
workspace where every adaptation is:

1. **Visible** — a phrase-by-phrase diff between the source text and the
   proposal (``difflib.SequenceMatcher`` over sentence fragments).
2. **Justified** — every grounded claim carries an ``EvidenceRef`` with the
   exact quote and its character offsets inside the source document.
3. **Controlled** — the user accepts, modifies, rejects or restores the source.
4. **Traceable** — every decision is appended to an immutable history.

Everything here is 100 % local, deterministic and side-effect free: no
network, no model, no filesystem.  Persistence lives in
``career.cv_review_store`` and HTTP exposure in ``career.router``.
"""

from __future__ import annotations

import difflib
import re
from dataclasses import dataclass, field, replace
from typing import Any, Iterable, Literal, Mapping, Sequence

from career.cv_variants import CVVariant
from career.models import EVIDENCE_PLACEHOLDER


# --------------------------------------------------------------------------- #
# Contract
# --------------------------------------------------------------------------- #

ReviewSection = Literal["experiences", "skills", "education", "projects", "languages"]
ReviewStatus = Literal["pending", "accepted", "rejected", "modified", "verified"]
DiffOp = Literal["equal", "insert", "delete"]
EvidenceKind = Literal["source", "profile"]

#: Canonical sections of the review workspace, in a stable, readable order.
REVIEW_SECTIONS: tuple[ReviewSection, ...] = (
    "experiences",
    "skills",
    "education",
    "projects",
    "languages",
)

#: Sections whose content decides whether the CV may be exported.
CRITICAL_SECTIONS: frozenset[str] = frozenset({"experiences", "skills"})

#: Statuses a user may set explicitly. ``verified`` is granted by the builder
#: when a direct proof exists, and ``pending`` is the reset state.
USER_DECISIONS: frozenset[str] = frozenset({"accepted", "rejected", "modified", "pending"})

#: The marker used by the targeted generator when a fact is missing.  It is
#: re-exported here so the review workspace and its tests share one
#: convention with the generator that writes it.
__all__ = [
    "CRITICAL_SECTIONS",
    "EVIDENCE_PLACEHOLDER",
    "EvidenceRef",
    "ProposedParagraph",
    "ProposedSection",
    "REVIEW_SECTIONS",
    "ReviewBlock",
    "ReviewWorkspace",
    "SourceSection",
    "build_workspace",
    "can_export",
    "decide_block",
    "diff_text",
    "effective_text",
    "find_placeholders",
    "find_quote",
    "is_evidence_placeholder",
    "placeholder_reason",
    "render_export_markdown",
    "workspace_progress",
]

#: Any bracketed marker is a placeholder the reader still has to complete.
PLACEHOLDER_PATTERN = re.compile(r"\[[^\[\]\n]{2,160}\]")

#: A sentence boundary: punctuation followed by a space (or the end of a line).
_PHRASE_SPLIT = re.compile(r"(?<=[.!?;])\s+")

#: The field separator used by the CV convention ``date | role | company``.
#: The separator stays attached to the field it closes, so a diff shows the
#: wording that changed and not the punctuation of the convention.
_FIELD_SPLIT = re.compile(r"(?<=\|)\s+")

SECTION_LABELS: dict[str, str] = {
    "experiences": "Expériences",
    "skills": "Compétences",
    "education": "Formation",
    "projects": "Projets",
    "languages": "Langues",
}

#: Approved profile fields read when the imported document does not carry
#: the section.  They are the user's own declared facts.
CV_REVIEW_PROFILE_FIELDS: dict[str, str] = {
    "experiences": "experience",
    "skills": "skills",
    "education": "education",
    "projects": "projects",
    "languages": "languages",
}

#: Headings (CV variants, drafts, generated documents) mapped to a canonical
#: section.  Unknown headings are ignored rather than guessed.
SECTION_ALIASES: dict[str, str] = {
    "experience": "experiences",
    "experiences": "experiences",
    "expérience": "experiences",
    "expériences": "experiences",
    "experience professionnelle": "experiences",
    "professional experience": "experiences",
    "transaction experience": "experiences",
    "finance experience": "experiences",
    "reporting & analysis": "experiences",
    "reporting and analysis": "experiences",
    "professional experiences": "experiences",
    "skills": "skills",
    "technical skills": "skills",
    "technical & transaction skills": "skills",
    "financial analysis skills": "skills",
    "competences": "skills",
    "compétences": "skills",
    "education": "education",
    "formation": "education",
    "educational background": "education",
    "projects": "projects",
    "quantitative projects": "projects",
    "projets": "projects",
    "languages": "languages",
    "langues": "languages",
}


# --------------------------------------------------------------------------- #
# Models
# --------------------------------------------------------------------------- #


@dataclass(frozen=True, slots=True)
class EvidenceRef:
    """One exact quote supporting (or originating) a proposed wording.

    Attributes:
        source: Where the quote lives — ``"cv"`` for the imported document,
            ``"profile.<field>"`` for an approved profile field.
        quote: The verbatim excerpt taken from that source.
        offset: Character offset of the quote inside the source text.
        length: Length of the quote in the source text.
        kind: ``"source"`` when the proposal is present in the reviewed source,
            ``"profile"`` when it is drafted from the approved profile.
        label: Human readable origin, shown in the review UI.
    """

    source: str
    quote: str
    offset: int
    length: int
    kind: EvidenceKind = "source"
    label: str = ""


@dataclass(frozen=True, slots=True)
class DiffSegment:
    """One fragment of the phrase-by-phrase diff."""

    op: DiffOp
    text: str


@dataclass(frozen=True, slots=True)
class ReviewBlock:
    """One reviewable unit of the targeted CV (one canonical section)."""

    block_id: str
    section: ReviewSection
    source_text: str
    proposed_text: str
    status: ReviewStatus = "pending"
    evidence: list[EvidenceRef] | None = None
    placeholder_reason: str | None = None
    user_text: str | None = None
    decided_at: str | None = None
    decided_by: str = "user"
    heading: str = ""
    section_headings: tuple[str, ...] = ()
    critical: bool = False
    diff: list[DiffSegment] = field(default_factory=list)

    @property
    def label(self) -> str:
        return self.heading or SECTION_LABELS.get(self.section, self.section)


@dataclass(frozen=True, slots=True)
class ReviewWorkspace:
    """Every reviewable block of one application, with its export verdict."""

    application_id: str
    blocks: list[ReviewBlock] = field(default_factory=list)
    language: str = "fr"
    variant: str = "m_a"
    created_at: str = ""
    updated_at: str = ""
    source_document: str = ""
    blocking_reasons: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @property
    def can_export(self) -> bool:
        return not self.blocking_reasons


@dataclass(frozen=True, slots=True)
class SourceSection:
    """The user's own text for one canonical section."""

    text: str
    source: str
    label: str = ""


@dataclass(frozen=True, slots=True)
class ProposedParagraph:
    """One paragraph of a proposal and the profile line it comes from."""

    text: str
    source_line: str | None = None
    style: str = "bullet"
    origin_field: str = ""


@dataclass(frozen=True, slots=True)
class ProposedSection:
    """One canonical section of the targeted CV proposal."""

    heading: str
    paragraphs: tuple[ProposedParagraph, ...] = ()
    headings: tuple[str, ...] = ()


# --------------------------------------------------------------------------- #
# Text helpers
# --------------------------------------------------------------------------- #


def split_phrases(text: str) -> list[str]:
    """Split a text into comparable phrases (sentences and list items).

    Sentence punctuation must be followed by a space so decimals such as
    ``20.5 %`` are never torn apart.  The ``|`` field separator of the CV
    convention also opens a new phrase, so a reformatting shows up as a
    precise difference instead of a wholesale replacement.
    """

    if not text:
        return []
    phrases: list[str] = []
    normalized = text.replace("\r\n", "\n").replace("\r", "\n")
    for raw_line in normalized.split("\n"):
        line = raw_line.strip()
        if not line:
            continue
        for sentence in _PHRASE_SPLIT.split(line):
            for phrase in _FIELD_SPLIT.split(sentence):
                stripped = phrase.strip()
                if stripped:
                    phrases.append(stripped)
    return phrases


def diff_text(source: str, proposed: str) -> list[DiffSegment]:
    """Build a phrase-by-phrase diff between the source and the proposal."""

    source_phrases = split_phrases(source)
    proposed_phrases = split_phrases(proposed)
    matcher = difflib.SequenceMatcher(a=source_phrases, b=proposed_phrases, autojunk=False)
    segments: list[DiffSegment] = []
    for tag, first, last, other_first, other_last in matcher.get_opcodes():
        if tag == "equal":
            segments.append(DiffSegment("equal", " ".join(source_phrases[first:last])))
        elif tag == "delete":
            segments.append(DiffSegment("delete", " ".join(source_phrases[first:last])))
        elif tag == "insert":
            segments.append(DiffSegment("insert", " ".join(proposed_phrases[other_first:other_last])))
        else:
            segments.append(DiffSegment("delete", " ".join(source_phrases[first:last])))
            segments.append(DiffSegment("insert", " ".join(proposed_phrases[other_first:other_last])))
    return [segment for segment in segments if segment.text]


def find_quote(haystack: str, needle: str) -> tuple[int, int] | None:
    """Locate ``needle`` inside ``haystack``, ignoring case and extra spaces.

    Returns the ``(offset, length)`` of the match inside the *original*
    ``haystack`` so the quote can be pointed at with exact offsets.
    """

    stripped = (needle or "").strip()
    if not haystack or not stripped:
        return None
    normalized_haystack, haystack_map = _normalized_with_map(haystack)
    normalized_needle, _needle_map = _normalized_with_map(stripped)
    if not normalized_needle:
        return None
    position = normalized_haystack.find(normalized_needle)
    if position < 0:
        return None
    start = haystack_map[position]
    end = haystack_map[position + len(normalized_needle) - 1]
    return start, end - start + 1


def _normalized_with_map(text: str) -> tuple[str, list[int]]:
    """Casefold and collapse whitespace, keeping a map back to the original.

    Folding is applied per character and never changes the character count,
    so the index map always points at the right offset in the original text.
    """

    characters: list[str] = []
    index_map: list[int] = []
    previous_space = True
    for index, character in enumerate(text):
        if character.isspace():
            if previous_space:
                continue
            characters.append(" ")
            index_map.append(index)
            previous_space = True
            continue
        folded = character.casefold()
        characters.append(folded if len(folded) == 1 else character)
        index_map.append(index)
        previous_space = False
    return "".join(characters), index_map


def find_placeholders(text: str) -> list[str]:
    """List every bracketed marker the reader still has to complete."""

    markers: list[str] = []
    for match in PLACEHOLDER_PATTERN.findall(text or ""):
        marker = match.strip()
        if marker and marker not in markers:
            markers.append(marker)
    return markers


def fold_locale(text: str) -> str:
    """Fold the two spellings the CV variants swap (modeling/modelling)."""

    return (text or "").replace("modelling", "modeling").replace("optimisation", "optimization")


def content_tokens(text: str) -> list[str]:
    """Split a text into comparable word tokens.

    Punctuation and case are ignored, and the two spellings the CV variants
    swap are folded: ``modeling`` and ``modelling`` are the same word.
    """

    return re.findall(r"[^\W_]+", fold_locale(text.casefold()), flags=re.UNICODE)


def placeholder_reason(text: str) -> str | None:
    """Explain why a proposal is incomplete, or ``None`` when it is complete."""

    markers = find_placeholders(text)
    if not markers:
        return None
    return "Preuve à compléter : " + " · ".join(markers[:3])


def is_evidence_placeholder(text: str) -> bool:
    """Whether the text carries the generator's explicit "proof missing" mark."""

    return EVIDENCE_PLACEHOLDER in (text or "")


def canonical_section(title: str) -> str | None:
    """Map a section heading to a canonical review section, or ``None``."""

    key = re.sub(r"\s+", " ", (title or "").strip().casefold())
    if not key:
        return None
    key = key.rstrip(":")
    return SECTION_ALIASES.get(key)


def gap_section(gap: Any, variant: CVVariant | None = None) -> str | None:
    """Map one coverage gap to the canonical section where it is reviewed.

    A gap is an adaptation the targeted CV proposes but cannot prove: it is
    shown to the user in the section it would land in.  Structural notes
    (section order) carry no wording, so they are not reviewable blocks.
    """

    requirement = str(getattr(gap, "requirement", "") or "").strip()
    if not requirement:
        return None
    state = str(getattr(gap, "current_state", "") or "")
    if state == "wrong_order":
        return None
    canonical = canonical_section(requirement)
    if canonical:
        return canonical
    if variant is not None:
        keywords = {keyword.casefold() for keyword in variant.mandatory_keywords}
        keywords |= {keyword.casefold() for keyword in variant.keyword_priorities}
        if requirement.casefold() in keywords:
            return "skills"
    if state == "unquantified":
        return "experiences"
    return "skills"


# --------------------------------------------------------------------------- #
# Workspace construction
# --------------------------------------------------------------------------- #


def build_workspace(
    application_id: str,
    *,
    language: str = "fr",
    variant: CVVariant | None = None,
    sources: Mapping[str, SourceSection] | None = None,
    proposals: Mapping[str, ProposedSection] | None = None,
    profile: Mapping[str, str] | None = None,
    source_document: str = "",
    saved: ReviewWorkspace | None = None,
    now: str = "",
) -> ReviewWorkspace:
    """Build the review workspace of one application.

    The function is pure: it reads its inputs and returns a new workspace.  A
    previously saved workspace can be replayed through ``saved`` so explicit
    user decisions survive a rebuild; a decision is only kept when the
    reviewed content did not change in between.
    """

    sources = sources or {}
    proposals = proposals or {}
    profile = profile or {}
    saved_blocks = {block.block_id: block for block in (saved.blocks if saved else [])}
    blocks: list[ReviewBlock] = []
    for section in REVIEW_SECTIONS:
        proposal = proposals.get(section)
        source = sources.get(section)
        source_text = source.text if source else ""
        proposed_text = _proposal_text(proposal)
        if not source_text.strip() and not proposed_text.strip():
            continue
        block = _build_block(
            section=section,
            proposal=proposal,
            source=source,
            source_text=source_text,
            proposed_text=proposed_text,
            profile=profile,
        )
        previous = saved_blocks.get(block.block_id)
        if previous is not None:
            block = _replay_decision(previous, block)
        blocks.append(block)
    blocking_reasons = can_export_blocks(blocks)[1]
    warnings = _workspace_warnings(blocks)
    return ReviewWorkspace(
        application_id=application_id,
        blocks=blocks,
        language=language,
        variant=variant.id if variant is not None else (saved.variant if saved else "m_a"),
        created_at=saved.created_at if saved and saved.created_at else now,
        updated_at=now or (saved.updated_at if saved else ""),
        source_document=source_document or (saved.source_document if saved else ""),
        blocking_reasons=blocking_reasons,
        warnings=warnings,
    )


def _build_block(
    *,
    section: str,
    proposal: ProposedSection | None,
    source: SourceSection | None,
    source_text: str,
    proposed_text: str,
    profile: Mapping[str, str],
) -> ReviewBlock:
    paragraphs = proposal.paragraphs if proposal else ()
    source_refs: list[EvidenceRef] = []
    profile_refs: list[EvidenceRef] = []
    grounded = True
    for paragraph in paragraphs:
        line = paragraph.source_line
        if not line:
            # A proposal without an origin (an evidence gap) is never proven.
            grounded = False
            continue
        if not _adds_no_content(paragraph.text, line):
            grounded = False
            profile_refs.extend(_profile_origin(paragraph, profile))
            continue
        found = find_quote(source_text, line)
        if found is None:
            grounded = False
            profile_refs.extend(_profile_origin(paragraph, profile))
            continue
        offset, length = found
        source_refs.append(
            EvidenceRef(
                source=source.source if source else "",
                quote=source_text[offset : offset + length],
                offset=offset,
                length=length,
                kind="source",
                label=source.label if source else "",
            )
        )
    evidence = list(source_refs)
    if source is not None and source.source != "profile":
        # The reviewed source is the imported document: the profile keeps the
        # provenance of the proposal, so the reader knows where it comes from.
        evidence.extend(profile_refs)
    reason = placeholder_reason(proposed_text)
    if reason is None and grounded and source_refs:
        status: ReviewStatus = "verified"
    else:
        status = "pending"
    headings = proposal.headings if proposal else ()
    heading = proposal.heading if proposal and proposal.heading else SECTION_LABELS.get(section, section)
    return ReviewBlock(
        block_id=section,
        section=section,  # type: ignore[arg-type]
        source_text=source_text,
        proposed_text=proposed_text,
        status=status,
        evidence=evidence,
        placeholder_reason=reason,
        heading=heading,
        section_headings=headings,
        critical=section in CRITICAL_SECTIONS,
        diff=diff_text(source_text, proposed_text),
    )


def _adds_no_content(proposed_text: str, origin_line: str) -> bool:
    """Whether the proposal only re-arranges the words of its origin line.

    A proposal that introduces a word the origin does not contain is an
    adaptation: it cannot be "proven" by the source, it must be reviewed.
    """

    proposed = set(content_tokens(proposed_text))
    if not proposed:
        return False
    return proposed <= set(content_tokens(origin_line))


def _profile_origin(
    paragraph: ProposedParagraph, profile: Mapping[str, str]
) -> list[EvidenceRef]:
    """Quote the approved profile line a proposal was drafted from."""

    field = paragraph.origin_field
    text = profile.get(field, "")
    line = paragraph.source_line
    if not field or not text or not line:
        return []
    found = find_quote(text, line)
    if found is None:
        return []
    offset, length = found
    return [
        EvidenceRef(
            source=f"profile.{field}",
            quote=text[offset : offset + length],
            offset=offset,
            length=length,
            kind="profile",
            label=f"Profil approuvé › {field}",
        )
    ]


def _proposal_text(proposal: ProposedSection | None) -> str:
    if proposal is None:
        return ""
    return "\n".join(paragraph.text for paragraph in proposal.paragraphs).strip()


def _replay_decision(previous: ReviewBlock, rebuilt: ReviewBlock) -> ReviewBlock:
    """Keep an explicit user decision when the reviewed content is unchanged."""

    if (
        previous.source_text != rebuilt.source_text
        or previous.proposed_text != rebuilt.proposed_text
    ):
        # The content moved under the user's feet: the block is reopened and
        # must be reviewed again, whatever its new evidence says.
        return replace(
            rebuilt,
            status="pending",
            user_text=None,
            decided_at=None,
            decided_by="user",
        )
    if previous.status not in USER_DECISIONS:
        # ``verified`` is granted by the builder, never replayed.
        return rebuilt
    return replace(
        rebuilt,
        status=previous.status,
        user_text=previous.user_text,
        decided_at=previous.decided_at,
        decided_by=previous.decided_by,
    )


def _workspace_warnings(blocks: Sequence[ReviewBlock]) -> list[str]:
    warnings: list[str] = []
    for block in blocks:
        if block.status == "rejected" and not effective_text(block).strip():
            warnings.append(
                f"« {block.label} » a été refusé et le texte source est vide : la section sera vide à l’export."
            )
        elif block.status == "modified" and block.user_text is not None and find_placeholders(block.user_text):
            warnings.append(f"« {block.label} » contient encore un marqueur à compléter.")
        elif (
            block.placeholder_reason
            and block.status == "pending"
            and block.section not in CRITICAL_SECTIONS
        ):
            warnings.append(
                f"« {block.label} » reste à compléter (section non critique : l’export n’est pas bloqué)."
            )
    return warnings


# --------------------------------------------------------------------------- #
# Decisions
# --------------------------------------------------------------------------- #


def effective_text(block: ReviewBlock) -> str:
    """Return the text that will actually be exported for one block."""

    if block.status == "rejected":
        return block.source_text
    if block.status == "modified" and block.user_text is not None:
        return block.user_text
    return block.proposed_text


def decide_block(
    workspace: ReviewWorkspace,
    block_id: str,
    status: str,
    *,
    user_text: str | None = None,
    now: str = "",
) -> tuple[ReviewWorkspace, ReviewBlock]:
    """Apply one user decision to a block and return the new workspace."""

    if status not in USER_DECISIONS:
        raise ValueError(f"Statut de décision inconnu : {status}")
    blocks = list(workspace.blocks)
    updated: ReviewBlock | None = None
    for index, block in enumerate(blocks):
        if block.block_id != block_id:
            continue
        text = (user_text or "").strip()
        if status == "modified":
            if not text:
                raise ValueError("Un bloc modifié doit contenir un texte.")
            if find_placeholders(text):
                raise ValueError(
                    "Le texte modifié contient encore un marqueur entre crochets : complète la preuve avant de valider."
                )
        elif status == "accepted" and block.placeholder_reason:
            # An explicit acceptance confirms the placeholder: it is kept as
            # is, on the user's responsibility.
            pass
        updated = replace(
            block,
            status=status,  # type: ignore[arg-type]
            user_text=text or None,
            decided_at=now or None,
            decided_by="user",
        )
        blocks[index] = updated
        break
    if updated is None:
        raise KeyError(block_id)
    reasons = can_export_blocks(blocks)[1]
    new_workspace = ReviewWorkspace(
        application_id=workspace.application_id,
        blocks=blocks,
        language=workspace.language,
        variant=workspace.variant,
        created_at=workspace.created_at,
        updated_at=now or workspace.updated_at,
        source_document=workspace.source_document,
        blocking_reasons=reasons,
        warnings=_workspace_warnings(blocks),
    )
    return new_workspace, updated


# --------------------------------------------------------------------------- #
# Export gate
# --------------------------------------------------------------------------- #


def can_export_blocks(blocks: Sequence[ReviewBlock]) -> tuple[bool, list[str]]:
    """Return whether the CV may be exported, and why it may not."""

    reasons: list[str] = []
    if not blocks:
        reasons.append("Aucun bloc de revue disponible : le CV ciblé est vide.")
    for block in blocks:
        if block.section not in CRITICAL_SECTIONS:
            continue
        if block.status == "pending":
            if block.placeholder_reason:
                reasons.append(
                    f"Placeholder critique non confirmé — « {block.label} » : {block.placeholder_reason}"
                )
            else:
                reasons.append(f"Bloc critique en attente de décision — « {block.label} ».")
        elif block.status == "rejected":
            # The block falls back to the user's own text: nothing unverified
            # remains, so it never blocks the export.
            continue
        elif block.placeholder_reason and block.status not in {"accepted", "modified"}:
            reasons.append(f"Placeholder critique non confirmé — « {block.label} ».")
    return (not reasons), reasons


def can_export(workspace: ReviewWorkspace) -> tuple[bool, list[str]]:
    """Return whether the workspace may be exported, and why it may not."""

    return can_export_blocks(workspace.blocks)


def workspace_progress(workspace: ReviewWorkspace) -> dict[str, Any]:
    """Summarise the review progress for the UI progress bar."""

    critical = [block for block in workspace.blocks if block.section in CRITICAL_SECTIONS]
    validated = [block for block in critical if block.status in {"verified", "accepted", "modified"}]
    decided = [
        block
        for block in workspace.blocks
        if block.status in {"verified", "accepted", "modified", "rejected"}
    ]
    total = len(workspace.blocks)
    return {
        "critical_total": len(critical),
        "critical_validated": len(validated),
        "decided_total": len(decided),
        "blocks_total": total,
        "percent": round(len(validated) / len(critical) * 100) if critical else 0,
    }


# --------------------------------------------------------------------------- #
# Export rendering
# --------------------------------------------------------------------------- #


def render_export_markdown(
    workspace: ReviewWorkspace,
    *,
    name: str = "",
    contact: str = "",
    headline: str = "",
) -> str:
    """Render the reviewed CV as the small Markdown subset we export."""

    lines: list[str] = []
    if name.strip():
        lines.append(f"# {name.strip()}")
    if contact.strip():
        lines.append(contact.strip())
    if headline.strip():
        lines.append(headline.strip())
    for block in workspace.blocks:
        text = effective_text(block).strip()
        lines.append("")
        lines.append(f"## {block.heading or SECTION_LABELS.get(block.section, block.section)}")
        if not text:
            continue
        for paragraph in text.splitlines():
            stripped = paragraph.strip()
            if stripped:
                lines.append(f"- {stripped}")
    return "\n".join(lines).strip() + "\n"


# --------------------------------------------------------------------------- #
# Serialization
# --------------------------------------------------------------------------- #


def evidence_to_dict(evidence: Iterable[EvidenceRef] | None) -> list[dict[str, Any]]:
    return [
        {
            "source": item.source,
            "quote": item.quote,
            "offset": item.offset,
            "length": item.length,
            "kind": item.kind,
            "label": item.label,
        }
        for item in (evidence or [])
    ]


def evidence_from_dict(payload: Any) -> list[EvidenceRef]:
    if not isinstance(payload, list):
        return []
    refs: list[EvidenceRef] = []
    for item in payload:
        if not isinstance(item, dict):
            continue
        refs.append(
            EvidenceRef(
                source=str(item.get("source") or ""),
                quote=str(item.get("quote") or ""),
                offset=int(item.get("offset") or 0),
                length=int(item.get("length") or 0),
                kind="profile" if item.get("kind") == "profile" else "source",
                label=str(item.get("label") or ""),
            )
        )
    return refs


def block_to_dict(block: ReviewBlock) -> dict[str, Any]:
    return {
        "block_id": block.block_id,
        "section": block.section,
        "source_text": block.source_text,
        "proposed_text": block.proposed_text,
        "status": block.status,
        "evidence": evidence_to_dict(block.evidence),
        "placeholder_reason": block.placeholder_reason,
        "user_text": block.user_text,
        "decided_at": block.decided_at,
        "decided_by": block.decided_by,
        "heading": block.heading,
        "section_headings": list(block.section_headings),
        "critical": block.critical,
        "diff": [{"op": segment.op, "text": segment.text} for segment in block.diff],
        "effective_text": effective_text(block),
    }


def block_from_dict(payload: Mapping[str, Any]) -> ReviewBlock:
    diff = payload.get("diff")
    segments = [
        DiffSegment(
            op=segment.get("op") if segment.get("op") in {"equal", "insert", "delete"} else "equal",
            text=str(segment.get("text") or ""),
        )
        for segment in (diff if isinstance(diff, list) else [])
        if isinstance(segment, dict)
    ]
    status = payload.get("status")
    return ReviewBlock(
        block_id=str(payload.get("block_id") or ""),
        section=str(payload.get("section") or "experiences"),  # type: ignore[arg-type]
        source_text=str(payload.get("source_text") or ""),
        proposed_text=str(payload.get("proposed_text") or ""),
        status=status if status in {"pending", "accepted", "rejected", "modified", "verified"} else "pending",  # type: ignore[arg-type]
        evidence=evidence_from_dict(payload.get("evidence")),
        placeholder_reason=payload.get("placeholder_reason"),
        user_text=payload.get("user_text"),
        decided_at=payload.get("decided_at"),
        decided_by=str(payload.get("decided_by") or "user"),
        heading=str(payload.get("heading") or ""),
        section_headings=tuple(str(item) for item in (payload.get("section_headings") or [])),
        critical=bool(payload.get("critical")),
        diff=segments,
    )


def workspace_to_dict(workspace: ReviewWorkspace) -> dict[str, Any]:
    allowed, reasons = can_export(workspace)
    return {
        "application_id": workspace.application_id,
        "language": workspace.language,
        "variant": workspace.variant,
        "created_at": workspace.created_at,
        "updated_at": workspace.updated_at,
        "source_document": workspace.source_document,
        "can_export": allowed,
        "blocking_reasons": list(reasons),
        "warnings": list(workspace.warnings),
        "progress": workspace_progress(workspace),
        "blocks": [block_to_dict(block) for block in workspace.blocks],
    }


def workspace_from_dict(payload: Mapping[str, Any]) -> ReviewWorkspace:
    blocks = [
        block_from_dict(item)
        for item in (payload.get("blocks") or [])
        if isinstance(item, dict)
    ]
    workspace = ReviewWorkspace(
        application_id=str(payload.get("application_id") or ""),
        blocks=blocks,
        language=str(payload.get("language") or "fr"),
        variant=str(payload.get("variant") or "m_a"),
        created_at=str(payload.get("created_at") or ""),
        updated_at=str(payload.get("updated_at") or ""),
        source_document=str(payload.get("source_document") or ""),
    )
    reasons = can_export_blocks(blocks)[1]
    return replace(
        workspace,
        blocking_reasons=reasons,
        warnings=_workspace_warnings(blocks),
    )
