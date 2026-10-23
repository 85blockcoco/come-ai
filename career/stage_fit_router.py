"""FastAPI router for Stage Fit Kit (SPEC-024)."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse

from .stage_fit_kit import StageFitKitOrchestrator


def _orchestrator_from_args(*args: Any, **kwargs: Any) -> StageFitKitOrchestrator:
    if kwargs.get("orchestrator") is not None:
        return kwargs["orchestrator"]
    base_dir = kwargs.get("base_dir")
    service = kwargs.get("service")
    if base_dir is None and service is not None and getattr(service, "base_dir", None) is not None:
        base_dir = service.base_dir
    if base_dir is None and args:
        # First positional may be base_dir or service.
        first = args[0]
        if hasattr(first, "base_dir"):
            service = first
            base_dir = first.base_dir
        else:
            base_dir = first
    return StageFitKitOrchestrator(base_dir=base_dir, service=service)


def create_stage_fit_router(*args: Any, **kwargs: Any) -> APIRouter:
    """Create router. Accepts service/orchestrator/base_dir positionally or by keyword."""
    orchestrator = _orchestrator_from_args(*args, **kwargs)
    router = APIRouter()

    @router.post("/stagefit/kit/{offer_id}")
    async def create_kit(offer_id: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        payload = payload or {}
        try:
            kit = await orchestrator.abuild_kit(
                offer_id,
                language=payload.get("language", "fr"),
                constraints=payload.get("constraints"),
                profile=payload.get("profile"),
                cv_variant_json=payload.get("cv_variant_json"),
                letter_draft_id=payload.get("letter_draft_id", ""),
                resume_kit_id=payload.get("resume_kit_id"),
                force=bool(payload.get("force", False)),
            )
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc))
        return kit.to_dict()

    @router.get("/stagefit/kit/{kit_id}")
    def get_kit(kit_id: str) -> dict[str, Any]:
        kit = orchestrator.get_kit(kit_id)
        if kit is None:
            raise HTTPException(status_code=404, detail="kit not found")
        return kit.to_dict()

    @router.get("/stagefit/kit/{kit_id}/export")
    def export_kit(kit_id: str) -> FileResponse:
        try:
            path = orchestrator.export(kit_id)
        except Exception as exc:
            raise HTTPException(status_code=404, detail=str(exc))
        return FileResponse(path, filename=path.name)

    @router.post("/stagefit/kit/{kit_id}/rerun")
    async def rerun_kit(kit_id: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        payload = payload or {}
        existing = orchestrator.get_kit(kit_id)
        if existing is None:
            raise HTTPException(status_code=404, detail="kit not found")
        try:
            kit = await orchestrator.abuild_kit(
                existing.offer_id,
                resume_kit_id=kit_id,
                constraints=payload.get("constraints", existing.constraints),
                force=True,
                profile=payload.get("profile"),
                cv_variant_json=payload.get("cv_variant_json"),
            )
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc))
        return kit.to_dict()

    # Aliases with different path styles.
    router.add_api_route("/stage-fit/kit/{offer_id}", create_kit, methods=["POST"])
    router.add_api_route("/stage-fit-kit/{offer_id}", create_kit, methods=["POST"])

    return router


# Aliases
create_stagefit_router = create_stage_fit_router
create_stage_fit_kit_router = create_stage_fit_router
StageFitRouter = create_stage_fit_router

__all__ = [
    "create_stage_fit_router",
    "create_stagefit_router",
    "create_stage_fit_kit_router",
    "StageFitRouter",
]
