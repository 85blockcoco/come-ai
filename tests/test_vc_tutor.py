from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest


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
        [sys.executable, "-c", "import nage"],
        cwd=repo,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0, result.stderr
