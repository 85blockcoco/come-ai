"""Offline tests for Côme AI V3.

All fixtures use a temporary directory. One test writes a fake key only to a
temporary `.env` to verify it is never exposed; no test contacts Gemini or
Ollama, or modifies the user's `data`, `output` or `logs` folders.
"""

from __future__ import annotations

import asyncio
import zipfile
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import come_ai_web
import pytest
from fastapi.testclient import TestClient
from google.genai import types
from openpyxl import load_workbook

from come_ai_web import create_app
from workspace_core import (
    AgentService,
    AppConfig,
    LocalTools,
    RequestBudget,
    TransientProviderError,
    UserFacingError,
    Workspace,
    error_status_code,
    safe_error,
    should_try_next_model,
    retryable,
    validate_local_ollama_url,
)


def make_workspace(tmp_path: Path) -> tuple[AppConfig, Workspace, LocalTools]:
    config = AppConfig.load(tmp_path)
    workspace = Workspace(config)
    return config, workspace, LocalTools(workspace)


def add_csv(config: AppConfig, name: str = "ventes.csv") -> Path:
    path = config.data_dir / name
    path.write_text(
        "mois;revenus;couts\nJanvier;100;60\nFévrier;130;80\nMars;110;72\n",
        encoding="utf-8",
    )
    return path


def test_local_csv_analysis_keeps_source_intact(tmp_path: Path) -> None:
    config, workspace, tools = make_workspace(tmp_path)
    source = add_csv(config)
    before = source.read_bytes()
    workspace.refresh()
    file_id = workspace.file_id_by_name(source.name)
    assert file_id

    inspected = tools.inspect_file(file_id)
    analysis = tools.analyze_table(file_id)
    report = tools.create_analysis_workbook(file_id)

    assert inspected["columns"] == 3
    assert analysis["numeric_statistics"]["revenus"]["sum"] == 340.0
    assert (config.output_dir / report["output_file"]).is_file()
    assert source.read_bytes() == before


def test_report_names_are_unique_and_formula_text_is_neutralized(tmp_path: Path) -> None:
    config, workspace, tools = make_workspace(tmp_path)
    source = config.data_dir / "formule.csv"
    source.write_text("=danger;valeur\ntexte;2\n", encoding="utf-8")
    workspace.refresh()
    file_id = workspace.file_id_by_name(source.name)
    assert file_id

    first = tools.create_analysis_workbook(file_id)
    second = tools.create_analysis_workbook(file_id)
    assert first["output_file"] != second["output_file"]
    workbook = load_workbook(config.output_dir / first["output_file"], data_only=False)
    summary = workbook["Résumé"]
    # A column name starting with = is stored as literal text, not a formula.
    assert any(
        cell.value == "'=danger"
        for row in summary.iter_rows()
        for cell in row
    )


def test_agent_denies_writes_without_server_confirmation(tmp_path: Path) -> None:
    config, workspace, _ = make_workspace(tmp_path)
    source = add_csv(config)
    workspace.refresh()
    file_id = workspace.file_id_by_name(source.name)
    assert file_id
    agent = AgentService(config, workspace)

    with pytest.raises(UserFacingError, match="confirmation"):
        agent._invoke_tool("create_analysis_workbook", {"file_id": file_id}, allow_writes=False)

    created = agent._invoke_tool("create_analysis_workbook", {"file_id": file_id}, allow_writes=True)
    assert created["created"] is True


def test_docx_text_and_document_search_work_offline(tmp_path: Path) -> None:
    config, workspace, tools = make_workspace(tmp_path)
    document = config.data_dir / "contrat.docx"
    document_xml = """<?xml version="1.0" encoding="UTF-8"?>
    <w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">
      <w:body>
        <w:p><w:r><w:t>Contrat de service</w:t></w:r></w:p>
        <w:tbl><w:tr><w:tc><w:p><w:r><w:t>Échéance : 30 juin</w:t></w:r></w:p></w:tc></w:tr></w:tbl>
      </w:body>
    </w:document>"""
    with zipfile.ZipFile(document, "w") as archive:
        archive.writestr("word/document.xml", document_xml)
    workspace.refresh()
    file_id = workspace.file_id_by_name(document.name)
    assert file_id

    inspection = tools.inspect_file(file_id)
    found = tools.search_documents("échéance", file_id)

    assert inspection["kind"] == "document"
    assert "Contrat de service" in inspection["excerpt"]
    assert found["count"] == 1
    assert "30 juin" in found["hits"][0]["excerpt"]


def test_pptx_slide_text_is_read_locally_without_an_extra_dependency(tmp_path: Path) -> None:
    config, workspace, tools = make_workspace(tmp_path)
    presentation = config.data_dir / "cours-finance.pptx"
    slide_xml = """<?xml version="1.0" encoding="UTF-8"?>
    <p:sld xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main"
           xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main">
      <p:cSld><p:spTree><p:sp><p:txBody><a:p><a:r><a:t>Delta et gamma</a:t></a:r></a:p>
      <a:p><a:r><a:t>Le delta mesure la sensibilité au sous-jacent.</a:t></a:r></a:p>
      </p:txBody></p:sp></p:spTree></p:cSld>
    </p:sld>"""
    with zipfile.ZipFile(presentation, "w") as archive:
        archive.writestr("ppt/slides/slide1.xml", slide_xml)
    workspace.refresh()
    file_id = workspace.file_id_by_name(presentation.name)
    assert file_id

    inspection = tools.inspect_file(file_id)

    assert inspection["kind"] == "document"
    assert "[Diapositive 1]" in inspection["excerpt"]
    assert "Delta et gamma" in inspection["excerpt"]


def test_assignment_outline_surfaces_sections_and_questions_without_a_model(tmp_path: Path) -> None:
    config, workspace, tools = make_workspace(tmp_path)
    source = config.data_dir / "devoir.txt"
    source.write_text(
        "TD Convertible Bond\nPart 1 - Greeks\nQ1.1 Compute delta and compare it with the pricer.\n"
        "Q1.2 Why is gamma highest near the money?\nPart 2 - Hedging\n",
        encoding="utf-8",
    )
    workspace.refresh()
    file_id = workspace.file_id_by_name(source.name)
    assert file_id

    outline = tools.inspect_file(file_id)["outline"]

    assert outline["title"] == "TD Convertible Bond"
    assert outline["sections"] == ["Part 1 - Greeks", "Part 2 - Hedging"]
    assert outline["task_count"] == 2
    assert outline["tasks"][1].startswith("Q1.2")


def test_ollama_fallback_uses_the_same_controlled_tools(tmp_path: Path) -> None:
    config, workspace, _ = make_workspace(tmp_path)
    config = replace(config, ollama_model="fake-local-model", retry_attempts=1)
    add_csv(config)
    workspace.refresh()
    agent = AgentService(config, workspace)
    responses = [
        {
            "message": {
                "content": "",
                "tool_calls": [{"function": {"name": "list_workspace_files", "arguments": {}}}],
            }
        },
        {"message": {"content": "Les fichiers ont été listés.", "tool_calls": []}},
    ]
    captured_messages: list[list[dict[str, object]]] = []

    def fake_ollama_chat(
        messages: list[dict[str, object]],
        _: list[dict[str, object]],
        *,
        timeout_seconds: float | None = None,
    ) -> dict[str, object]:
        assert timeout_seconds is not None
        captured_messages.append(messages.copy())
        return responses.pop(0)

    agent._ollama_chat = fake_ollama_chat  # type: ignore[method-assign]
    result = agent._ask_ollama("Liste mes fichiers", "test", allow_writes=False)

    assert result["provider"] == "Ollama local · fake-local-model"
    assert result["tool_events"] == ["list_workspace_files"]
    assert any(message.get("role") == "tool" for message in captured_messages[-1])


def test_provider_fallback_shares_one_budget(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    config, workspace, _ = make_workspace(tmp_path)
    config = replace(config, ollama_model="fake-local-model")
    agent = AgentService(config, workspace)
    budgets: list[RequestBudget | None] = []

    # No key is needed: this only exercises routing, never a provider client.
    monkeypatch.setattr(AppConfig, "has_gemini_key", property(lambda _: True))

    def fake_gemini(
        _: str,
        *,
        allow_writes: bool,
        allow_cloud_context: bool = False,
        local_context_present: bool = False,
        budget: RequestBudget | None = None,
    ) -> dict[str, object]:
        assert allow_writes is False
        budgets.append(budget)
        raise RuntimeError("503 unavailable")

    def fake_ollama(
        _: str,
        __: str,
        *,
        allow_writes: bool,
        budget: RequestBudget | None = None,
    ) -> dict[str, object]:
        assert allow_writes is False
        budgets.append(budget)
        return {"answer": "secours local", "tool_events": [], "provider": "Ollama"}

    agent._ask_gemini = fake_gemini  # type: ignore[method-assign]
    agent._ask_ollama = fake_ollama  # type: ignore[method-assign]
    result = agent.ask("Réponds localement")

    assert result["provider"] == "Ollama"
    assert len(budgets) == 2
    assert budgets[0] is budgets[1]
    assert isinstance(budgets[0], RequestBudget)


def test_manual_gemini_tool_loop_uses_user_role_and_preserves_call_id(tmp_path: Path) -> None:
    config, workspace, _ = make_workspace(tmp_path)
    config = replace(config, retry_attempts=1)
    agent = AgentService(config, workspace)
    call = types.FunctionCall(name="list_workspace_files", args={}, id="call-abc")
    model_content = types.Content(
        role="model",
        parts=[types.Part.from_function_call(name="list_workspace_files", args={})],
    )
    first_response = SimpleNamespace(
        function_calls=[call],
        candidates=[SimpleNamespace(content=model_content)],
        text=None,
    )
    second_response = SimpleNamespace(function_calls=[], candidates=[], text="Analyse terminée.")

    class FakeModels:
        def __init__(self) -> None:
            self.calls: list[list[types.Content]] = []
            self.responses = [first_response, second_response]

        def generate_content(self, **kwargs: object) -> object:
            self.calls.append(kwargs["contents"])  # type: ignore[arg-type]
            return self.responses.pop(0)

    client = SimpleNamespace(models=FakeModels())
    history = [types.Content(role="user", parts=[types.Part.from_text(text="liste les fichiers")])]
    result = agent._run_tool_loop(
        client,
        types,
        "fake-model",
        history,
        types.GenerateContentConfig(http_options=types.HttpOptions(timeout=30_000)),
        RequestBudget(max_requests=3),
        allow_writes=False,
        allow_cloud_context=True,
    )

    assert result["answer"] == "Analyse terminée."
    second_turn_history = client.models.calls[1]
    assert second_turn_history[-1].role == "user"
    function_response = second_turn_history[-1].parts[0].function_response
    assert function_response is not None
    assert function_response.id == "call-abc"
    assert function_response.name == "list_workspace_files"


def test_error_classification_masks_secret_and_stops_quota_rotation() -> None:
    error = SimpleNamespace(code=429)
    assert error_status_code(error) == 429
    assert should_try_next_model(error) is False
    assert "[clé masquée]" in safe_error(Exception("api_key=AIzaVeryFakeSecret"))
    assert "AIzaVeryFakeSecret" not in safe_error(Exception("api_key=AIzaVeryFakeSecret"))
    masked_path = safe_error(Exception("Impossible de lire /Users/come/AI-Excel-Agent/data/budget.csv"))
    assert "/Users/come" not in masked_path
    assert "[chemin local masqué]" in masked_path
    assert retryable(TransientProviderError("Ollama local indisponible"))


def test_agent_tool_result_is_redacted_before_gemini_followup(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    config, workspace, _ = make_workspace(tmp_path)
    agent = AgentService(config, workspace)
    secrets = ["AIza" + "A" * 32, "sk-or-v1-" + "B" * 48,
               "Authorization: Bearer " + "C" * 32]
    monkeypatch.setattr(agent, "_invoke_tool", lambda *args, **kwargs: {
        "excerpt": " ".join(secrets), "nested": {"password": "synthetic-private-password"}
    })
    call = types.FunctionCall(name="list_workspace_files", args={}, id="call-secret")
    first = SimpleNamespace(function_calls=[call], candidates=[SimpleNamespace(content=types.Content(role="model", parts=[]))], text=None)
    second = SimpleNamespace(function_calls=[], candidates=[], text="Faits fictifs masqués.")
    class FakeModels:
        def __init__(self):
            self.calls = []
            self.responses = [first, second]
        def generate_content(self, **kwargs):
            self.calls.append(kwargs["contents"])
            return self.responses.pop(0)
    client = SimpleNamespace(models=FakeModels())
    history = [types.Content(role="user", parts=[types.Part.from_text(text="Inspecte le fichier synthétique")])]
    result = agent._run_tool_loop(
        client, types, "fictional-model", history,
        types.GenerateContentConfig(http_options=types.HttpOptions(timeout=30_000)),
        RequestBudget(max_requests=3), allow_writes=False, allow_cloud_context=True,
    )
    assert result["answer"] == "Faits fictifs masqués."
    function_response = client.models.calls[1][-1].parts[0].function_response
    serialized = str(function_response.response)
    for secret in secrets:
        assert secret not in serialized
    assert "synthetic-private-password" not in serialized
    assert "[secret redacted]" in serialized


def test_agent_tool_request_without_consent_refuses_before_running_tool(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    config, workspace, _ = make_workspace(tmp_path)
    agent = AgentService(config, workspace)
    invoked = []
    monkeypatch.setattr(agent, "_invoke_tool", lambda *args, **kwargs: invoked.append(True))
    call = types.FunctionCall(name="list_workspace_files", args={})
    response = SimpleNamespace(function_calls=[call], candidates=[SimpleNamespace(content=types.Content(role="model", parts=[]))], text=None)
    class FakeModels:
        def __init__(self):
            self.calls = 0
        def generate_content(self, **kwargs):
            self.calls += 1
            return response
    client = SimpleNamespace(models=FakeModels())
    with pytest.raises(UserFacingError, match="données locales"):
        agent._run_tool_loop(
            client, types, "fictional-model",
            [types.Content(role="user", parts=[types.Part.from_text(text="Lis le fichier")])],
            types.GenerateContentConfig(http_options=types.HttpOptions(timeout=30_000)),
            RequestBudget(max_requests=3), allow_writes=False,
        )
    assert client.models.calls == 1
    assert invoked == []


def test_ollama_url_must_stay_on_loopback(tmp_path: Path) -> None:
    (tmp_path / ".env").write_text(
        "OLLAMA_BASE_URL=http://example.invalid:11434/api/chat\n",
        encoding="utf-8",
    )
    with pytest.raises(UserFacingError, match="Ollama local"):
        AppConfig.load(tmp_path)
    assert validate_local_ollama_url("http://[::1]:11434/api/chat").startswith("http://[::1]")


def test_gemini_rejects_more_than_four_tool_calls(tmp_path: Path) -> None:
    config, workspace, _ = make_workspace(tmp_path)
    config = replace(config, retry_attempts=1)
    agent = AgentService(config, workspace)
    calls = [types.FunctionCall(name="list_workspace_files", args={}) for _ in range(5)]
    response = SimpleNamespace(function_calls=calls, candidates=[], text=None)

    class FakeModels:
        def generate_content(self, **_: object) -> object:
            return response

    client = SimpleNamespace(models=FakeModels())
    history = [types.Content(role="user", parts=[types.Part.from_text(text="liste les fichiers")])]
    with pytest.raises(UserFacingError, match="trop d’outils simultanément"):
        agent._run_tool_loop(
            client,
            types,
            "fake-model",
            history,
            types.GenerateContentConfig(http_options=types.HttpOptions(timeout=30_000)),
            RequestBudget(max_requests=3),
            allow_writes=False,
        )


def test_health_reports_only_key_presence_not_key_value(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    fake_key = "AIzaTestOnlyNotARealKey"
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    (tmp_path / ".env").write_text(f"GEMINI_API_KEY={fake_key}\n", encoding="utf-8")
    client = TestClient(create_app(tmp_path))

    response = client.get("/api/health")

    assert response.status_code == 200
    assert response.json()["providers"]["gemini"]["configured"] is True
    assert fake_key not in response.text


def test_web_rejects_oversized_upload_body_before_parsing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(come_ai_web, "MAX_UPLOAD_BATCH_BYTES", 64)
    client = TestClient(create_app(tmp_path))

    response = client.post(
        "/api/files/upload",
        files=[("files", ("budget.csv", b"mois;budget\nJanvier;100\n", "text/csv"))],
    )

    assert response.status_code == 413
    assert "100 Mo" in response.json()["detail"]
    assert list((tmp_path / "data").iterdir()) == []


def test_web_rejects_chunked_oversized_upload_while_receiving(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(come_ai_web, "MAX_UPLOAD_BATCH_BYTES", 64)
    app = create_app(tmp_path)
    boundary = b"come-ai-boundary"
    body = (
        b"--" + boundary + b"\r\n"
        b'Content-Disposition: form-data; name="files"; filename="budget.csv"\r\n'
        b"Content-Type: text/csv\r\n\r\n"
        + b"x" * 128
        + b"\r\n--" + boundary + b"--\r\n"
    )
    pending = [
        {"type": "http.request", "body": body[:16], "more_body": True},
        {"type": "http.request", "body": body[16:], "more_body": False},
    ]
    sent: list[dict[str, object]] = []
    scope: dict[str, object] = {
        "type": "http",
        "asgi": {"version": "3.0", "spec_version": "2.3"},
        "http_version": "1.1",
        "method": "POST",
        "scheme": "http",
        "path": "/api/files/upload",
        "raw_path": b"/api/files/upload",
        "query_string": b"",
        "root_path": "",
        "headers": [
            (b"host", b"testserver"),
            (b"content-type", b"multipart/form-data; boundary=" + boundary),
            (b"transfer-encoding", b"chunked"),
        ],
        "client": ("127.0.0.1", 1234),
        "server": ("testserver", 80),
    }

    async def receive() -> dict[str, object]:
        return pending.pop(0) if pending else {"type": "http.disconnect"}

    async def send(message: dict[str, object]) -> None:
        sent.append(message)

    asyncio.run(app(scope, receive, send))  # type: ignore[arg-type]

    start = next(message for message in sent if message["type"] == "http.response.start")
    assert start["status"] == 413
    assert list((tmp_path / "data").iterdir()) == []


class FakeAgent:
    def __init__(self) -> None:
        self.messages: list[tuple[str, bool]] = []

    def provider_status(self) -> dict[str, object]:
        return {
            "gemini": {"configured": False, "primary_model": "gemini-test", "fallback_models": []},
            "ollama": {"configured": False, "model": None},
            "request_timeout_seconds": 60,
            "retry_attempts": 1,
        }

    def ask(self, message: str, *, allow_writes: bool, allow_cloud_context: bool = False,
            local_context_present: bool = False) -> dict[str, object]:
        self.messages.append((message, allow_writes))
        return {"answer": "Réponse simulée", "tool_events": ["inspect_file"], "provider": "Faux modèle"}


def test_local_web_api_upload_actions_and_chat_are_isolated(tmp_path: Path) -> None:
    fake_agent = FakeAgent()
    app = create_app(tmp_path, agent_override=fake_agent)
    client = TestClient(app)

    homepage = client.get("/")
    assert homepage.status_code == 200
    assert "Côme AI" in homepage.text
    assert "content-security-policy" in homepage.headers

    uploaded = client.post(
        "/api/files/upload",
        files=[("files", ("budget.csv", b"mois;budget\nJanvier;100\n", "text/csv"))],
    )
    assert uploaded.status_code == 200
    result = uploaded.json()["results"][0]
    assert result["status"] == "importé"
    file_id = result["file_id"]

    inspection = client.post("/api/actions/inspect", json={"file_id": file_id})
    assert inspection.status_code == 200
    assert inspection.json()["kind"] == "table"

    report = client.post("/api/actions/report", json={"file_id": file_id})
    assert report.status_code == 200
    output_name = report.json()["output_file"]
    download = client.get(f"/api/outputs/{output_name}")
    assert download.status_code == 200
    assert download.headers["content-type"].startswith("application/vnd.openxmlformats")

    chat = client.post(
        "/api/chat",
        json={"message": "Analyse le fichier sélectionné", "selected_file_ids": [file_id], "allow_write": False,
              "allow_cloud_context": True},
    )
    assert chat.status_code == 200
    assert chat.json()["answer"] == "Réponse simulée"
    assert fake_agent.messages[-1][1] is False
    assert "budget.csv" in fake_agent.messages[-1][0]
    assert "Janvier;100" not in fake_agent.messages[-1][0]

    # Clients may normalize ../ before the request reaches FastAPI; either a
    # route-level 404 or a controlled 400 is a safe outcome.
    blocked_path = client.get("/api/outputs/../secret.xlsx")
    assert blocked_path.status_code in {400, 404}

