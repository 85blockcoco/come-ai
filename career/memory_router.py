"""HTTP surface for the local personal style memory (SPEC-023).

Every route is local: no provider, no upload to a third party, no automatic
submission.  The router is mounted by ``come_ai_web`` so a person can inspect,
correct, export and undo what the reformulation workflow remembers.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from .memory_report import build_report, render_markdown
from .personal_memory import (
    MemoryCorruptionError,
    MemoryStoreError,
    StyleMemoryStore,
    inject_constraints,
)
from .memory_types import PreferenceSource


class PreferencePayload(BaseModel):
    key: str = Field(min_length=1, max_length=80)
    value: str = Field(min_length=1, max_length=300)
    source: PreferenceSource = "manual"


class ChoicePayload(BaseModel):
    context: str = Field(min_length=1, max_length=240)
    chosen: dict[str, Any] = Field(default_factory=dict)
    rejected: list[dict[str, Any]] = Field(default_factory=list, max_length=20)
    evidence_refs: list[str] = Field(default_factory=list, max_length=20)


def _raise_memory_error(error: MemoryStoreError) -> None:
    status = 409 if isinstance(error, MemoryCorruptionError) else 400
    raise HTTPException(status_code=status, detail=str(error)) from error


def create_memory_router(store: StyleMemoryStore) -> APIRouter:
    router = APIRouter()

    @router.get("/memory/prefs")
    def list_preferences() -> dict[str, Any]:
        try:
            preferences = [item.to_dict() for item in store.list_preferences()]
            return {
                "preferences": preferences,
                "top_constraints": store.constraints(5),
                "stats": store.stats(),
            }
        except MemoryStoreError as error:
            _raise_memory_error(error)
            raise  # pragma: no cover - keeps type checkers aware of the exit

    @router.post("/memory/prefs", status_code=201)
    def create_preference(payload: PreferencePayload) -> dict[str, Any]:
        try:
            preference = store.record_preference(payload.key, payload.value, source=payload.source)
            return {"preference": preference.to_dict()}
        except MemoryStoreError as error:
            _raise_memory_error(error)
            raise  # pragma: no cover

    @router.delete("/memory/prefs/{key}")
    def delete_preference(key: str, reason: str = Query(default="Demande de l’utilisateur", max_length=240)) -> dict[str, Any]:
        try:
            purged = store.purge_preference(key, reason=reason)
        except MemoryStoreError as error:
            _raise_memory_error(error)
            raise  # pragma: no cover
        if not purged:
            raise HTTPException(status_code=404, detail="Cette préférence est introuvable.")
        return {"purged": True, "key": key}

    @router.get("/memory/back")
    def list_choices(limit: int = Query(default=50, ge=1, le=200)) -> dict[str, Any]:
        try:
            choices = [item.to_dict() for item in store.list_choices()][:limit]
            return {"choices": choices, "count": len(choices)}
        except MemoryStoreError as error:
            _raise_memory_error(error)
            raise  # pragma: no cover

    @router.post("/memory/back", status_code=201)
    def record_choice(payload: ChoicePayload) -> dict[str, Any]:
        """Post-choice hook used by the reformulation arena."""
        try:
            return store.record_choice(
                payload.context,
                payload.chosen,
                payload.rejected,
                payload.evidence_refs,
            )
        except MemoryStoreError as error:
            _raise_memory_error(error)
            raise  # pragma: no cover

    @router.post("/memory/back/{choice_id}/undo")
    def undo_choice(choice_id: str) -> dict[str, Any]:
        try:
            return store.undo_choice(choice_id)
        except MemoryStoreError as error:
            _raise_memory_error(error)
            raise  # pragma: no cover

    @router.get("/memory/constraints")
    def constraints(limit: int = Query(default=5, ge=1, le=20), only_auto: bool = False) -> dict[str, Any]:
        """Fail-closed injection point for future generation workflows."""
        try:
            return {
                "constraints": store.constraints(limit, only_auto=only_auto),
                "degraded": False,
                "generation_allowed": True,
            }
        except MemoryStoreError:
            # The dedicated helper returns a safe, non-generating payload.
            return inject_constraints(store, limit)

    @router.get("/memory/report")
    def report(format: str = Query(default="json", pattern="^(json|markdown)$")) -> Any:
        payload = build_report(store)
        if format == "markdown":
            return JSONResponse(
                content={"markdown": render_markdown(payload)},
                headers={"Content-Disposition": 'inline; filename="memoire-style.md"'},
            )
        return payload

    @router.post("/memory/export")
    def export_memory() -> JSONResponse:
        try:
            payload = store.export_envelope()
        except MemoryStoreError as error:
            _raise_memory_error(error)
            raise  # pragma: no cover
        return JSONResponse(
            content=payload,
            headers={"Content-Disposition": 'attachment; filename="memoire-style.json"'},
        )

    @router.post("/memory/import")
    def import_memory(payload: dict[str, Any]) -> dict[str, Any]:
        try:
            return store.import_envelope(payload)
        except MemoryStoreError as error:
            _raise_memory_error(error)
            raise  # pragma: no cover

    return router
