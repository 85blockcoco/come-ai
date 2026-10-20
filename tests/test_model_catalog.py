from datetime import datetime
import json

import pytest

from devkit.model_catalog import (
    CATALOG_TTL_SECONDS, GEMINI_MODELS_URL, OPENROUTER_MODELS_URL,
    ModelCatalog, ModelCatalogError,
)


@pytest.fixture
def catalog(tmp_path, monkeypatch):
    project = tmp_path / "project"
    project.mkdir()
    monkeypatch.setattr("devkit.evolution_providers._credential", lambda root, name: "catalogue-test-credential")
    return ModelCatalog(project, project / ".devkit")


def gemini_model(name, methods=None):
    return {"name": "models/" + name,
            "supportedGenerationMethods": ["generateContent", "countTokens"] if methods is None else methods,
            "inputTokenLimit": 1_048_576, "outputTokenLimit": 65_536}


def openrouter_model(name="vendor/code:free", prices=None, params=None):
    return {"id": name, "pricing": {"prompt": "0", "completion": "0", "request": "0"} if prices is None else prices,
            "supported_parameters": [] if params is None else params,
            "context_length": 200_000, "top_provider": {"max_completion_tokens": 8192},
            "architecture": {"output_modalities": ["text"]}}


def test_snapshot_is_inert_and_does_not_create_storage(catalog):
    catalog.transport = lambda *args: pytest.fail("metadata request from snapshot")
    assert catalog.snapshot()["status"] == "not_refreshed"
    assert catalog.eligible("gemini") == []
    assert not catalog.storage_root.exists()


def test_gemini_refresh_lists_metadata_only_and_never_persists_credentials(catalog):
    requests = []
    def transport(*args):
        requests.append(args)
        return {"models": [gemini_model("gemini-3.8-flash"), gemini_model("gemini-2.5-flash")],
                "api_key": "upstream-not-persisted", "description": "unsafe body omitted"}
    catalog.transport = transport
    result = catalog.refresh("gemini", gemini_free_project_confirmed=True)
    assert requests == [("GET", GEMINI_MODELS_URL, {"x-goog-api-key": "catalogue-test-credential"}, None, 20)]
    assert result["generation_requests"] == 0
    assert result["network_used"] is True
    assert result["providers"]["gemini"]["quota_status"] == "unknown"
    assert catalog.choose_model("gemini") == "gemini-3.8-flash"
    persisted = catalog.path.read_text()
    assert "catalogue-test-credential" not in persisted
    assert "upstream-not-persisted" not in persisted
    assert "unsafe body omitted" not in persisted
    assert catalog.path.stat().st_mode & 0o777 == 0o600


def test_confirmation_and_configuration_required_before_network(catalog, monkeypatch):
    catalog.transport = lambda *args: pytest.fail("unauthorized metadata request")
    with pytest.raises(ModelCatalogError, match="gratuit"):
        catalog.refresh("gemini")
    monkeypatch.setattr("devkit.evolution_providers._credential", lambda root, name: None)
    with pytest.raises(ModelCatalogError, match="clé Gemini"):
        catalog.refresh("gemini", gemini_free_project_confirmed=True)


def test_gemini_unknown_paid_models_and_non_generating_models_ineligible(catalog):
    catalog.transport = lambda *args: {"models": [
        gemini_model("gemini-3.1-pro-preview"), gemini_model("gemini-9.9-flash"),
        gemini_model("gemini-3.6-flash", ["countTokens"]), gemini_model("gemini-3.8-flash"),
    ]}
    catalog.refresh("gemini", gemini_free_project_confirmed=True)
    assert [item["model_id"] for item in catalog.eligible("gemini")] == ["gemini-3.8-flash"]
    assert catalog.eligible("gemini", "function_calling") == []
    assert catalog.eligible("gemini", "structured_output") == []
    with pytest.raises(ModelCatalogError):
        catalog.choose_model("gemini", "gemini-3.1-pro-preview")


def test_refresh_replaces_disappeared_model_and_preserves_other_provider(catalog):
    responses = {GEMINI_MODELS_URL: {"models": [gemini_model("gemini-3.8-flash")]},
                 OPENROUTER_MODELS_URL: {"data": [openrouter_model()]}}
    catalog.transport = lambda method, url, *args: responses[url]
    catalog.refresh("gemini", gemini_free_project_confirmed=True)
    catalog.refresh("openrouter")
    responses[GEMINI_MODELS_URL] = {"models": [gemini_model("gemini-3.6-flash")]}
    catalog.refresh("gemini", gemini_free_project_confirmed=True)
    assert catalog.choose_model("gemini") == "gemini-3.6-flash"
    assert catalog.choose_model("openrouter") == "vendor/code:free"
    with pytest.raises(ModelCatalogError):
        catalog.choose_model("gemini", "gemini-3.8-flash")


@pytest.mark.parametrize("prices", [
    {}, {"prompt": "0"}, {"prompt": "0", "completion": "0", "request": "0.01"},
    {"prompt": "0", "completion": "0", "image": None},
    {"prompt": "0", "completion": "NaN"}, {"prompt": False, "completion": 0},
    {"prompt": "0", "completion": "0", "discount": "-0.1"},
])
def test_openrouter_rejects_missing_nonzero_or_unknown_price(catalog, prices):
    catalog.transport = lambda *args: {"data": [openrouter_model(prices=prices)]}
    catalog.refresh("openrouter")
    assert catalog.eligible("openrouter") == []
    with pytest.raises(ModelCatalogError):
        catalog.choose_model("openrouter")


def test_openrouter_public_catalogue_and_explicit_capabilities(catalog):
    calls = []
    def transport(*args):
        calls.append(args)
        return {"data": [openrouter_model(params=["tools", "response_format"]),
                         openrouter_model("vendor/paid", prices={"prompt": "0", "completion": "0"})]}
    catalog.transport = transport
    catalog.refresh("openrouter")
    assert calls == [("GET", OPENROUTER_MODELS_URL, {}, None, 20)]
    assert len(catalog.eligible("openrouter", "function_calling")) == 1
    assert len(catalog.eligible("openrouter", "structured_output")) == 1
    assert catalog.eligible("openrouter")[0]["quota_status"] == "unknown"
    with pytest.raises(ModelCatalogError):
        catalog.choose_model("openrouter", "vendor/paid")


def test_expired_catalogue_cannot_select_cloud_model(catalog, monkeypatch):
    catalog.transport = lambda *args: {"data": [openrouter_model()]}
    catalog.refresh("openrouter")
    stamp = datetime.fromisoformat(catalog.snapshot()["providers"]["openrouter"]["verified_at"]).timestamp()
    monkeypatch.setattr("devkit.model_catalog.time.time", lambda: stamp + CATALOG_TTL_SECONDS + 1)
    assert catalog.snapshot()["providers"]["openrouter"]["status"] == "stale"
    assert catalog.eligible("openrouter") == []
    with pytest.raises(ModelCatalogError):
        catalog.choose_model("openrouter")


def test_partial_catalogue_is_honest_and_ids_are_sanitized(catalog):
    catalog.transport = lambda *args: {"models": [gemini_model("gemini-3.8-flash"),
                                                   gemini_model("gemini-unsafe://evil"),
                                                   gemini_model("gemini-AIza-fake")],
                                        "nextPageToken": "upstream-token-not-persisted"}
    catalog.refresh("gemini", gemini_free_project_confirmed=True)
    assert catalog.snapshot()["providers"]["gemini"]["complete"] is False
    assert len(catalog.eligible("gemini")) == 1
    assert "upstream-token-not-persisted" not in catalog.path.read_text()
    assert "unsafe://evil" not in catalog.path.read_text()


def test_404_exclusion_selects_only_another_certified_accessible_model(catalog):
    catalog.transport = lambda *args: {"models": [gemini_model("gemini-3.8-flash"), gemini_model("gemini-3.6-flash")]}
    catalog.refresh("gemini", gemini_free_project_confirmed=True)
    assert catalog.choose_model("gemini", exclude_models=("gemini-3.8-flash",)) == "gemini-3.6-flash"
    with pytest.raises(ModelCatalogError):
        catalog.choose_model("gemini", exclude_models=("gemini-3.8-flash", "gemini-3.6-flash"))


def test_saved_metadata_cannot_supply_new_gemini_price_certification(catalog):
    catalog.transport = lambda *args: {"models": [gemini_model("gemini-9.9-flash")]}
    catalog.refresh("gemini", gemini_free_project_confirmed=True)
    data = json.loads(catalog.path.read_text())
    data["providers"]["gemini"]["models"][0]["price_status"] = "zero_confirmed"
    data["providers"]["gemini"]["models"][0]["evil_raw_body"] = "cached-value-not-returned"
    catalog.path.write_text(json.dumps(data))
    snapshot = catalog.snapshot()
    assert snapshot["providers"]["gemini"]["models"][0]["price_status"] == "unknown"
    assert "cached-value-not-returned" not in json.dumps(snapshot)


def test_symlink_cache_is_rejected_without_writing_target(catalog, tmp_path):
    target = tmp_path / "private.json"
    target.write_text("private-data")
    catalog.directory.mkdir(parents=True)
    catalog.path.symlink_to(target)
    with pytest.raises(ModelCatalogError, match="symbolique"):
        catalog.snapshot()
    assert target.read_text() == "private-data"


def test_malformed_provider_reply_does_not_replace_existing_catalogue(catalog):
    catalog.transport = lambda *args: {"data": [openrouter_model()]}
    catalog.refresh("openrouter")
    prior = catalog.path.read_bytes()
    catalog.transport = lambda *args: {"data": "wrong"}
    with pytest.raises(ModelCatalogError, match="inexploitable"):
        catalog.refresh("openrouter")
    assert catalog.path.read_bytes() == prior


def test_unexpected_transport_error_cannot_expose_body_or_headers(catalog):
    def broken(*args):
        raise RuntimeError("private-provider-body credential-placeholder")
    catalog.transport = broken
    with pytest.raises(ModelCatalogError) as captured:
        catalog.refresh("openrouter")
    assert "credential-placeholder" not in str(captured.value)
    assert not catalog.path.exists()
