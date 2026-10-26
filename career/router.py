"""FastAPI routes for the local-first Côme AI Career 4.1 workspace."""

from __future__ import annotations

import hashlib
import os
from datetime import date
from pathlib import Path
from typing import Any, Callable

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from starlette.concurrency import run_in_threadpool
from starlette.datastructures import UploadFile

from .exploration_service import ExplorationService
from .send_confirmation import SendEvidence, parse_sent_datetime
from .profile_import import MAX_PROFILE_IMPORT_BYTES
from .ats_guide import human_apply_guide
from .offer_dates import extract_offer_dates
from .offer_qualification import qualify_offer
from .service import CareerService
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
    contract_types: list[str] = Field(default_factory=lambda: ["stage"], max_length=4)
    start_months: list[int] = Field(default_factory=lambda: [1, 2, 3], max_length=12)
    minimum_stage_duration_months: int = Field(default=6, ge=1, le=24)
    education_preference: str = Field(default="bachelor_m1_then_m2", max_length=40)
    study_level: str = Field(default="", max_length=120)
    languages: list[str] = Field(default_factory=list, max_length=10)
    constraints: str = Field(default="", max_length=2_000)
    ranking: dict[str, float] = Field(default_factory=dict)
    # Geographic ranking signal of the brief (CVBOOST-13).  Both fields stay
    # optional: when they are absent, the local defaults apply (the European
    # target countries, France penalized).  ``None`` means "not configured",
    # an explicit empty list means "turned off".
    preferred_countries: list[str] | None = Field(default=None, max_length=40)
    geo_excluded_countries: list[str] | None = Field(default=None, max_length=40)


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


class SendConfirmationPayload(BaseModel):
    """SPEC-047 — déclaration d'un envoi effectué manuellement par la personne.

    Aucune soumission automatique n'existe : cet appel enregistre un dépôt que
    la personne confirme avoir fait elle-même (site, e-mail ou portail).
    """

    channel: str = Field(pattern="^(website|email|portal)$")
    sent_at: str = Field(min_length=10, max_length=64)
    note: str = Field(default="", max_length=1_000)


class FollowupDonePayload(BaseModel):
    """SPEC-047 — déclaration d'une relance déjà faite (brouillon copié soi-même)."""

    done_on: str = Field(default="", max_length=32)
    note: str = Field(default="", max_length=1_000)


class ApplicationChecklistPayload(BaseModel):
    """Cinq cases locales seulement ; rien n'est transitionné ni envoyé."""

    checked: list[str] = Field(default_factory=list, max_length=10)


class ResetPayload(BaseModel):
    confirmation: str = Field(min_length=1, max_length=100)


class TranslationDetectPayload(BaseModel):
    text: str = Field(default="", max_length=20_000)


class TranslationBuildPayload(BaseModel):
    variant_id: str = Field(min_length=1, max_length=40)
    target_lang: str = Field(min_length=2, max_length=5, pattern="^(en|de|es|fr)$")
    arena_available: bool = False


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


class ApplyKitPayload(BaseModel):
    """Optional body for the one-call apply kit endpoint."""

    language: str = Field(default="fr", min_length=2, max_length=16)
    variant: str | None = Field(default=None, pattern="^(m_a|markets|corporate_finance)$")


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


def create_career_router(
    service: CareerService,
    *,
    ai_generator: Callable[[str], dict[str, Any]] | None = None,
) -> APIRouter:
    if not CAREER_STATIC_DIR.is_dir():
        raise RuntimeError("Les fichiers Career Agent sont introuvables.")
    router = APIRouter()
    # One exploration service per application: it owns the background runs and
    # the cooperative cancellation between two sources.
    explorations = ExplorationService(service)
    router.on_shutdown.append(explorations.shutdown)

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
            "ats_guide": capabilities["ats_guide"],
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

    @router.get("/api/career/stage-search/coverage")
    async def stage_search_coverage(run_id: str | None = Query(default=None, max_length=160)) -> Any:
        """Recalculate exact source coverage from the selected local run."""
        return await local(lambda: service.get_stage_source_coverage(run_id))

    @router.post("/api/career/stage-search/explore")
    async def explore_stages(payload: DiscoverySearchPayload) -> Any:
        return await local(lambda: service.explore_internships(force=payload.force))

    # --- Exploration runs -------------------------------------------------
    # The synchronous explorer above answers in one response.  These three
    # routes expose a real, server-side run: every phase and every counter is
    # incremented by a step that really finished, the state survives a page
    # reload and the run can be stopped between two sources.

    @router.get("/api/career/stage-search/explorations")
    async def list_explorations() -> Any:
        """The recent runs, so a reloaded page can resume the last one."""
        return await local(lambda: {"runs": explorations.list_runs()})

    @router.post("/api/career/stage-search/explorations", status_code=202)
    async def start_exploration(payload: DiscoverySearchPayload) -> Any:
        """Start one exploration and return its first real state."""
        return await local(lambda: explorations.start(force=payload.force))

    @router.get("/api/career/stage-search/explorations/{run_id}")
    async def exploration_state(run_id: str) -> Any:
        state = await local(lambda: explorations.state(run_id))
        if state is None:
            raise HTTPException(status_code=404, detail="Exploration introuvable.")
        return state

    @router.post("/api/career/stage-search/explorations/{run_id}/cancel")
    async def cancel_exploration(run_id: str) -> Any:
        state = await local(lambda: explorations.cancel(run_id))
        if state is None:
            raise HTTPException(status_code=404, detail="Exploration introuvable.")
        return state

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
        import_payload = payload.model_dump()
        # The request model intentionally does not accept a client supplied
        # qualification. Derive source-attributed facts locally instead, with
        # neutral limits so the caller's search preferences are not guessed.
        qualification = qualify_offer(
            import_payload,
            minimum_duration_months=1,
            minimum_stage_duration_months=1,
            allowed_contract_types=["internship", "apprenticeship", "graduate", "VIE", "permanent", "fixed_term"],
            allowed_start_months=list(range(1, 13)),
        ).to_dict()
        qualification["temporal_facts"] = [
            fact.to_dict() for fact in extract_offer_dates(import_payload)
        ]
        import_payload["qualification"] = qualification
        result = await local(lambda: service.import_job(import_payload))
        return result

    @router.get("/api/career/jobs/{job_id}")
    async def job(job_id: str) -> Any:
        return await local(lambda: service.get_job(job_id))

    @router.get("/api/career/jobs/{job_id}/offer-intelligence")
    async def job_offer_intelligence(job_id: str) -> Any:
        return await local(lambda: service.get_offer_intelligence(job_id))

    @router.get("/api/career/offer-intelligence/{job_id}")
    async def offer_intelligence(job_id: str) -> Any:
        """Same snapshot, same identifiers: this route is an alias, not a copy."""
        return await local(lambda: service.get_offer_intelligence(job_id))

    @router.get("/api/career/jobs/{job_id}/prep")
    async def job_prep(job_id: str) -> Any:
        return await local(lambda: service.get_job_prep(job_id))

    @router.get("/api/career/quick-answers/{job_id}")
    async def quick_answers(
        job_id: str,
        lang: str = Query(default="fr", pattern="^(fr|en)$"),
    ) -> Any:
        return await local(lambda: service.get_quick_answers(job_id, lang=lang))

    @router.get("/api/career/ats-guide/{job_id}")
    async def ats_guide(job_id: str) -> Any:
        """Guide humain d'application : local, sans requête sortante, sans envoi."""

        def build() -> dict[str, Any]:
            stored_job = service.get_job(job_id)
            guide = human_apply_guide(stored_job).to_dict()
            return {
                "job_id": stored_job.get("id", job_id),
                "company": stored_job.get("company", ""),
                "title": stored_job.get("title", ""),
                **guide,
                "automated_submission": False,
            }

        return await local(build)

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

    @router.post("/api/career/apply-kit/{job_id}")
    async def apply_kit(job_id: str, payload: ApplyKitPayload | None = None) -> Any:
        """One call: ready-to-review application dossier for one offer."""
        language = payload.language if payload is not None else "fr"
        variant = payload.variant if payload is not None else None
        return await local(
            lambda: service.build_apply_kit(job_id, language, variant)
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

    # SPEC-047 : la confirmation d'envoi est une déclaration humaine — la
    # personne effectue le dépôt manuel puis l'enregistre ici ; le module ne
    # soumet jamais rien. La route de lecture du suivi de relance reste
    # enregistrée avant les routes paramétrées de confirmation.
    @router.get("/api/career/apply-tracker")
    async def apply_tracker() -> Any:
        return await local(service.apply_tracker)

    @router.post("/api/career/send-confirmation/{job_id}", status_code=201)
    async def record_send_confirmation(job_id: str, payload: SendConfirmationPayload) -> Any:
        sent_at = parse_sent_datetime(payload.sent_at)
        if sent_at is None:
            raise HTTPException(
                status_code=422,
                detail="Horodatage d'envoi illisible : attends un format ISO (ex. 2026-10-26T10:30:00+00:00).",
            )
        evidence = SendEvidence(channel=payload.channel, sent_at=sent_at, note=payload.note or None)
        return await local(lambda: service.record_send(job_id, evidence))

    @router.get("/api/career/send-confirmation/{job_id}")
    async def send_confirmation_record(job_id: str) -> Any:
        return await local(lambda: service.get_send_record(job_id))

    @router.post("/api/career/send-confirmation/{job_id}/followup")
    async def record_followup_done(job_id: str, payload: FollowupDonePayload) -> Any:
        done_on = None
        if payload.done_on.strip():
            try:
                done_on = date.fromisoformat(payload.done_on)
            except ValueError as error:
                raise HTTPException(
                    status_code=422,
                    detail="Date de relance illisible : attends un format ISO (ex. 2026-10-26).",
                ) from error
        return await local(
            lambda: service.record_followup_done(job_id, done_on=done_on, note=payload.note)
        )

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

    # --- Translation variants (SPEC-033) -------------------------------------
    # Payload models live at module level (see top of file): with
    # ``from __future__ import annotations`` FastAPI cannot resolve nested
    # classes and would treat ``payload`` as a required query parameter.

    @router.post("/api/career/translation-variants/detect")
    async def translation_detect(payload: TranslationDetectPayload) -> Any:
        from career.translation_variants import detect_offer_lang

        return await local(
            lambda: {
                "detected_lang": detect_offer_lang(payload.text),
                "text_sample": payload.text[:200],
            }
        )

    @router.post("/api/career/translation-variants/build", status_code=201)
    async def translation_build(payload: TranslationBuildPayload) -> Any:
        import dataclasses

        from career.translation_variants import build_variant

        report = await local(lambda: dataclasses.asdict(build_variant(
            payload.variant_id,
            payload.target_lang,
            arena_available=payload.arena_available,
        )))
        return report

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
