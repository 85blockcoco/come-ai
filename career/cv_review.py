"""Evidence-backed CV review workspace — local, deterministic, offline core.

SPEC-004 : chaque adaptation proposée du CV ciblé est

1. **visible** : diff phrase par phrase (source → proposé) ;
2. **justifiée** : preuve exacte (source, quote, offsets) ou placeholder explicite ;
3. **contrôlée** : accepter / modifier / refuser / revenir à la source ;
4. **traçable** : historique immuable des décisions (voir ``cv_review_store``).

Ce module est volontairement *pur* : aucun appel réseau, aucune écriture, aucune
dépendance à la base Career. Il transforme des faits locaux (profil approuvé,
offre enregistrée, couverture, variante de CV) en objets de revue ; la
persistance et l'historique vivent dans ``career/cv_review_store.py``.

La preuve est référencée par :class:`EvidenceRef`. C'est la référence locale,
auto-suffisante, comprise par la revue : ``source`` (le champ de profil ou la
source de l'offre), ``quote`` (la citation exacte) et les offsets dans le texte
source. Elle est volontairement compatible avec le format de citation déjà
utilisé par ``career/cv_fit`` et ``career/application_studio``
(``{"source", "quote", "offset"}``) pour qu'un EvidenceCenter puisse alimenter
la revue sans changer le contrat.
"""

from __future__ import annotations

import difflib
import re
from dataclasses import dataclass, field, replace
from typing import Any, Literal

from .application_studio import variant_text
from .cv_fit import CoverageResult
from .cv_variants import MA_VARIANT, CVVariant


ReviewSection = Literal["experiences", "skills", "education", "projects", "languages"]
ReviewStatus = Literal["pending", "accepted", "rejected", "modified", "verified"]
DiffOp = Literal["equal", "insert", "delete"]

#: Sections revues, dans l'ordre d'affichage du workspace.
REVIEW_SECTIONS: tuple[ReviewSection, ...] = (
    "experiences",
    "skills",
    "education",
    "projects",
    "languages",
)

#: Sections critiques : une adaptation non tranchée dans ces sections bloque
#: l'export du CV révisé.
CRITICAL_SECTIONS: tuple[ReviewSection, ...] = ("experiences", "skills")

SECTION_LABELS: dict[str, str] = {
    "experiences": "Expériences",
    "skills": "Compétences",
    "education": "Formation",
    "projects": "Projets",
    "languages": "Langues",
}

#: Statuts qu'un utilisateur peut poser explicitement sur un bloc.
DECISION_STATUSES: tuple[str, ...] = ("accepted", "rejected", "modified", "pending")

#: Statuts qui comptent comme « validés » dans la barre de progression.
VALIDATED_STATUSES: tuple[str, ...] = ("verified", "accepted", "modified")

#: Texte placeholder utilisé par le kit ciblé (application_studio).
PLACEHOLDER_TEXT = "[AJOUTER PREUVE CHIFFRÉE]"

#: Titres de section du CV ciblé → champ de profil source.
_HEADING_FIELDS: dict[str, str] = {
    "professional experience": "experience",
    "transaction experience": "experience",
    "finance experience": "experience",
    "reporting & analysis": "experience",
    "quantitative projects": "projects",
    "projects": "projects",
    "education": "education",
    "technical skills": "skills",
    "languages": "languages",
}

#: Champ de profil → section canonique de la revue.
_FIELD_SECTIONS: dict[str, ReviewSection] = {
    "experience": "experiences",
    "skills": "skills",
    "education": "education",
    "projects": "projects",
    "languages": "languages",
}

#: Faits d'offre qui suivent la candidature ou l'offre elle-même : ils ne
#: sont pas du contenu de CV et ne sont donc pas des blocs de revue.
_OFFER_FACTS_OUTSIDE_CV: frozenset[str] = frozenset(
    {
        "publication",
        "début",
        "fin",
        "langue",
        "pays",
        "ville",
        "jour de début vérifiable",
        "année de début",
        "mois de début",
        "durée",
        "lien officiel valide",
        "date limite vérifiable",
    }
)

_TOKEN_PATTERN = re.compile(r"\s+|\w+|[^\w\s]", re.UNICODE)


class ReviewError(ValueError):
    """A review decision that cannot be applied (unknown block or status)."""


@dataclass(frozen=True, slots=True)
class EvidenceRef:
    """One exact proof behind a proposed CV line.

    ``start_offset`` / ``end_offset`` locate ``quote`` inside the source text
    it was taken from (``source``), so the interface can highlight the very
    same characters instead of a paraphrase.
    """

    source: str
    quote: str
    start_offset: int = 0
    end_offset: int = 0

    @classmethod
    def from_citation(cls, citation: dict[str, Any]) -> "EvidenceRef":
        """Build a reference from the ``{"source", "quote", "offset"}`` format."""

        offset = citation.get("offset")
        quote = str(citation.get("quote") or "")
        try:
            start = max(0, int(offset))
        except (TypeError, ValueError):
            start = 0
        return cls(
            source=str(citation.get("source") or "profile"),
            quote=quote,
            start_offset=start,
            end_offset=start + len(quote),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "source": self.source,
            "quote": self.quote,
            "start_offset": self.start_offset,
            "end_offset": self.end_offset,
        }


@dataclass(frozen=True, slots=True)
class DiffSegment:
    """One part of a phrase-by-phrase diff between source and proposal."""

    op: DiffOp
    text: str

    def to_dict(self) -> dict[str, Any]:
        return {"op": self.op, "text": self.text}


@dataclass
class ReviewBlock:
    """One reviewable unit of the targeted CV.

    A block is either a sourced line (the approved profile line and the
    targeted rendering of it) or an explicit placeholder (no proof available).
    """

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

    @property
    def critical(self) -> bool:
        return self.section in CRITICAL_SECTIONS

    @property
    def is_placeholder(self) -> bool:
        return bool(self.placeholder_reason)

    def to_dict(self) -> dict[str, Any]:
        return {
            "block_id": self.block_id,
            "section": self.section,
            "source_text": self.source_text,
            "proposed_text": self.proposed_text,
            "status": self.status,
            "evidence": [item.to_dict() for item in self.evidence] if self.evidence else None,
            "placeholder_reason": self.placeholder_reason,
            "user_text": self.user_text,
            "decided_at": self.decided_at,
            "decided_by": self.decided_by,
            "critical": self.critical,
            "is_placeholder": self.is_placeholder,
            "final_text": resolve_block_text(self),
            "diff": [segment.to_dict() for segment in diff_segments(self.source_text, self.proposed_text)],
            "badge": review_badge(self),
        }


@dataclass
class ReviewWorkspace:
    """The reviewable state of one targeted CV, for one application."""

    application_id: str
    job_id: str = ""
    variant_id: str = ""
    language: str = "fr"
    blocks: list[ReviewBlock] = field(default_factory=list)
    section_headings: dict[str, str] = field(default_factory=dict)
    created_at: str = ""
    updated_at: str = ""

    def block(self, block_id: str) -> ReviewBlock | None:
        for item in self.blocks:
            if item.block_id == block_id:
                return item
        return None

    def critical_blocks(self) -> list[ReviewBlock]:
        return [item for item in self.blocks if item.critical]

    def to_dict(self) -> dict[str, Any]:
        return workspace_to_dict(self)


def _text(value: Any) -> str:
    return str(value or "")


def profile_lines(value: Any) -> list[tuple[str, int, int]]:
    """Return the profile lines with their exact offsets in the source text.

    The offsets point at the stripped line inside the raw profile field, so an
    ``EvidenceRef`` can highlight the very same characters.
    """

    raw = _text(value)
    lines: list[tuple[str, int, int]] = []
    cursor = 0
    for chunk in raw.split("\n"):
        start = cursor
        cursor += len(chunk) + 1
        stripped = chunk.strip(" •-\t\r")
        if not stripped:
            continue
        offset = chunk.find(stripped)
        if offset < 0:
            offset = 0
        lines.append((stripped, start + offset, start + offset + len(stripped)))
    return lines


def _tokens(value: str) -> list[str]:
    return _TOKEN_PATTERN.findall(value)

def diff_segments(source_text: str, proposed_text: str) -> list[DiffSegment]:
    """Phrase-by-phrase diff between the source wording and the proposal."""

    source_tokens = _tokens(source_text)
    proposed_tokens = _tokens(proposed_text)
    matcher = difflib.SequenceMatcher(a=source_tokens, b=proposed_tokens, autojunk=False)
    segments: list[DiffSegment] = []
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag == "equal":
            text = "".join(source_tokens[i1:i2])
            if text:
                segments.append(DiffSegment("equal", text))
            continue
        removed = "".join(source_tokens[i1:i2])
        if removed:
            segments.append(DiffSegment("delete", removed))
        added = "".join(proposed_tokens[j1:j2])
        if added:
            segments.append(DiffSegment("insert", added))
    return segments


def review_badge(block: ReviewBlock) -> dict[str, str]:
    """The evidence badge shown next to a block."""

    if block.is_placeholder:
        return {"key": "placeholder", "label": "Placeholder", "tone": "danger"}
    if block.status == "verified":
        return {"key": "verified", "label": "Vérifié", "tone": "good"}
    if block.status == "pending":
        return {"key": "to_verify", "label": "À vérifier", "tone": "warning"}
    if block.status == "accepted":
        return {"key": "accepted", "label": "Accepté", "tone": "good"}
    if block.status == "modified":
        return {"key": "modified", "label": "Modifié", "tone": "info"}
    return {"key": "rejected", "label": "Refusé", "tone": "muted"}


def resolve_block_text(block: ReviewBlock) -> str:
    """The wording that ends up in the exported CV for one block.

    * ``modified`` → the wording written by the user ;
    * ``accepted`` / ``verified`` → the targeted proposal ;
    * ``rejected`` → the source wording ;
    * ``pending`` → the source wording when it exists, otherwise nothing
      (an unconfirmed placeholder is never exported as-is).
    """

    if block.status == "modified" and block.user_text is not None:
        return block.user_text
    if block.status in {"accepted", "verified"}:
        return block.proposed_text
    if block.status == "rejected":
        return block.source_text
    return block.source_text


def _section_heading(variant: CVVariant, section: ReviewSection) -> tuple[str, str]:
    """Return the targeted heading and the profile field for one section."""

    for heading in variant.section_order:
        field_name = _HEADING_FIELDS.get(heading.casefold())
        if field_name and _FIELD_SECTIONS.get(field_name) == section:
            return heading, field_name
    return "", ""


def _gap_section(requirement: str) -> ReviewSection:
    """Map an uncovered offer requirement to the reviewed section.

    A requirement that is not documented by the profile is a skill or a
    keyword of the targeted variant: it belongs to the skills section. The
    facts that follow the application itself are filtered out earlier.
    """

    del requirement
    return "skills"


def build_workspace(
    application_id: str,
    *,
    job: dict[str, Any] | None = None,
    profile: dict[str, Any] | None = None,
    variant: CVVariant | None = None,
    coverage: CoverageResult | None = None,
    language: str = "fr",
    created_at: str = "",
    updated_at: str = "",
) -> ReviewWorkspace:
    """Build the review workspace of one application from local facts only.

    The function is pure: the same inputs always produce the same workspace,
    and nothing is read from or written to disk.
    """

    selected_variant = variant or MA_VARIANT
    job_data = job if isinstance(job, dict) else {}
    profile_data = profile if isinstance(profile, dict) else {}
    blocks: list[ReviewBlock] = []
    headings: dict[str, str] = {}

    for section in REVIEW_SECTIONS:
        heading, field_name = _section_heading(selected_variant, section)
        if not heading:
            continue
        headings[section] = heading
        lines = profile_lines(profile_data.get(field_name))
        if not lines:
            blocks.append(
                ReviewBlock(
                    block_id=f"{section}:empty",
                    section=section,
                    source_text="",
                    proposed_text=PLACEHOLDER_TEXT,
                    status="pending",
                    evidence=None,
                    placeholder_reason=(
                        f"Aucune ligne sourcée dans le profil local pour la section « {heading} »."
                    ),
                )
            )
            continue
        for index, (line, start, end) in enumerate(lines):
            proposed = variant_text(line, selected_variant)
            blocks.append(
                ReviewBlock(
                    block_id=f"{section}:{index}",
                    section=section,
                    source_text=line,
                    proposed_text=proposed,
                    # A line copied word for word from the approved profile is
                    # directly proven; a reworded line still needs a look.
                    status="verified" if proposed == line else "pending",
                    evidence=[
                        EvidenceRef(
                            source=f"profile.{field_name}",
                            quote=line,
                            start_offset=start,
                            end_offset=end,
                        )
                    ],
                    placeholder_reason=None,
                )
            )

    gap_index = 0
    for gap in list(coverage.gaps) if coverage else []:
        requirement = _text(gap.requirement).strip()
        if not requirement or requirement.casefold() in _OFFER_FACTS_OUTSIDE_CV:
            continue
        section = _gap_section(requirement)
        blocks.append(
            ReviewBlock(
                block_id=f"{section}:gap:{gap_index}",
                section=section,
                source_text="",
                proposed_text=f"{requirement}: {PLACEHOLDER_TEXT}",
                status="pending",
                evidence=None,
                placeholder_reason=(
                    f"Exigence de l’offre non étayée par le profil local : {requirement}."
                ),
            )
        )
        gap_index += 1

    return ReviewWorkspace(
        application_id=_text(application_id),
        job_id=_text(job_data.get("id")),
        variant_id=selected_variant.id,
        language=_text(language) or "fr",
        blocks=blocks,
        section_headings=headings,
        created_at=created_at,
        updated_at=updated_at or created_at,
    )


def merge_decisions(
    workspace: ReviewWorkspace, stored: ReviewWorkspace | None
) -> ReviewWorkspace:
    """Re-apply the stored decisions onto a freshly built workspace.

    A decision is kept only while the reviewed wording did not change: if the
    profile or the offer moved, the stored decision no longer applies and the
    block goes back to ``pending`` for a new look.
    """

    if stored is None:
        return workspace
    previous = {item.block_id: item for item in stored.blocks}
    blocks: list[ReviewBlock] = []
    for block in workspace.blocks:
        earlier = previous.get(block.block_id)
        if (
            earlier is not None
            and earlier.proposed_text == block.proposed_text
            and earlier.source_text == block.source_text
        ):
            block = replace(
                block,
                status=earlier.status,
                user_text=earlier.user_text,
                decided_at=earlier.decided_at,
                decided_by=earlier.decided_by,
            )
        blocks.append(block)
    return replace(
        workspace,
        blocks=blocks,
        created_at=stored.created_at or workspace.created_at,
        updated_at=stored.updated_at or workspace.updated_at,
    )


def apply_decision(
    workspace: ReviewWorkspace,
    block_id: str,
    status: str,
    *,
    user_text: str | None = None,
    decided_at: str = "",
    decided_by: str = "user",
) -> ReviewWorkspace:
    """Return a new workspace with one decision applied (pure)."""

    if status not in DECISION_STATUSES:
        raise ReviewError("Statut de décision inconnu.")
    index = next(
        (position for position, item in enumerate(workspace.blocks) if item.block_id == block_id),
        None,
    )
    if index is None:
        raise ReviewError("Bloc de revue inconnu pour cette candidature.")
    cleaned = (user_text or "").strip()
    if status == "modified" and not cleaned:
        raise ReviewError("Une modification exige un texte.")
    if status != "modified" and cleaned:
        raise ReviewError("Un texte ne peut être fourni que pour une modification.")
    block = workspace.blocks[index]
    updated = replace(
        block,
        status=status,  # type: ignore[arg-type]
        user_text=cleaned if status == "modified" else None,
        decided_at=decided_at or block.decided_at or "",
        decided_by=decided_by,
    )
    blocks = list(workspace.blocks)
    blocks[index] = updated
    return replace(workspace, blocks=blocks, updated_at=decided_at or workspace.updated_at)


def can_export(workspace: ReviewWorkspace) -> tuple[bool, list[str]]:
    """Whether the reviewed CV may be exported, and why it may not.

    The export is blocked when a critical block (experiences, skills) is still
    ``pending`` without any proof behind it, and when a critical placeholder
    has not been confirmed by the user.
    """

    reasons: list[str] = []
    for block in workspace.blocks:
        if not block.critical:
            continue
        if block.status != "pending":
            continue
        if not block.evidence:
            if block.placeholder_reason:
                reasons.append(f"Placeholder critique non confirmé : {block.placeholder_reason}")
            else:
                reasons.append(
                    f"Bloc critique non validé : {SECTION_LABELS.get(block.section, block.section)} — {block.block_id}."
                )
    return (not reasons), reasons


def review_progress(workspace: ReviewWorkspace) -> dict[str, Any]:
    """The "X/Y blocs critiques validés" counter of the interface."""

    critical = workspace.critical_blocks()
    validated = [item for item in critical if item.status in VALIDATED_STATUSES]
    total = len(critical)
    return {
        "critical_total": total,
        "critical_validated": len(validated),
        "percent": round(len(validated) * 100 / total) if total else 100,
        "label": f"{len(validated)}/{total} blocs critiques validés",
    }


def status_counts(workspace: ReviewWorkspace) -> dict[str, int]:
    counts = {status: 0 for status in ("pending", "verified", "accepted", "rejected", "modified")}
    for block in workspace.blocks:
        counts[block.status] = counts.get(block.status, 0) + 1
    counts["total"] = len(workspace.blocks)
    return counts


def workspace_to_dict(workspace: ReviewWorkspace) -> dict[str, Any]:
    """JSON-ready view of a workspace (blocks, diffs, progress, blockers)."""

    allowed, blockers = can_export(workspace)
    return {
        "application_id": workspace.application_id,
        "job_id": workspace.job_id,
        "variant_id": workspace.variant_id,
        "language": workspace.language,
        "created_at": workspace.created_at,
        "updated_at": workspace.updated_at,
        "sections": [
            {
                "section": section,
                "label": SECTION_LABELS.get(section, section),
                "heading": workspace.section_headings.get(section, ""),
                "critical": section in CRITICAL_SECTIONS,
            }
            for section in REVIEW_SECTIONS
            if section in workspace.section_headings
        ],
        "blocks": [block.to_dict() for block in workspace.blocks],
        "progress": review_progress(workspace),
        "counts": status_counts(workspace),
        "can_export": allowed,
        "export_blockers": blockers,
        "critical_sections": list(CRITICAL_SECTIONS),
        "disclaimer": (
            "Revue locale du CV ciblé : chaque ligne montre la source, la proposition et sa preuve. "
            "Aucune candidature n’est envoyée ; l’export DOCX est un fichier local."
        ),
    }


def _split_experience_line(text: str) -> tuple[str, str]:
    """Split a profile experience line into its header and its result."""

    if text.count("|") < 2:
        return text, ""
    date_text, role, company_and_result = (part.strip() for part in text.split("|", 2))
    company, separator, result = company_and_result.partition(" — ")
    header = f"{date_text} | {role} | {company}"
    if separator and result:
        return header, result.strip()
    return header, ""


def build_review_markdown(
    workspace: ReviewWorkspace, profile: dict[str, Any] | None = None
) -> str:
    """Render the reviewed CV as the local Markdown subset used for exports."""

    profile_data = profile if isinstance(profile, dict) else {}
    parts: list[str] = []
    name = _text(profile_data.get("display_name"))
    if name:
        parts.append(f"# {name}")
    contacts = " · ".join(
        part
        for part in (
            _text(profile_data.get("contact_email")),
            _text(profile_data.get("contact_phone")),
            _text(profile_data.get("linkedin_url")),
        )
        if part
    )
    if contacts:
        parts.append(contacts)
    graduation = _text(profile_data.get("education"))
    if graduation:
        parts.append(f"Graduation : {graduation}")
    for section in REVIEW_SECTIONS:
        heading = workspace.section_headings.get(section)
        if not heading:
            continue
        blocks = [item for item in workspace.blocks if item.section == section]
        if not blocks:
            continue
        rendered: list[str] = []
        for block in blocks:
            text = resolve_block_text(block).strip()
            if not text:
                continue
            if block.section == "experiences":
                header, result = _split_experience_line(text)
                rendered.append(header)
                if result:
                    rendered.append(f"- {result}")
            else:
                rendered.append(f"- {text}")
        # An unconfirmed placeholder leaves the section empty: the heading is
        # dropped rather than exported as an empty section.
        if not rendered:
            continue
        parts.append(f"## {heading}")
        parts.extend(rendered)
    return "\n\n".join(parts).strip() + "\n"
