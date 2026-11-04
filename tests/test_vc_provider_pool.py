"""Provider orchestration using synthetic secrets and zero network requests."""

from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest

from vc_tutor import VCTutor


@pytest.fixture(autouse=True)
def isolated_sources(tmp_path: Path, monkeypatch):
    import vc_tutor

    import os

    for name in tuple(os.environ):
        if vc_tutor._provider_setting(name):
            monkeypatch.delenv(name, raising=False)
    monkeypatch.setattr(vc_tutor, "_REPO_ROOT", tmp_path)
    monkeypatch.setattr(vc_tutor, "_CENTRAL_PROVIDER_ENV", tmp_path / "central" / "providers.env")
    monkeypatch.setenv("NAGE_VC_HOME", str(tmp_path / "state"))


def tutor(tmp_path, **settings):
    return VCTutor(
        environ={
            "VC_TUTOR_CLOUD": "1",
            "GEMINI_API_KEY": "synthetic-first-secret",
            "GEMINI_API_KEY_2": "synthetic-second-secret",
            **settings,
        },
        data_dir=tmp_path / "state",
        env_paths=[],
    )


class Response:
    def __init__(self, status, text="Synthetic explanation.", error_status=None):
        self.status_code = status
        self.text = "sensitive body synthetic-first-secret"
        self._text = text
        self._error_status = error_status

    def json(self):
        if self._error_status:
            return {"error": {"status": self._error_status}}
        return {"candidates": [{"content": {"parts": [{"text": self._text}]}}]}


def fake_http(monkeypatch, responses):
    calls = []
    responses = iter(responses)

    def post(url, **kwargs):
        calls.append((url, kwargs))
        return next(responses)

    monkeypatch.setattr(httpx, "post", post)
    return calls


def test_quota_rotates_to_second_key_and_preserves_model(tmp_path, monkeypatch):
    calls = fake_http(monkeypatch, [Response(429), Response(200)])
    instance = tutor(tmp_path, GEMINI_PRIMARY_MODEL="configured-gemini-model")
    assert instance.call_gemini("question") == "Synthetic explanation."
    assert [call[1]["headers"]["x-goog-api-key"] for call in calls] == ["synthetic-first-secret", "synthetic-second-secret"]
    assert all("configured-gemini-model:generateContent" in call[0] for call in calls)
    assert all("secret" not in call[0] for call in calls)
    assert instance.last_error is None


def test_every_quota_exhausted_then_controlled_kilo(tmp_path, monkeypatch):
    calls = fake_http(monkeypatch, [Response(429), Response(429)])
    instance = tutor(tmp_path, VC_TUTOR_KILO="1")
    fallback_calls = []
    instance._kilo_fallback = lambda prompt, system: fallback_calls.append((prompt, system)) or "Kilo reply."
    assert instance.call_kilo("direct") is None
    assert instance.call_gemini("question", "system") == "Kilo reply."
    assert len(calls) == 2
    assert fallback_calls == [("question", "system")]
    assert instance.provider_status()["last_provider"] == "kilo"


@pytest.mark.parametrize("status", [400, 401, 402, 403, 404, 500, 503])
def test_nonquota_failure_stops_pool_and_never_kilo(tmp_path, monkeypatch, status):
    calls = fake_http(monkeypatch, [Response(status)])
    instance = tutor(tmp_path, VC_TUTOR_KILO="1")
    instance._kilo_fallback = lambda *args: pytest.fail("Kilo after nonquota failure")
    assert instance.call_gemini("question") is None
    assert len(calls) == 1
    assert "synthetic" not in instance.last_error


def test_known_resource_exhausted_rotates(tmp_path, monkeypatch):
    calls = fake_http(monkeypatch, [Response(400, error_status="RESOURCE_EXHAUSTED"), Response(200)])
    assert tutor(tmp_path).call_gemini("question") == "Synthetic explanation."
    assert len(calls) == 2


def test_quota_without_kilo_opt_in_stays_unavailable(tmp_path, monkeypatch):
    fake_http(monkeypatch, [Response(429), Response(429)])
    instance = tutor(tmp_path)
    instance._kilo_fallback = lambda *args: pytest.fail("Kilo requires explicit consent")
    assert instance.call_gemini("question") is None
    assert "quota" in instance.last_error


def test_deduplicates_every_supported_alias(tmp_path, monkeypatch):
    instance = tutor(
        tmp_path,
        GEMINI_API_KEY2="synthetic-second-secret",
        GOOGLE_API_KEY="synthetic-first-secret",
        GEMINI_API_KEYS="synthetic-first-secret, synthetic-third-secret, synthetic-third-secret",
    )
    assert instance.provider_status()["gemini_key_count"] == 3
    calls = fake_http(monkeypatch, [Response(429), Response(429), Response(200)])
    assert instance.call_gemini("question")
    assert len(calls) == 3
    assert len({call[1]["headers"]["x-goog-api-key"] for call in calls}) == 3


def test_attempt_bound_does_not_authorize_kilo_with_untried_keys(tmp_path, monkeypatch):
    instance = tutor(tmp_path, VC_TUTOR_KILO="1", GEMINI_API_KEYS="third,fourth,fifth")
    instance._kilo_fallback = lambda *args: pytest.fail("An untried Gemini key remains")
    calls = fake_http(monkeypatch, [Response(429)] * 4)
    assert instance.call_gemini("question") is None
    assert len(calls) == 4
    assert "untried" in instance.last_error


def test_no_key_in_output_status_or_exception(tmp_path, monkeypatch):
    instance = tutor(tmp_path)
    fake_http(monkeypatch, [Response(200, text="Echo synthetic-first-secret synthetic-second-secret")])
    reply = instance.call_gemini("question")
    assert "synthetic" not in reply

    def failing(*args, **kwargs):
        raise RuntimeError("secret URL synthetic-first-secret synthetic-second-secret")

    monkeypatch.setattr(httpx, "post", failing)
    assert instance.call_gemini("question") is None
    public = json.dumps(instance.provider_status())
    assert "synthetic" not in public
    assert "RuntimeError" not in public


def test_files_are_private_allowlisted_and_explicit_env_wins(tmp_path, monkeypatch):
    root = tmp_path / ".env"
    local = tmp_path / ".env.local"
    central = tmp_path / "central" / "providers.env"
    central.parent.mkdir()
    root.write_text("GEMINI_API_KEY=file-first\nGEMINI_PRIMARY_MODEL=from-root\nUNRELATED=private\n")
    local.write_text("export GEMINI_API_KEY_2='file-second'\nGEMINI_PRIMARY_MODEL=from-local # note\n")
    central.write_text('VC_TUTOR_CLOUD=1\nGEMINI_PRIMARY_MODEL="from-central"\n')
    (tmp_path / ".env.example").write_text("GOOGLE_API_KEY=template-secret\n")
    (tmp_path / ".env.backup").write_text("MISTRAL_API_KEY=backup-secret\n")
    monkeypatch.delenv("UNRELATED", raising=False)
    monkeypatch.delenv("GEMINI_API_KEY_2", raising=False)
    instance = VCTutor(load_env=True, environ={"GEMINI_PRIMARY_MODEL": "explicit-model"}, data_dir=tmp_path / "state")
    assert instance.cloud_enabled
    assert instance.provider_status()["gemini_key_count"] == 2
    assert instance.provider_status()["gemini_model"] == "explicit-model"
    assert not instance.provider_status()["mistral_key_present"]
    assert "UNRELATED" not in instance._provider_config
    assert "UNRELATED" not in __import__("os").environ
    assert "GEMINI_API_KEY_2" not in __import__("os").environ


def test_keys_alone_do_not_enable_cloud(tmp_path, monkeypatch):
    (tmp_path / ".env").write_text("GEMINI_API_KEY=synthetic-secret\nMISTRAL_API_KEY=synthetic-mistral\n")
    instance = VCTutor(load_env=True, environ={}, data_dir=tmp_path / "state")
    assert not instance.cloud_enabled
    assert instance.provider_status()["gemini_key_count"] == 1
    assert instance.provider_status()["mistral_key_count"] == 1
    monkeypatch.setattr(httpx, "post", lambda *a, **kw: pytest.fail("No cloud consent"))
    assert instance.call_gemini("question") is None
    assert instance.call_mistral("question") is None
    assert instance.call_kilo("question") is None


def test_explicit_offline_does_not_read_process_provider_configuration(tmp_path, monkeypatch):
    monkeypatch.setenv("VC_TUTOR_CLOUD", "1")
    monkeypatch.setenv("GEMINI_API_KEY", "process-key-must-not-be-read")
    instance = VCTutor(cloud=False, load_env=False, data_dir=tmp_path / "state")
    assert not instance.cloud_enabled
    assert instance.provider_status()["gemini_key_count"] == 0


def test_explicit_cloud_false_overrides_consent_file(tmp_path):
    env_file = tmp_path / ".env"
    env_file.write_text("VC_TUTOR_CLOUD=1\nGEMINI_API_KEY=synthetic-key\n")
    instance = VCTutor(load_env=True, environ={"VC_TUTOR_CLOUD": "0"}, data_dir=tmp_path / "state")
    assert not instance.cloud_enabled
    assert instance.provider_status()["gemini_key_count"] == 1


def test_kilo_lazy_adapter_requires_explicit_model(tmp_path, monkeypatch):
    import sys
    from types import ModuleType

    module = ModuleType("academics.vc.kilo_tutor")
    calls = []
    module.run_kilo_tutor = lambda prompt, **kwargs: calls.append((prompt, kwargs)) or "Verified adapter response."
    monkeypatch.setitem(sys.modules, module.__name__, module)
    fake_http(monkeypatch, [Response(429)] * 4)
    instance = tutor(tmp_path, VC_TUTOR_KILO="1")
    assert instance.call_gemini("question") is None
    assert calls == []
    instance._provider_config["VC_TUTOR_KILO_MODEL"] = "verified-model:free"
    assert instance.call_gemini("question", "system") == "Verified adapter response."
    assert calls == [("question", {"system": "system", "model": "verified-model:free", "timeout": 90})]
