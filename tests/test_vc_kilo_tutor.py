from __future__ import annotations

import json
from pathlib import Path
import subprocess

import pytest

from academics.vc import kilo_tutor as kilo


MODEL = "kilo/cohere/north-mini-code:free"


@pytest.fixture
def cli(monkeypatch):
    calls = []
    monkeypatch.setattr(kilo.shutil, "which", lambda name: "/synthetic/bin/kilo")
    monkeypatch.delenv("VC_TUTOR_KILO_MODEL", raising=False)

    def fake_run(argv, **kwargs):
        calls.append((argv, kwargs))
        cfg = json.loads(kwargs["env"]["KILO_CONFIG_CONTENT"])
        if argv[1:] == ["--version"]:
            output = "7.8.18\n"
        elif argv[1:3] == ["debug", "config"]:
            output = json.dumps(cfg)
        elif argv[1:3] == ["debug", "agent"]:
            output = json.dumps({
                "name": kilo._AGENT, "mode": "primary", "prompt": kilo._PROMPT,
                "tools": {"read": False, "bash": False, "webfetch": False},
            })
        else:
            output = "\n".join(json.dumps(e) for e in [
                {"type": "step_start", "part": {"type": "step-start"}},
                {"type": "text", "part": {"type": "text", "text": "Synthetic answer", "time": {"end": 1}}},
                {"type": "step_finish", "part": {"type": "step-finish", "reason": "stop"}},
            ])
        return subprocess.CompletedProcess(argv, 0, output, "synthetic stderr secret")

    monkeypatch.setattr(kilo.subprocess, "run", fake_run)
    return calls, fake_run


def test_stdin_no_shell_pristine_directory_and_secret_free_environment(cli, monkeypatch):
    calls, _ = cli
    monkeypatch.setenv("SYNTHETIC_API_KEY", "must-not-propagate")
    monkeypatch.setenv("KILO_CONFIG", "/synthetic/unsafe.json")
    prompt = "Course question $(touch /tmp/never) `never`; --command build"
    assert kilo.run_kilo_tutor(prompt, system="Synthetic course", model=MODEL) == "Synthetic answer"
    assert len(calls) == 4
    directory = calls[0][1]["cwd"]
    assert not Path(directory).exists()
    for argv, kwargs in calls:
        assert isinstance(argv, list) and argv[0] == "/synthetic/bin/kilo"
        assert kwargs["shell"] is False and kwargs["capture_output"] is True
        assert kwargs["cwd"] == directory and kwargs["timeout"] <= 90
        assert prompt not in argv and "Synthetic course" not in argv
        assert kwargs["env"]["HOME"] == str(Path.home())
        assert kwargs["env"]["KILO_TEST_HOME"] == directory
        assert kwargs["env"]["KILO_PERMISSION"] == '{"*": "deny"}'
        assert "SYNTHETIC_API_KEY" not in kwargs["env"]
        assert "KILO_CONFIG" not in kwargs["env"]
        assert "--auto" not in argv and "--command" not in argv
    assert calls[-1][1]["input"] == "Synthetic course\n\n" + prompt
    assert calls[-1][0][1:3] == ["run", "--pure"]


@pytest.mark.parametrize("model", [None, "kilo/paid/model", "kilo/kilo-auto/free", "--command build"])
def test_requires_explicit_verified_free_model(cli, model):
    calls, _ = cli
    with pytest.raises(kilo.KiloTutorError):
        kilo.run_kilo_tutor("Synthetic question", model=model)
    assert calls == []


def test_env_model_is_explicit_opt_in(cli, monkeypatch):
    monkeypatch.setenv("VC_TUTOR_KILO_MODEL", MODEL)
    assert kilo.run_kilo_tutor("Synthetic question") == "Synthetic answer"


@pytest.mark.parametrize("stage", ["version", "config", "agent", "run"])
def test_cli_failure_is_generic_and_never_returns_raw_output(cli, monkeypatch, stage):
    calls, original = cli
    index = {"version": 1, "config": 2, "agent": 3, "run": 4}[stage]

    def fail(argv, **kwargs):
        if len(calls) + 1 == index:
            return subprocess.CompletedProcess(argv, 1, "SECRET", "SECRET")
        return original(argv, **kwargs)

    monkeypatch.setattr(kilo.subprocess, "run", fail)
    with pytest.raises(kilo.KiloTutorError) as error:
        kilo.run_kilo_tutor("Synthetic", model=MODEL)
    assert "SECRET" not in str(error.value)


def test_timeout_is_generic(cli, monkeypatch):
    monkeypatch.setattr(kilo.subprocess, "run", lambda *a, **kw: (_ for _ in ()).throw(
        subprocess.TimeoutExpired("SECRET", 1, output="SECRET", stderr="SECRET")))
    with pytest.raises(kilo.KiloTutorError) as error:
        kilo.run_kilo_tutor("Synthetic", model=MODEL, timeout=1)
    assert "SECRET" not in str(error.value)


@pytest.mark.parametrize("mutation", ["enabled_tool", "changed_prompt", "provider", "share", "bad_json"])
def test_unsafe_effective_configuration_fails_before_inference(cli, monkeypatch, mutation):
    calls, original = cli

    def unsafe(argv, **kwargs):
        result = original(argv, **kwargs)
        if argv[1:3] == ["debug", "config"] and mutation in {"provider", "share", "bad_json"}:
            cfg = json.loads(result.stdout)
            if mutation == "provider":
                cfg["provider"] = {"kilo": {"options": {"baseURL": "https://synthetic.invalid"}}}
            elif mutation == "share":
                cfg["share"] = "auto"
            result.stdout = "SECRET invalid json" if mutation == "bad_json" else json.dumps(cfg)
        if argv[1:3] == ["debug", "agent"]:
            cfg = json.loads(result.stdout)
            if mutation == "enabled_tool":
                cfg["tools"]["read"] = True
            elif mutation == "changed_prompt":
                cfg["prompt"] = "Build things"
            result.stdout = json.dumps(cfg)
        return result

    monkeypatch.setattr(kilo.subprocess, "run", unsafe)
    with pytest.raises(kilo.KiloTutorError):
        kilo.run_kilo_tutor("Synthetic", model=MODEL)
    assert all(argv[1] != "run" for argv, _ in calls)


@pytest.mark.parametrize("output", ["SECRET", "{}", '{"type":"error","error":"SECRET"}',
    '{"type":"tool_use","part":{"text":"SECRET"}}',
    '{"type":"text","part":{"type":"text","text":"partial","time":{"end":1}}}',
    '{"type":"step_finish","part":{"reason":"length"}}'])
def test_malformed_error_tool_or_incomplete_output_fails_closed(cli, monkeypatch, output):
    _, original = cli

    def malformed(argv, **kwargs):
        result = original(argv, **kwargs)
        if argv[1] == "run":
            result.stdout = output
        return result

    monkeypatch.setattr(kilo.subprocess, "run", malformed)
    with pytest.raises(kilo.KiloTutorError) as error:
        kilo.run_kilo_tutor("Synthetic", model=MODEL)
    assert "SECRET" not in str(error.value)
