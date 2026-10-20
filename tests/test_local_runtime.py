"""Project-local startup tests: no binary execution, downloads or provider calls."""
from local_ai_runtime import ensure_local_runtime


def test_existing_runtime_is_reused_without_install_or_start(tmp_path, monkeypatch):
    monkeypatch.setattr("local_ai_runtime.local_status", lambda: {"running": True, "version": "fixture"})
    monkeypatch.setattr("local_ai_runtime.subprocess.Popen", lambda *a, **k: (_ for _ in ()).throw(AssertionError("must not launch")))
    assert ensure_local_runtime(tmp_path)["started"] is False
    assert not (tmp_path / ".local-ai").exists()


def test_missing_runtime_never_installs_or_downloads(tmp_path, monkeypatch):
    monkeypatch.setattr("local_ai_runtime.local_status", lambda: {"running": False, "version": None})
    result = ensure_local_runtime(tmp_path)
    assert result["running"] is False
    assert not (tmp_path / ".local-ai").exists()


def test_new_runtime_denies_external_network_and_drops_credentials(tmp_path, monkeypatch):
    binary = tmp_path / ".local-ai" / "ollama" / "v0.40.3" / "ollama"
    binary.parent.mkdir(parents=True)
    binary.write_text("fixture", encoding="utf-8")
    fake_sandbox = tmp_path / "sandbox-exec"
    fake_sandbox.write_text("#!/bin/sh\n", encoding="utf-8")
    monkeypatch.setattr("local_ai_runtime.SANDBOX_EXEC", fake_sandbox)
    statuses = iter([{"running": False, "version": None}, {"running": True, "version": "fixture"}])
    monkeypatch.setattr("local_ai_runtime.local_status", lambda: next(statuses))
    monkeypatch.setenv("GEMINI_API_KEY", "fictional-do-not-propagate")
    monkeypatch.setenv("OPENROUTER_API_KEY", "fictional-do-not-propagate")
    monkeypatch.setenv("HTTPS_PROXY", "http://fictional-proxy.invalid")
    captured = {}

    class FakeProcess:
        pid = 12345
        def poll(self):
            return None

    def start(command, **kwargs):
        captured.update(command=command, **kwargs)
        return FakeProcess()

    monkeypatch.setattr("local_ai_runtime.subprocess.Popen", start)
    result = ensure_local_runtime(tmp_path)
    assert result["network_isolated"] is True
    assert captured["command"][:2] == [str(fake_sandbox), "-p"]
    assert "(deny network*)" in captured["command"][2]
    assert captured["env"]["OLLAMA_NO_CLOUD"] == "1"
    assert all(name not in captured["env"] for name in ("GEMINI_API_KEY", "OPENROUTER_API_KEY", "HTTPS_PROXY"))
    assert captured["env"]["OLLAMA_HOST"] == "127.0.0.1:11434"
    assert captured["env"]["OLLAMA_MAX_LOADED_MODELS"] == "1"
