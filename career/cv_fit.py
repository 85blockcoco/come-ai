"""Foundational fit-analysis models for targeted CV variants."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Literal

from career.cv_quality.models import CVAnalysisResult, Provenance
from career.cv_variants import CVVariant, JOB_FAMILY_TO_VARIANT
from career.models import PipelineStage


RequirementType = Literal["mandatory", "preferred"]
CurrentState = Literal[
    "missing",
    "weak",
    "unquantified",
    "wrong_variant",
    "wrong_order",
]


@dataclass(frozen=True, slots=True)
class FitGap:
    """One evidence-linked gap between a current CV and an offer."""

    requirement: str
    requirement_type: RequirementType
    current_state: CurrentState
    adapted_state: str
    provenance: Provenance | dict[str, str | int] | None
    variant_specific: bool


@dataclass(frozen=True, slots=True)
class CoverageResult:
    """Mandatory and preferred coverage for one offer and CV variant."""

    mandatory_total: int
    mandatory_covered: int
    preferred_total: int
    preferred_covered: int
    mandatory_pct: float
    preferred_pct: float
    gaps: list[FitGap]
    recommended_variant: CVVariant
    variant_rationale: str


@dataclass(frozen=True, slots=True)
class PipelineItem:
    """Serializable view of an offer's derived application-pipeline state."""

    job_id: str
    company: str
    title: str
    stage: PipelineStage
    variant: CVVariant | None
    variant_label: str | None
    kit_generated_at: str | None
    tracking_stage: str | None
    readiness: str
    match_score: int


@dataclass(frozen=True, slots=True)
class VariantClassificationResult:
    """Deterministic scores and explanation for a selected CV variant."""

    primary_variant: CVVariant
    scores: dict[str, float]
    rationale: str


EvidenceCitation = dict[str, str | int]


def _text(value: Any) -> str:
    return str(value or "")


def _profile_text(profile: dict[str, Any]) -> str:
    return " ".join(_text(profile.get(field)) for field in ("experience", "skills", "projects"))


def _profile_citation(requirement: str, profile: dict[str, Any]) -> EvidenceCitation | None:
    needle = requirement.casefold()
    if not needle:
        return None
    for field in ("experience", "skills", "projects"):
        value = _text(profile.get(field))
        offset = value.casefold().find(needle)
        if offset >= 0:
            start = max(0, offset - 60)
            end = min(len(value), offset + len(requirement) + 60)
            return {
                "source": f"profile.{field}",
                "quote": value[start:end],
                "offset": offset,
            }
    return None


def _matched_citation(requirement: str, matched_elements: list[dict[str, Any]]) -> EvidenceCitation | None:
    needle = requirement.casefold()
    for element in matched_elements:
        candidate = _text(element.get("requirement"))
        if needle in candidate.casefold() or candidate.casefold() in needle:
            evidence = _text(element.get("evidence"))
            field = _text(element.get("profile_field")) or "profile"
            return {
                "source": f"profile.{field}" if field != "profile" else field,
                "quote": evidence,
                "offset": 0,
            }
    return None


def classify_variant(
    job: dict[str, Any],
    profile: dict[str, Any],
    variants: tuple[CVVariant, ...],
) -> VariantClassificationResult:
    """Select a CV variant using only local offer and approved-profile facts."""

    job_family = _text(job.get("job_family"))
    requirements = _text(job.get("requirements")).casefold()
    experience = _text(profile.get("experience")).casefold()
    qualification = job.get("qualification")
    qualification = qualification if isinstance(qualification, dict) else {}
    provenance = qualification.get("provenance")
    provenance = provenance if isinstance(provenance, dict) else {}

    scores: dict[str, float] = {}
    signals: dict[str, tuple[bool, int, int, bool]] = {}
    family_variants = JOB_FAMILY_TO_VARIANT.get(job_family, [])
    for variant in variants:
        family_match = variant.id in family_variants
        keyword_hits = sum(keyword.casefold() in requirements for keyword in variant.mandatory_keywords)
        theme_hits = sum(keyword.casefold() in experience for keyword in variant.mandatory_keywords)
        # Seuls les faits scalaires cités participent à ce signal : une
        # preuve textuelle volumineuse (liste de missions, SK-18) ne doit
        # pas décaler le choix de variante par une simple mention de mot.
        provenance_match = any(
            variant.id in _text(value).casefold()
            for value in provenance.values()
            if isinstance(value, str)
        )
        score = (
            (0.5 if family_match else 0.0)
            + min(0.4, keyword_hits * 0.1)
            + min(0.15, theme_hits * 0.05)
            + (0.05 if provenance_match else 0.0)
        )
        scores[variant.id] = round(min(1.0, score), 2)
        signals[variant.id] = (
            family_match,
            keyword_hits,
            theme_hits,
            provenance_match,
        )

    primary = max(variants, key=lambda variant: scores[variant.id])
    if not scores[primary.id]:
        return VariantClassificationResult(
            primary_variant=primary,
            scores=scores,
            rationale="Aucun signal fort ; défaut M&A",
        )

    family_match, keyword_hits, theme_hits, provenance_match = signals[primary.id]
    reasons: list[str] = []
    if family_match:
        reasons.append(f"job_family '{job_family}' exact match (+0.50)")
    if keyword_hits:
        reasons.append(f"{keyword_hits} mot(s)-clé(s) obligatoire(s) dans l’offre")
    if theme_hits:
        reasons.append(f"{theme_hits} thème(s) étayé(s) dans l’expérience approuvée")
    if provenance_match:
        reasons.append("qualification alignée et citée")
    return VariantClassificationResult(primary, scores, "; ".join(reasons))


def _percentage(covered: int, total: int) -> float:
    return round(covered / total * 100, 1) if total else 0.0


def compute_coverage(
    job: dict[str, Any],
    cv_analysis: CVAnalysisResult,
    profile: dict[str, Any],
    variant: CVVariant,
) -> CoverageResult:
    """Compute mandatory/preferred coverage without inferring absent facts."""

    qualification = job.get("qualification")
    qualification = qualification if isinstance(qualification, dict) else {}
    qualification_provenance = qualification.get("provenance")
    qualification_provenance = qualification_provenance if isinstance(qualification_provenance, dict) else {}
    matched_elements = [item for item in (job.get("matched_elements") or []) if isinstance(item, dict)]
    matched_requirements = {_text(item.get("requirement")).casefold() for item in matched_elements}

    mandatory: list[tuple[str, str]] = []
    for field in qualification.get("missing_fields") or []:
        item = ("offer_fact", _text(field))
        if item not in mandatory:
            mandatory.append(item)
    for action in job.get("cv_action_plan") or []:
        if isinstance(action, dict) and action.get("status") == "needs_evidence":
            item = ("profile_skill", _text(action.get("requirement")))
            if item not in mandatory:
                mandatory.append(item)
    for keyword in variant.mandatory_keywords:
        if keyword.casefold() not in matched_requirements:
            item = ("variant_keyword", keyword)
            if item not in mandatory:
                mandatory.append(item)

    mandatory_covered = 0
    gaps: list[FitGap] = []
    profile_blob = _profile_text(profile).casefold()
    for source, requirement in mandatory:
        citation: EvidenceCitation | None = None
        covered = False
        if source == "offer_fact":
            evidence = qualification_provenance.get(requirement)
            covered = evidence is not None
            citation = evidence if isinstance(evidence, dict) else None
        elif source == "profile_skill":
            citation = _matched_citation(requirement, matched_elements)
            covered = citation is not None
        else:
            covered = requirement.casefold() in profile_blob
            citation = _profile_citation(requirement, profile) if covered else None
        if covered:
            mandatory_covered += 1
        else:
            gaps.append(
                FitGap(
                    requirement=requirement,
                    requirement_type="mandatory",
                    current_state="missing",
                    adapted_state=(f"Add '{requirement}' with quantified evidence: [AJOUTER PREUVE CHIFFRÉE]"),
                    provenance=citation,
                    variant_specific=source == "variant_keyword",
                )
            )

    preferred: list[tuple[str, str]] = []
    for element in matched_elements:
        item = ("matched", _text(element.get("requirement")))
        if item not in preferred:
            preferred.append(item)
    for field in qualification_provenance:
        item = ("verified_fact", _text(field))
        if item not in preferred:
            preferred.append(item)
    for keyword, _weight in sorted(variant.keyword_priorities.items(), key=lambda item: -item[1])[:10]:
        item = ("variant_preferred", keyword)
        if item not in preferred:
            preferred.append(item)

    preferred_covered = sum(
        source in {"matched", "verified_fact"} or (source == "variant_preferred" and requirement.casefold() in profile_blob)
        for source, requirement in preferred
    )
    return CoverageResult(
        mandatory_total=len(mandatory),
        mandatory_covered=mandatory_covered,
        preferred_total=len(preferred),
        preferred_covered=preferred_covered,
        mandatory_pct=_percentage(mandatory_covered, len(mandatory)),
        preferred_pct=_percentage(preferred_covered, len(preferred)),
        gaps=gaps,
        recommended_variant=variant,
        variant_rationale=f"{variant.label}: analyse locale déterministe des exigences citées.",
    )


def _section_name(finding_metadata: dict[str, Any] | None) -> str:
    metadata = finding_metadata or {}
    return _text(metadata.get("section") or metadata.get("section_name"))


def generate_diff(
    coverage: CoverageResult,
    cv_analysis: CVAnalysisResult,
    profile: dict[str, Any],
    variant: CVVariant,
    max_gaps: int = 5,
) -> list[FitGap]:
    """Build at most ``max_gaps`` actionable current-to-adapted CV changes."""

    structural: list[FitGap] = []
    for finding in cv_analysis.findings:
        if finding.code == "MISSING_SECTION":
            section = _section_name(finding.metadata) or "Required section"
            structural.append(
                FitGap(
                    requirement=section,
                    requirement_type="mandatory",
                    current_state="missing",
                    adapted_state=(f"Add {variant.section_headers.get(section, section)} section aligned with {variant.label}."),
                    provenance=None,
                    variant_specific=True,
                )
            )
        elif finding.code == "UNQUANTIFIED_EXPERIENCE":
            experience = next(
                (item for item in cv_analysis.experiences if item.source_offset == finding.source_offset),
                cv_analysis.experiences[0] if cv_analysis.experiences else None,
            )
            requirement = f"{experience.company} — {experience.role}" if experience else "Professional experience"
            structural.append(
                FitGap(
                    requirement=requirement,
                    requirement_type="mandatory",
                    current_state="unquantified",
                    adapted_state=(f"Quantify {requirement}: add a cited metric (€, %, count, duration)."),
                    provenance=cv_analysis.provenance,
                    variant_specific=False,
                )
            )

    detected_order = tuple(section.title for section in cv_analysis.sections)
    normalized_detected_order = tuple(section.casefold() for section in detected_order)
    normalized_variant_order = tuple(section.casefold() for section in variant.section_order)
    if detected_order and normalized_detected_order != normalized_variant_order[: len(normalized_detected_order)]:
        structural.append(
            FitGap(
                requirement="Section order",
                requirement_type="preferred",
                current_state="wrong_order",
                adapted_state=(f"Reorder sections for {variant.label}: " + " → ".join(variant.section_order[:4]) + "."),
                provenance=cv_analysis.provenance,
                variant_specific=True,
            )
        )

    combined = structural + list(coverage.gaps)
    unique: list[FitGap] = []
    seen: set[tuple[str, str]] = set()
    for gap in combined:
        key = (gap.requirement.casefold(), gap.current_state)
        if key not in seen:
            seen.add(key)
            unique.append(gap)
    return unique[: max(0, int(max_gaps))]


def serialize_gap(gap: FitGap, *, include_source_text: bool = False) -> dict[str, Any]:
    """Convert a gap to the public JSON contract.

    The complete CV source is private working data.  Callers must opt in
    explicitly when a trusted local workflow needs it; regular API payloads
    expose only the document metadata.
    """

    payload = asdict(gap)
    provenance = payload.get("provenance")
    if isinstance(provenance, dict) and not include_source_text:
        provenance.pop("source_text", None)
    return payload


def derive_pipeline_stage(job_id: str, context: Any) -> PipelineStage:
    """Derive the furthest evidenced stage without writing pipeline state."""

    context = context if isinstance(context, dict) else {}
    applications = context.get("applications") or []
    drafts = context.get("application_drafts") or []
    prep_cache = context.get("prep_cache") or set()
    selected = context.get("selected_variant") or {}
    sprint = context.get("sprint_queue") or []
    jobs = context.get("jobs") or {}
    application_job_ids = context.get("application_job_ids")
    if (
        job_id in application_job_ids
        if isinstance(application_job_ids, (set, frozenset))
        else any(_text(item.get("job_id")) == job_id for item in applications)
    ):
        return PipelineStage.TRACKING_CREATED
    draft_job_ids = context.get("draft_job_ids")
    if (
        job_id in draft_job_ids
        if isinstance(draft_job_ids, (set, frozenset))
        else any(_text(item.get("job_id")) == job_id for item in drafts)
    ):
        return PipelineStage.KIT_GENERATED
    if job_id in prep_cache and selected.get(job_id):
        return PipelineStage.VARIANT_SELECTED
    if job_id in prep_cache:
        return PipelineStage.PREP_ANALYZED
    sprint_job_ids = context.get("sprint_job_ids")
    if (
        job_id in sprint_job_ids
        if isinstance(sprint_job_ids, (set, frozenset))
        else any(_text(item.get("job_id")) == job_id for item in sprint)
    ):
        return PipelineStage.SPRINT_QUEUED
    job = jobs.get(job_id) if isinstance(jobs, dict) else None
    if isinstance(job, dict) and job.get("qualification_facts_json"):
        return PipelineStage.QUALIFIED
    return PipelineStage.DISCOVERED
