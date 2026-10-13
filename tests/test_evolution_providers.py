"""Offline provider contracts: fictitious credentials, no SDK or network calls."""

from __future__ import annotations

import json
import socket

import pytest

from devkit import evolution_providers as providers
from devkit.evolution_providers import ProviderSettings, ProviderUnavailable, create_provider
from devkit.proposals import ProposalContext


FIXTURE_CREDENTIAL = "fixture-not-a-real-key"
SOURCE = {"sample.py": "def add(a, b):\n    return a - b\n"}
CORRECTION = {"files": {"sample.py": "def add(a, b):\n    return a + b\n"}}


@pytest.fixture(autouse=True)
def forbid_real_configuration_and_network(monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("These tests must never use a real network or credential")

    monkeypatch.setattr(socket, "create_connection", forbidden)
    monkeypatch.setattr(providers, "bounded_json_transport", forbidden)
    monkeypatch.setattr(providers, "_credential", forbidden)
    monkeypatch.setattr(providers, "read_dotenv", lambda path: {})
    monkeypatch.delenv("OLLAMA_BASE_URL", raising=False)


class FakeTransport:
    def __init__(self, *responses):
        self.responses = list(responses)
        self.calls = []

    def __call__(self, method, url, headers, payload, timeout):
        self.calls.append((method, url, dict(headers), payload, timeout))
        if not self.responses:
            raise AssertionError("An unexpected retry or request was attempted")
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response


def context(sources=None, issue=None):
    return ProposalContext(issue or {"title": "Fix fixture arithmetic", "description": "Addition must add."}, SOURCE if sources is None else sources)


def gemini(text=None, **extra):
    return {
        "candidates": [{"content": {"parts": [{"text": "ignored internal thought", "thought": True}, {"text": json.dumps(CORRECTION) if text is None else text}]}, "finishReason": "STOP"}],
        "usageMetadata": {"promptTokenCount": 120, "candidatesTokenCount": 30, "totalTokenCount": 150},
        **extra,
    }


def openrouter_catalogue(pricing=None):
    return {"data": [{"id": "fixture/coder:free", "pricing": {"prompt": "0", "completion": "0", "request": "0"} if pricing is None else pricing}]}


def openrouter_response():
    return {"model": "fixture/coder:free", "choices": [{"message": {"content": json.dumps(CORRECTION)}, "finish_reason": "stop"}], "usage": {"prompt_tokens": 12, "completion_tokens": 9, "total_tokens": 21}}


def adapter(tmp_path, transport, provider="gemini", **settings):
    defaults = {
        "gemini": {"model": "gemini-2.5-flash", "allow_remote": True, "gemini_free_project_confirmed": True},
        "openrouter": {"model": "fixture/coder:free", "allow_remote": True},
        "ollama": {"model": "fixture-qwen:4b"},
    }
    options = {**defaults[provider], **settings}
    return create_provider(tmp_path, ProviderSettings(provider=provider, **options), transport=transport, credential_loader=lambda root, name: FIXTURE_CREDENTIAL)


def test_gemini_structured_proposal_is_inert_and_usage_is_reported(tmp_path):
    transport = FakeTransport(gemini())
    model = adapter(tmp_path, transport)
    assert not transport.calls  # Construction never probes, generates or loads a credential.
    proposal = model.propose(context(issue={"title": "fixture", "profile": {"name": "private-profile-fixture"}}))

    assert dict(proposal.files) == CORRECTION["files"]
    assert proposal.patch is None
    assert not (tmp_path / "sample.py").exists()
    assert len(transport.calls) == 1
    method, url, headers, payload, timeout = transport.calls[0]
    assert method == "POST" and url.endswith("/gemini-2.5-flash:generateContent")
    assert headers == {"x-goog-api-key": FIXTURE_CREDENTIAL}
    assert payload["generationConfig"]["responseMimeType"] == "application/json"
    assert "tools" not in payload and "private-profile-fixture" not in str(payload)
    assert SOURCE["sample.py"] in json.loads(payload["contents"][0]["parts"][0]["text"].split("\n", 1)[1])["selected_sources"].values()
    assert model.last_usage["input_tokens"] == 120
    assert model.last_usage["output_tokens"] == 30
    assert model.last_usage["total_tokens"] == 150
    assert model.last_usage["generation_requests"] == 1
    assert model.last_usage["latency_ms"] >= 0


@pytest.mark.parametrize("code,category", [(429, "quota"), (503, "transient"), (401, "authentication"), (403, "authentication")])
def test_gemini_failures_have_no_hidden_retry_or_error_body_leak(tmp_path, code, category):
    transport = FakeTransport({"error": {"code": code, "message": FIXTURE_CREDENTIAL + " upstream-private-body"}})
    model = adapter(tmp_path, transport)
    with pytest.raises(ProviderUnavailable) as error:
        model.propose(context())
    assert error.value.category == category
    assert FIXTURE_CREDENTIAL not in str(error.value)
    assert "upstream-private-body" not in str(error.value)
    assert len(transport.calls) == 1
    assert model.last_usage["generation_requests"] == 1


def test_injected_transport_exception_does_not_disclose_credentials(tmp_path):
    model = adapter(tmp_path, FakeTransport(RuntimeError(FIXTURE_CREDENTIAL)))
    with pytest.raises(ProviderUnavailable) as error:
        model.propose(context())
    assert error.value.category == "transient" and FIXTURE_CREDENTIAL not in str(error.value)


@pytest.mark.parametrize("options,category", [
    ({"allow_remote": False}, "missing_configuration"),
    ({"gemini_free_project_confirmed": False}, "price_unknown"),
    ({"model": "gemini-fixture-unverified"}, "price_unknown"),
])
def test_gemini_guard_rejects_before_credentials_or_requests(tmp_path, options, category):
    transport = FakeTransport()
    model = adapter(tmp_path, transport, **options)
    with pytest.raises(ProviderUnavailable) as error:
        model.propose(context())
    assert error.value.category == category and not transport.calls


def test_openrouter_refreshes_price_evidence_and_caps_generation_to_zero(tmp_path):
    transport = FakeTransport(openrouter_catalogue(), openrouter_response())
    model = adapter(tmp_path, transport, "openrouter")
    assert dict(model.propose(context()).files) == CORRECTION["files"]
    assert [call[:2] for call in transport.calls] == [("GET", providers.OPENROUTER_MODELS_URL), ("POST", providers.OPENROUTER_GENERATION_URL)]
    assert transport.calls[0][2] == {} and transport.calls[0][3] is None
    payload = transport.calls[1][3]
    assert payload["model"] == "fixture/coder:free"
    assert payload["provider"]["allow_fallbacks"] is False
    assert payload["provider"]["require_parameters"] is True
    assert all(value == 0 for value in payload["provider"]["max_price"].values())
    assert "tools" not in payload
    assert model.last_usage["total_tokens"] == 21
    assert model.last_usage["generation_requests"] == 1


@pytest.mark.parametrize("pricing", [
    {}, {"prompt": "0"},
    {"prompt": "0", "completion": "0", "request": "0.01"},
    {"prompt": "0", "completion": None, "request": "0"},
    {"prompt": "0", "completion": "unknown", "request": "0"},
    {"prompt": "0", "completion": "0", "request": False},
    {"prompt": "0", "completion": "0", "request": "NaN"},
    {"prompt": "0", "completion": "0", "request": "0", "web_search": "1"},
])
def test_openrouter_unknown_or_paid_pricing_prevents_generation(tmp_path, pricing):
    transport = FakeTransport(openrouter_catalogue(pricing))
    model = adapter(tmp_path, transport, "openrouter")
    with pytest.raises(ProviderUnavailable) as error:
        model.propose(context())
    assert error.value.category == "price_unknown"
    assert len(transport.calls) == 1 and transport.calls[0][0] == "GET"
    assert model.last_usage["generation_requests"] == 0


def test_openrouter_duplicate_model_evidence_is_rejected(tmp_path):
    catalogue = openrouter_catalogue()
    catalogue["data"].append(dict(catalogue["data"][0]))
    transport = FakeTransport(catalogue)
    with pytest.raises(ProviderUnavailable) as error:
        adapter(tmp_path, transport, "openrouter").propose(context())
    assert error.value.category == "price_unknown" and len(transport.calls) == 1


def test_openrouter_paid_model_name_rejected_without_request(tmp_path):
    transport = FakeTransport()
    with pytest.raises(ProviderUnavailable) as error:
        adapter(tmp_path, transport, "openrouter", model="fixture/coder").propose(context())
    assert error.value.category == "price_unknown" and not transport.calls


def test_ollama_requires_local_gguf_before_generation(tmp_path):
    transport = FakeTransport({"details": {"format": "gguf"}}, {"done": True, "response": json.dumps(CORRECTION), "prompt_eval_count": 40, "eval_count": 12})
    model = adapter(tmp_path, transport, "ollama")
    assert model.is_remote is False
    assert dict(model.propose(context()).files) == CORRECTION["files"]
    assert [call[1] for call in transport.calls] == ["http://127.0.0.1:11434/api/show", "http://127.0.0.1:11434/api/generate"]
    assert transport.calls[1][3]["stream"] is False
    assert transport.calls[1][3]["format"] == "json"
    assert transport.calls[1][3]["options"]["num_predict"] == 3000
    assert model.last_usage["input_tokens"] == 40 and model.last_usage["output_tokens"] == 12
    assert model.last_usage["total_tokens"] is None


@pytest.mark.parametrize("metadata", [{}, {"details": {"format": "safetensors"}}, {"details": {"format": "gguf"}, "remote_host": "https://fixture.invalid"}, {"details": {"format": "gguf"}, "remote_model": "fixture-cloud"}])
def test_ollama_cloud_or_unverified_weights_do_not_generate(tmp_path, metadata):
    transport = FakeTransport(metadata)
    model = adapter(tmp_path, transport, "ollama")
    with pytest.raises(ProviderUnavailable) as error:
        model.propose(context())
    assert error.value.category == "price_unknown" and len(transport.calls) == 1
    assert model.last_usage["generation_requests"] == 0


def test_ollama_remote_address_never_receives_source(tmp_path, monkeypatch):
    monkeypatch.setenv("OLLAMA_BASE_URL", "https://fixture.invalid")
    transport = FakeTransport()
    with pytest.raises(ProviderUnavailable) as error:
        adapter(tmp_path, transport, "ollama").propose(context())
    assert error.value.category == "missing_configuration" and not transport.calls


@pytest.mark.parametrize("source", [{}, {"../sample.py": "x"}, {"/private/fixture.py": "x"}, {"data/private.py": "x"}, {".env": "fixture"}, {"sample.py": "x" * providers.MAX_PROMPT_BYTES}, {f"tests/fixture_{index}.py": "x" for index in range(providers.MAX_SELECTED_FILES + 1)}])
def test_source_context_bounds_and_paths_fail_before_network(tmp_path, source):
    transport = FakeTransport()
    with pytest.raises(ProviderUnavailable) as error:
        adapter(tmp_path, transport).propose(context(sources=source))
    assert error.value.category == "missing_configuration" and not transport.calls


@pytest.mark.parametrize("text", [
    '{"files":{"unselected.py":"x"}}',
    '{"files":{"../sample.py":"x"}}',
    '{"files":{"sample.py":null}}',
    '{"files":{}}',
    '{"files":{"sample.py":"x"},"execute":"anything"}',
    '{"files":{"sample.py":"a"},"files":{"sample.py":"b"}}',
    '{"patch":"x","files":{"sample.py":"x"}}',
    '[]', 'not-json',
])
def test_malformed_or_outside_selection_output_is_rejected(tmp_path, text):
    transport = FakeTransport(gemini(text))
    with pytest.raises(ProviderUnavailable) as error:
        adapter(tmp_path, transport).propose(context())
    assert error.value.category == "malformed_output" and len(transport.calls) == 1


def test_patch_outside_selected_sources_is_rejected(tmp_path):
    patch = "--- a/unselected.py\n+++ b/unselected.py\n@@ -1 +1 @@\n-old\n+new\n"
    with pytest.raises(ProviderUnavailable) as error:
        adapter(tmp_path, FakeTransport(gemini(json.dumps({"patch": patch})))).propose(context())
    assert error.value.category == "malformed_output"


def test_patch_within_selected_sources_remains_inert(tmp_path):
    patch = "--- a/sample.py\n+++ b/sample.py\n@@ -1,2 +1,2 @@\n def add(a, b):\n-    return a - b\n+    return a + b\n"
    proposal = adapter(tmp_path, FakeTransport(gemini(json.dumps({"patch": patch})))).propose(context())
    assert proposal.patch == patch and proposal.files is None
    assert not (tmp_path / "sample.py").exists()


def test_oversized_model_text_is_rejected_before_patch_staging(tmp_path):
    with pytest.raises(ProviderUnavailable) as error:
        adapter(tmp_path, FakeTransport(gemini("x" * (providers.MAX_RESPONSE_BYTES + 1)))).propose(context())
    assert error.value.category == "malformed_output"


@pytest.mark.parametrize("provider", ["gemini", "openrouter", "ollama"])
def test_unfinished_generation_is_rejected_without_retry(tmp_path, provider):
    if provider == "gemini":
        response = gemini()
        response["candidates"][0]["finishReason"] = "MAX_TOKENS"
        transport = FakeTransport(response)
    elif provider == "openrouter":
        response = openrouter_response()
        response["choices"][0]["finish_reason"] = "length"
        transport = FakeTransport(openrouter_catalogue(), response)
    else:
        transport = FakeTransport({"details": {"format": "gguf"}}, {"done": False, "response": json.dumps(CORRECTION), "prompt_eval_count": 40, "eval_count": 12})
    model = adapter(tmp_path, transport, provider)
    with pytest.raises(ProviderUnavailable) as error:
        model.propose(context())
    assert error.value.category == "malformed_output" and not transport.responses
    expected = {"gemini": (120, 30, 150), "openrouter": (12, 9, 21), "ollama": (40, 12, None)}
    assert tuple(model.last_usage[key] for key in ("input_tokens", "output_tokens", "total_tokens")) == expected[provider]
    assert model.last_usage["generation_requests"] == 1
    assert model.last_usage["latency_ms"] >= 0


def test_openrouter_different_response_model_is_rejected(tmp_path):
    response = openrouter_response()
    response["model"] = "fixture/paid"
    model = adapter(tmp_path, FakeTransport(openrouter_catalogue(), response), "openrouter")
    with pytest.raises(ProviderUnavailable) as error:
        model.propose(context())
    assert error.value.category == "malformed_output"
    assert model.last_usage["input_tokens"] == 12
    assert model.last_usage["output_tokens"] == 9
    assert model.last_usage["total_tokens"] == 21
    assert model.last_usage["generation_requests"] == 1


@pytest.mark.parametrize("response", [
    {"candidates": [{"content": []}]},
    {"candidates": [{"content": {"parts": None}}]},
])
def test_malformed_nested_gemini_response_has_safe_failure(tmp_path, response):
    with pytest.raises(ProviderUnavailable) as error:
        adapter(tmp_path, FakeTransport(response)).propose(context())
    assert error.value.category == "malformed_output"


def test_malformed_nested_openrouter_response_has_safe_failure(tmp_path):
    response = {"choices": [{"message": []}]}
    with pytest.raises(ProviderUnavailable) as error:
        adapter(tmp_path, FakeTransport(openrouter_catalogue(), response), "openrouter").propose(context())
    assert error.value.category == "malformed_output"


def test_reported_invalid_usage_remains_unknown(tmp_path):
    response = gemini(usageMetadata={"promptTokenCount": True, "candidatesTokenCount": -1, "totalTokenCount": "12"})
    model = adapter(tmp_path, FakeTransport(response))
    model.propose(context())
    assert model.last_usage["input_tokens"] is None
    assert model.last_usage["output_tokens"] is None
    assert model.last_usage["total_tokens"] is None


def test_prompt_contains_minimal_few_shot_example(tmp_path):
    transport = FakeTransport(gemini())
    adapter(tmp_path, transport).propose(context())
    prompt_text = transport.calls[0][3]["contents"][0]["parts"][0]["text"]
    assert '{"files": {"module.py"' in prompt_text
    assert "JSON coupé est rejeté" in prompt_text


@pytest.mark.parametrize("text", ['{"patch": ""}', '{"patch": 123}', '{"files": "module.py"}'])
def test_empty_or_wrong_typed_primary_fields_are_rejected(tmp_path, text):
    with pytest.raises(ProviderUnavailable) as error:
        adapter(tmp_path, FakeTransport(gemini(text))).propose(context())
    assert error.value.category == "malformed_output"


def test_openrouter_truncated_output_is_named_without_leaking_content(tmp_path):
    response = {"model": "fixture/coder:free",
                "choices": [{"message": {"content": '{"files": {"sample.py": "trunc'}, "finish_reason": "length"}],
                "usage": {"prompt_tokens": 12, "completion_tokens": 9}}
    with pytest.raises(ProviderUnavailable) as error:
        adapter(tmp_path, FakeTransport(openrouter_catalogue(), response), "openrouter").propose(context())
    assert error.value.category == "malformed_output"
    assert "length" in str(error.value)
    assert "trunc" not in str(error.value)


def test_gemini_non_stop_finish_reason_is_reported_safely(tmp_path):
    response = {"candidates": [{"content": {"parts": [{"text": "{}"}]}, "finishReason": "MAX_TOKENS"}],
                "usageMetadata": {"promptTokenCount": 1, "candidatesTokenCount": 1}}
    with pytest.raises(ProviderUnavailable) as error:
        adapter(tmp_path, FakeTransport(response)).propose(context())
    assert error.value.category == "malformed_output"
    assert "MAX_TOKENS" in str(error.value)


def test_extra_field_rejection_lists_keys_but_never_values(tmp_path):
    text = json.dumps({"explanation": FIXTURE_CREDENTIAL, "patch": "--- a/sample.py\n+++ b/sample.py\n@@ -1 +1 @@\n-old\n+new\n"})
    with pytest.raises(ProviderUnavailable) as error:
        adapter(tmp_path, FakeTransport(gemini(text))).propose(context())
    assert error.value.category == "malformed_output"
    assert "explanation" in str(error.value)
    assert FIXTURE_CREDENTIAL not in str(error.value)


def test_valid_json_patch_containing_a_secret_is_still_rejected(tmp_path):
    secret = "sk-or-v1-" + "a" * 64
    patch = "--- a/sample.py\n+++ b/sample.py\n@@ -1 +1 @@\n-token = \"old\"\n+token = \"" + secret + "\"\n"
    with pytest.raises(ProviderUnavailable) as error:
        adapter(tmp_path, FakeTransport(gemini(json.dumps({"patch": patch})))).propose(context())
    assert error.value.category == "malformed_output"
    assert secret not in str(error.value)


def fictional_secret(prefix):
    # Synthetic values are constructed rather than copied from any configuration.
    return prefix + "fictional" * 8


@pytest.mark.parametrize("prefix", ["AQ.", "AIza", "sk-or-v1-"])
def test_unexpected_json_key_never_exposes_secret_fragments(tmp_path, prefix):
    secret = fictional_secret(prefix)
    text = json.dumps({secret: "irrelevant"})
    with pytest.raises(ProviderUnavailable) as error:
        adapter(tmp_path, FakeTransport(gemini(text))).propose(context())
    detail = str(error.value)
    assert error.value.category == "malformed_output"
    assert "[champ non autorisé]" in detail
    assert secret not in detail and secret[:32] not in detail


@pytest.mark.parametrize("prefix", ["AQ.", "AIza", "sk-or-v1-"])
@pytest.mark.parametrize("provider", ["gemini", "openrouter"])
def test_unknown_finish_reason_never_exposes_secret_and_preserves_usage(tmp_path, prefix, provider):
    secret = fictional_secret(prefix)
    if provider == "gemini":
        response = gemini()
        response["candidates"][0]["finishReason"] = secret
        transport = FakeTransport(response)
        expected = (120, 30, 150)
    else:
        response = openrouter_response()
        response["choices"][0]["finish_reason"] = secret
        transport = FakeTransport(openrouter_catalogue(), response)
        expected = (12, 9, 21)
    model = adapter(tmp_path, transport, provider)
    with pytest.raises(ProviderUnavailable) as error:
        model.propose(context())
    detail = str(error.value)
    assert error.value.category == "malformed_output"
    assert "[raison non reconnue]" in detail
    assert secret not in detail and secret[:32] not in detail
    assert tuple(model.last_usage[key] for key in ("input_tokens", "output_tokens", "total_tokens")) == expected


@pytest.mark.parametrize("provider", ["gemini", "openrouter"])
@pytest.mark.parametrize("finish", [{"arbitrary": "value"}, ["STOP"]])
def test_non_string_finish_reason_is_rejected_without_echo(tmp_path, provider, finish):
    if provider == "gemini":
        response = gemini()
        response["candidates"][0]["finishReason"] = finish
        transport = FakeTransport(response)
    else:
        response = openrouter_response()
        response["choices"][0]["finish_reason"] = finish
        transport = FakeTransport(openrouter_catalogue(), response)
    with pytest.raises(ProviderUnavailable) as error:
        adapter(tmp_path, transport, provider).propose(context())
    assert "[raison non reconnue]" in str(error.value)
    assert "arbitrary" not in str(error.value)
