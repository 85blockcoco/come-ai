"""Synthetic hybrid-chat tests: no real key, provider or personal file is used."""

from __future__ import annotations

import json
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import ProxyHandler

import pytest

import hybrid_chat
from hybrid_chat import HybridChatService, calculate_expression, hybrid_json_transport
from devkit.evolution_providers import ProviderUnavailable, _NoRedirect
from personal_memory import PersonalMemoryStore
from workspace_core import AppConfig, LocalTools, UserFacingError, Workspace


class FakeCatalog:
    def __init__(self, model="gemini-3.8-flash"):
        self.model = model
        self.calls = []

    def snapshot(self):
        self.calls.append("snapshot")
        return {"status": "synthetic", "providers": {}, "network_used": False}

    def eligible(self, provider, capability="text"):
        self.calls.append(("eligible", provider, capability))
        return [{"model_id": self.model}]

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

