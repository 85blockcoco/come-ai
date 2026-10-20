"""Synthetic hybrid-chat tests: no real key, provider or personal file is used."""

from __future__ import annotations

import json
import socket
from urllib.error import HTTPError
from urllib.request import ProxyHandler

import pytest

import hybrid_chat
from hybrid_chat import HybridChatService, calculate_expression, hybrid_json_transport
from devkit.evolution_providers import ProviderUnavailable, _NoRedirect
from devkit.model_catalog import ModelCatalogError
from free_ai_router import classify_task
from personal_memory import PersonalMemoryStore
from workspace_core import AppConfig, LocalTools, UserFacingError, Workspace


def catalogue_record(model_id):
    return {"model_id": model_id, "price_status": "zero_confirmed",
            "price_evidence": "synthetic_explicit_zero_price", "capabilities": ["code", "text"]}


class FakeCatalog:
    def __init__(self, model="gemini-3.8-flash"):
        self.model = model
        self.calls = []

    def snapshot(self):
        self.calls.append("snapshot")
        return {"status": "synthetic", "providers": {}, "network_used": False}

    def eligible(self, provider, capability="text"):
        self.calls.append(("eligible", provider, capability))
        return [catalogue_record(self.model)]

    def refresh(self, provider, **kwargs):
        self.calls.append(("refresh", provider))

    def choose_model(self, provider, requested="auto", exclude_models=()):
        self.calls.append(("choose", provider, requested, exclude_models))
        return self.model if requested == "auto" else requested


def make_service(tmp_path, transport=None, *, catalog=None, credential_loader=None, memory=None):
    workspace = Workspace(AppConfig.load(tmp_path))
    service = HybridChatService(tmp_path, workspace, LocalTools(workspace), memory,
                                transport=transport or local_transport, catalog=catalog,
                                credential_loader=credential_loader)
    return service


def local_transport(method, url, headers, payload, timeout):
    assert url.startswith("http://127.0.0.1:11434/")
    assert not headers
    if url.endswith("/api/show"):
        return {"details": {"format": "gguf"}}
    assert url.endswith("/api/chat")
    return {"done": True, "done_reason": "stop", "message": {"content": "Bonjour, voici une réponse locale."},
            "prompt_eval_count": 20, "eval_count": 10, "total_duration": 40_000_000}


def no_credentials(*args):
    raise AssertionError("No cloud credentials should be loaded")


def test_offline_really_selects_local_and_records_only_measured_metadata(tmp_path):
    calls = []
    catalog = FakeCatalog()

    def transport(*args):
        calls.append(args)
        return local_transport(*args)

    service = make_service(tmp_path, transport, catalog=catalog, credential_loader=no_credentials)
    result = service.ask("Bonjour", mode="offline")
    assert result["provider"] == "ollama"
    assert result["model"] == "qwen3.5:2b-q4_K_M"
    assert result["remote_model_used"] is False
    assert result["usage"]["input_tokens"] == 20
    assert result["usage"]["output_tokens"] == 10
    assert result["usage"]["total_tokens"] is None
    assert catalog.calls == []
    assert len(calls) == 2
    chat = calls[1]
    assert chat[4] == 180
    assert chat[3]["think"] is False
    assert chat[3]["options"] == {"temperature": 0.15, "num_ctx": 4096, "num_predict": 256, "num_thread": 4}
    assert "tools" not in chat[3]
    event = service.ledger.list_events()[0].to_dict()
    assert event["input_tokens"] == 20
    assert "Bonjour" not in json.dumps(event)
    assert event["cost_state"] == "unknown"


def test_offline_ignores_cloud_keys_even_when_present(tmp_path, monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "fictional-not-a-real-secret")
    monkeypatch.setenv("OPENROUTER_API_KEY", "fictional-not-a-real-secret")
    monkeypatch.setenv("COME_AI_GEMINI_FREE_PROJECT_CONFIRMED", "true")
    catalog = FakeCatalog()
    service = make_service(tmp_path, catalog=catalog, credential_loader=no_credentials)
    result = service.ask("Réponds en anglais", mode="offline")
    assert result["remote_model_used"] is False
    assert catalog.calls == []


def test_offline_cloud_manual_selection_refused_before_any_work(tmp_path):
    def forbidden(*args):
        raise AssertionError("No transport is allowed")
    service = make_service(tmp_path, forbidden, catalog=FakeCatalog(), credential_loader=no_credentials)
    with pytest.raises(UserFacingError, match="Hors ligne"):
        service.ask("Bonjour", provider="gemini", mode="offline")
    assert not service.ledger.list_events()


@pytest.mark.parametrize("metadata", [
    {"details": {"format": "gguf"}, "remote_host": "external.invalid"},
    {"details": {"format": "gguf"}, "remote_model": "cloud-model"},
    {"details": {"format": "other"}}, {},
])
def test_cloud_ollama_aliases_refused_before_generation(tmp_path, metadata):
    calls = []
    def transport(method, url, headers, payload, timeout):
        calls.append(url)
        assert url.endswith("/api/show")
        return metadata
    service = make_service(tmp_path, transport)
    with pytest.raises(UserFacingError, match="GGUF"):
        service.ask("Bonjour")
    assert len(calls) == 1
    assert not service.ledger.list_events()


@pytest.mark.parametrize("model", ["qwen-cloud", "vendor/model", "https://external.invalid"])
def test_cloud_or_url_local_model_name_refused(tmp_path, model):
    def forbidden(*args):
        raise AssertionError("No transport is allowed")
    service = make_service(tmp_path, forbidden)
    with pytest.raises(UserFacingError):
        service.ask("Bonjour", model=model)


def test_local_file_and_memory_context_uses_opaque_ids_and_sources(tmp_path):
    memory = PersonalMemoryStore(tmp_path / "memory_data")
    memory.import_text("La VAN actualise les flux futurs.", title="Cours synthétique", category="study")
    calls = []
    def transport(*args):
        calls.append(args)
        return local_transport(*args)
    service = make_service(tmp_path, transport, memory=memory)
    document = tmp_path / "data" / "cours.md"
    document.write_text("La diversification réduit les risques spécifiques.", encoding="utf-8")
    service.workspace.refresh()
    file_id = service.workspace.file_id_by_name("cours.md")
    result = service.ask('Résume le document et cherche "VAN" dans ma mémoire.', selected_file_ids=[file_id])
    assert [event["tool"] for event in result["tool_events"]] == ["inspect_file", "search_memory"]
    assert len(result["citations"]) == 2
    text = json.dumps(calls[-1][3], ensure_ascii=False)
    assert "diversification" in text
    assert "actualise" in text
    assert str(tmp_path) not in text
    assert document.read_text() == "La diversification réduit les risques spécifiques."


@pytest.mark.parametrize("provider", ["gemini", "openrouter"])
def test_local_context_cloud_is_refused_before_any_network_without_request_consent(tmp_path, monkeypatch, provider):
    calls = []
    def transport(*args):
        calls.append(args)
        raise AssertionError("No catalogue or generation request is allowed without consent")
    service = make_service(tmp_path, transport, catalog=FakeCatalog(),
                          credential_loader=lambda *args: "fictional-key-only")
    source = tmp_path / "data" / "private-synthetic.md"
    source.write_text("Synthetic local fact: portfolio note.", encoding="utf-8")
    service.workspace.refresh()
    file_id = service.workspace.file_id_by_name(source.name)
    socket_attempts = []
    def blocked(*args, **kwargs):
        socket_attempts.append((args, kwargs))
        raise AssertionError("Socket access must be blocked")
    monkeypatch.setattr(socket, "create_connection", blocked)
    monkeypatch.setattr(socket, "getaddrinfo", blocked)
    for method in ("connect", "connect_ex", "sendto", "sendmsg"):
        if hasattr(socket.socket, method):
            monkeypatch.setattr(socket.socket, method, blocked)
    with pytest.raises(UserFacingError, match="contexte local"):
        service.ask("Résume le document", selected_file_ids=[file_id], mode="performance", provider=provider)
    assert calls == []
    assert socket_attempts == []


@pytest.mark.parametrize("provider", ["gemini", "openrouter"])
def test_consented_cloud_receives_redacted_local_context_and_permission_is_per_request(tmp_path, provider):
    gemini_secret = "AIza" + "F" * 36
    router_secret = "sk-or-v1-" + "R" * 48
    bearer_secret = "BearerToken-" + "Z" * 32
    calls = []
    def transport(method, url, headers, payload, timeout):
        calls.append((method, url, payload))
        if url.endswith("/models"):
            return {"data": [{"id": "synthetic/model:free", "pricing": {
                "prompt": "0", "completion": "0", "request": "0", "image": "0"}}]}
        if "generativelanguage.googleapis.com" in url:
            return {"candidates": [{"finishReason": "STOP", "content": {"parts": [{"text": "Synthèse fictive."}]}}],
                    "usageMetadata": {"promptTokenCount": 20, "candidatesTokenCount": 4, "totalTokenCount": 24}}
        return {"model": "synthetic/model:free", "choices": [{"finish_reason": "stop", "message": {"content": "Synthèse fictive."}}],
                "usage": {"total_tokens": 24}}

    model = "gemini-3.8-flash" if provider == "gemini" else "synthetic/model:free"
    (tmp_path / ".env").write_text("COME_AI_GEMINI_FREE_PROJECT_CONFIRMED=true\n", encoding="utf-8")
    service = make_service(tmp_path, transport, catalog=FakeCatalog(model),
                           credential_loader=lambda *args: "fictional-key-only")
    source = tmp_path / "data" / "secrets-synthetic.md"
    source.write_text(
        f"api_key={gemini_secret}\nopenrouter_key={router_secret}\nAuthorization: Bearer {bearer_secret}\npassword=synthetic-password-value",
        encoding="utf-8",
    )
    service.workspace.refresh()
    file_id = service.workspace.file_id_by_name(source.name)
    result = service.ask("Résume ce document", selected_file_ids=[file_id], mode="performance",
                         provider=provider, allow_cloud_context=True)
    assert result["remote_model_used"] is True
    sent = json.dumps([call[2] for call in calls], ensure_ascii=False)
    assert gemini_secret not in sent
    assert router_secret not in sent
    assert bearer_secret not in sent
    assert "synthetic-password-value" not in sent
    assert "secret" in sent.casefold() and ("masqué" in sent.casefold() or "redacted" in sent.casefold())

    # A second HTTP action has its own default-denied permission; the previous
    # request does not authorize it or cause another provider attempt.
    prior_calls = len(calls)
    with pytest.raises(UserFacingError, match="contexte local"):
        service.ask("Résume encore", selected_file_ids=[file_id], mode="performance", provider=provider)
    assert len(calls) == prior_calls


def test_ollama_can_receive_redacted_local_context_without_cloud_consent(tmp_path):
    secret = "sk-or-v1-" + "L" * 42
    calls = []
    def transport(method, url, headers, payload, timeout):
        calls.append((url, payload))
        return local_transport(method, url, headers, payload, timeout)
    service = make_service(tmp_path, transport, catalog=FakeCatalog(), credential_loader=no_credentials)
    source = tmp_path / "data" / "local-synthetic.md"
    source.write_text(f"api_key={secret}", encoding="utf-8")
    service.workspace.refresh()
    file_id = service.workspace.file_id_by_name(source.name)
    result = service.ask("Résume le document", selected_file_ids=[file_id], mode="offline", provider="ollama")
    assert result["provider"] == "ollama"
    sent = json.dumps([payload for _, payload in calls], ensure_ascii=False)
    assert secret not in sent
    assert "secret" in sent.casefold() and ("masqué" in sent.casefold() or "redacted" in sent.casefold())


def test_arbitrary_file_path_is_not_a_workspace_id(tmp_path):
    service = make_service(tmp_path)
    with pytest.raises(UserFacingError):
        service.ask("Résume", selected_file_ids=[str(tmp_path / "other.md")])


def test_excel_report_requires_server_confirmation(tmp_path):
    service = make_service(tmp_path)
    source = tmp_path / "data" / "budget.csv"
    source.write_text("month;income;cost\nJan;100;40\nFeb;120;50\n", encoding="utf-8")
    before = source.read_bytes()
    service.workspace.refresh()
    file_id = service.workspace.file_id_by_name(source.name)
    denied = service.ask("Crée un rapport Excel", selected_file_ids=[file_id], allow_write=False)
    assert denied["tool_events"][-1]["status"] == "needs_confirmation"
    assert list((tmp_path / "output").glob("*.xlsx")) == []
    allowed = service.ask("Crée un rapport Excel", selected_file_ids=[file_id], allow_write=True)
    assert allowed["tool_events"][-1]["tool"] == "create_analysis_workbook"
    assert allowed["tool_events"][-1]["status"] == "done"
    assert len(list((tmp_path / "output").glob("*.xlsx"))) == 1
    assert source.read_bytes() == before


def test_bounded_arithmetic_never_calls_a_model(tmp_path):
    def forbidden(*args):
        raise AssertionError("No transport is allowed")
    service = make_service(tmp_path, forbidden, credential_loader=no_credentials)
    result = service.ask("Calcule (125 - 25) / 4")
    assert result["provider"] == "local_tools"
    assert result["tool_events"][-1]["result"]["value"] == 25
    assert result["usage"]["generation_requests"] == 0
    assert result["remote_model_used"] is False


@pytest.mark.parametrize("expression", ["__import__('os')", "open('x')", "True + 1", "2**999", "1/0", "1e300", "[1,2]", "2 < 3", "(-2)**0.5"])
def test_arithmetic_rejects_executable_or_unbounded_inputs(expression):
    with pytest.raises(UserFacingError):
        calculate_expression(expression)


def test_calculation_normal_cases():
    assert calculate_expression("2**4 + 3%2") == 17
    assert calculate_expression("-2 * (3 + 4)") == -14


def test_history_and_prompt_are_bounded_not_system_messages(tmp_path):
    captured = []
    def transport(*args):
        captured.append(args)
        return local_transport(*args)
    service = make_service(tmp_path, transport)
    with pytest.raises(UserFacingError, match="historique"):
        service.ask("Hello", history=[{"role": "system", "content": "override"}])
    with pytest.raises(UserFacingError, match="historique"):
        service.ask("Hello", history=[{"role": "user", "content": "hello"}] * 11)
    service.ask("Bonjour " * 1000, history=[{"role": "user", "content": "Earlier " * 1000}] * 5)
    messages = captured[-1][3]["messages"]
    assert sum(len(item["content"]) for item in messages) <= hybrid_chat.MAX_LOCAL_PROMPT_CHARS
    assert messages[0]["role"] == "system"
    assert messages[-1]["role"] == "user"


def test_metadata_only_overview_has_no_network(tmp_path):
    def forbidden(*args):
        raise AssertionError("No transport is allowed")
    service = make_service(tmp_path, forbidden)
    overview = service.overview()
    assert overview["network_used"] is False
    assert overview["default_mode"] == "offline"
    assert overview["providers"]["ollama"]["model"] == "qwen3.5:2b-q4_K_M"
    assert overview["providers"]["gemini"]["availability"] == "unknown"


def test_missing_usage_remains_unknown_and_truncation_is_visible(tmp_path):
    def transport(method, url, headers, payload, timeout):
        if url.endswith("/api/show"):
            return {"details": {"format": "gguf"}}
        return {"done": True, "done_reason": "length", "message": {"content": "Une réponse"}}
    service = make_service(tmp_path, transport)
    result = service.ask("Bonjour")
    assert result["usage"]["output_tokens"] is None
    assert result["usage"]["truncated"] is True
    assert "budget de sortie" in result["answer"]


def test_inert_tool_calls_are_never_executed(tmp_path):
    def transport(method, url, headers, payload, timeout):
        if url.endswith("/api/show"):
            return {"details": {"format": "gguf"}}
        return {"done": True, "message": {"tool_calls": [{"function": {"name": "run_shell", "arguments": {}}}]}}
    service = make_service(tmp_path, transport)
    with pytest.raises(UserFacingError, match="réponse finale"):
        service.ask("Bonjour")
    assert service.ledger.list_events()[0].outcome == "failed"


def test_generation_errors_are_sanitized_and_not_retried_offline(tmp_path):
    calls = []
    def transport(method, url, headers, payload, timeout):
        calls.append(url)
        if url.endswith("/api/show"):
            return {"details": {"format": "gguf"}}
        raise RuntimeError("private document text should not appear")
    service = make_service(tmp_path, transport)
    with pytest.raises(UserFacingError) as error:
        service.ask("Bonjour")
    assert "private document" not in str(error.value)
    assert len(calls) == 2
    event = service.ledger.list_events()[0].to_dict()
    assert "private document" not in json.dumps(event)
    assert event["outcome"] == "failed"


def test_gemini_free_declaration_required_before_catalogue(tmp_path):
    catalog = FakeCatalog()
    service = make_service(tmp_path, catalog=catalog)
    with pytest.raises(UserFacingError, match="gratuit"):
        service.ask("Bonjour", mode="automatic", provider="gemini")
    assert catalog.calls == []


def test_gemini_synthetic_accessible_free_model_no_paid_fallback(tmp_path):
    (tmp_path / ".env").write_text("COME_AI_GEMINI_FREE_PROJECT_CONFIRMED=true\n", encoding="utf-8")
    calls = []
    def transport(method, url, headers, payload, timeout):
        calls.append((method, url, headers, payload))
        assert url.endswith("/gemini-3.8-flash:generateContent")
        return {"candidates": [{"finishReason": "STOP", "content": {"parts": [{"text": "Réponse synthétique."}]}}],
                "usageMetadata": {"promptTokenCount": 15, "candidatesTokenCount": 7, "totalTokenCount": 22}}
    catalog = FakeCatalog()
    service = make_service(tmp_path, transport, catalog=catalog, credential_loader=lambda *args: "fictional-key-only")
    result = service.ask("Bonjour", mode="performance", provider="gemini")
    assert result["remote_model_used"] is True
    assert result["usage"]["total_tokens"] == 22
    assert len(calls) == 1
    assert catalog.calls[-1][-1] == ("gemini-2.5-flash",)
    assert "fictional-key-only" not in json.dumps(service.overview())


@pytest.mark.parametrize("pricing", [
    {"prompt": "0"},
    {"prompt": "0", "completion": "0", "request": "0", "image": "1"},
    {"prompt": "0", "completion": "0", "request": None},
    {"prompt": "0", "completion": "NaN", "request": "0"},
])
def test_openrouter_unknown_or_nonzero_prices_refuse_before_generation(tmp_path, pricing):
    calls = []
    def transport(method, url, headers, payload, timeout):
        calls.append((method, url))
        assert method == "GET"
        return {"data": [{"id": "synthetic/model:free", "pricing": pricing}]}
    service = make_service(tmp_path, transport, catalog=FakeCatalog("synthetic/model:free"), credential_loader=lambda *args: "fictional-key-only")
    with pytest.raises(UserFacingError, match="prix|Prix"):
        service.ask("Bonjour", mode="automatic", provider="openrouter")
    assert len(calls) == 1
    assert not service.ledger.list_events()


def test_openrouter_zero_cap_and_no_substitution(tmp_path):
    calls = []
    def transport(method, url, headers, payload, timeout):
        calls.append((method, url, payload))
        if method == "GET":
            return {"data": [{"id": "synthetic/model:free", "pricing": {"prompt": "0", "completion": "0", "request": "0"}}]}
        assert payload["provider"]["allow_fallbacks"] is False
        assert all(value == 0 for value in payload["provider"]["max_price"].values())
        return {"model": "synthetic/model:free", "choices": [{"finish_reason": "stop", "message": {"content": "Bonjour."}}], "usage": {"total_tokens": 11}}
    service = make_service(tmp_path, transport, catalog=FakeCatalog("synthetic/model:free"), credential_loader=lambda *args: "fictional-key-only")
    result = service.ask("Bonjour", mode="performance", provider="openrouter")
    assert result["provider"] == "openrouter"
    assert result["usage"]["total_tokens"] == 11
    assert len(calls) == 2


def test_actual_loopback_transport_disables_proxy_and_redirect(monkeypatch):
    captured = []
    class Response:
        def read(self, maximum):
            return b'{"done":true}'
        def __enter__(self):
            return self
        def __exit__(self, *args):
            return None
    class Opener:
        def open(self, request, timeout):
            captured.append((request, timeout))
            return Response()
    def opener(*handlers):
        assert any(isinstance(handler, ProxyHandler) and handler.proxies == {} for handler in handlers)
        assert any(isinstance(handler, _NoRedirect) for handler in handlers)
        return Opener()
    monkeypatch.setattr(hybrid_chat, "build_opener", opener)
    result = hybrid_json_transport("POST", "http://127.0.0.1:11434/api/chat", {}, {"message": "synthetic"}, 180)
    assert result == {"done": True}
    assert captured[0][1] == 180


@pytest.mark.parametrize("url", ["http://external.invalid:11434/api/chat", "http://127.0.0.1:11434/private", "http://127.0.0.1:11434/api/chat?url=bad", "http://" + "user" + ":" + "pass" + "@" + "127.0.0.1:11434/api/chat"])
def test_local_transport_refuses_nonloopback_or_modified_endpoints(url):
    with pytest.raises(ProviderUnavailable):
        hybrid_json_transport("POST", url, {}, {}, 1)


def test_local_transport_redirect_response_is_refused_without_body(monkeypatch):
    class Opener:
        def open(self, request, timeout):
            raise HTTPError(request.full_url, 302, "private secret body", {}, None)
    monkeypatch.setattr(hybrid_chat, "build_opener", lambda *args: Opener())
    with pytest.raises(ProviderUnavailable, match="redirection"):
        hybrid_json_transport("POST", "http://127.0.0.1:11434/api/chat", {}, {}, 1)


def test_legacy_ollama_chat_url_is_normalized_and_remote_configuration_refused(tmp_path, monkeypatch):
    monkeypatch.setenv("OLLAMA_BASE_URL", "http://localhost:11434/api/chat")
    service = make_service(tmp_path)
    assert service.ask("Bonjour")["provider"] == "ollama"
    monkeypatch.setenv("OLLAMA_BASE_URL", "https://external.invalid")
    with pytest.raises(UserFacingError, match="boucle locale"):
        service.ask("Bonjour")


def test_secret_shapes_not_forwarded_or_returned(tmp_path):
    fictional = "".join(("AI", "za")) + "x" * 30
    captured = []
    def transport(*args):
        captured.append(args)
        result = local_transport(*args)
        if args[1].endswith("/api/chat"):
            result["message"]["content"] += fictional
        return result
    service = make_service(tmp_path, transport)
    result = service.ask("Ne partage pas " + fictional)
    assert fictional not in result["answer"]
    assert fictional not in json.dumps(captured[-1][3])
    assert fictional not in json.dumps(service.overview())


def test_task_creation_is_only_an_explicit_proposal_without_network(tmp_path):
    def forbidden(*args):
        raise AssertionError("No transport is allowed")
    service = make_service(tmp_path, forbidden)
    result = service.ask("Crée une tâche pour réviser demain")
    assert result["task_proposal"]["created"] is False
    assert result["task_proposal"]["requires_confirmation"] is True
    assert result["usage"]["generation_requests"] == 0
    assert "non enregistrée" in result["answer"]


def test_local_reasoning_and_summary_limitations_are_explicit(tmp_path):
    service = make_service(tmp_path)
    result = service.ask("Combien reste-t-il après le calcul de finance ?")
    assert "pas fiables" in result["answer"]
    assert len(result["limitations"]) == 2
    result = service.ask("Résume ce cours")
    assert "omettre" in result["answer"]


def test_benchmark_snapshot_exposes_only_measurements_not_outputs(tmp_path):
    directory = tmp_path / ".devkit" / "intelligence"
    directory.mkdir(parents=True)
    (directory / "benchmark-local.json").write_text(json.dumps({
        "model": "qwen3.5:2b-q4_K_M", "synthetic_only": True,
        "cases": [{"name": "summary", "passed": False, "seconds": 12, "tokens_per_second": 4,
                   "output": "Should never appear in overview", "prompt": "Should not appear either",
                   "resources": {"ollama_rss_bytes": 2_200_000_000, "ollama_cpu_percent": 345}}],
    }))
    service = make_service(tmp_path)
    overview = service.overview()
    bench = overview["local_benchmark"]
    assert bench["passed"] == 0 and bench["total"] == 1
    assert bench["sample_resources"]["rss_bytes"] == 2_200_000_000
    assert bench["comparative_quality"] == "not_established"
    assert "Should" not in json.dumps(overview)


def test_automatic_fallback_is_bounded_and_reports_actual_generation_attempts(tmp_path, monkeypatch):
    (tmp_path / ".env").write_text("COME_AI_GEMINI_FREE_PROJECT_CONFIRMED=true\n")
    monkeypatch.setattr(hybrid_chat, "_configured_key", lambda root, name: name == "GEMINI_API_KEY")
    calls = []
    def transport(method, url, headers, payload, timeout):
        calls.append(url)
        if url.endswith("/api/show"):
            return {"details": {"format": "gguf"}}
        if url.endswith("/api/chat"):
            raise ProviderUnavailable("Incident local synthétique.", "transient", http_status=503)
        return {"candidates": [{"finishReason": "STOP", "content": {"parts": [{"text": "Réponse cloud synthétique."}]}}]}
    service = make_service(tmp_path, transport, catalog=FakeCatalog(), credential_loader=lambda *args: "fictional-key-only")
    result = service.ask("Bonjour", mode="automatic")
    assert result["provider"] == "gemini"
    assert result["usage"]["generation_requests_total"] == 2
    assert "Repli vers gemini" in result["route_reason"]
    assert len(result["fallbacks"]) == 1
    assert len(service.ledger.list_events()) == 2
    assert len(calls) == 3


def test_explicit_provider_quota_error_never_rotates_models(tmp_path):
    (tmp_path / ".env").write_text("COME_AI_GEMINI_FREE_PROJECT_CONFIRMED=true\n")
    calls = []
    def transport(*args):
        calls.append(args[1])
        raise ProviderUnavailable("Quota gratuit indisponible.", "quota", http_status=429)
    service = make_service(tmp_path, transport, catalog=FakeCatalog(), credential_loader=lambda *args: "fictional-key-only")
    with pytest.raises(UserFacingError, match="Quota"):
        service.ask("Bonjour", mode="performance", provider="gemini")
    assert len(calls) == 1
    assert service.ledger.list_events()[0].error_category == "quota"


def test_local_summary_benchmark_failure_guides_cloud_preference_without_claiming_superiority(tmp_path, monkeypatch):
    directory = tmp_path / ".devkit" / "intelligence"
    directory.mkdir(parents=True)
    (directory / "benchmark-local.json").write_text(json.dumps({"model": "qwen3.5:2b-q4_K_M", "synthetic_only": True,
                                                               "cases": [{"name": "summary", "passed": False}]}))
    (tmp_path / ".env").write_text("COME_AI_GEMINI_FREE_PROJECT_CONFIRMED=true\n")
    monkeypatch.setattr(hybrid_chat, "_configured_key", lambda root, name: name == "GEMINI_API_KEY")
    def transport(method, url, headers, payload, timeout):
        assert url.startswith("https://generativelanguage.googleapis.com/")
        return {"candidates": [{"content": {"parts": [{"text": "Résumé synthétique."}]}}]}
    service = make_service(tmp_path, transport, catalog=FakeCatalog(), credential_loader=lambda *args: "fictional-key-only")
    result = service.ask("Résume un cours", mode="automatic")
    assert result["provider"] == "gemini"
    assert "sans supériorité mesurée" in result["route_reason"]


def test_explicit_memory_lookup_returns_real_cited_excerpts_without_model(tmp_path):
    memory = PersonalMemoryStore(tmp_path / "memory_data")
    memory.import_text("La VAN actualise les flux futurs et aide à comparer des projets.", title="Cours synthétique", category="study")
    def forbidden(*args):
        raise AssertionError("A simple memory search must not call any model")
    service = make_service(tmp_path, forbidden, memory=memory, credential_loader=no_credentials)
    result = service.ask('Cherche "VAN" dans ma mémoire.', mode="offline")
    assert result["provider"] == "local_tools"
    assert result["usage"]["generation_requests"] == 0
    assert "actualise les flux" in result["answer"]
    assert "Mémoire locale consultée" in result["answer"]
    assert "Cours synthétique" in result["answer"]
    assert result["verification"] == "deterministic_retrieval"
    assert service.ledger.list_events()[0].verification_state == "verified"


def test_explicit_memory_search_reports_zero_hits_without_claiming_model_access(tmp_path):
    memory = PersonalMemoryStore(tmp_path / "memory_data")
    def forbidden(*args):
        raise AssertionError("A simple memory search must not call any model")
    service = make_service(tmp_path, forbidden, memory=memory)
    result = service.ask('Search for "MissingTerm" in my memory.', mode="offline")
    assert result["usage"]["generation_requests"] == 0
    assert "aucun passage" in result["answer"]


def test_complex_memory_synthesis_still_passes_real_context_to_local_model(tmp_path):
    memory = PersonalMemoryStore(tmp_path / "memory_data")
    memory.import_text("La VAN actualise les flux futurs.", title="Cours synthétique", category="study")
    captured = []
    def transport(*args):
        captured.append(args)
        return local_transport(*args)
    service = make_service(tmp_path, transport, memory=memory)
    result = service.ask('Cherche "VAN" dans ma mémoire et explique les résultats.')
    assert result["provider"] == "ollama"
    assert "actualise les flux" in json.dumps(captured[-1][3])
    assert "la mémoire a bien été consultée" in captured[-1][3]["messages"][0]["content"]


@pytest.mark.parametrize("prefix", ["".join(("AQ", ".")), "".join(("AI", "za")), "-".join(("sk", "or", "v1", ""))])
def test_credential_shapes_in_model_input_are_refused_without_persistence(tmp_path, prefix):
    fictional = prefix + "fictional" * 5
    def forbidden(*args):
        raise AssertionError("No transport is allowed")
    service = make_service(tmp_path, forbidden)
    with pytest.raises(UserFacingError) as error:
        service.ask("Bonjour", model=fictional)
    assert fictional not in str(error.value)
    assert not service.ledger.list_events()


@pytest.mark.parametrize("prefix", ["".join(("AQ", ".")), "".join(("AI", "za")), "-".join(("sk", "or", "v1", ""))])
def test_credential_shapes_in_local_model_config_never_appear_in_overview(tmp_path, monkeypatch, prefix):
    fictional = prefix + "fictional" * 5
    monkeypatch.setenv("OLLAMA_MODEL", fictional)
    def forbidden(*args):
        raise AssertionError("No transport is allowed")
    service = make_service(tmp_path, forbidden)
    with pytest.raises(UserFacingError) as error:
        service.overview()
    assert fictional not in str(error.value)
    assert not service.ledger.list_events()


def test_chat_creates_task_when_write_allowed_and_queue_configured(tmp_path):
    from task_queue import TaskQueue
    queue = TaskQueue(tmp_path / "tasks.sqlite3")
    def forbidden(*args):
        raise AssertionError("No transport is allowed")
    service = make_service(tmp_path, forbidden)
    service.task_queue = queue

    # Without allow_write: proposal only
    res_proposal = service.ask("Crée une tâche pour ranger mes cours", allow_write=False)
    assert res_proposal["task_proposal"]["created"] is False
    assert res_proposal["task_proposal"]["requires_confirmation"] is True
    assert "non enregistrée" in res_proposal["answer"]
    assert len(queue.list_tasks()) == 0

    # With allow_write: task enqueued
    res_created = service.ask("Crée une tâche pour ranger mes cours", allow_write=True)
    assert res_created["task_proposal"]["created"] is True
    assert res_created["task_proposal"]["task_id"]
    assert "enregistrée avec succès" in res_created["answer"]
    tasks = queue.list_tasks()
    assert len(tasks) == 1
    assert tasks[0].payload["message"] == "Crée une tâche pour ranger mes cours"



def test_provider_retry_after_reaches_the_ledger_as_a_measured_fact(tmp_path):
    (tmp_path / ".env").write_text("COME_AI_GEMINI_FREE_PROJECT_CONFIRMED=true\n")
    def transport(*args):
        raise ProviderUnavailable("Quota gratuit indisponible.", "quota", http_status=429, retry_after_seconds=1800)
    service = make_service(tmp_path, transport, catalog=FakeCatalog(), credential_loader=lambda *args: "fictional-key-only")
    with pytest.raises(UserFacingError, match="Quota"):
        service.ask("Bonjour", mode="performance", provider="gemini")
    event = service.ledger.list_events()[0]
    # The provider's own delay is stored, not a local guess.
    assert event.error_category == "quota"
    assert event.retry_after_seconds == 1800


def test_quota_failure_without_provider_delay_stays_empty(tmp_path):
    (tmp_path / ".env").write_text("COME_AI_GEMINI_FREE_PROJECT_CONFIRMED=true\n")
    def transport(*args):
        raise ProviderUnavailable("Quota gratuit indisponible.", "quota", http_status=429)
    service = make_service(tmp_path, transport, catalog=FakeCatalog(), credential_loader=lambda *args: "fictional-key-only")
    with pytest.raises(UserFacingError, match="Quota"):
        service.ask("Bonjour", mode="performance", provider="gemini")
    assert service.ledger.list_events()[0].retry_after_seconds is None


class ProviderCatalog:
    """Catalogue that answers per provider, as the real one does."""

    def __init__(self, models):
        self.models = dict(models)
        self.calls = []

    def snapshot(self):
        self.calls.append("snapshot")
        return {"status": "synthetic", "providers": {}, "network_used": False}

    def eligible(self, provider, capability="text"):
        self.calls.append(("eligible", provider, capability))
        return [catalogue_record(model_id) for model_id in self.models.get(provider, [])]

    def refresh(self, provider, **kwargs):
        self.calls.append(("refresh", provider))

    def choose_model(self, provider, requested="auto", exclude_models=()):
        self.calls.append(("choose", provider, requested, exclude_models))
        candidates = [m for m in self.models.get(provider, []) if m not in set(exclude_models)]
        if requested != "auto":
            return requested if requested in candidates else "gemini-2.5-flash"
        return candidates[0] if candidates else "gemini-2.5-flash"


def plan(service, message="Bonjour", *, mode="performance", benchmark=None):
    config = service._config()
    return service._route_plan(message, mode=mode, provider="auto", config=config,
                               benchmark=benchmark or {}, task_kind="general",
                               needs_cloud_capabilities=False)


def resolved_models(service, routes):
    config = service._config()
    return [(provider, config["local_model"]) if provider == "ollama"
            else (provider, service._cloud_model(provider, hint, config)) for provider, hint in routes]


def routed_service(tmp_path, monkeypatch, models):
    """Both cloud keys present: the router has a real choice to make."""
    (tmp_path / ".env").write_text("COME_AI_GEMINI_FREE_PROJECT_CONFIRMED=true\n")
    monkeypatch.setattr(hybrid_chat, "_configured_key", lambda root, name: True)
    return make_service(tmp_path, catalog=ProviderCatalog(models), credential_loader=lambda *args: "fictional-key-only")


def test_router_confirms_its_own_model_through_the_catalogue_with_auto_exclusions(tmp_path, monkeypatch):
    service = routed_service(tmp_path, monkeypatch, {"gemini": ["gemini-3.8-flash"], "openrouter": ["synthetic/model:free"]})

    routes, reason = plan(service)
    # No measured quality yet: the local model keeps the lead, and the router
    # says so instead of claiming the cloud is better.
    assert [provider for provider, _ in routes] == ["ollama", "gemini"]
    assert "aucune supériorité qualité présumée" in reason
    assert resolved_models(service, routes) == [
        ("ollama", "qwen3.5:2b-q4_K_M"),
        ("gemini", "gemini-3.8-flash"),
    ]
    # The model the router picked is re-confirmed by the catalogue, and the
    # auto-selection exclusion still applies to it.
    assert service.catalog.calls[-1][-1] == ("gemini-2.5-flash",)
    assert service._cloud_model("gemini", "gemini-3.8-flash", service._config()) == "gemini-3.8-flash"


def test_measured_reliability_moves_the_routes(tmp_path, monkeypatch):
    service = routed_service(tmp_path, monkeypatch, {"gemini": ["gemini-3.8-flash"], "openrouter": ["synthetic/model:free"]})
    for _ in range(4):
        service.ledger.record_execution(provider="gemini", model="gemini-3.8-flash", mode="performance",
                                        task_kind="general", outcome="succeeded", latency_ms=90)
        service.ledger.record_execution(provider="ollama", model="qwen3.5:2b-q4_K_M", mode="performance",
                                        task_kind="general", outcome="failed", latency_ms=900)
    routes, reason = plan(service)
    # Measured reliability, not a claimed benchmark: the reliable model leads.
    assert [provider for provider, _ in routes][0] == "gemini"
    assert "sans supériorité mesurée" in reason


def test_an_observed_quota_cooldown_removes_the_provider_from_the_routes(tmp_path, monkeypatch):
    service = routed_service(tmp_path, monkeypatch, {"gemini": ["gemini-3.8-flash"], "openrouter": ["synthetic/model:free"]})
    assert [provider for provider, _ in plan(service)[0]] == ["ollama", "gemini"]

    # Gemini has just been refused for quota: the provider itself said so.
    service.ledger.record_execution(provider="gemini", model="gemini-3.8-flash", mode="performance",
                                    task_kind="general", outcome="failed", error_category="quota")
    routes, reason = plan(service)
    assert "gemini" not in [provider for provider, _ in routes]
    assert routes[0][0] == "ollama"
    assert "quota" in reason.casefold()


def test_a_model_the_host_excluded_is_never_named_by_the_router(tmp_path, monkeypatch):
    service = routed_service(tmp_path, monkeypatch, {"gemini": ["gemini-2.5-flash"], "openrouter": ["synthetic/model:free"]})
    routes, reason = plan(service)
    assert "gemini" not in [provider for provider, _ in routes]
    assert routes[0][0] == "ollama"
    # OpenRouter is still routable, so nothing has to raise an alarm either.
    assert any(provider == "openrouter" for provider, _ in routes)


def test_measured_routing_failure_revalidates_a_local_route_and_says_why(tmp_path, monkeypatch):
    (tmp_path / ".env").write_text("COME_AI_GEMINI_FREE_PROJECT_CONFIRMED=true\n")
    monkeypatch.setattr(hybrid_chat, "_configured_key", lambda root, name: True)

    class BrokenCatalogue(ProviderCatalog):
        def eligible(self, provider, capability="text"):
            raise ModelCatalogError("catalogue indisponible")

    service = make_service(tmp_path, catalog=BrokenCatalogue({"gemini": ["gemini-3.8-flash"]}),
                           credential_loader=lambda *args: "fictional-key-only")
    routes, reason = plan(service)
    assert routes == [("ollama", "qwen3.5:2b-q4_K_M")]
    assert "Routage mesuré indisponible" in reason
    assert "sélection locale revalidée" in reason


def test_router_reads_the_capabilities_the_catalogue_proved(tmp_path, monkeypatch):
    service = routed_service(tmp_path, monkeypatch, {"gemini": ["gemini-3.8-flash"]})
    message = "Analyse ce tableau excel en profondeur"
    assert classify_task(message).kind.value == "spreadsheet_analysis"
    routes, reason = plan(service, message=message)
    # A cloud-only capability keeps a cloud provider in the ordered routes.
    assert "gemini" in [provider for provider, _ in routes]
    assert routes[0][0] == "ollama"


def test_benchmark_measured_local_gap_takes_the_local_model_out_of_that_task(tmp_path, monkeypatch):
    service = routed_service(tmp_path, monkeypatch, {"gemini": ["gemini-3.8-flash"], "openrouter": ["synthetic/model:free"]})
    benchmark = {"model": "qwen3.5:2b-q4_K_M", "cases": [{"name": "summary", "passed": False}]}
    routes, reason = plan(service, message="Résume ce cours", benchmark=benchmark)
    # The local model is measured as failing summaries, so it is not proposed
    # for this task at all rather than being merely ranked lower.
    assert routes[0][0] == "gemini"
    assert "benchmark local" in reason


def test_quota_status_is_the_observed_one_not_a_fixed_unknown(tmp_path):
    (tmp_path / ".env").write_text("COME_AI_GEMINI_FREE_PROJECT_CONFIRMED=true\n")
    service = make_service(tmp_path, catalog=ProviderCatalog({"gemini": ["gemini-3.8-flash"]}),
                           credential_loader=lambda *args: "fictional-key-only")

    def transport(method, url, headers, payload, timeout):
        if url.endswith("/api/show"):
            return {"details": {"format": "gguf"}}
        return {"message": {"content": "Réponse locale."}, "prompt_eval_count": 5, "eval_count": 3}

    result = service.ask("Bonjour", mode="automatic")
    # Nobody reported anything about the quota, so the answer says unknown.
    assert result["quota_status"] == "unknown"
    assert result["provider"] == "ollama"

    service.ledger.record_execution(provider="ollama", model="qwen3.5:2b-q4_K_M", mode="automatic",
                                    task_kind="general", outcome="failed", error_category="quota")
    service.transport = lambda *args: pytest.fail("An exhausted local provider must not generate again")
    with pytest.raises(UserFacingError, match="quotas"):
        service.ask("Bonjour", mode="automatic")
    assert service.routing_state()["observed_quota"]["ollama"] == "exhausted"


@pytest.mark.parametrize("provider,model", [("auto", "auto"), ("gemini", "auto"), ("gemini", "gemini-3.6-flash")])
def test_the_measured_second_gemini_model_is_sent_to_the_generation_endpoint(tmp_path, monkeypatch, provider, model):
    service = routed_service(tmp_path, monkeypatch, {"gemini": ["gemini-3.8-flash", "gemini-3.6-flash"]})
    for _ in range(3):
        service.ledger.record_execution(provider="gemini", model="gemini-3.6-flash", mode="performance",
                                        task_kind="general", outcome="succeeded", latency_ms=2)
    calls = []

    def transport(method, url, headers, payload, timeout):
        calls.append((method, url, payload))
        assert url.endswith("models/gemini-3.6-flash:generateContent")
        assert payload["contents"][-1]["parts"][0]["text"].startswith("Bonjour\n")
        return {"candidates": [{"content": {"parts": [{"text": "Réponse du modèle retenu."}]}}]}

    service.transport = transport
    result = service.ask("Bonjour", mode="performance", provider=provider, model=model)
    assert (result["provider"], result["model"]) == ("gemini", "gemini-3.6-flash")
    assert len(calls) == 1
    assert ("choose", "gemini", "gemini-3.6-flash", ("gemini-2.5-flash",)) in service.catalog.calls


class UnavailableCatalog(FakeCatalog):
    def eligible(self, provider, capability="text"):
        self.calls.append(("eligible", provider, capability))
        return []

    def refresh(self, provider, **kwargs):
        raise ProviderUnavailable("Catalogue temporairement indisponible.", "transient", http_status=503)


@pytest.mark.parametrize("mode", ["automatic", "performance"])
def test_a_catalogue_503_falls_back_only_to_a_local_route_the_router_approves(tmp_path, monkeypatch, mode):
    monkeypatch.setattr(hybrid_chat, "_configured_key", lambda *args: True)
    calls = []

    def transport(*args):
        calls.append(args)
        return local_transport(*args)

    service = make_service(tmp_path, transport, catalog=UnavailableCatalog(), credential_loader=no_credentials)
    monkeypatch.setattr(service, "_config", lambda: {"local_model": "qwen3.5:2b-q4_K_M",
                                                     "local_url": "http://127.0.0.1:11434", "gemini_free_confirmed": True})
    result = service.ask("Bonjour", mode=mode)
    assert result["provider"] == "ollama"
    assert "ProviderUnavailable" in result["route_reason"]
    assert "sélection locale revalidée" in result["route_reason"]
    assert len(calls) == 2


@pytest.mark.parametrize("refusal", ["vision", "ollama", "ollama_local"])
def test_a_catalogue_503_cannot_bypass_local_capability_or_quota_refusals(tmp_path, monkeypatch, refusal):
    monkeypatch.setattr(hybrid_chat, "_configured_key", lambda *args: True)
    service = make_service(tmp_path, lambda *args: pytest.fail("Refused routes cannot call a model"),
                           catalog=UnavailableCatalog(), credential_loader=no_credentials)
    monkeypatch.setattr(service, "_config", lambda: {"local_model": "qwen3.5:2b-q4_K_M",
                                                     "local_url": "http://127.0.0.1:11434", "gemini_free_confirmed": True})
    message = "Décris cette image" if refusal == "vision" else "Bonjour"
    if refusal != "vision":
        service.ledger.record_execution(provider=refusal, model="qwen3.5:2b-q4_K_M", mode="performance",
                                        task_kind="general", outcome="failed", error_category="quota")
    before = [event.id for event in service.ledger.list_events()]
    with pytest.raises(UserFacingError, match="refusé"):
        service.ask(message, mode="performance")
    assert [event.id for event in service.ledger.list_events()] == before


@pytest.mark.parametrize("mode,provider", [("offline", "auto"), ("offline", "ollama"),
                                          ("automatic", "auto"), ("performance", "auto"),
                                          ("performance", "gemini"), ("automatic", "ollama"),
                                          ("performance", "openrouter")])
def test_vision_refusal_is_enforced_for_offline_manual_and_automatic_routes(tmp_path, monkeypatch, mode, provider):
    service = routed_service(tmp_path, monkeypatch, {"gemini": ["gemini-3.8-flash"], "openrouter": ["vendor/model:free"]})
    service.transport = lambda *args: pytest.fail("No refused route may reach a model transport")
    service.credential_loader = no_credentials
    with pytest.raises(UserFacingError, match="refusé"):
        service.ask("Décris cette image", mode=mode, provider=provider)
    assert not service.ledger.list_events()
    if mode == "offline" or provider == "ollama":
        assert service.catalog.calls == []


def test_when_every_provider_has_an_observed_cooldown_no_model_is_generated(tmp_path, monkeypatch):
    service = routed_service(tmp_path, monkeypatch, {"gemini": ["gemini-3.8-flash", "gemini-3.6-flash"],
                                                   "openrouter": ["vendor/model:free"]})
    service.transport = lambda *args: pytest.fail("An exhausted provider cannot generate")
    for provider, model in [("ollama", "qwen3.5:2b-q4_K_M"), ("gemini", "gemini-3.8-flash"),
                            ("openrouter", "vendor/model:free")]:
        service.ledger.record_execution(provider=provider, model=model, mode="performance", task_kind="general",
                                        outcome="failed", error_category="quota")
    with pytest.raises(UserFacingError, match="refusé"):
        service.ask("Bonjour", mode="performance")
    assert len(service.ledger.list_events()) == 3


def test_local_alias_measurements_change_chat_routes_and_quota_display(tmp_path, monkeypatch):
    service = routed_service(tmp_path, monkeypatch, {"gemini": ["gemini-3.8-flash"]})
    assert plan(service)[0][0][0] == "ollama"
    for provider in ("ollama", "ollama_local", "ollama"):
        service.ledger.record_execution(provider=provider, model="qwen3.5:2b-q4_K_M", mode="performance",
                                        task_kind="general", outcome="failed", error_category="transient")
    assert plan(service)[0][0] == ("gemini", "gemini-3.8-flash")
    state = service.routing_state()
    assert state["measured_reliability"]["ollama_local/qwen3.5:2b-q4_K_M"]["quality_rank"] == 0
    service.ledger.record_execution(provider="ollama", model="qwen3.5:2b-q4_K_M", mode="performance",
                                    task_kind="general", outcome="failed", error_category="quota")
    assert service.routing_state()["observed_quota"]["ollama"] == "exhausted"
    assert "ollama" not in [provider for provider, _ in plan(service)[0]]


@pytest.mark.parametrize("field,value", [("price_status", "non_zero"), ("price_status", None),
                                         ("price_evidence", None), ("capabilities", None)])
@pytest.mark.parametrize("provider", ["auto", "gemini"])
def test_incomplete_or_paid_catalogue_records_never_reach_cloud_generation(tmp_path, monkeypatch, field, value, provider):
    class IncompleteCatalog(FakeCatalog):
        def eligible(self, *args, **kwargs):
            entry = catalogue_record(self.model)
            entry[field] = value
            return [entry]

    service = routed_service(tmp_path, monkeypatch, {})
    service.catalog = IncompleteCatalog()
    service.transport = local_transport if provider == "auto" else lambda *args: pytest.fail("A manual refusal cannot fall back")
    service.credential_loader = no_credentials
    if provider == "auto":
        result = service.ask("Bonjour", mode="performance")
        assert result["provider"] == "ollama"
    else:
        with pytest.raises(UserFacingError):
            service.ask("Bonjour", mode="performance", provider=provider)
        assert not service.ledger.list_events()


def test_a_catalogue_cannot_substitute_a_manually_selected_model(tmp_path, monkeypatch):
    class SubstitutingCatalog(ProviderCatalog):
        def choose_model(self, *args, **kwargs):
            return "gemini-3.8-flash"

    service = routed_service(tmp_path, monkeypatch, {})
    service.catalog = SubstitutingCatalog({"gemini": ["gemini-3.8-flash", "gemini-3.6-flash"]})
    service.transport = lambda *args: pytest.fail("Substitution must be refused before generation")
    with pytest.raises(UserFacingError, match="substitué"):
        service.ask("Bonjour", mode="performance", provider="gemini", model="gemini-3.6-flash")
    assert not service.ledger.list_events()


@pytest.mark.parametrize("category,status", [("quota", 429), ("authentication", 401), ("authentication", 403)])
def test_a_new_provider_refusal_does_not_rotate_to_another_model_of_the_same_provider(tmp_path, monkeypatch, category, status):
    service = routed_service(tmp_path, monkeypatch, {"gemini": ["gemini-3.8-flash", "gemini-3.6-flash"]})
    for model in ("gemini-3.8-flash", "gemini-3.6-flash"):
        for _ in range(3):
            service.ledger.record_execution(provider="gemini", model=model, mode="performance", task_kind="general",
                                            outcome="succeeded", latency_ms=1)
    assert [provider for provider, _ in plan(service)[0]] == ["gemini", "gemini"]
    calls = []

    def transport(*args):
        calls.append(args)
        message = "Quota fournisseur épuisé." if category == "quota" else "Authentification fournisseur refusée."
        raise ProviderUnavailable(message, category, http_status=status)

    service.transport = transport
    with pytest.raises(UserFacingError, match="Quota|Authentification"):
        service.ask("Bonjour", mode="performance")
    assert len(calls) == 1
    assert sum(event.outcome.value == "failed" for event in service.ledger.list_events()) == 1


@pytest.mark.parametrize("provider", ["ollama_local", "local", " OLLAMA_LOCAL "])
def test_public_local_aliases_are_normalized_before_provider_validation(tmp_path, provider):
    service = make_service(tmp_path, catalog=FakeCatalog(), credential_loader=no_credentials)
    result = service.ask("Bonjour", mode="offline", provider=provider)
    assert (result["provider"], result["model"]) == ("ollama", "qwen3.5:2b-q4_K_M")
    assert service.catalog.calls == []
    service.transport = lambda *args: pytest.fail("An alias cannot bypass a capability refusal")
    with pytest.raises(UserFacingError, match="refusé"):
        service.ask("Décris cette image", mode="offline", provider=provider)


def test_the_measured_second_openrouter_model_is_the_generation_payload_model(tmp_path, monkeypatch):
    selected = "vendor/second:free"
    service = routed_service(tmp_path, monkeypatch, {"openrouter": ["vendor/first:free", selected]})
    for _ in range(3):
        service.ledger.record_execution(provider="openrouter", model=selected, mode="performance", task_kind="general",
                                        outcome="succeeded", latency_ms=1)
    calls = []

    def transport(method, url, headers, payload, timeout):
        calls.append((method, url, payload))
        if method == "GET":
            assert url == hybrid_chat.OPENROUTER_MODELS_URL
            return {"data": [{"id": identifier, "pricing": {"prompt": "0", "completion": "0", "request": "0"}}
                             for identifier in ("vendor/first:free", selected)]}
        assert url == hybrid_chat.OPENROUTER_GENERATION_URL
        assert payload["model"] == selected
        return {"model": selected, "choices": [{"message": {"content": "Réponse du modèle retenu."}}]}

    service.transport = transport
    result = service.ask("Bonjour", mode="performance", provider="openrouter")
    assert (result["provider"], result["model"]) == ("openrouter", selected)
    assert [method for method, _, _ in calls] == ["GET", "POST"]
    assert ("choose", "openrouter", selected, ("gemini-2.5-flash",)) in service.catalog.calls


@pytest.mark.parametrize("identifier,pricing,provider", [("gemini-3.1-pro-preview", "non_zero", "gemini"),
                                                       ("vendor/model:paid", "non_zero", "openrouter"),
                                                       ("vendor/model:free", "unknown", "openrouter")])
def test_paid_pro_paid_suffix_and_unknown_prices_are_refused_before_any_generation_post(tmp_path, monkeypatch, identifier, pricing, provider):
    class NonFreeCatalog(FakeCatalog):
        def eligible(self, *args, **kwargs):
            entry = catalogue_record(identifier)
            entry["price_status"] = pricing
            return [entry]

    service = routed_service(tmp_path, monkeypatch, {})
    service.catalog = NonFreeCatalog()
    service.transport = lambda *args: pytest.fail("A nonzero or unknown price cannot reach a generation POST")
    service.credential_loader = no_credentials
    with pytest.raises(UserFacingError, match="prix"):
        service.ask("Bonjour", mode="performance", provider=provider)
    assert not service.ledger.list_events()


def test_routing_state_reports_measurements_and_never_touches_a_provider(tmp_path, monkeypatch):
    (tmp_path / ".env").write_text("COME_AI_GEMINI_FREE_PROJECT_CONFIRMED=true\n")
    monkeypatch.setattr(hybrid_chat, "_configured_key", lambda root, name: True)

    def forbidden(*args):
        raise AssertionError("The routing state must not call any provider")

    service = make_service(tmp_path, forbidden, catalog=ProviderCatalog({"gemini": ["gemini-3.8-flash"]}),
                           credential_loader=lambda *args: "fictional-key-only")
    for _ in range(3):
        service.ledger.record_execution(provider="gemini", model="gemini-3.8-flash", mode="performance",
                                        task_kind="general", outcome="succeeded", latency_ms=80)
    state = service.routing_state()
    assert state["network_used"] is False
    assert state["observed_quota"]["gemini"] == "unknown"
    measured = state["measured_reliability"]["gemini/gemini-3.8-flash"]
    assert measured["attempts"] == 3 and measured["succeeded"] == 3
    assert measured["quality_rank"] == 100
    assert "not_a_claimed_reasoning_benchmark" in state["quality_measurement"]

    # The UI snapshot exposes it, still without any provider call.
    overview = service.overview()
    assert overview["routing"] == state
    assert overview["network_used"] is False
