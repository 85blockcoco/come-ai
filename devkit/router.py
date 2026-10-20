"""Loopback workshop routes. No paths, commands or provider keys in requests."""

from __future__ import annotations

import hmac
from typing import Any, Callable

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from starlette.concurrency import run_in_threadpool

from devkit.service import DeveloperWorkshop


class IssueRequest(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    description: str = Field(min_length=1, max_length=12_000)
    errors: str = Field(default="", max_length=32_000)
    selected_files: list[str] = Field(default_factory=list, max_length=40)


class PatchRequest(BaseModel):
    patch: str = Field(min_length=1, max_length=500_000)


class FilesRequest(BaseModel):
    files: dict[str, str]


class CheckRequest(BaseModel):
    candidate_id: str | None = Field(default=None, max_length=64)


class ConfirmRequest(BaseModel):
    confirmed: bool = False


class EvolutionTaskRequest(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    description: str = Field(min_length=1, max_length=12_000)
    selected_files: list[str] = Field(min_length=1, max_length=8)
    acceptance: str = Field(default="", max_length=4_000)
    priority: int = Field(default=50, ge=0, le=100)


class EvolutionSettingsRequest(BaseModel):
    provider: str = Field(pattern="^(gemini|ollama|openrouter)$")
    model: str = Field(min_length=1, max_length=192)
    allow_remote: bool = False
    gemini_free_project_confirmed: bool = False
    max_output_tokens: int = Field(default=3000, ge=256, le=6000)
    timeout_seconds: int = Field(default=45, ge=5, le=60)
    mode: str = Field(default="automatic", pattern="^(automatic|offline|performance)$")


class EvolutionRunRequest(BaseModel):
    task_id: str | None = Field(default=None, max_length=64)
    max_requests: int = Field(default=2, ge=1, le=3)
    max_attempts: int = Field(default=2, ge=1, le=3)
    demo: bool = False


def create_developer_router(service_factory: Callable[[], DeveloperWorkshop]) -> APIRouter:
    router = APIRouter(prefix="/api/devkit", tags=["Atelier Développeur"])

    def authorise(request: Request) -> DeveloperWorkshop:
        workshop = service_factory()
        origin = request.headers.get("origin")
        expected_origin = f"{request.url.scheme}://{request.url.netloc}"
        fetch_site = request.headers.get("sec-fetch-site", "").strip().lower()
        if origin and origin != expected_origin:
            raise HTTPException(403, "Cette action doit être lancée depuis l’atelier local.")
        if fetch_site == "cross-site":
            raise HTTPException(403, "Cette action doit être lancée depuis l’atelier local.")
        if not hmac.compare_digest(request.headers.get("x-workshop-token", ""), workshop.token):
            raise HTTPException(403, "Recharge l’atelier avant de lancer cette action.")
        return workshop

    async def action(callback: Callable[[], Any]) -> Any:
        try:
            return await run_in_threadpool(callback)
        except ValueError as error:
            # Kit/Patch errors are authored, bounded messages. Raw OS/library
            # exceptions never leave the local route.
            from workspace_core import safe_error

            raise HTTPException(400, safe_error(error)) from error
        except OSError as error:
            raise HTTPException(400, "Le fichier local n’a pas pu être lu ou sauvegardé.") from error

    @router.get("/status")
    async def status(request: Request) -> dict[str, Any]:
        workshop = service_factory()
        result = await action(workshop.status)
        origin = request.headers.get("origin")
        expected_origin = f"{request.url.scheme}://{request.url.netloc}"
        fetch_site = request.headers.get("sec-fetch-site", "").strip().lower()
        # Le jeton ne part que vers un navigateur de l'application elle-même :
        # une page étrangère ne peut ni le lire ni le déduire, et un processus
        # local non-navigateur (curl, script) ne le reçoit plus. Les GET
        # same-origin n'envoyent pas toujours Origin, mais un navigateur
        # moderne envoie Sec-Fetch-Site: same-origin sur toutes ses requêtes.
        browser_local = (origin and hmac.compare_digest(origin, expected_origin)) or fetch_site == "same-origin"
        if origin and not hmac.compare_digest(origin, expected_origin):
            raise HTTPException(403, "Cet atelier n'est accessible que depuis cette application locale.")
        result["workshop_token"] = workshop.token if browser_local else ""
        return result

    @router.get("/evolution")
    async def evolution_overview() -> dict[str, Any]:
        return await action(lambda: service_factory().evolution().overview())

    @router.post("/evolution/settings")
    async def evolution_settings(payload: EvolutionSettingsRequest, request: Request) -> dict[str, Any]:
        workshop = authorise(request)
        return await action(lambda: workshop.evolution().configure(payload.model_dump()))

    @router.post("/evolution/catalogue/refresh")
    async def evolution_catalogue(request: Request) -> dict[str, Any]:
        return await action(authorise(request).evolution().refresh_catalogue)

    @router.post("/evolution/tasks")
    async def evolution_task(payload: EvolutionTaskRequest, request: Request) -> dict[str, Any]:
        workshop = authorise(request)
        return await action(lambda: workshop.evolution().engine.store.add_task(**payload.model_dump()))

    @router.get("/evolution/runs/{run_id}")
    async def evolution_run_detail(run_id: str) -> dict[str, Any]:
        return await action(lambda: service_factory().evolution().engine.store.get_run(run_id))

    @router.post("/evolution/run")
    async def evolution_run(payload: EvolutionRunRequest, request: Request) -> dict[str, Any]:
        workshop = authorise(request)
        return await action(lambda: workshop.start_evolution(**payload.model_dump()))

    @router.post("/evolution/stop")
    async def evolution_stop(request: Request) -> dict[str, Any]:
        return await action(authorise(request).evolution().cancel)

    @router.post("/evolution/from-diagnostics")
    async def evolution_from_diagnostics(request: Request) -> dict[str, Any]:
        workshop = authorise(request)
        return await action(lambda: workshop.evolution().engine.import_diagnostic_issue(workshop.latest_report() or {}))

    @router.post("/diagnostics")
    async def diagnostics(payload: CheckRequest, request: Request) -> dict[str, Any]:
        workshop = authorise(request)
        return await action(lambda: workshop.start_diagnostics(payload.candidate_id))

    @router.get("/jobs/{job_id}")
    async def job(job_id: str) -> dict[str, Any]:
        return await action(lambda: service_factory().job(job_id))

    @router.post("/exports")
    async def export_project(request: Request) -> dict[str, Any]:
        return await action(authorise(request).export_project)

    @router.post("/issues")
    async def export_issue(payload: IssueRequest, request: Request) -> dict[str, Any]:
        workshop = authorise(request)
        return await action(lambda: workshop.export_issue(**payload.model_dump()))

    @router.get("/artifacts/{artifact_id}")
    async def artifact(artifact_id: str) -> FileResponse:
        path = await action(lambda: service_factory().artifact_path(artifact_id))
        return FileResponse(path, filename=path.name, media_type="application/zip")

    @router.post("/candidates/patch")
    async def stage_patch(payload: PatchRequest, request: Request) -> dict[str, Any]:
        workshop = authorise(request)
        return await action(lambda: workshop.patches.stage_patch(payload.patch))

    @router.post("/candidates/files")
    async def stage_files(payload: FilesRequest, request: Request) -> dict[str, Any]:
        if not 1 <= len(payload.files) <= 40 or sum(len(text) for text in payload.files.values()) > 500_000:
            raise HTTPException(400, "Correctif trop volumineux : maximum 40 fichiers et 500 000 caractères.")
        workshop = authorise(request)
        return await action(lambda: workshop.patches.stage_files(payload.files))

    @router.get("/candidates/{candidate_id}")
    async def preview(candidate_id: str) -> dict[str, Any]:
        return await action(lambda: service_factory().patches.preview(candidate_id))

    @router.post("/candidates/{candidate_id}/apply")
    async def apply(candidate_id: str, payload: ConfirmRequest, request: Request) -> dict[str, Any]:
        workshop = authorise(request)
        if not payload.confirmed:
            raise HTTPException(400, "Confirme l’aperçu du correctif avant de l’appliquer.")
        return await action(lambda: workshop.apply(candidate_id))

    @router.post("/transactions/{transaction_id}/rollback")
    async def rollback(transaction_id: str, payload: ConfirmRequest, request: Request) -> dict[str, Any]:
        workshop = authorise(request)
        if not payload.confirmed:
            raise HTTPException(400, "Confirme le retour arrière avant de restaurer le code.")
        return await action(lambda: workshop.rollback(transaction_id))

    return router
