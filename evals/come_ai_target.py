"""Evaluate real deterministic Côme AI services with isolated synthetic inputs.

No response is reconstructed from ``case.expected``. Each supported action calls
the application's services, and the runner judges their returned observations.
This target deliberately does not measure language-model generation quality.
Runtime memory UUIDs are aliased to fixture IDs; volatile timestamps are omitted
from traces so the same synthetic request has a deterministic service trace.
"""

from __future__ import annotations

import csv
from collections.abc import Mapping
from contextlib import ExitStack, contextmanager
from dataclasses import fields, is_dataclass
from pathlib import Path
import socket
import tempfile
from typing import Any, Iterator
from unittest.mock import patch

from free_ai_router import (
    FunctionCallValidationError,
    FunctionTool,
    FunctionToolRegistry,
    classify_task,
    prepare_function_calls,
)
from career.service import CareerService
from career.connectors import LeverConnector
from career.offer_qualification import qualify_offer
from career.router import create_career_router
from fastapi import FastAPI
from fastapi.testclient import TestClient
from hybrid_chat import HybridChatService
from openpyxl import Workbook
from personal_memory import PersonalMemoryStore
from v5_orchestrator import LocalOrchestrator
from workspace_core import AppConfig, LocalTools, TOOL_SCHEMAS, UserFacingError, Workspace

from .runner import TargetResult
from .schema import Case, load_cases


REAL_CASES_PATH = Path(__file__).parent / "cases" / "come_ai_real.json"


class NetworkAccessBlocked(RuntimeError):
    """The evaluation permits neither cloud nor loopback network traffic."""


def load_real_cases() -> list[Case]:
    """Load the small real-service suite separately from the 60 core cases."""
    return load_cases(REAL_CASES_PATH)


def _isolated_config(root: Path) -> AppConfig:
    # AppConfig.load reads .env and user environment overrides. Explicit paths
    # prevent an evaluation from opening the user's configured memory store.
    return AppConfig(
        base_dir=root, data_dir=root / "data", output_dir=root / "output",
        log_dir=root / "logs", memory_dir=root / "memory_data",
        settings_path=root / "settings.json", env_path=root / ".env",
        primary_model="unused", fallback_models=(), request_timeout_seconds=10,
        retry_attempts=1, ollama_model=None,
        ollama_base_url="http://127.0.0.1:11434/api/chat",
    )


class ComeAITarget:
    """Bounded adapter for existing local calculation, memory and file services.

    Every run gets a fresh temporary workspace which is removed afterward.
    Supported actions are data-only and never execute a caller-selected method.
    ``trace`` records calls/results, including refusals, and a network counter.
    A normal application refusal is a real observation, not an infrastructure
    exception. Unexpected exceptions produce ``execution_error`` with no payload.
    """

    name = "come-ai"
    execution_kind = "real"
    supported_features = frozenset({
        "local_arithmetic", "memory_search", "citations", "csv_inspection",
        "excel_inspection", "table_statistics", "local_plan_execution",
        "write_confirmation", "opaque_file_ids", "tool_validation", "cloud_context_consent",
        "career_http_qualification", "public_ats_http",
    })
    _ACTIONS = frozenset({"calculate", "memory_search", "orchestrate", "invalid_file_id", "validate_tools",
                          "cloud_context_refusal", "career_qualification_http", "public_ats_connector_http"})

    def __init__(self) -> None:
        self.network_attempts = 0
        self._trace: list[dict[str, Any]] = []
        self._source_aliases: dict[str, str] = {}
        self._root: Path | None = None

    def supports_case(self, case: Case) -> tuple[bool, str]:
        missing = sorted(set(case.required_features) - self.supported_features)
        if missing:
            return False, "Capacités non évaluées : " + ", ".join(missing)
        if case.input.get("action") not in self._ACTIONS:
            return False, "Aucun handler réel pour ce contrat de cas."
        return True, ""

    def _deny_network(self, *_args: Any, **_kwargs: Any) -> Any:
        self.network_attempts += 1
        raise NetworkAccessBlocked("Network access is blocked during real-service evaluations.")

    @contextmanager
    def network_boundary(self) -> Iterator[None]:
        """Block actual socket entry points as well as injected HTTP transport."""
        with ExitStack() as stack:
            for name in ("connect", "connect_ex", "sendto", "sendmsg"):
                if hasattr(socket.socket, name):
                    stack.enter_context(patch.object(socket.socket, name, self._deny_network))
            stack.enter_context(patch.object(socket, "create_connection", self._deny_network))
            stack.enter_context(patch.object(socket, "getaddrinfo", self._deny_network))
            yield

    def _stable(self, value: Any) -> Any:
        if is_dataclass(value) and not isinstance(value, type):
            return {item.name: self._stable(getattr(value, item.name)) for item in fields(value)}
        if isinstance(value, Mapping):
            return {key: self._stable(item) for key, item in value.items()
                    if key not in {"imported_at", "updated_at", "latency_seconds"}}
        if isinstance(value, (list, tuple)):
            return [self._stable(item) for item in value]
        if isinstance(value, str):
            text = self._source_aliases.get(value, value)
            if self._root is not None:
                text = text.replace(str(self._root), "[synthetic-workspace]")
            return text
        return value

    def _call(self, component: str, method: str, function: Any, **arguments: Any) -> Any:
        event = {"component": component, "method": method, "arguments": self._stable(arguments)}
        self._trace.append(event)
        try:
            result = function(**arguments)
        except (UserFacingError, FunctionCallValidationError) as error:
            event.update(status="refused", error=str(error))
            raise
        except Exception as error:
            event.update(status="execution_error", error_type=type(error).__name__)
            raise
        event.update(status="returned", result=self._stable(result))
        return result

    @staticmethod
    def _observation(*, answer: str | None = None, structured: dict | None = None,
                     error: str | None = None) -> dict[str, Any]:
        return {"answer": answer, "structured": structured, "citations": [], "facts": [],
                "tools_called": [], "plan": [], "usage": None, "error": error}

    @staticmethod
    def _create_synthetic_http_app(root: Path, career: CareerService):
        """Build an isolated app around the production Career HTTP router.

        The target deliberately mounts the real router instead of the entire
        desktop app: unrelated tests are allowed to replace global app
        dependencies, while this evidence must remain hermetic and must never
        load credentials, memory stores or background workers.
        """
        del root
        app = FastAPI()
        app.include_router(create_career_router(career))
        return app

    def _chat(self, root: Path, workspace: Workspace, tools: LocalTools,
              memory: PersonalMemoryStore | None = None) -> HybridChatService:
        return HybridChatService(root, workspace, tools, memory,
                                 transport=self._deny_network, credential_loader=self._deny_network)

    def _from_service(self, result: dict[str, Any]) -> dict[str, Any]:
        observation = self._observation(answer=result.get("answer"))
        events = result.get("tool_events", result.get("events", []))
        observation["tools_called"] = [event["tool"] for event in events
                                       if event.get("status") == "done"]
        # The real orchestrator executes its plan serially. Its PlanStep has no
        # depends_on field; expose that existing serial ordering to the lab's
        # plan contract without changing application execution or proposals.
        plan = result.get("plan", [])
        observation["plan"] = [dict(step, depends_on=[] if index == 0 else [plan[index - 1]["step_id"]])
                               for index, step in enumerate(plan)]
        observation["structured"] = {"events": events, "remote_model_used": result["remote_model_used"]}
        for event in events:
            if event.get("tool") == "calculate_expression" and event.get("status") == "done":
                observation["structured"]["value"] = event["result"]["value"]
            if event.get("tool") == "analyze_table" and event.get("status") == "done":
                observation["structured"]["analysis"] = event["result"]
            if event.get("tool") == "inspect_file" and event.get("status") == "done":
                observation["structured"]["inspection"] = event["result"]
        return observation

    @staticmethod
    def _fixture(workspace: Workspace, fixture: dict[str, Any]) -> tuple[str, bytes]:
        name = fixture["name"]
        if not isinstance(name, str) or len(name) > 80 or Path(name).name != name or "/" in name or "\\" in name:
            raise ValueError("Synthetic fixture names must be plain basenames.")
        path = workspace.config.data_dir / name
        rows = fixture["rows"]
        if not isinstance(rows, list) or not 1 <= len(rows) <= 100 or any(
            not isinstance(row, list) or not 1 <= len(row) <= 20
            or any(type(cell) not in {str, int, float, bool, type(None)}
                   or isinstance(cell, str) and len(cell) > 500 for cell in row)
            for row in rows
        ):
            raise ValueError("Synthetic fixtures are bounded to 100 rows and 20 columns.")
        if path.suffix == ".csv":
            with path.open("w", encoding="utf-8", newline="") as stream:
                csv.writer(stream, delimiter=";").writerows(rows)
        elif path.suffix == ".xlsx":
            workbook = Workbook()
            workbook.active.title = fixture.get("sheet", "Budget")
            for row in rows:
                workbook.active.append(row)
            workbook.save(path)
        else:
            raise ValueError("Only synthetic CSV/XLSX fixtures are supported.")
        workspace.refresh()
        file_id = workspace.file_id_by_name(name)
        if file_id is None:
            raise ValueError("The synthetic file was not registered.")
        return file_id, path.read_bytes()

    def _execute(self, case: Case, root: Path) -> dict[str, Any]:
        workspace = Workspace(_isolated_config(root))
        tools = LocalTools(workspace)
        data = case.input
        action = data["action"]
        if action == "calculate":
            service = self._chat(root, workspace, tools)
            result = self._call("HybridChatService", "ask", service.ask,
                                message=data["message"], mode="offline")
            return self._from_service(result)
        if action == "memory_search":
            memory = PersonalMemoryStore(workspace.config.memory_dir)
            if not isinstance(data["sources"], list) or not 1 <= len(data["sources"]) <= 8:
                raise ValueError("Memory fixtures are bounded to eight synthetic sources.")
            for source in data["sources"]:
                if not isinstance(source["text"], str) or len(source["text"]) > 3000:
                    raise ValueError("Memory fixture texts are bounded to 3000 characters.")
                result = memory.import_text(source["text"], title=source["title"], category="eval_synthetic")
                self._source_aliases[result["source_id"]] = source["id"]
                self._trace.append({"component": "PersonalMemoryStore", "method": "import_text",
                                    "status": "returned", "arguments": {"title": source["title"], "text": source["text"]},
                                    "result": self._stable(result)})
            service = self._chat(root, workspace, tools, memory)
            result = self._call("HybridChatService", "ask", service.ask,
                                message=data["message"], mode="offline")
            observation = self._from_service(result)
            search = next(event["result"] for event in result["tool_events"] if event["tool"] == "search_memory")
            self._trace.append({"component": "PersonalMemoryStore", "method": "search", "status": "returned", "result": self._stable(search)})
            observation["structured"]["count"] = search["count"]
            observation["structured"]["note"] = search.get("note") or ""
            observation["citations"] = [{"source_id": hit["source_id"], "quote": hit["excerpt"],
                                         "label": hit["citation"]["label"], "line_start": hit["citation"]["line_start"],
                                         "line_end": hit["citation"]["line_end"]} for hit in search["results"]]
            return observation
        if action == "orchestrate":
            fixture = data["file"]
            file_id, before = self._fixture(workspace, fixture)
            orchestrator = LocalOrchestrator(workspace, tools)
            result = self._call("LocalOrchestrator", "run", orchestrator.run,
                                message=data["message"], selected_file_ids=[file_id],
                                allow_write=data.get("allow_write", False))
            observation = self._from_service(result)
            for event in result["events"]:
                if event["status"] == "done":
                    self._trace.append({"component": "LocalTools", "method": event["tool"],
                                        "status": "returned", "result": event.get("result")})
                else:
                    # A planned but gated tool is not a LocalTools invocation.
                    self._trace.append({"component": "LocalOrchestrator", "method": "step_gate",
                                        "tool": event["tool"], "status": event["status"]})
            observation["structured"]["source_unchanged"] = (workspace.config.data_dir / fixture["name"]).read_bytes() == before
            observation["structured"]["output_files"] = sorted(path.name for path in workspace.config.output_dir.iterdir())
            observation["structured"]["report_status"] = next(
                (event["status"] for event in result["events"] if event["tool"] == "create_analysis_workbook"), None)
            analyze_event = next((event for event in result["events"] if event["tool"] == "analyze_table" and event["status"] == "done"), None)
            observation["structured"]["numeric_columns"] = (
                len(analyze_event["result"].get("numeric_statistics", {})) if analyze_event else 0)
            return observation
        if action == "invalid_file_id":
            result = self._call("LocalTools", "inspect_file", tools.inspect_file, file_id=data["file_id"])
            return self._observation(structured=result)
        if action == "validate_tools":
            registry = FunctionToolRegistry(FunctionTool(
                name=schema["name"], description=schema["description"], parameters_schema=schema["parameters"])
                for schema in TOOL_SCHEMAS)
            prepared = prepare_function_calls(classify_task("Inspecte le document"), registry,
                                              approved_names=["inspect_file"])
            approved = self._call("PreparedFunctionCalls", "validate_proposal", prepared.validate_proposal,
                                  call_id="eval_valid", name="inspect_file", arguments={"file_id": "f_synthetic"})
            try:
                self._call("PreparedFunctionCalls", "validate_proposal", prepared.validate_proposal,
                           call_id="eval_denied", name=data["forbidden_tool"], arguments={})
            except FunctionCallValidationError:
                rejected = True
            else:
                rejected = False
            return {**self._observation(answer="Validation réelle des propositions d'outils."),
                    "structured": {"validated_tool": approved.name, "rejected_tool": data["forbidden_tool"], "rejected": rejected},
                    "tools_called": ["validate_proposal", "validate_proposal"]}
        if action == "cloud_context_refusal":
            fixture = data["file"]
            file_id, _ = self._fixture(workspace, fixture)
            service = self._chat(root, workspace, tools)
            return self._from_service(self._call(
                "HybridChatService", "ask", service.ask,
                message=data["message"], selected_file_ids=[file_id], mode="performance",
                provider="gemini", allow_cloud_context=False,
            ))
        if action == "career_qualification_http":
            offer = dict(data["offer"])
            offer.setdefault("company", "Entreprise synthétique")
            offer.setdefault("source_name", "greenhouse")
            offer.setdefault("source_id", "synthetic-career-offer")
            offer.setdefault("official_url", "https://careers.example.test/synthetic-offer")
            offer.setdefault("source_status", "open")

            # Store the synthetic input through the real local service, then
            # ask the actual HTTP matching endpoint to qualify it.  A fixture
            # URL is deliberately not treated as a verified live source, so a
            # technically eligible offer remains ``to_verify``.
            service = CareerService(root, curated_sources=())
            imported_job = service.import_job(offer)
            with TestClient(self._create_synthetic_http_app(root, service)) as client:
                criteria_response = client.put(
                    "/api/career/stage-search",
                    json={
                        # Submit a complete, explicitly configured brief so
                        # the evaluation does not depend on process-global
                        # defaults mutated by unrelated tests.
                        "domains": ["Corporate Finance"],
                        "contract_types": ["stage"],
                        "start_months": [1, 2, 3],
                        "minimum_stage_duration_months": 6,
                        "excluded_countries": ["France"],
                        "excluded_cities": ["Paris"],
                        "require_known_location": True,
                    },
                )
                if criteria_response.status_code != 200:
                    return self._observation(error=f"Career criteria returned {criteria_response.status_code}.")
                response = client.get(f"/api/career/jobs/{imported_job['id']}")
            if response.status_code != 200:
                return self._observation(error=f"Career HTTP returned {response.status_code}.")
            stored_job = response.json()
            qualification = qualify_offer(
                stored_job,
                allowed_contract_types=["stage"],
                allowed_start_months=[1, 2, 3],
                minimum_stage_duration_months=6,
                excluded_countries=["France"],
                excluded_cities=["Paris"],
                require_known_location=True,
            ).to_dict()
            excluded = (
                qualification.get("target_status") == "non_conforming"
                or qualification.get("contract_status") == "excluded"
            )
            missing_fields = qualification.get("missing_fields", [])
            structured = {"http_status": response.status_code,
                          "retained_count": int(not excluded),
                          "excluded_count": int(excluded),
                          "qualification": qualification,
                          "missing_start": "début" in missing_fields,
                          "missing_duration": "durée" in missing_fields,
                          "synthetic_fixture": True, "network_attempts": self.network_attempts}
            return {**self._observation(answer="Parcours HTTP Career exécuté sur fixture synthétique."),
                    "structured": structured,
                    "usage": {"api_calls": 0, "generation_requests": 0,
                              "network_attempts": self.network_attempts}}
        if action == "public_ats_connector_http":
            source = {"id": "synthetic:lever:board", "provider": "lever", "company": "Finance synthétique",
                      "board_token": "synthetic-board", "verified_at": "2026-10-18T00:00:00Z",
                      "provenance_url": "https://careers.example.test/synthetic"}
            posting = [{"id": "synthetic-lever-01", "text": "Finance Intern (synthetic)",
                        "categories": {"location": "London, United Kingdom", "commitment": "Intern"},
                        "country": "GB", "descriptionPlain": "Synthetic finance internship.",
                        "hostedUrl": "https://jobs.lever.co/synthetic-board/synthetic-lever-01",
                        "applyUrl": "https://jobs.lever.co/synthetic-board/synthetic-lever-01/apply"}]

            class SyntheticTransport:
                def get_json(self, _endpoint: str, _timeout_seconds: int) -> Any:
                    return posting

            connector = LeverConnector(transport=SyntheticTransport(), enabled=True,
                                       clock=lambda: "2026-10-18T00:00:00Z")
            service = CareerService(root, curated_sources=(source,), exploration_connectors={"lever": connector})
            with TestClient(self._create_synthetic_http_app(root, service)) as client:
                response = client.post("/api/career/stage-search/explore", json={"force": True})
            if response.status_code != 200:
                return self._observation(error=f"Career HTTP returned {response.status_code}.")
            payload = response.json()
            self._trace.append({"component": "LeverConnector", "method": "get_json",
                                "status": "returned", "synthetic_only": True})
            return {**self._observation(answer="Connecteur ATS et route Career HTTP exécutés sur fixture synthétique."),
                    "structured": {"http_status": response.status_code, "provider": "lever",
                                   "raw_count": payload.get("summary", {}).get("raw_count", 0),
                                   "synthetic_fixture": True, "network_attempts": self.network_attempts},
                    "usage": {"api_calls": 0, "generation_requests": 0,
                              "network_attempts": self.network_attempts}}
        raise ValueError("Unsupported action reached execution.")

    def run(self, case: Case) -> TargetResult:
        self.network_attempts = 0
        self._trace = []
        self._source_aliases = {}
        self._root = None
        supported, reason = self.supports_case(case)
        if not supported:
            return TargetResult(status="unsupported", reason=reason)
        try:
            with tempfile.TemporaryDirectory(prefix="come-evals-synthetic-") as directory:
                self._root = Path(directory)
                with self.network_boundary():
                    try:
                        observation = self._execute(case, self._root)
                    except (UserFacingError, FunctionCallValidationError) as error:
                        observation = self._observation(error=str(error))
                        observation["tools_called"] = [event["method"] for event in self._trace
                                                       if event["component"] == "LocalTools"]
                observation["usage"] = {"api_calls": 0, "generation_requests": 0,
                                        "network_attempts": self.network_attempts}
                self._trace.append({"component": "evaluation_boundary", "method": "network_guard",
                                    "status": "blocked", "attempts": self.network_attempts,
                                    "synthetic_only": True, "model_generation_measured": False})
                return TargetResult(observation=self._stable(observation), status="real", trace=self._stable(self._trace))
        except Exception as error:
            self._trace.append({"component": "evaluation_boundary", "method": "execution",
                                "status": "execution_error", "error_type": type(error).__name__,
                                "network_attempts": self.network_attempts})
            return TargetResult(status="execution_error", reason=type(error).__name__, trace=self._stable(self._trace))

