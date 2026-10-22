"""FastAPI routes for the local-first Côme AI Career 4.1 workspace."""

from __future__ import annotations

import hashlib
import os
from pathlib import Path
from typing import Any, Callable

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import FileResponse, Response
from pydantic import BaseModel, Field
from starlette.concurrency import run_in_threadpool
from starlette.datastructures import UploadFile

from .profile_import import MAX_PROFILE_IMPORT_BYTES
from .service import CareerService
from .traceability import TraceabilityRegistry
from .traceability_audit import (
    audit_summary,
    coverage_by_cv,
    coverage_by_offer,
    coverage_over_time,
    critical_gaps,
    history_timeline,
    waived_requirements,
)
from .traceability_store import TraceabilityStore
from workspace_core import UserFacingError, to_jsonable


CAREER_STATIC_DIR = Path(__file__).resolve().parent.parent / "career_static"
PROFILE_UPLOAD_CHUNK_SIZE = 1_024 * 1_024


class ProfilePayload(BaseModel):
    display_name: str = Field(default="", max_length=160)
    contact_email: str = Field(default="", max_length=320)
    contact_phone: str = Field(default="", max_length=80)
    linkedin_url: str = Field(default="", max_length=2_000)
    education: str = Field(default="", max_length=1_000)
    experience: str = Field(default="", max_length=6_000)
    skills: str = Field(default="", max_length=4_000)
    languages: str = Field(default="", max_length=2_000)
    eligibility: str = Field(default="unknown", max_length=40)
    target_companies: str = Field(default="", max_length=2_000)
    notes: str = Field(default="", max_length=4_000)


class PreferenceItemPayload(BaseModel):
    key: str = Field(min_length=1, max_length=80)
    label: str = Field(min_length=1, max_length=160)
    enabled: bool = True
    priority: int = Field(default=100, ge=0, le=1_000)
    scope: str = Field(default="primary", max_length=20)


class PreferencesPayload(BaseModel):
    availability: dict[str, Any] = Field(default_factory=dict)
    families: list[PreferenceItemPayload] = Field(default_factory=list, max_length=30)
    locations: list[PreferenceItemPayload] = Field(default_factory=list, max_length=30)


class JobImportPayload(BaseModel):
    company: str = Field(min_length=1, max_length=240)
    title: str = Field(min_length=1, max_length=300)
    source_name: str = Field(default="manual", max_length=120)
    source_id: str = Field(default="", max_length=240)
    official_url: str = Field(default="", max_length=2_000)
    job_family: str = Field(default="À préciser", max_length=160)
    city: str = Field(default="", max_length=160)
    country: str = Field(default="", max_length=120)
    posted_date: str = Field(default="", max_length=32)
    deadline_date: str = Field(default="", max_length=32)
    start_date: str = Field(default="", max_length=32)
    end_date: str = Field(default="", max_length=32)
    duration_months: int | None = Field(default=None, ge=1, le=24)
    source_status: str = Field(default="unknown", max_length=40)
    employment_type: str = Field(default="", max_length=120)
    role_level: str = Field(default="", max_length=120)
    requirements: str = Field(default="", max_length=12_000)
    languages_required: str = Field(default="", max_length=2_000)
    eligibility_requirement: str = Field(default="", max_length=2_000)
    description_original: str = Field(default="", max_length=30_000)


class ShortlistPayload(BaseModel):
    shortlisted: bool
    note: str = Field(default="", max_length=4_000)


class NotePayload(BaseModel):
    note: str = Field(default="", max_length=4_000)


class StageSearchPayload(BaseModel):
    """The person's own internship-search brief; every field is optional so no
    preference is presumed before they fill it in."""

    domains: list[str] = Field(default_factory=list, max_length=12)
    other_domains: list[str] = Field(default_factory=list, max_length=12)
    roles: list[str] = Field(default_factory=list, max_length=20)
    countries: list[str] = Field(default_factory=list, max_length=20)
    cities: list[str] = Field(default_factory=list, max_length=20)
    excluded_countries: list[str] = Field(default_factory=lambda: ["France"], max_length=20)
    excluded_cities: list[str] = Field(default_factory=lambda: ["Paris"], max_length=20)
    require_known_location: bool = True
    start_date: str = Field(default="", max_length=32)
    duration_months: int | None = Field(default=None, ge=1, le=24)
    contract_types: list[str] = Field(default_factory=lambda: ["stage", "cdd", "cdi", "vie"], max_length=4)
    start_months: list[int] = Field(default_factory=lambda: [1, 2, 3], max_length=12)
    minimum_stage_duration_months: int = Field(default=6, ge=1, le=24)
    education_preference: str = Field(default="bachelor_m1_then_m2", max_length=40)
    study_level: str = Field(default="", max_length=120)
    languages: list[str] = Field(default_factory=list, max_length=10)
    constraints: str = Field(default="", max_length=2_000)
    ranking: dict[str, float] = Field(default_factory=dict)


class ApplicationCreatePayload(BaseModel):
    job_id: str = Field(min_length=8, max_length=80)


class ApplicationStagePayload(BaseModel):
    stage: str = Field(min_length=2, max_length=80)
    note: str = Field(default="", max_length=1_000)


class ApprovalPayload(BaseModel):
    approved: bool
    note: str = Field(default="", max_length=1_000)


class ReceiptPayload(BaseModel):
    confirmation_reference: str = Field(min_length=2, max_length=1_000)


class ReceiptUnknownPayload(BaseModel):
    note: str = Field(default="", max_length=1_000)


class ApplicationChecklistPayload(BaseModel):
    """Cinq cases locales seulement ; rien n'est transitionné ni envoyé."""

    checked: list[str] = Field(default_factory=list, max_length=10)


class ResetPayload(BaseModel):
    confirmation: str = Field(min_length=1, max_length=100)


class ProfileTextImportPayload(BaseModel):
    source_kind: str = Field(default="linkedin_text", min_length=2, max_length=40)
    text: str = Field(min_length=1, max_length=100_000)
    original_name: str = Field(default="texte-profil", max_length=180)


class ProfileImportUpdatePayload(BaseModel):
    field: str = Field(min_length=2, max_length=80)
    value: str = Field(min_length=1, max_length=6_000)
    mode: str = Field(default="replace", max_length=20)


class ProfileImportApplyPayload(BaseModel):
    updates: list[ProfileImportUpdatePayload] = Field(min_length=1, max_length=8)
    base_profile_updated_at: str = Field(default="", max_length=64)


class IntakeAnswerPayload(BaseModel):
    answer: str = Field(min_length=1, max_length=1_500)


class ApplicationDraftPayload(BaseModel):
    job_id: str = Field(min_length=8, max_length=80)
    language: str = Field(default="fr", min_length=2, max_length=16)
    mode: str = Field(default="local", max_length=12)
    consent_external: bool = False


class ApplicationKitPayload(BaseModel):
    """One explicit user action to open a local application kit for one offer."""

    job_id: str = Field(min_length=8, max_length=80)
    language: str = Field(default="fr", min_length=2, max_length=16)
    variant: str = Field(default="m_a", pattern="^(m_a|markets|corporate_finance)$")


class ApplicationKitTextsPayload(BaseModel):
    """Edited kit texts; each field stays optional so saves can be partial."""

    motivation_short: str | None = Field(default=None, max_length=1_200)
    availability: str | None = Field(default=None, max_length=400)


class ApplicationDraftEditPayload(BaseModel):
    """Reviewed CV/letter corrections saved before any local export."""

    cv_markdown: str = Field(min_length=1, max_length=18_000)
    letter_markdown: str = Field(min_length=1, max_length=18_000)


class JobSummaryPayload(BaseModel):
    mode: str = Field(default="local", max_length=12)
    consent_external: bool = False
    consent_id: str = Field(default="", max_length=120)


class DiscoverySourcePayload(BaseModel):
    company: str = Field(min_length=1, max_length=240)
    board_reference: str = Field(min_length=1, max_length=2_000)
    enabled: bool = True


class DiscoverySourceUpdatePayload(BaseModel):
    enabled: bool


class DiscoverySearchPayload(BaseModel):
    force: bool = False


class InterviewSessionPayload(BaseModel):
    mode: str = Field(default="technical", min_length=2, max_length=80)
    difficulty: str = Field(default="intermediate", min_length=2, max_length=80)
    language: str = Field(default="fr", min_length=2, max_length=16)
    job_id: str = Field(default="", max_length=80)
    application_id: str = Field(default="", max_length=80)


class InterviewAnswerPayload(BaseModel):
    answer: str = Field(min_length=3, max_length=6_000)


class CVAnalyzePayload(BaseModel):
    """Request payload for CV structural analysis."""
    text: str = Field(min_length=1, max_length=200_000)
    filename: str | None = Field(default=None, max_length=256)
    filetype: str = Field(default="txt", pattern="^(txt|pdf|docx)$")


class CVAnalyzeResponse(BaseModel):
    """Response payload for CV structural analysis."""
    findings: list[dict[str, Any]]
    sections: list[dict[str, Any]]
    experiences: list[dict[str, Any]]
    readability: dict[str, Any]
    provenance: dict[str, Any]


# --- SPEC-011 : registre de traçabilité des exigences ------------------------


class TraceabilityRequirementPayload(BaseModel):
    """One requirement to trace (creation)."""

    requirement_id: str = Field(default="", max_length=240)
    requirement_text: str = Field(min_length=1, max_length=4_000)
    source: str = Field(default="manual", min_length=1, max_length=240)
    category: str = Field(default="other", max_length=40)
    criticality: str = Field(default="contextual", max_length=40)
    evidence_id: str = Field(default="", max_length=240)
    evidence_quote: str = Field(default="", max_length=2_000)
    status: str = Field(default="", max_length=40)
    tags: list[str] = Field(default_factory=list, max_length=20)
    comment: str = Field(default="", max_length=2_000)
    actor: str = Field(default="user", max_length=20)


class TraceabilityUpdatePayload(BaseModel):
    """Partial update of a traced requirement."""

    status: str | None = Field(default=None, max_length=40)
    evidence_id: str | None = Field(default=None, max_length=240)
    evidence_quote: str | None = Field(default=None, max_length=2_000)
    tags: list[str] | None = Field(default=None, max_length=20)
    category: str | None = Field(default=None, max_length=40)
    criticality: str | None = Field(default=None, max_length=40)
    comment: str = Field(default="", max_length=2_000)
    actor: str = Field(default="user", max_length=20)


class TraceabilityLinkPayload(BaseModel):
    """Evidence to attach to a traced requirement."""

    evidence_id: str = Field(min_length=1, max_length=240)
    evidence_quote: str = Field(default="", max_length=2_000)
    status: str = Field(default="", max_length=40)
    comment: str = Field(default="", max_length=2_000)
    actor: str = Field(default="user", max_length=20)


class TraceabilityCommentPayload(BaseModel):
    """Comment carried by an action that does not change the proof."""

    comment: str = Field(default="", max_length=2_000)
    actor: str = Field(default="user", max_length=20)


class TraceabilityWaivePayload(BaseModel):
    """Waiver of a requirement, with its mandatory justification."""

    justification: str = Field(min_length=3, max_length=2_000)
    actor: str = Field(default="user", max_length=20)


class TraceabilityOfferSyncPayload(BaseModel):
    """Offer whose SK-02 analysis feeds the registry."""

    offer: dict[str, Any] = Field(default_factory=dict)
    actor: str = Field(default="system", max_length=20)


class TraceabilityImportPayload(BaseModel):
    """Registry previously exported as JSON."""

    registry: dict[str, Any] = Field(default_factory=dict)
    mode: str = Field(default="replace", pattern="^(replace|merge)$")


def _traceability_store(service: CareerService) -> TraceabilityStore:
    """Return the local registry store of the Career workspace."""

    data_dir = getattr(service, "data_dir", None)
    base = Path(data_dir) if data_dir else Path.cwd() / "career_data"
    return TraceabilityStore(base / "traceability" / "registry.json")


def create_traceability_router(service: CareerService) -> APIRouter:
    """CRUD, audit and export routes of the traceability registry (SPEC-011).

    Every route is exposed twice: under the historical Career prefix
    (``/api/career/traceability/…``) and under the SPEC-011 paths
    (``/traceability/…``) so both contracts answer the same registry.
    """

    router = APIRouter()

    async def local(call: Any) -> Any:
        return to_jsonable(await run_in_threadpool(call))

    def load_registry() -> TraceabilityRegistry:
        return _traceability_store(service).load()

    def save_registry(registry: TraceabilityRegistry) -> None:
        _traceability_store(service).save(registry)

    @router.post("/api/career/traceability/requirements", status_code=201)
    @router.post("/traceability/requirements", status_code=201)
    async def create_traceability_requirement(payload: TraceabilityRequirementPayload) -> Any:
        """Record one requirement and start its history."""

        def operation() -> dict[str, Any]:
            registry = load_registry()
            trace = registry.create(
                requirement_id=payload.requirement_id,
                requirement_text=payload.requirement_text,
                source=payload.source,
                category=payload.category,
                criticality=payload.criticality,
                evidence_id=payload.evidence_id or None,
                evidence_quote=payload.evidence_quote or None,
                status=payload.status or None,
                tags=payload.tags,
                actor=payload.actor,
                comment=payload.comment or None,
            )
            save_registry(registry)
            return trace.to_dict()

        return await local(operation)

    @router.get("/api/career/traceability/requirements")
    @router.get("/traceability/requirements")
    async def list_traceability_requirements(
        status: str = Query(default="", max_length=40),
        category: str = Query(default="", max_length=40),
        criticality: str = Query(default="", max_length=40),
        source: str = Query(default="", max_length=240),
        offer_id: str = Query(default="", max_length=240),
        cv_id: str = Query(default="", max_length=240),
        tag: str = Query(default="", max_length=60),
        q: str = Query(default="", max_length=240),
        include_deleted: bool = Query(default=False),
    ) -> Any:
        """List the traced requirements, filtered."""

        def operation() -> dict[str, Any]:
            registry = load_registry()
            traces = registry.filter(
                status=status or None,
                category=category or None,
                criticality=criticality or None,
                source=source or None,
                offer_id=offer_id or None,
                cv_id=cv_id or None,
                tag=tag or None,
                text=q or None,
                include_deleted=include_deleted,
            )
            return {
                "traces": [trace.to_dict() for trace in traces],
                "count": len(traces),
                "filters": {
                    "status": status,
                    "category": category,
                    "criticality": criticality,
                    "source": source,
                    "offer_id": offer_id,
                    "cv_id": cv_id,
                    "tag": tag,
                    "q": q,
                },
            }

        return await local(operation)

    @router.get("/api/career/traceability/requirements/{trace_id}")
    @router.get("/traceability/requirements/{trace_id}")
    async def get_traceability_requirement(trace_id: str) -> Any:
        """Return one traced requirement with its whole history."""

        def operation() -> dict[str, Any]:
            registry = load_registry()
            trace = registry.require(trace_id)
            payload = trace.to_dict()
            payload["justification"] = trace.justification()
            return payload

        return await local(operation)

    @router.patch("/api/career/traceability/requirements/{trace_id}")
    @router.patch("/traceability/requirements/{trace_id}")
    async def update_traceability_requirement(trace_id: str, payload: TraceabilityUpdatePayload) -> Any:
        """Change the status, the proof, the tags or the classification."""

        def operation() -> dict[str, Any]:
            registry = load_registry()
            trace = registry.update(
                trace_id,
                status=payload.status,
                evidence_id=payload.evidence_id,
                evidence_quote=payload.evidence_quote,
                tags=payload.tags,
                category=payload.category,
                criticality=payload.criticality,
                comment=payload.comment or None,
                actor=payload.actor,
            )
            save_registry(registry)
            return trace.to_dict()

        return await local(operation)

    @router.post("/api/career/traceability/requirements/{trace_id}/link-evidence")
    @router.post("/traceability/requirements/{trace_id}/link-evidence")
    async def link_traceability_evidence(trace_id: str, payload: TraceabilityLinkPayload) -> Any:
        """Attach a proof to a requirement."""

        def operation() -> dict[str, Any]:
            registry = load_registry()
            trace = registry.link_evidence(
                trace_id,
                payload.evidence_id,
                payload.evidence_quote,
                status=payload.status or None,
                actor=payload.actor,
                comment=payload.comment or None,
            )
            save_registry(registry)
            return trace.to_dict()

        return await local(operation)

    @router.post("/api/career/traceability/requirements/{trace_id}/unlink-evidence")
    @router.post("/traceability/requirements/{trace_id}/unlink-evidence")
    async def unlink_traceability_evidence(trace_id: str, payload: TraceabilityCommentPayload) -> Any:
        """Detach the proof of a requirement."""

        def operation() -> dict[str, Any]:
            registry = load_registry()
            trace = registry.unlink_evidence(
                trace_id,
                actor=payload.actor,
                comment=payload.comment or None,
            )
            save_registry(registry)
            return trace.to_dict()

        return await local(operation)

    @router.post("/api/career/traceability/requirements/{trace_id}/waive")
    @router.post("/traceability/requirements/{trace_id}/waive")
    async def waive_traceability_requirement(trace_id: str, payload: TraceabilityWaivePayload) -> Any:
        """Waive a requirement with an explicit justification."""

        def operation() -> dict[str, Any]:
            registry = load_registry()
            trace = registry.waive(trace_id, payload.justification, actor=payload.actor)
            save_registry(registry)
            return trace.to_dict()

        return await local(operation)

    @router.post("/api/career/traceability/requirements/{trace_id}/reopen")
    @router.post("/traceability/requirements/{trace_id}/reopen")
    async def reopen_traceability_requirement(trace_id: str, payload: TraceabilityCommentPayload) -> Any:
        """Reopen a waived requirement."""

        def operation() -> dict[str, Any]:
            registry = load_registry()
            trace = registry.reopen(trace_id, actor=payload.actor, comment=payload.comment or None)
            save_registry(registry)
            return trace.to_dict()

        return await local(operation)

    @router.delete("/api/career/traceability/requirements/{trace_id}")
    @router.delete("/traceability/requirements/{trace_id}")
    async def delete_traceability_requirement(trace_id: str, payload: TraceabilityCommentPayload) -> Any:
        """Archive a requirement; the audit trail survives the deletion."""

        def operation() -> dict[str, Any]:
            registry = load_registry()
            trace = registry.delete(trace_id, actor=payload.actor, comment=payload.comment or None)
            save_registry(registry)
            return {"deleted": True, "trace_id": trace.trace_id}

        return await local(operation)

    @router.get("/api/career/traceability/audit/coverage")
    @router.get("/traceability/audit/coverage")
    async def traceability_coverage() -> Any:
        """Coverage report per offer and per CV, plus the coverage curve."""

        def operation() -> dict[str, Any]:
            registry = load_registry()
            return {
                "summary": audit_summary(registry),
                "by_offer": coverage_by_offer(registry),
                "by_cv": coverage_by_cv(registry),
                "over_time": coverage_over_time(registry),
            }

        return await local(operation)

    @router.get("/api/career/traceability/audit/gaps")
    @router.get("/traceability/audit/gaps")
    async def traceability_gaps(
        limit: int = Query(default=200, ge=1, le=2_000),
    ) -> Any:
        """Mandatory requirements that are not covered."""

        def operation() -> dict[str, Any]:
            registry = load_registry()
            gaps = critical_gaps(registry, limit=limit)
            return {"gaps": gaps, "count": len(gaps)}

        return await local(operation)

    @router.get("/api/career/traceability/audit/history")
    @router.get("/traceability/audit/history")
    async def traceability_history(
        trace_id: str = Query(default="", max_length=64),
        event_type: str = Query(default="", max_length=40),
        actor: str = Query(default="", max_length=20),
        source: str = Query(default="", max_length=240),
        since: str = Query(default="", max_length=64),
        until: str = Query(default="", max_length=64),
        limit: int = Query(default=500, ge=1, le=5_000),
    ) -> Any:
        """Chronological, filtered audit trail."""

        def operation() -> dict[str, Any]:
            registry = load_registry()
            events = history_timeline(
                registry,
                trace_id=trace_id or None,
                event_type=event_type or None,
                actor=actor or None,
                source_filter=source or None,
                since=since or None,
                until=until or None,
                limit=limit,
            )
            return {"events": events, "count": len(events)}

        return await local(operation)

    @router.get("/api/career/traceability/audit/waived")
    @router.get("/traceability/audit/waived")
    async def traceability_waived() -> Any:
        """Waived requirements with their justification."""

        def operation() -> dict[str, Any]:
            registry = load_registry()
            waived = waived_requirements(registry)
            return {"waived": waived, "count": len(waived)}

        return await local(operation)

    @router.get("/api/career/traceability/export")
    @router.get("/traceability/export")
    async def export_traceability(
        export_format: str = Query(default="json", pattern="^(json|csv)$"),
    ) -> Any:
        """Export the whole registry (JSON or CSV)."""

        def operation() -> Any:
            store = _traceability_store(service)
            registry = store.load()
            if export_format == "csv":
                return Response(
                    content=store.export_csv(registry),
                    media_type="text/csv; charset=utf-8",
                    headers={"Content-Disposition": 'attachment; filename="traceability.csv"'},
                )
            return Response(
                content=store.export_json(registry),
                media_type="application/json",
                headers={"Content-Disposition": 'attachment; filename="traceability.json"'},
            )

        return await run_in_threadpool(operation)

    @router.post("/api/career/traceability/sync-offer")
    @router.post("/traceability/sync-offer")
    async def sync_traceability_offer(payload: TraceabilityOfferSyncPayload) -> Any:
        """Create the traces of an offer from its SK-02 analysis."""

        def operation() -> dict[str, Any]:
            from career.offer_requirements import analyze_offer

            analysis = analyze_offer(payload.offer)
            registry = load_registry()
            summary = registry.sync_offer_analysis(analysis, actor=payload.actor)
            save_registry(registry)
            return {"summary": summary, "requirements": len(analysis.get("requirements", []))}

        return await local(operation)

    @router.post("/api/career/traceability/import")
    @router.post("/traceability/import")
    async def import_traceability(payload: TraceabilityImportPayload) -> Any:
        """Import a registry exported as JSON."""

        def operation() -> dict[str, Any]:
            store = _traceability_store(service)
            imported = store.import_json(payload.registry)
            if payload.mode == "merge":
                registry = store.load()
                for trace in imported.traces(include_deleted=True):
                    if registry.get(trace.trace_id) is None:
                        registry.add(trace)
            else:
                registry = imported
            store.save(registry)
            return {"imported": len(registry.traces()), "mode": payload.mode}

        return await local(operation)

    return router


def create_career_router(
    service: CareerService,
    *,
    ai_generator: Callable[[str], dict[str, Any]] | None = None,
) -> APIRouter:
    if not CAREER_STATIC_DIR.is_dir():
        raise RuntimeError("Les fichiers Career Agent sont introuvables.")
    router = APIRouter()
    # SPEC-011 : le registre de traçabilité partage le même service Career et
    # le même espace de données local ; il n'ouvre aucune connexion réseau.
    router.include_router(create_traceability_router(service))

    async def local(call: Any) -> Any:
        return to_jsonable(await run_in_threadpool(call))

    @router.get("/career", include_in_schema=False)
    async def career_page() -> FileResponse:
        return FileResponse(CAREER_STATIC_DIR / "index.html", media_type="text/html; charset=utf-8")

    @router.get("/api/career/health")
    async def health() -> dict[str, Any]:
        capabilities = await local(service.local_capabilities)
        return {
            "module": "Côme AI Career 4.1",
            "mode": "local par défaut",
            "network_connectors": capabilities["discovery"]["enabled"],
            "automated_submission": False,
            "profile_imports": {
                "enabled": True,
                "local_only": True,
                "linkedin_connection": False,
                "review_required": True,
            },
            "ocr": capabilities["ocr"],
            "guided_intake": capabilities["guided_intake"],
            "application_studio": capabilities["application_studio"],
            "ai_enhancement": {"available": ai_generator is not None, "explicit_consent_required": True},
            "discovery": capabilities["discovery"],
            "scoring": capabilities["scoring"],
            "interview_coach": capabilities["interview_coach"],
            "calendar_export": capabilities["calendar_export"],
            "stage_search": capabilities["stage_search"],
        }

    @router.post("/api/career/cv/analyze")
    async def analyze_cv_endpoint(payload: CVAnalyzePayload) -> CVAnalyzeResponse:
        """Analyze a CV for structural quality issues (100% local, deterministic)."""
        from career.cv_quality import analyze_cv, DocumentInput

        document = DocumentInput(
            text=payload.text,
            filename=payload.filename,
            filetype=payload.filetype,
        )
        result = await local(lambda: analyze_cv(document))

        # Convert dataclasses to dicts for JSON serialization
        def finding_to_dict(f):
            return {
                "code": f.code,
                "status": f.status,
                "message": f.message,
                "source_offset": f.source_offset,
                "source_excerpt": f.source_excerpt,
                "metadata": f.metadata,
            }

        def section_to_dict(s):
            return {
                "title": s.title,
                "start_offset": s.start_offset,
                "end_offset": s.end_offset,
                "content_preview": s.content_preview,
            }

        def exp_to_dict(e):
            return {
                "company": e.company,
                "role": e.role,
                "start_date": e.start_date,
                "end_date": e.end_date,
                "description": e.description,
                "has_quantified_result": e.has_quantified_result,
                "source_offset": e.source_offset,
            }

        return CVAnalyzeResponse(
            findings=[finding_to_dict(f) for f in result.findings],
            sections=[section_to_dict(s) for s in result.sections],
            experiences=[exp_to_dict(e) for e in result.experiences],
            readability={
                "flesch_kincaid_fr": result.readability.flesch_kincaid_fr,
                "avg_sentence_length": result.readability.avg_sentence_length,
                "complex_word_ratio": result.readability.complex_word_ratio,
            },
            provenance={
                "filename": result.provenance.filename,
                "filetype": result.provenance.filetype,
                "text_length": result.provenance.text_length,
                "page_count": result.provenance.page_count,
            },
        )

    @router.get("/api/career/dashboard")
    async def dashboard() -> Any:
        return await local(service.dashboard)

    @router.get("/api/career/profile")
    async def profile() -> Any:
        return await local(service.get_profile)

    @router.put("/api/career/profile")
    async def update_profile(payload: ProfilePayload) -> Any:
        return await local(lambda: service.update_profile(payload.model_dump()))

    @router.get("/api/career/profile-imports")
    async def profile_imports() -> Any:
        return await local(lambda: {"profile_imports": service.list_profile_imports()})

    @router.post("/api/career/profile-imports", status_code=201)
    async def import_profile_document(request: Request) -> Any:
        form = None
        try:
            form = await request.form(max_files=1, max_fields=2, max_part_size=64 * 1024)
        except (HTTPException, ValueError) as error:
            raise UserFacingError(
                "Import de profil invalide : envoie un document et un type de source court."
            ) from error
        try:
            upload_items = [
                (key, value) for key, value in form.multi_items() if isinstance(value, UploadFile)
            ]
            if len(upload_items) != 1 or upload_items[0][0] != "document":
                raise UserFacingError("Sélectionne un seul fichier dans le champ « document ».")
            text_fields = [key for key, value in form.multi_items() if not isinstance(value, UploadFile)]
            if any(key != "source_kind" for key in text_fields):
                raise UserFacingError("L’import de profil contient un champ inattendu.")
            source_kind = str(form.get("source_kind", "cv"))
            return await _store_profile_document(service, upload_items[0][1], source_kind)
        finally:
            if form is not None:
                await form.close()

    @router.post("/api/career/profile-imports/text", status_code=201)
    async def import_profile_text(payload: ProfileTextImportPayload) -> Any:
        return await local(
            lambda: service.import_profile_text(
                source_kind=payload.source_kind,
                text=payload.text,
                original_name=payload.original_name,
            )
        )

    @router.get("/api/career/profile-imports/{import_id}")
    async def profile_import(import_id: str) -> Any:
        return await local(lambda: service.get_profile_import(import_id))

    @router.post("/api/career/profile-imports/{import_id}/apply")
    async def apply_profile_import(import_id: str, payload: ProfileImportApplyPayload) -> Any:
        return await local(
            lambda: service.apply_profile_import(
                import_id,
                [item.model_dump() for item in payload.updates],
                payload.base_profile_updated_at,
            )
        )

    @router.delete("/api/career/profile-imports/{import_id}")
    async def delete_profile_import(import_id: str) -> dict[str, bool]:
        await local(lambda: service.delete_profile_import(import_id))
        return {"deleted": True}

    @router.get("/api/career/intake")
    async def intake() -> Any:
        return await local(service.get_intake)

    @router.post("/api/career/intake/answers")
    async def answer_career_intake(payload: IntakeAnswerPayload) -> Any:
        return await local(lambda: service.answer_intake(payload.answer))

    @router.delete("/api/career/intake")
    async def reset_career_intake() -> Any:
        return await local(service.reset_intake)

    @router.get("/api/career/preferences")
    async def preferences() -> Any:
        return await local(service.get_preferences)

    @router.put("/api/career/preferences")
    async def update_preferences(payload: PreferencesPayload) -> Any:
        return await local(lambda: service.update_preferences(payload.model_dump()))

    @router.get("/api/career/stage-search")
    async def stage_search() -> Any:
        return await local(service.get_stage_search)

    @router.put("/api/career/stage-search")
    async def update_stage_search(payload: StageSearchPayload) -> Any:
        return await local(lambda: service.update_stage_search(payload.model_dump()))

    @router.get("/api/career/stage-search/matches")
    async def stage_search_matches() -> Any:
        return await local(service.list_stage_matches)

    @router.get("/api/career/application-sprint")
    async def application_sprint(limit: int = Query(default=12, ge=1, le=30)) -> Any:
        """Build a local preparation queue; this route never submits anything."""
        return await local(lambda: service.get_application_sprint(limit=limit))

    @router.get("/api/career/application-pipeline")
    async def application_pipeline() -> Any:
        return await local(service.get_application_pipeline)

    @router.get("/api/career/stage-search/explore")
    async def last_stage_exploration() -> Any:
        # Opening Career reads the last local report; it never fetches boards.
        return await local(service.get_exploration)

    @router.post("/api/career/stage-search/explore")
    async def explore_stages(payload: DiscoverySearchPayload) -> Any:
        return await local(lambda: service.explore_internships(force=payload.force))

    @router.get("/api/career/discovery-sources")
    async def discovery_sources() -> Any:
        return await local(lambda: {"sources": service.list_discovery_sources()})

    @router.post("/api/career/discovery-sources", status_code=201)
    async def create_discovery_source(payload: DiscoverySourcePayload) -> Any:
        return await local(lambda: service.create_discovery_source(payload.model_dump()))

    @router.patch("/api/career/discovery-sources/{source_id}")
    async def update_discovery_source(source_id: str, payload: DiscoverySourceUpdatePayload) -> Any:
        return await local(lambda: service.set_discovery_source_enabled(source_id, payload.enabled))

    @router.get("/api/career/discovery-runs")
    async def discovery_runs() -> Any:
        return await local(lambda: {"runs": service.list_discovery_runs()})

    @router.post("/api/career/discovery/search")
    async def discover_opportunities(payload: DiscoverySearchPayload) -> Any:
        return await local(lambda: service.discover_opportunities(force=payload.force))

    @router.get("/api/career/jobs")
    async def jobs(
        query: str = Query(default="", max_length=240),
        family: str = Query(default="", max_length=160),
        city: str = Query(default="", max_length=160),
        source_status: str = Query(default="", max_length=40),
        shortlisted: bool | None = None,
        calendar_status: str = Query(default="", max_length=80),
    ) -> Any:
        return await local(
            lambda: {
                "jobs": service.list_jobs(
                    query=query,
                    family=family,
                    city=city,
                    source_status=source_status,
                    shortlisted=shortlisted,
                    calendar_status=calendar_status,
                )
            }
        )

    @router.post("/api/career/jobs/import", status_code=201)
    async def import_job(payload: JobImportPayload) -> Any:
        result = await local(lambda: service.import_job(payload.model_dump()))
        return result

    @router.get("/api/career/jobs/{job_id}")
    async def job(job_id: str) -> Any:
        return await local(lambda: service.get_job(job_id))

    @router.get("/api/career/jobs/{job_id}/prep")
    async def job_prep(job_id: str) -> Any:
        return await local(lambda: service.get_job_prep(job_id))

    @router.get("/api/career/jobs/{job_id}/summary")
    async def job_summary(
        job_id: str,
        mode: str = "local",
        consent_external: bool = False,
        consent_id: str = "",
    ) -> Any:
        normalized_mode = str(mode or "local").strip().lower()
        if normalized_mode not in {"local", "ai"}:
            raise UserFacingError("Le mode de résumé doit être local ou IA.")
        return await local(
            lambda: service.get_job_summary(
                job_id,
                mode=normalized_mode,
                consent_external=bool(consent_external),
                consent_id=consent_id or None,
                ai_generator=ai_generator if normalized_mode == "ai" else None,
            )
        )

    @router.post("/api/career/jobs/{job_id}/summary")
    async def job_summary_post(job_id: str, payload: JobSummaryPayload) -> Any:
        normalized_mode = str(payload.mode or "local").strip().lower()
        if normalized_mode not in {"local", "ai"}:
            raise UserFacingError("Le mode de résumé doit être local ou IA.")
        return await local(
            lambda: service.get_job_summary(
                job_id,
                mode=normalized_mode,
                consent_external=bool(payload.consent_external),
                consent_id=payload.consent_id or None,
                ai_generator=ai_generator if normalized_mode == "ai" else None,
            )
        )

    @router.post("/api/career/jobs/{job_id}/shortlist")
    async def shortlist(job_id: str, payload: ShortlistPayload) -> Any:
        return await local(lambda: service.set_shortlist(job_id, payload.shortlisted, payload.note))

    @router.patch("/api/career/jobs/{job_id}/note")
    async def job_note(job_id: str, payload: NotePayload) -> Any:
        return await local(lambda: service.update_job_note(job_id, payload.note))

    @router.delete("/api/career/jobs/{job_id}")
    async def delete_job(job_id: str) -> dict[str, bool]:
        await local(lambda: service.delete_job(job_id))
        return {"deleted": True}

    @router.get("/api/career/application-drafts")
    async def application_drafts() -> Any:
        return await local(lambda: {"application_drafts": service.list_application_drafts()})

    @router.post("/api/career/application-drafts", status_code=201)
    async def create_application_draft(payload: ApplicationDraftPayload) -> Any:
        use_ai = payload.mode.strip().lower() == "ai"
        if payload.mode.strip().lower() not in {"local", "ai"}:
            raise UserFacingError("Le mode de brouillon doit être local ou IA.")
        if use_ai and not payload.consent_external:
            raise UserFacingError(
                "Coche la confirmation avant d’envoyer le profil et l’offre sélectionnés au fournisseur IA configuré."
            )
        if use_ai and ai_generator is None:
            raise UserFacingError("Aucun fournisseur IA Career n’est configuré. Utilise le mode local.")
        return await local(
            lambda: service.create_application_draft(
                payload.job_id,
                payload.language,
                use_ai=use_ai,
                ai_generator=ai_generator if use_ai else None,
            )
        )

    @router.get("/api/career/application-drafts/{draft_id}")
    async def application_draft(draft_id: str) -> Any:
        return await local(lambda: service.get_application_draft(draft_id))

    @router.delete("/api/career/application-drafts/{draft_id}")
    async def delete_application_draft(draft_id: str) -> dict[str, bool]:
        await local(lambda: service.delete_application_draft(draft_id))
        return {"deleted": True}

    @router.get("/api/career/application-drafts/{draft_id}/download/{kind}/{export_format}")
    async def download_application_draft(draft_id: str, kind: str, export_format: str) -> FileResponse:
        path = await run_in_threadpool(lambda: service.export_application_draft(draft_id, kind, export_format))
        media_types = {
            "md": "text/markdown; charset=utf-8",
            "html": "text/html; charset=utf-8",
            "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            "pdf": "application/pdf",
        }
        media_type = media_types.get(export_format)
        if not media_type:
            raise UserFacingError("Format de brouillon non pris en charge.")
        return FileResponse(
            path,
            filename=path.name,
            media_type=media_type,
            headers={"Cache-Control": "no-store"},
        )

    @router.get("/api/career/applications")
    async def applications() -> Any:
        return await local(lambda: {"applications": service.list_applications()})

    @router.post("/api/career/application-kits")
    async def create_application_kit(payload: ApplicationKitPayload) -> Any:
        """One user action: idempotent tracking + reusable local draft + kit."""
        return await local(
            lambda: service.create_application_kit(
                payload.job_id, payload.language, payload.variant
            )
        )

    @router.get("/api/career/applications/{application_id}/kit")
    async def application_kit(application_id: str, language: str = "fr") -> Any:
        return await local(lambda: service.get_application_kit(application_id, language))

    @router.patch("/api/career/applications/{application_id}/kit")
    async def update_application_kit(application_id: str, payload: ApplicationKitTextsPayload) -> Any:
        texts = {"motivation_short": payload.motivation_short, "availability": payload.availability}
        return await local(lambda: service.update_kit_texts(application_id, texts))

    @router.patch("/api/career/application-drafts/{draft_id}")
    async def update_application_draft(draft_id: str, payload: ApplicationDraftEditPayload) -> Any:
        return await local(
            lambda: service.update_application_draft(draft_id, payload.cv_markdown, payload.letter_markdown)
        )

    @router.post("/api/career/applications", status_code=201)
    async def create_application(payload: ApplicationCreatePayload) -> Any:
        return await local(lambda: service.create_application(payload.job_id))

    # CVBOOST-09 : cette route de lecture doit rester enregistrée avant la
    # route paramétrée /applications/{application_id} pour ne jamais être
    # interprétée comme un identifiant de candidature.
    @router.get("/api/career/applications/dashboard")
    async def applications_dashboard(
        stage: str = Query(default="", max_length=80),
        receipt: str = Query(default="", max_length=80),
        action_required: str = Query(default="", max_length=16),
        deadline: str = Query(default="", max_length=40),
        query: str = Query(default="", max_length=120),
    ) -> Any:
        if action_required and action_required not in {"true", "false"}:
            raise HTTPException(status_code=422, detail="Le filtre de prochaine action doit valoir true ou false.")
        action_filter: bool | None = (action_required == "true") if action_required else None
        return await local(
            lambda: service.application_dashboard(
                stage=stage,
                receipt=receipt,
                action_required=action_filter,
                deadline=deadline,
                query=query,
            )
        )

    @router.get("/api/career/applications/{application_id}")
    async def application(application_id: str) -> Any:
        return await local(lambda: service.get_application(application_id))

    @router.patch("/api/career/applications/{application_id}")
    async def update_application(application_id: str, payload: ApplicationStagePayload) -> Any:
        return await local(lambda: service.update_application_stage(application_id, payload.stage, payload.note))

    @router.post("/api/career/applications/{application_id}/approve")
    async def approve_application(application_id: str, payload: ApprovalPayload) -> Any:
        return await local(
            lambda: service.approve_for_manual_submission(application_id, payload.approved, payload.note)
        )

    @router.post("/api/career/applications/{application_id}/confirm-receipt")
    async def confirm_receipt(application_id: str, payload: ReceiptPayload) -> Any:
        return await local(lambda: service.confirm_receipt(application_id, payload.confirmation_reference))

    @router.post("/api/career/applications/{application_id}/receipt-unknown")
    async def receipt_unknown(application_id: str, payload: ReceiptUnknownPayload) -> Any:
        return await local(lambda: service.mark_receipt_unknown(application_id, payload.note))

    @router.post("/api/career/applications/{application_id}/checklist")
    async def application_checklist(application_id: str, payload: ApplicationChecklistPayload) -> Any:
        return await local(lambda: service.set_application_checklist(application_id, payload.checked))

    @router.get("/api/career/interview-sessions")
    async def interview_sessions() -> Any:
        return await local(lambda: {"interview_sessions": service.list_interview_sessions()})

    @router.post("/api/career/interview-sessions", status_code=201)
    async def create_interview_session(payload: InterviewSessionPayload) -> Any:
        return await local(lambda: service.create_interview_session(payload.model_dump()))

    @router.get("/api/career/interview-sessions/{session_id}")
    async def interview_session(session_id: str) -> Any:
        return await local(lambda: service.get_interview_session(session_id))

    @router.post("/api/career/interview-sessions/{session_id}/answers")
    async def answer_interview_session(session_id: str, payload: InterviewAnswerPayload) -> Any:
        return await local(lambda: service.answer_interview_session(session_id, payload.answer))

    @router.post("/api/career/interview-sessions/{session_id}/complete")
    async def complete_interview_session(session_id: str) -> Any:
        return await local(lambda: service.complete_interview_session(session_id))

    @router.delete("/api/career/interview-sessions/{session_id}")
    async def delete_interview_session(session_id: str) -> dict[str, bool]:
        await local(lambda: service.delete_interview_session(session_id))
        return {"deleted": True}

    @router.get("/api/career/export/{export_format}")
    async def export_applications(export_format: str) -> FileResponse:
        path = await run_in_threadpool(lambda: service.export_applications(export_format))
        media_type = "text/csv; charset=utf-8" if export_format == "csv" else "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        return FileResponse(path, filename=path.name, media_type=media_type)

    @router.get("/api/career/deadlines.ics")
    async def export_deadline_calendar() -> FileResponse:
        path = await run_in_threadpool(service.export_deadline_calendar)
        return FileResponse(
            path,
            filename=path.name,
            media_type="text/calendar; charset=utf-8",
            headers={"Cache-Control": "no-store"},
        )

    @router.get("/api/career/privacy-export")
    async def export_personal_data() -> FileResponse:
        path = await run_in_threadpool(service.export_personal_data)
        return FileResponse(path, filename=path.name, media_type="application/json")

    @router.delete("/api/career/data")
    async def reset_data(payload: ResetPayload) -> dict[str, bool]:
        await local(lambda: service.reset_personal_data(payload.confirmation))
        return {"deleted": True}

    return router


async def _store_profile_document(
    service: CareerService, uploaded: UploadFile, source_kind: str
) -> Any:
    """Stream one document into the private Career directory before parsing it.

    ``UploadFile`` is already a request-local spool.  This second, bounded
    streaming step makes the final location opaque, calculates the checksum,
    and never hands a Career profile source to the general V3 workspace.
    """
    original_name = CareerService._safe_profile_source_name(uploaded.filename, fallback="document-profil")
    temporary = service.profile_upload_temp_path()
    digest = hashlib.sha256()
    bytes_written = 0
    try:
        with temporary.open("xb") as destination:
            try:
                os.chmod(temporary, 0o600)
            except OSError:
                pass
            while chunk := await uploaded.read(PROFILE_UPLOAD_CHUNK_SIZE):
                bytes_written += len(chunk)
                if bytes_written > MAX_PROFILE_IMPORT_BYTES:
                    raise UserFacingError("Document de profil trop volumineux (maximum 10 Mo).")
                digest.update(chunk)
                destination.write(chunk)
        return await run_in_threadpool(
            lambda: service.import_profile_document(
                source_kind=source_kind,
                original_name=original_name,
                temporary_path=temporary,
                content_sha256=digest.hexdigest(),
                size_bytes=bytes_written,
            )
        )
    finally:
        temporary.unlink(missing_ok=True)
