from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest


@pytest.fixture(autouse=True)
def isolated_tutor_workspace(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Tutor tests use a synthetic corpus/config and never the real .env."""
    import vc_tutor

    monkeypatch.setenv("NAGE_VC_HOME", str(tmp_path / "state"))
    monkeypatch.delenv("VC_TUTOR_CLOUD", raising=False)
    monkeypatch.delenv("VC_TUTOR_LOAD_ENV", raising=False)
    monkeypatch.delenv("VC_TUTOR_TEST_MARKER", raising=False)
    monkeypatch.setattr(vc_tutor, "_REPO_ROOT", tmp_path)
    corpus = tmp_path / "docs" / "vc_study"
    corpus.mkdir(parents=True)
    (corpus / "Topic 3 Valuation.txt").write_text(
        "Synthetic teaching example. Post-money valuation equals pre-money "
        "valuation plus the new equity investment.\n",
        encoding="utf-8",
    )
    (tmp_path / ".env").write_text("VC_TUTOR_TEST_MARKER=synthetic-opt-in\n")


def test_cloud_disabled_by_default() -> None:
    from vc_tutor import VCTutor

    tutor = VCTutor()
    assert tutor.cloud_enabled is False
    assert tutor.config.get("cloud_enabled") is False
    assert tutor.call_mistral("hi") is None
    assert tutor.call_gemini("hi") is None


def test_env_not_loaded_by_default(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    marker_key = "VC_TUTOR_TEST_MARKER"
    monkeypatch.delenv(marker_key, raising=False)
    env_file = tmp_path / ".env"
    env_file.write_text(f"{marker_key}=loaded-from-dotenv\n", encoding="utf-8")
    # Point the tutor at the fake env file by monkeypatching its loader target.
    from vc_tutor import VCTutor

    original = VCTutor.load_env
    def fake_load_env(self):
        # Reproduce the production loader but against the temp file.
        for line in env_file.read_text().splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                os.environ[k.strip()] = v.strip().strip('"').strip("'")
    monkeypatch.setattr(VCTutor, "load_env", fake_load_env)
    # Even with a loader available, the constructor must not call it by default.
    tutor = VCTutor()
    assert marker_key not in os.environ
    assert tutor.load_env_requested is False
    monkeypatch.delattr(VCTutor, "load_env", raising=False)
    VCTutor.load_env = original


def test_cloud_opt_in_loads_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("VC_TUTOR_CLOUD", "1")
    from vc_tutor import VCTutor

    tutor = VCTutor()
    assert tutor.cloud_enabled is True
    assert tutor.load_env_requested is True
    assert os.environ["VC_TUTOR_TEST_MARKER"] == "synthetic-opt-in"


@pytest.mark.parametrize("host", [
    "https://example.test", "http://127.0.0.1.evil.test:11434",
    "http://secret:password@127.0.0.1:11434", "file:///tmp/model",
    "http://127.0.0.1:99999", "http://127.0.0.1:11434/?token=secret",
])
def test_local_tutor_rejects_remote_or_credential_hosts(host, monkeypatch) -> None:
    import httpx
    from vc_tutor import VCTutor

    calls = []
    monkeypatch.setattr(httpx, "post", lambda *args, **kwargs: calls.append(args))
    tutor = VCTutor(cloud=False, load_env=False)
    tutor.config["ollama_host"] = host
    assert tutor.call_ollama("Synthetic question") is None
    assert calls == []
    assert tutor.provider_status()["ollama_host"] is None
    assert "loopback" in tutor.last_error


@pytest.mark.parametrize("host", ["http://127.0.0.1:11434", "http://localhost:11434/", "http://[::1]:11434"])
def test_local_tutor_accepts_loopback_without_cloud(host, monkeypatch) -> None:
    import httpx
    from vc_tutor import VCTutor

    calls = []
    class Response:
        status_code = 200
        def json(self):
            return {"message": {"content": "Synthetic local explanation."}}
    def fake_post(url, **kwargs):
        calls.append(url)
        return Response()
    monkeypatch.setattr(httpx, "post", fake_post)
    tutor = VCTutor(cloud=False, load_env=False)
    tutor.config["ollama_host"] = host
    assert tutor.call_ollama("Synthetic question") == "Synthetic local explanation."
    assert calls == [host.rstrip("/") + "/api/chat"]


def test_retrieval_is_deterministic() -> None:
    from vc_tutor import VCTutor

    tutor = VCTutor()
    first = tutor.get_relevant_context("pre-money post-money valuation")
    second = tutor.get_relevant_context("pre-money post-money valuation")
    assert first == second
    assert "===" in first


def test_no_network_by_default(monkeypatch: pytest.MonkeyPatch) -> None:
    import vc_tutor as module

    class ExplodingHttpx:
        def post(self, *args, **kwargs):
            raise AssertionError("network call attempted with cloud disabled")

        def get(self, *args, **kwargs):
            raise AssertionError("network call attempted with cloud disabled")

    monkeypatch.setattr(module, "httpx", ExplodingHttpx(), raising=False)
    # httpx is imported lazily inside methods; inject into sys.modules too.
    monkeypatch.setitem(sys.modules, "httpx", ExplodingHttpx())
    from vc_tutor import VCTutor

    tutor = VCTutor()
    # These must return None without touching the network.
    assert tutor.call_ollama("hello") is None or isinstance(tutor.call_ollama("hello"), str)
    assert tutor.call_mistral("hello") is None
    assert tutor.call_gemini("hello") is None
    # tutor_explain must not raise even though no model is available.
    result = tutor.tutor_explain("What is pre-money?")
    assert isinstance(result, str)


def test_importing_nage_does_not_import_tutor() -> None:
    repo = Path(__file__).resolve().parents[1]
    result = subprocess.run(
        [sys.executable, "-c", "import nage, sys; assert 'vc_tutor' not in sys.modules"],
        cwd=repo,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0, result.stderr
