"""Loopback-only web application for Côme AI V3.

This module deliberately exposes a small HTTP surface rather than a general
filesystem or code-execution API. The browser talks only to 127.0.0.1 and all
model actions are routed through the controlled tools in ``workspace_core``.
"""

from __future__ import annotations

import hmac
import json
import logging
import re
import threading
import uuid
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Annotated, Any, Callable, Literal

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.trustedhost import TrustedHostMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict, Field
from starlette.concurrency import run_in_threadpool
from starlette.datastructures import UploadFile

from career.profile_import import MAX_PROFILE_IMPORT_BYTES
from career.router import CAREER_STATIC_DIR, create_career_router
from career.service import CareerService
from personal_memory import PersonalMemoryError, PersonalMemoryStore
from memory_storage import MemoryStorageError, MemoryStorageService
from task_queue import (
    ACTIVE_STATUSES,
    TaskExecutionContext,
    TaskKind,
    TaskQueue,
    TaskQueueError,
    TaskRecord,
    TaskRunner,
    TaskStatus,
)
from v5_orchestrator import LocalOrchestrator
from workspace_core import (
    MAX_IMPORT_BYTES,
    SUPPORTED_SUFFIXES,
    AgentService,
    AppConfig,
    LocalTools,
    UserFacingError,
    Workspace,
    safe_error,
    to_jsonable,
)


WEB_STATIC_DIR = Path(__file__).resolve().parent / "web_static"
V5_STATIC_DIR = Path(__file__).resolve().parent / "v5_static"
UPLOAD_CHUNK_SIZE = 1_024 * 1_024
MAX_CHAT_CHARS = 12_000
MAX_UPLOAD_FILES = 12
MAX_UPLOAD_FIELDS = 8
# A personal workspace does not need to spool an unbounded multipart request.
# Each supported file remains capped at 50 MiB by ``_store_upload``.
MAX_UPLOAD_BATCH_BYTES = 100 * 1024 * 1024
# Career profile documents are intentionally smaller than the general
# workspace imports and remain in a different, private storage area.
MAX_CAREER_PROFILE_IMPORT_BYTES = MAX_PROFILE_IMPORT_BYTES


class UploadRequestTooLarge(UserFacingError):
    """Raised while receiving an oversized multipart body before it is parsed."""


class UploadBodyLimitMiddleware:
    """Apply a request-body cap before Starlette parses multipart data.

    FastAPI resolves file dependencies only after Starlette has parsed and
    spooled the multipart body. This ASGI middleware wraps ``receive`` before
    that happens, so chunked requests cannot bypass the batch limit.
    """

    def __init__(
        self,
        app: Any,
        *,
        max_bytes: int,
        paths: tuple[str, ...],
        error_message: str,
        prefix: bool = False,
    ):
        self.app = app
        self.max_bytes = max_bytes
        self.paths = paths
        self.error_message = error_message
        self.prefix = prefix

    def _matches(self, path: str) -> bool:
        if self.prefix:
            return any(path.startswith(item) for item in self.paths)
        return path in self.paths

    async def __call__(self, scope: dict[str, Any], receive: Any, send: Any) -> None:
        if scope.get("type") != "http" or not self._matches(str(scope.get("path", ""))):
            await self.app(scope, receive, send)
            return

        raw_length = dict(scope.get("headers", [])).get(b"content-length", b"")
        try:
            content_length = int(raw_length)
        except (TypeError, ValueError):
            content_length = None
        if content_length is not None and content_length > self.max_bytes:
            await _send_upload_too_large(scope, receive, send, self.error_message)
            return

        received = 0

        async def limited_receive() -> dict[str, Any]:
            nonlocal received
            message = await receive()
            if message.get("type") == "http.request":
                received += len(message.get("body", b""))
                if received > self.max_bytes:
                    raise UploadRequestTooLarge(self.error_message)
            return message

        await self.app(scope, limited_receive, send)


class CrossSiteWriteMiddleware:
    """Reject cross-site writing requests (CSRF on unsafe methods).

    A browser POST from a foreign origin always carries an Origin header, so a
    simple form (no preflight required) cannot reach mutating endpoints
    silently. Non-browser clients (curl, TestClient) send no Origin and stay
    welcome. This complements the per-endpoint chat/devkit origin checks and
    covers the multipart endpoints they did not protect.
    """

    UNSAFE_METHODS = "POST", "PUT", "PATCH", "DELETE"

    def __init__(self, app: Any) -> None:
        self.app = app

    async def __call__(self, scope: dict[str, Any], receive: Any, send: Any) -> None:
        if scope.get("type") != "http" or scope.get("method") not in self.UNSAFE_METHODS:
            await self.app(scope, receive, send)
            return
        headers = dict(scope.get("headers", []))
        origin = (headers.get(b"origin") or b"").decode("latin-1").strip()
        fetch_site = (headers.get(b"sec-fetch-site") or b"").decode("latin-1").strip().lower()
        # Un navigateur moderne marque toute requête d'un autre site comme
        # cross-site même quand Origin est absent (anciens formulaires).
        if fetch_site == "cross-site":
            await self._reject(send)
            return
        if origin:
            server_host = ""
            for key in (b"host",):
                server_host = (headers.get(key) or b"").decode("latin-1").strip()
                if server_host:
                    break
            scheme = str(scope.get("scheme", "http"))
            expected = f"{scheme}://{server_host}" if server_host else ""
            if not expected or not hmac.compare_digest(origin.lower(), expected.lower()):
                await self._reject(send)
                return
        await self.app(scope, receive, send)

    @staticmethod
    async def _reject(send: Any) -> None:
        payload = json.dumps({"detail": "Cette action doit être lancée depuis cette application locale."}).encode("utf-8")
        await send(
            {
                "type": "http.response.start",
                "status": 403,
                "headers": [
                    (b"content-type", b"application/json; charset=utf-8"),
                    (b"content-length", str(len(payload)).encode("ascii")),
                ],
            }
        )
        await send({"type": "http.response.body", "body": payload})


@dataclass
class Runtime:
    config: AppConfig
    workspace: Workspace
    tools: LocalTools
    agent: AgentService
    workspace_lock: threading.RLock
    agent_lock: threading.Lock
    logger: logging.Logger
    memory: PersonalMemoryStore | None
    memory_error: str | None
    orchestrator: LocalOrchestrator
    task_queue: TaskQueue | None
    task_runner: TaskRunner | None
    task_queue_error: str | None
    hybrid_chat: Any | None = None


class FileActionRequest(BaseModel):
    file_id: str = Field(min_length=3, max_length=128)
    sheet_name: str = Field(default="", max_length=250)


class ChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=MAX_CHAT_CHARS)
    selected_file_ids: list[str] = Field(default_factory=list, max_length=12)
    allow_write: bool = False
    allow_cloud_context: bool = False


class V5TaskRequest(BaseModel):
    """Browser input for the single V5 task kind exposed in this increment.

    The browser can describe a goal and opaque workspace IDs; it cannot select
    a Python handler, a disk path, a provider, or a free-form list of tools.
    """

    message: str = Field(min_length=1, max_length=MAX_CHAT_CHARS)
    selected_file_ids: list[str] = Field(default_factory=list, max_length=4)
    allow_write: bool = False
    memory_project_id: str | None = Field(default=None, max_length=48)


class HybridHistoryMessage(BaseModel):
    """Only conversation text, never browser-authored tools or system roles."""

    model_config = ConfigDict(extra="forbid")
    role: Literal["user", "assistant"]
    content: str = Field(min_length=1, max_length=MAX_CHAT_CHARS)


class HybridChatRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    message: str = Field(min_length=1, max_length=MAX_CHAT_CHARS)
    selected_file_ids: list[Annotated[str, Field(min_length=3, max_length=128)]] = Field(default_factory=list, max_length=4)
    history: list[HybridHistoryMessage] = Field(default_factory=list, max_length=10)
    mode: Literal["offline", "automatic", "performance"] = "offline"
    provider: Literal["auto", "ollama", "gemini", "openrouter"] = "auto"
    model: str = Field(default="auto", min_length=1, max_length=128, pattern=r"^[A-Za-z0-9._:/-]+$")
    allow_write: bool = False
    memory_project_id: str | None = Field(default=None, max_length=48)
    allow_cloud_context: bool = False


class MemoryFileImportRequest(BaseModel):
    file_id: str = Field(min_length=3, max_length=128)
    project_id: str | None = Field(default=None, max_length=48)


class MemoryIndexTaskRequest(BaseModel):
    """Request an asynchronous, local-only document-memory indexation.

    Unlike the legacy immediate endpoint, this request deliberately contains
    only an opaque workspace ID and optional opaque project ID.  The browser
    cannot point the worker at an arbitrary local path or choose a handler.
    """

    file_id: str = Field(min_length=3, max_length=128)
    project_id: str | None = Field(default=None, max_length=48)


class MemoryProjectRequest(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    description: str = Field(default="", max_length=2_000)


def create_app(
    base_dir: Path | None = None,
    agent_override: Any | None = None,
    career_override: CareerService | None = None,
    hybrid_override: Any | None = None,
) -> FastAPI:
    """Build an app instance.

    ``base_dir`` and the optional service overrides make API tests
    self-contained: the suite never touches the user's data, outputs, logs,
    public job boards, or API key.
    """
    if not WEB_STATIC_DIR.is_dir() or not V5_STATIC_DIR.is_dir():
        raise RuntimeError("Les fichiers web locaux sont introuvables.")

    config = AppConfig.load(base_dir)
    workspace = Workspace(config)
    logger = _build_logger(config.log_dir)
    agent = agent_override or AgentService(config, workspace)
    career = career_override or CareerService(config.base_dir)
    tools = LocalTools(workspace)
    memory: PersonalMemoryStore | None = None
    memory_error: str | None = None
    try:
        memory = PersonalMemoryStore(config.memory_dir)
    except PersonalMemoryError as error:
        # V3/Career must remain usable if an optional external-SSD memory
        # location is offline. Do not disclose the configured path in the UI.
        memory_error = "La mémoire locale n’est pas disponible sur ce Mac."
        logger.warning("V5 memory unavailable: %s", safe_error(error))

    task_queue: TaskQueue | None = None
    task_queue_error: str | None = None
    try:
        # Keep machine state separate from user documents (`data`) and Career's
        # intentionally isolated database/directory.
        task_queue = TaskQueue(config.base_dir / "state" / "task_queue.sqlite3")
    except (TaskQueueError, OSError) as error:
        task_queue_error = "La file de tâches locale n’est pas disponible."
        logger.warning("V5 task queue unavailable: %s", safe_error(error))

    runtime = Runtime(
        config=config,
        workspace=workspace,
        tools=tools,
        agent=agent,
        workspace_lock=threading.RLock(),
        agent_lock=threading.Lock(),
        logger=logger,
        memory=memory,
        memory_error=memory_error,
        orchestrator=LocalOrchestrator(workspace, tools, memory),
        task_queue=task_queue,
        task_runner=None,
        task_queue_error=task_queue_error,
        hybrid_chat=hybrid_override,
    )
    # The maintenance workshop is lazy: ordinary app startup never runs tests,
    # scans source or creates an export. It owns a separate single worker.
    workshop_instances: list[Any] = []
    workshop_lock = threading.Lock()

    def get_workshop() -> Any:
        with workshop_lock:
            if not workshop_instances:
                from devkit.service import DeveloperWorkshop

                workshop_instances.append(DeveloperWorkshop(config.base_dir, busy_check=lambda: bool(_task_queue_health(runtime).get("active_count", 0))))
            return workshop_instances[0]

    def get_hybrid_chat() -> Any:
        # Construction is inert: opening the interface never loads a model or
        # performs discovery against a cloud provider. It shares agent_lock
        # with the legacy chat, preventing concurrent generation requests.
        if runtime.hybrid_chat is None:
            from hybrid_chat import HybridChatService

            runtime.hybrid_chat = HybridChatService(
                config.base_dir, runtime.workspace, runtime.tools, memory=runtime.memory, task_queue=runtime.task_queue
            )
        return runtime.hybrid_chat
    if task_queue is not None:
        runtime.task_runner = TaskRunner(
            task_queue,
            {
                TaskKind.ORCHESTRATOR_PLAN: lambda context, payload: _execute_v5_task(runtime, context, payload),
                # Memory indexing shares the single local worker with plans so
                # an Intel Mac never runs a heavy PDF/Excel parse alongside a
                # second pandas/PDF task.  The handler accepts only opaque
                # workspace/project identifiers and revalidates both below.
                TaskKind.MEMORY_INDEX: lambda context, payload: _execute_memory_index_task(runtime, context, payload),
            },
            # One worker is intentional: it prevents concurrent heavy pandas,
            # PDF extraction or report writes from saturating an Intel Mac.
            poll_interval_seconds=0.12,
        )
        runtime.task_runner.start()

    @asynccontextmanager
    async def app_lifespan(_: FastAPI) -> Any:
        try:
            yield
        finally:
            # A task interrupted by an app restart is recovered safely by the
            # queue on the next start. Do not force-kill pandas/PDF work.
            if runtime.task_runner is not None:
                runtime.task_runner.stop(wait=False)
            for workshop in workshop_instances:
                workshop.close()

    app = FastAPI(
        title="Côme AI 5.0",
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
        lifespan=app_lifespan,
    )
    app.state.runtime = runtime
    app.state.career = career
    app.state.get_workshop = get_workshop
    # The launcher binds Uvicorn to 127.0.0.1. This is a second line of
    # defence against unexpected Host headers when using a local browser.
    app.add_middleware(
        TrustedHostMiddleware,
        allowed_hosts=["127.0.0.1", "localhost", "testserver", "[::1]"],
    )
    app.add_middleware(
        UploadBodyLimitMiddleware,
        max_bytes=MAX_UPLOAD_BATCH_BYTES,
        paths=("/api/files/upload",),
        error_message="Lot d’import trop volumineux (maximum 100 Mo au total).",
    )
    app.add_middleware(
        UploadBodyLimitMiddleware,
        max_bytes=MAX_CAREER_PROFILE_IMPORT_BYTES,
        paths=("/api/career/profile-imports",),
        prefix=True,
        error_message="Document de profil trop volumineux (maximum 10 Mo).",
    )
    app.add_middleware(
        UploadBodyLimitMiddleware,
        max_bytes=1_024 * 1_024,
        paths=("/api/devkit",),
        prefix=True,
        error_message="Demande de maintenance trop volumineuse (maximum 1 Mo).",
    )
    app.add_middleware(
        UploadBodyLimitMiddleware,
        max_bytes=512 * 1_024,
        paths=("/api/v5/chat",),
        error_message="Conversation trop volumineuse (maximum 512 Ko).",
    )
    # CSRF : tout POST/PUT/PATCH/DELETE avec Origin d'un autre site est refusé
    # (les formulaires simples n'ont pas de preflight). Les clients locaux
    # (curl, tests) sans Origin ne sont pas concernés.
    app.add_middleware(CrossSiteWriteMiddleware)

    @app.middleware("http")
    async def security_headers(request: Request, call_next: Any) -> Any:
        response = await call_next(request)
        path = request.url.path
        # Les assets statiques sont versionnés par la livraison locale (pas de
        # HTML fragment modifiable par l'utilisateur) : autoriser un cache
        # court évite de re-télécharger career.js (~110 Ko) à chaque visite.
        # Le HTML, les API et les exports restent strictement no-store.
        if path.startswith(("/static/", "/v5-static/", "/career-static/")) and not path.endswith((".html", "/")):
            response.headers["Cache-Control"] = "public, max-age=3600"
        else:
            response.headers["Cache-Control"] = "no-store"
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; base-uri 'none'; form-action 'self'; "
            "frame-ancestors 'none'; img-src 'self' data:; "
            "style-src 'self'; script-src 'self'; connect-src 'self'"
        )
        return response

    @app.exception_handler(UserFacingError)
    async def known_error(_: Request, error: UserFacingError) -> JSONResponse:
        error_id = _log_error(runtime, error, level=logging.INFO)
        return JSONResponse(status_code=400, content={"detail": str(error), "error_id": error_id})

    @app.exception_handler(PersonalMemoryError)
    async def known_memory_error(_: Request, error: PersonalMemoryError) -> JSONResponse:
        error_id = _log_error(runtime, error, level=logging.INFO)
        return JSONResponse(status_code=400, content={"detail": str(error), "error_id": error_id})

    @app.exception_handler(TaskQueueError)
    async def known_task_error(_: Request, error: TaskQueueError) -> JSONResponse:
        error_id = _log_error(runtime, error, level=logging.INFO)
        return JSONResponse(status_code=400, content={"detail": str(error), "error_id": error_id})

    @app.exception_handler(UploadRequestTooLarge)
    async def upload_too_large(_: Request, error: UploadRequestTooLarge) -> JSONResponse:
        _log_error(runtime, error, level=logging.INFO)
        return JSONResponse(status_code=413, content={"detail": str(error)})

    @app.exception_handler(RequestValidationError)
    async def validation_error(_: Request, error: RequestValidationError) -> JSONResponse:
        # Validation exceptions embed rejected input. Never log conversation
        # text, documents or a secret accidentally pasted into a request.
        error_id = uuid.uuid4().hex[:10]
        runtime.logger.info("error_id=%s Request validation failed", error_id)
        return JSONResponse(
            status_code=422,
            content={"detail": "La demande envoyée à l’application est invalide.", "error_id": error_id},
        )

    @app.exception_handler(Exception)
    async def unexpected_error(_: Request, error: Exception) -> JSONResponse:
        error_id = _log_error(runtime, error, level=logging.ERROR)
        return JSONResponse(
            status_code=500,
            content={
                "detail": "Une erreur locale est survenue. Tes fichiers n’ont pas été modifiés.",
                "error_id": error_id,
            },
        )

    @app.get("/")
    async def homepage() -> FileResponse:
        return FileResponse(WEB_STATIC_DIR / "index.html", media_type="text/html; charset=utf-8")

    @app.get("/v5")
    async def v5_homepage() -> FileResponse:
        """The new unified local shell; V3 remains available at `/`."""
        return FileResponse(V5_STATIC_DIR / "index.html", media_type="text/html; charset=utf-8")

    @app.get("/api/health")
    async def health() -> dict[str, Any]:
        provider = runtime.agent.provider_status()
        return {
            "application": "Côme AI 5.0 (V3 + Career 4.1)",
            "mode": "local seulement (127.0.0.1)",
            "providers": provider,
            "supported_formats": sorted(item.lstrip(".") for item in SUPPORTED_SUFFIXES),
            "max_file_mb": round(MAX_IMPORT_BYTES / 1024 / 1024),
            "career_agent": {
                "enabled": True,
                "mode": "local",
                "phase": 4.1,
                "profile_imports": "local-review-required",
                "interview_coach": "local-text-persistent",
            },
            "v5": _v5_capabilities(runtime),
        }

    @app.get("/api/v5/overview")
    async def v5_overview() -> dict[str, Any]:
        return await run_in_threadpool(lambda: _v5_overview(runtime))

    @app.get("/api/v5/intelligence")
    async def v5_intelligence() -> dict[str, Any]:
        def read() -> dict[str, Any]:
            with runtime.agent_lock:
                return to_jsonable(get_hybrid_chat().overview())

        return await run_in_threadpool(read)

    @app.post("/api/v5/chat")
    async def hybrid_chat(payload: HybridChatRequest, request: Request) -> dict[str, Any]:
        origin = request.headers.get("origin")
        if origin and origin != f"{request.url.scheme}://{request.url.netloc}":
            raise HTTPException(status_code=403, detail="La conversation doit être lancée depuis cette application locale.")
        if (payload.selected_file_ids and payload.mode != "offline" and payload.provider != "ollama"
                and not payload.allow_cloud_context):
            raise HTTPException(
                status_code=400,
                detail="La demande contient un fichier local. Confirme sa transmission cloud pour cette demande, ou passe en mode Hors ligne.",
            )

        # A cloud permission belongs only to this request. The service checks
        # whether local context exists and consumes its exact provider/model
        # consent before any contextual generation call.

        def ask() -> dict[str, Any]:
            with runtime.agent_lock, runtime.workspace_lock:
                return to_jsonable(get_hybrid_chat().ask(
                    payload.message,
                    selected_file_ids=list(payload.selected_file_ids),
                    history=[item.model_dump() for item in payload.history],
                    mode=payload.mode,
                    provider=payload.provider,
                    model=payload.model,
                    allow_write=payload.allow_write,
                    memory_project_id=payload.memory_project_id,
                    allow_cloud_context=payload.allow_cloud_context,
                ))

        return await run_in_threadpool(ask)

    @app.get("/api/v5/tasks")
    async def list_v5_tasks(limit: int = 25) -> dict[str, Any]:
        def read() -> dict[str, Any]:
            queue = _require_task_queue(runtime)
            return {"tasks": [_task_to_response(task) for task in queue.list_tasks(limit=limit)]}

        return await run_in_threadpool(read)

    @app.post("/api/v5/tasks")
    async def create_v5_task(payload: V5TaskRequest) -> dict[str, Any]:
        """Queue one server-authored, bounded local orchestration plan."""

        def create() -> dict[str, Any]:
            runner = _require_task_runner(runtime)
            with runtime.workspace_lock:
                plan = runtime.orchestrator.build_plan(
                    payload.message,
                    selected_file_ids=payload.selected_file_ids,
                    allow_write=payload.allow_write,
                    memory_project_id=payload.memory_project_id,
                )
            task = runner.submit(
                TaskKind.ORCHESTRATOR_PLAN,
                {
                    "message": payload.message.strip(),
                    "selected_file_ids": list(payload.selected_file_ids),
                    "allow_write": payload.allow_write,
                    "memory_project_id": payload.memory_project_id,
                    # This UI plan is generated only on the server. The worker
                    # recomputes it, so a persisted task never gains trust in
                    # a browser-provided tool name or argument.
                    "plan": [
                        {
                            "step_id": item.step_id,
                            "tool": item.tool,
                            "label": item.label,
                            "requires_confirmation": item.requires_confirmation,
                        }
                        for item in plan
                    ],
                },
            )
            return _task_to_response(task)

        return await run_in_threadpool(create)

    @app.get("/api/v5/tasks/{task_id}")
    async def get_v5_task(task_id: str) -> dict[str, Any]:
        def read() -> dict[str, Any]:
            return _task_to_response(_require_task_queue(runtime).get_task(task_id))

        return await run_in_threadpool(read)

    @app.post("/api/v5/tasks/{task_id}/cancel")
    async def cancel_v5_task(task_id: str) -> dict[str, Any]:
        def cancel() -> dict[str, Any]:
            return _task_to_response(_require_task_runner(runtime).cancel(task_id))

        return await run_in_threadpool(cancel)

    @app.get("/api/v5/memory/health")
    async def memory_health() -> dict[str, Any]:
        return await run_in_threadpool(lambda: _memory_health(runtime))

    @app.get("/api/v5/memory/storage")
    async def memory_storage() -> dict[str, Any]:
        """Return read-only, redacted Memory & Storage diagnostics.

        The service inventories only Côme AI's configured memory directory;
        it never scans an entire home folder or attached volume.  It can be
        safely refreshed from the UI while the index worker is running.
        """

        return await run_in_threadpool(lambda: _memory_storage_snapshot(runtime))

    @app.get("/api/v5/memory/projects")
    async def memory_projects() -> dict[str, Any]:
        def read() -> dict[str, Any]:
            memory = _require_memory(runtime)
            return {"projects": [_project_to_response(item) for item in memory.list_projects()]}

        return await run_in_threadpool(read)

    @app.post("/api/v5/memory/projects")
    async def create_memory_project(payload: MemoryProjectRequest) -> dict[str, Any]:
        def create() -> dict[str, Any]:
            result = _require_memory(runtime).create_project(payload.name, payload.description)
            return {"status": result["status"], "project": _project_to_response(result["project"])}

        return await run_in_threadpool(create)

    @app.get("/api/v5/memory/sources")
    async def memory_sources(project_id: str | None = None) -> dict[str, Any]:
        def read() -> dict[str, Any]:
            sources = _require_memory(runtime).list_sources(project_id=project_id)
            return {"sources": [_source_to_response(item) for item in sources]}

        return await run_in_threadpool(read)

    @app.get("/api/v5/memory/search")
    async def memory_search(q: str, project_id: str | None = None) -> dict[str, Any]:
        def search() -> dict[str, Any]:
            result = _require_memory(runtime).search(q, project_id=project_id, limit=8)
            response: dict[str, Any] = {
                "query": result["query"],
                "count": result["count"],
                "results": [_memory_result_to_response(item) for item in result["results"]],
            }
            if result.get("note"):
                response["note"] = result["note"]
            return response

        return await run_in_threadpool(search)

    @app.post("/api/v5/memory/import-file")
    async def memory_import_file(payload: MemoryFileImportRequest) -> dict[str, Any]:
        """Compatibility endpoint for a small, immediate local import.

        The V5 interface now uses ``/index-tasks`` below so documents can be
        followed, cancelled between safe checkpoints and recovered after a
        server restart.  This endpoint stays in place for existing V5 clients
        and tests; it never receives a path from the browser.
        """

        def index() -> dict[str, Any]:
            memory = _require_memory(runtime)
            with runtime.workspace_lock:
                path = runtime.workspace.get_path(payload.file_id)
                result = memory.import_file(path, project_id=payload.project_id)
            return {
                "status": result["status"],
                "source_id": result["source_id"],
                "message": result["message"],
                "source": _source_to_response(result["source"]),
            }

        return await run_in_threadpool(index)

    @app.post("/api/v5/memory/index-tasks")
    async def create_memory_index_task(payload: MemoryIndexTaskRequest) -> dict[str, Any]:
        """Queue one explicit document indexation in the persistent worker.

        The local task queue intentionally owns the long-running part of a
        PDF, Word or spreadsheet extraction.  The request is accepted quickly
        and the browser polls the ordinary V5 task endpoint for real state.
        """

        def create() -> dict[str, Any]:
            _require_memory(runtime)
            runner = _require_task_runner(runtime)
            # Resolve now only to reject a stale/unknown opaque ID before a
            # queue row is created.  The worker resolves it again under the
            # workspace lock, so recovered jobs never trust this lookup.
            with runtime.workspace_lock:
                runtime.workspace.get_path(payload.file_id)
            task = runner.submit(
                TaskKind.MEMORY_INDEX,
                {
                    "file_id": payload.file_id,
                    "project_id": payload.project_id,
                    "plan": [
                        {
                            "step_id": "memory-index-1",
                            "tool": "index_memory",
                            "label": "Indexer le document dans la mémoire locale",
                            "requires_confirmation": False,
                        }
                    ],
                },
            )
            return _task_to_response(task)

        return await run_in_threadpool(create)

    @app.get("/api/files")
    async def list_files() -> dict[str, Any]:
        def read() -> list[dict[str, Any]]:
            with runtime.workspace_lock:
                return runtime.workspace.refresh()

        files = await run_in_threadpool(read)
        return {"files": files, "count": len(files)}

    @app.post("/api/files/upload")
    async def upload_files(request: Request) -> dict[str, Any]:
        try:
            form = await request.form(
                max_files=MAX_UPLOAD_FILES,
                max_fields=MAX_UPLOAD_FIELDS,
                max_part_size=64 * 1024,
            )
        except HTTPException as error:
            raise UserFacingError(
                "Import invalide : maximum 12 fichiers et 8 champs courts par envoi."
            ) from error
        try:
            all_uploads = [value for _, value in form.multi_items() if isinstance(value, UploadFile)]
            files = [value for key, value in form.multi_items() if key == "files" and isinstance(value, UploadFile)]
            if not files:
                raise UserFacingError("Sélectionne au moins un fichier à importer.")
            if len(all_uploads) != len(files):
                raise UserFacingError("Le champ d’import doit s’appeler « files ».")
            results = [await _store_upload(runtime, uploaded) for uploaded in files]
            with runtime.workspace_lock:
                current_files = runtime.workspace.list_files()
            return {"results": results, "files": current_files}
        finally:
            await form.close()

    @app.post("/api/actions/inspect")
    async def inspect_file(payload: FileActionRequest) -> dict[str, Any]:
        return await _run_local_tool(runtime, lambda: runtime.tools.inspect_file(payload.file_id))

    @app.post("/api/actions/analyze")
    async def analyze_table(payload: FileActionRequest) -> dict[str, Any]:
        return await _run_local_tool(
            runtime,
            lambda: runtime.tools.analyze_table(payload.file_id, payload.sheet_name),
        )

    @app.post("/api/actions/report")
    async def create_report(payload: FileActionRequest) -> dict[str, Any]:
        # This dedicated endpoint is only reached after a direct browser click.
        # It is therefore the deterministic user confirmation for a new file.
        return await _run_local_tool(
            runtime,
            lambda: runtime.tools.create_analysis_workbook(payload.file_id, payload.sheet_name),
        )

    @app.get("/api/outputs")
    async def list_outputs() -> dict[str, Any]:
        return {"outputs": _list_outputs(runtime.config.output_dir)}

    @app.get("/api/outputs/{filename}")
    async def download_output(filename: str) -> FileResponse:
        path = _safe_output_path(runtime.config.output_dir, filename)
        return FileResponse(
            path,
            filename=path.name,
            media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )

    @app.post("/api/chat")
    async def chat(payload: ChatRequest, request: Request) -> dict[str, Any]:
        message = payload.message.strip()
        if not message:
            raise UserFacingError("Écris une demande avant de l’envoyer.")
        origin = request.headers.get("origin")
        if origin and origin != f"{request.url.scheme}://{request.url.netloc}":
            raise HTTPException(status_code=403, detail="La conversation doit être lancée depuis cette application locale.")
        if payload.selected_file_ids and not payload.allow_cloud_context:
            raise HTTPException(
                status_code=400,
                detail="La sélection contient des données locales. Confirme leur transmission cloud pour cette demande, ou utilise le mode hors ligne.",
            )
        selected_names = await _selected_file_names(runtime, payload.selected_file_ids)
        if selected_names:
            message = (
                f"{message}\n\n"
                "[Contexte explicitement sélectionné par l’utilisateur — noms uniquement]\n"
                + "\n".join(f"- {name}" for name in selected_names)
            )

        def ask_agent() -> dict[str, Any]:
            # A single provider workflow at a time makes retry/timeout behaviour
            # predictable and prevents simultaneous calls from burning a quota.
            # Keep the file registry stable too: an upload cannot replace the
            # selected file while a provider is choosing controlled tools.
            with runtime.agent_lock, runtime.workspace_lock:
                if agent_override is None:
                    result = get_hybrid_chat().ask(
                        message,
                        mode="automatic",
                        selected_file_ids=list(payload.selected_file_ids),
                        allow_write=payload.allow_write,
                        allow_cloud_context=payload.allow_cloud_context,
                    )
                    # The legacy UI displays tool names, not structured events.
                    # Preserve the full free-only routing metadata alongside
                    # that presentation adapter, without invoking the old SDK.
                    response = dict(result)
                    response["tool_events"] = [
                        event.get("tool", "outil_local") if isinstance(event, dict) else str(event)
                        for event in result.get("tool_events", [])
                    ]
                    return response
                return runtime.agent.ask(
                    message,
                    allow_writes=payload.allow_write,
                    allow_cloud_context=payload.allow_cloud_context,
                    local_context_present=bool(selected_names),
                )

        result = await run_in_threadpool(ask_agent)
        return to_jsonable(result)

    career_ai_generator: Callable[[str], dict[str, Any]] | None = None
    if agent_override is None or callable(getattr(agent, "generate_career_application", None)):
        def generate_career_application(prompt: str) -> dict[str, Any]:
            # Career drafts are a consciously initiated, separate provider
            # action. It shares the existing one-at-a-time lock so a second
            # browser tab cannot consume quota concurrently with general chat.
            with runtime.agent_lock:
                if agent_override is None:
                    result = get_hybrid_chat().ask(prompt, mode="performance")
                    usage = result.get("usage", {})
                    if isinstance(usage, dict) and usage.get("truncated"):
                        raise UserFacingError(
                            "La réponse IA est incomplète et n’a pas été enregistrée. "
                            "Tes brouillons existants restent inchangés ; utilise le brouillon local ou réduis la demande."
                        )
                    return {
                        "text": result.get("answer", ""),
                        "provider": " · ".join(str(result.get(key) or "") for key in ("provider", "model")).strip(" ·"),
                    }
                return agent.generate_career_application(prompt)

        career_ai_generator = generate_career_application

    app.include_router(create_career_router(career, ai_generator=career_ai_generator))
    from devkit.router import create_developer_router

    app.include_router(create_developer_router(get_workshop))
    app.mount("/static", StaticFiles(directory=WEB_STATIC_DIR), name="static")
    app.mount("/v5-static", StaticFiles(directory=V5_STATIC_DIR), name="v5-static")
    app.mount("/career-static", StaticFiles(directory=CAREER_STATIC_DIR), name="career-static")
    return app


def _execute_v5_task(
    runtime: Runtime,
    context: TaskExecutionContext,
    payload: dict[str, Any],
) -> dict[str, Any]:
    """The only registered V5 background handler in this increment.

    ``TaskRunner`` dispatches it by an enum chosen in application code.  This
    function revalidates the small payload even though it came from the local
    server, so a corrupted/recovered SQLite row cannot turn into an arbitrary
    action.
    """

    message = payload.get("message")
    file_ids = payload.get("selected_file_ids", [])
    allow_write = payload.get("allow_write", False)
    project_id = payload.get("memory_project_id")
    if not isinstance(message, str) or not isinstance(file_ids, list) or not isinstance(allow_write, bool):
        raise UserFacingError("La tâche locale enregistrée est invalide.")
    if any(not isinstance(item, str) for item in file_ids):
        raise UserFacingError("La tâche locale contient un identifiant de fichier invalide.")
    if project_id is not None and not isinstance(project_id, str):
        raise UserFacingError("La tâche locale contient un projet de mémoire invalide.")

    def report_progress(fraction: float, text: str) -> None:
        bounded = max(0, min(100, int(round(float(fraction) * 100))))
        context.set_progress(bounded, text)

    context.checkpoint()
    # Serializing workspace work has two benefits: an upload cannot replace a
    # selected ID during a plan and old Intel Macs are not saturated by two
    # pandas/PDF operations at once. The runner still leaves HTTP responsive.
    with runtime.workspace_lock:
        return runtime.orchestrator.run(
            message,
            selected_file_ids=file_ids,
            allow_write=allow_write,
            memory_project_id=project_id,
            progress=report_progress,
            is_cancelled=context.is_cancellation_requested,
        )


def _execute_memory_index_task(
    runtime: Runtime,
    context: TaskExecutionContext,
    payload: dict[str, Any],
) -> dict[str, Any]:
    """Index one selected workspace document through the persistent worker.

    This handler has deliberately narrow authority: a persisted row may carry
    only a workspace ``file_id`` and a memory ``project_id``.  It cannot turn a
    recovered task into a recursive scan, a raw filesystem operation or a
    model/API call.  Import is idempotent in ``PersonalMemoryStore`` through
    its content hash, which also makes a task safely retryable after a restart.
    """

    file_id = payload.get("file_id")
    project_id = payload.get("project_id")
    if not isinstance(file_id, str) or not file_id.strip():
        raise UserFacingError("La tâche d’indexation ne contient pas de document valide.")
    if project_id is not None and not isinstance(project_id, str):
        raise UserFacingError("La tâche d’indexation ne contient pas de projet valide.")

    memory = _require_memory(runtime)
    context.set_progress(3, "Vérification du document sélectionné.")
    # Resolve the opaque ID while the registry is stable, then release the
    # workspace lock before a potentially long parse.  The source file lives
    # in the controlled data directory and V5 has no destructive file route,
    # so this avoids unnecessarily blocking uploads and file browsing during a
    # large PDF/Excel indexation.
    with runtime.workspace_lock:
        path = runtime.workspace.get_path(file_id)
    context.set_progress(12, "Extraction locale et préparation de l’index.")
    result = memory.import_file(path, project_id=project_id)
    context.checkpoint()
    context.set_progress(96, "Finalisation de l’index de recherche locale.")
    source = result.get("source")
    if not isinstance(source, dict):
        raise UserFacingError("L’indexation locale n’a retourné aucune source valide.")
    return {
        "mode": "mémoire locale FTS5",
        "remote_model_used": False,
        "status": result.get("status", "indexed"),
        "message": result.get("message", "Document indexé dans la mémoire locale."),
        "source": _source_to_response(source),
        "citations": [],
    }


def _require_memory(runtime: Runtime) -> PersonalMemoryStore:
    if runtime.memory is None:
        raise UserFacingError(runtime.memory_error or "La mémoire locale n’est pas disponible.")
    return runtime.memory


def _require_task_queue(runtime: Runtime) -> TaskQueue:
    if runtime.task_queue is None:
        raise UserFacingError(runtime.task_queue_error or "La file de tâches locale n’est pas disponible.")
    return runtime.task_queue


def _require_task_runner(runtime: Runtime) -> TaskRunner:
    if runtime.task_runner is None:
        raise UserFacingError(runtime.task_queue_error or "La file de tâches locale n’est pas disponible.")
    return runtime.task_runner


def _task_to_response(task: TaskRecord) -> dict[str, Any]:
    status_names = {
        TaskStatus.QUEUED: "queued",
        TaskStatus.RUNNING: "running",
        TaskStatus.CANCELLING: "cancelling",
        TaskStatus.CANCELLED: "cancelled",
        TaskStatus.SUCCEEDED: "completed",
        TaskStatus.FAILED: "failed",
    }
    payload_plan = task.payload.get("plan", [])
    plan = payload_plan if isinstance(payload_plan, list) else []
    last_message = task.messages[-1].text if task.messages else "Tâche locale planifiée."
    return {
        "task_id": task.id,
        "kind": task.kind.value,
        "status": status_names[task.status],
        "progress": round(task.progress / 100, 2),
        "progress_percent": task.progress,
        "message": last_message,
        "cancellation_requested": task.cancellation_requested,
        "created_at": task.created_at,
        "updated_at": task.updated_at,
        "plan": to_jsonable(plan),
        "result": to_jsonable(task.result),
        "error": task.error,
        "messages": [
            {"created_at": item.created_at, "level": item.level.value, "text": item.text}
            for item in task.messages
        ],
    }


def _project_to_response(project: dict[str, Any]) -> dict[str, Any]:
    return {
        "project_id": project.get("id"),
        "name": project.get("name", "Projet"),
        "description": project.get("description", ""),
        "source_count": project.get("source_count", 0),
        "created_at": project.get("created_at", ""),
        "updated_at": project.get("updated_at", ""),
    }


def _source_to_response(source: dict[str, Any]) -> dict[str, Any]:
    projects = source.get("projects", [])
    names = [str(item.get("name", "")) for item in projects if isinstance(item, dict) and item.get("name")]
    return {
        "source_id": source.get("id"),
        "title": source.get("title", "Document"),
        "kind": source.get("source_type", "document"),
        "category": source.get("category", "general"),
        "chunk_count": source.get("chunk_count", 0),
        "char_count": source.get("char_count", 0),
        "imported_at": source.get("imported_at", ""),
        "project_name": ", ".join(names) if names else "sans projet",
    }


def _memory_result_to_response(result: dict[str, Any]) -> dict[str, Any]:
    citation = result.get("citation", {})
    if not isinstance(citation, dict):
        citation = {}
    return {
        "source_id": citation.get("source_id") or result.get("source_id"),
        "source_title": citation.get("title") or result.get("title", "Source locale"),
        "citation": citation.get("label") or result.get("title", "Source locale"),
        "page": citation.get("page"),
        "sheet": citation.get("sheet"),
        "line_start": citation.get("line_start"),
        "line_end": citation.get("line_end"),
        "row_start": citation.get("row_start"),
        "row_end": citation.get("row_end"),
        "excerpt": result.get("excerpt", ""),
    }


def _memory_health(runtime: Runtime) -> dict[str, Any]:
    if runtime.memory is None:
        return {"available": False, "detail": runtime.memory_error or "Mémoire locale indisponible."}
    try:
        stats = runtime.memory.stats()
    except PersonalMemoryError:
        return {"available": False, "detail": "La mémoire locale n’est pas disponible."}
    return {
        "available": True,
        "project_count": stats["projects"],
        "source_count": stats["sources"],
        "chunk_count": stats["chunks"],
        "engine": "SQLite FTS5 local",
    }


def _memory_storage_snapshot(runtime: Runtime) -> dict[str, Any]:
    """Compose safe disk diagnostics with live memory/queue state.

    ``MemoryStorageService`` deliberately owns the bounded filesystem walk and
    fixed SQLite inspection.  This web adapter only adds counts from the
    already-authorised V5 services; it does not reveal ``config.memory_dir``
    or make the browser choose a path to scan.
    """

    health = _memory_health(runtime)
    if not health.get("available"):
        return {
            "available": False,
            "detail": health.get("detail", "La mémoire locale n’est pas disponible."),
            "indexing": {"active_count": 0, "queued_count": 0},
        }
    try:
        snapshot = MemoryStorageService(runtime.config.memory_dir).snapshot()
    except MemoryStorageError:
        # The dashboard is optional.  A malformed local diagnostic setting
        # must not disable the memory engine or disclose its configuration.
        return {
            "available": False,
            "detail": "Les informations de stockage local ne sont pas disponibles.",
            "indexing": {"active_count": 0, "queued_count": 0},
        }

    # The default directory is intentionally described by role, not its full
    # absolute path.  A deliberately configured external/local location keeps
    # the storage service's redacted display form so its owner can recognise
    # the selected volume without an account name being exposed.
    default_memory_dir = (runtime.config.base_dir / "memory_data").resolve()
    try:
        is_default_location = runtime.config.memory_dir.resolve() == default_memory_dir
    except OSError:
        is_default_location = False
    location = snapshot.get("location")
    if isinstance(location, dict):
        location["mode"] = "default_local" if is_default_location else "configured_local_storage"
        if is_default_location:
            location["display_path"] = "Dossier local Côme AI · memory_data"

    active_count = 0
    queued_count = 0
    if runtime.task_queue is not None:
        try:
            tasks = runtime.task_queue.list_tasks(limit=100)
            for task in tasks:
                if task.kind is not TaskKind.MEMORY_INDEX:
                    continue
                if task.status in ACTIVE_STATUSES:
                    active_count += 1
                if task.status is TaskStatus.QUEUED:
                    queued_count += 1
        except TaskQueueError:
            # The disk snapshot remains useful if task-history inspection is
            # temporarily unavailable.  Do not leak the internal SQLite error.
            pass
    resource_limits: dict[str, Any] = {}
    memory = runtime.memory
    raw_limits = getattr(memory, "resource_limits", None)
    if raw_limits is not None and callable(getattr(raw_limits, "as_dict", None)):
        resource_limits = raw_limits.as_dict()
    return {
        "available": True,
        "engine": "SQLite FTS5 local",
        "memory": health,
        "indexing": {"active_count": active_count, "queued_count": queued_count},
        "resource_limits": resource_limits,
        "storage": snapshot,
    }


def _task_queue_health(runtime: Runtime) -> dict[str, Any]:
    if runtime.task_queue is None:
        return {"available": False, "detail": runtime.task_queue_error or "File locale indisponible."}
    try:
        tasks = runtime.task_queue.list_tasks(limit=100)
    except TaskQueueError:
        return {"available": False, "detail": "File locale indisponible."}
    return {
        "available": True,
        "active_count": sum(1 for task in tasks if task.status in ACTIVE_STATUSES),
        "worker_running": bool(runtime.task_runner and runtime.task_runner.is_running),
        # Scheduler-level errors are logged locally through ``safe_error``;
        # returning their raw text could otherwise disclose a SQLite/volume
        # path if a future handler fails outside the controlled wrappers.
        "worker_error": "Un problème local a été journalisé." if runtime.task_runner and runtime.task_runner.last_worker_error else None,
    }


def _v5_capabilities(runtime: Runtime) -> dict[str, Any]:
    return {
        "enabled": True,
        "mode": "hybrid-controlled",
        "provider_execution": "explicit-chat-request-only",
        "chat_modes": ["offline", "automatic", "performance"],
        "memory": _memory_health(runtime),
        "task_queue": _task_queue_health(runtime),
        "write_confirmation": "required-per-task",
    }


def _v5_overview(runtime: Runtime) -> dict[str, Any]:
    return {
        "application": "Côme AI 5.0",
        "mode": "local seulement (127.0.0.1)",
        "providers": runtime.agent.provider_status(),
        "memory": _memory_health(runtime),
        "task_queue": _task_queue_health(runtime),
    }


async def _run_local_tool(runtime: Runtime, action: Any) -> dict[str, Any]:
    def run() -> dict[str, Any]:
        with runtime.workspace_lock:
            return to_jsonable(action())

    return await run_in_threadpool(run)


async def _selected_file_names(runtime: Runtime, file_ids: list[str]) -> list[str]:
    def resolve() -> list[str]:
        names: list[str] = []
        with runtime.workspace_lock:
            runtime.workspace.refresh()
            for file_id in file_ids:
                path = runtime.workspace.get_path(file_id)
                if path.name not in names:
                    names.append(path.name)
        return names

    return await run_in_threadpool(resolve)


async def _store_upload(runtime: Runtime, uploaded: UploadFile) -> dict[str, Any]:
    filename = _safe_upload_name(uploaded.filename)
    suffix = Path(filename).suffix.lower()
    if suffix not in SUPPORTED_SUFFIXES:
        return {"name": filename, "error": "Format non pris en charge."}

    temp_path = runtime.config.data_dir / f".upload-{uuid.uuid4().hex}.part"
    bytes_written = 0
    try:
        with temp_path.open("xb") as output:
            while chunk := await uploaded.read(UPLOAD_CHUNK_SIZE):
                bytes_written += len(chunk)
                if bytes_written > MAX_IMPORT_BYTES:
                    raise UserFacingError("Fichier trop volumineux (maximum 50 Mo).")
                output.write(chunk)
        with runtime.workspace_lock:
            destination = runtime.workspace.unique_destination(filename)
            temp_path.replace(destination)
            runtime.workspace.refresh()
            file_id = runtime.workspace.file_id_by_name(destination.name)
        return {
            "name": destination.name,
            "file_id": file_id,
            "size_kb": round(bytes_written / 1024, 1),
            "status": "importé",
        }
    except UserFacingError as error:
        return {"name": filename, "error": str(error)}
    except OSError as error:
        runtime.logger.info("Upload error %s", safe_error(error))
        return {"name": filename, "error": "Import impossible."}
    finally:
        temp_path.unlink(missing_ok=True)


def _safe_upload_name(raw_name: str | None) -> str:
    name = Path(raw_name or "fichier").name
    name = re.sub(r"[\x00-\x1f]", "", name).strip().lstrip(".")
    if not name or name in {".", ".."}:
        raise UserFacingError("Nom de fichier invalide.")
    return name[:180]


async def _send_upload_too_large(
    scope: dict[str, Any], receive: Any, send: Any, message: str
) -> None:
    response = JSONResponse(
        status_code=413,
        content={"detail": message},
    )
    await response(scope, receive, send)


def _safe_output_path(output_dir: Path, filename: str) -> Path:
    if filename != Path(filename).name or "/" in filename or "\\" in filename:
        raise UserFacingError("Rapport introuvable.")
    candidate = (output_dir / Path(filename).name).resolve()
    if candidate.parent != output_dir.resolve() or not candidate.is_file() or candidate.suffix.lower() != ".xlsx":
        raise UserFacingError("Rapport introuvable.")
    return candidate


def _list_outputs(output_dir: Path) -> list[dict[str, Any]]:
    reports: list[dict[str, Any]] = []
    for path in sorted(output_dir.glob("*.xlsx"), key=lambda item: item.stat().st_mtime, reverse=True):
        stat = path.stat()
        reports.append({
            "name": path.name,
            "size_kb": round(stat.st_size / 1024, 1),
            "created_at": datetime.fromtimestamp(stat.st_mtime).strftime("%Y-%m-%d %H:%M"),
        })
    return reports


def _build_logger(log_dir: Path) -> logging.Logger:
    logger = logging.getLogger("come_ai.web")
    logger.setLevel(logging.INFO)
    logger.propagate = False
    if not logger.handlers:
        handler = logging.FileHandler(log_dir / "come-ai-web.log", encoding="utf-8")
        handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
        logger.addHandler(handler)
    return logger


def _log_error(runtime: Runtime, error: Exception, *, level: int) -> str:
    error_id = uuid.uuid4().hex[:10]
    runtime.logger.log(level, "error_id=%s %s", error_id, safe_error(error))
    return error_id



