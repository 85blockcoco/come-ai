"""All Keychain operations are simulated; no real account or HOME is touched."""

from __future__ import annotations

import io
import re
import subprocess

import pytest

from academics.vc import keychain


class Store:
    def __init__(self):
        self.values = {}
        self.calls = []

    def __call__(self, args, **kwargs):
        self.calls.append((args, kwargs))
        assert kwargs["capture_output"] and kwargs["text"]
        assert "shell" not in kwargs
        if args == ["/usr/bin/security", "-i", "-q"]:
            match = re.search(r" -s ([^ ]+) -w ([^ ]+) ", kwargs["input"])
            self.values[match[1]] = match[2]
            return subprocess.CompletedProcess(args, 0, "", "")
        service = args[args.index("-s") + 1]
        value = self.values.get(service)
        return subprocess.CompletedProcess(args, 0 if value else 44, (value + "\n") if value else "", "")


@pytest.fixture(autouse=True)
def forbid_real_keychain(monkeypatch):
    monkeypatch.setattr(keychain.subprocess, "run", lambda *a, **kw: pytest.fail("Real Keychain access"))


def test_write_stdin_only_and_verified_persistent_read(tmp_path):
    runner = Store()
    secret = "synthetic_key_1234567890"
    keychain.write_key(2, secret, runner=runner, keychain=tmp_path / "fake.keychain")
    assert runner.calls[0][0] == ["/usr/bin/security", "-i", "-q"]
    assert all(secret not in " ".join(args) for args, _ in runner.calls)
    assert secret in runner.calls[0][1]["input"]
    assert len(runner.calls) == 2  # Write plus verification read.
    assert keychain.read_key(2, runner=runner, keychain=tmp_path / "fake.keychain") == secret
    assert keychain.gemini_key_environment(runner=runner, keychain=tmp_path / "fake.keychain") == {"GEMINI_API_KEY_2": secret}


@pytest.mark.parametrize("slot", [0, 4, -1, True, "1", None])
def test_invalid_slots_never_run(slot):
    with pytest.raises(keychain.KeychainError):
        keychain.read_key(slot, runner=lambda *a, **kw: pytest.fail("Invalid slot"))


@pytest.mark.parametrize(
    "value", ["short", "x" * 257, "secret\n" + "x" * 30, "x" * 30 + "\r", "é" * 30, "x" * 30 + '"', "x" * 30 + ";", "x" * 30 + " "]
)
def test_invalid_values_never_run(value):
    with pytest.raises(keychain.KeychainError):
        keychain.write_key(1, value, runner=lambda *a, **kw: pytest.fail("Invalid token"))


def test_errors_never_include_subprocess_secret(tmp_path):
    secret = "synthetic_secret_1234567890"

    def broken(*args, **kwargs):
        raise RuntimeError(secret)

    with pytest.raises(keychain.KeychainError) as caught:
        keychain.write_key(1, secret, runner=broken, keychain=tmp_path / "fake")
    assert secret not in str(caught.value)
    assert caught.value.__suppress_context__


def test_read_error_and_invalid_stored_value_are_private():
    for code, value in [(1, "private-token-123456789"), (0, "bad\nsecret")]:
        with pytest.raises(keychain.KeychainError) as caught:
            keychain.read_key(1, runner=lambda *args, **kw: subprocess.CompletedProcess(args, code, value, value))
        assert value not in str(caught.value)


def test_verification_mismatch_fails():
    def runner(args, **kwargs):
        return subprocess.CompletedProcess(args, 0, "wrong_key_123456789012345", "")

    with pytest.raises(keychain.KeychainError, match="verification"):
        keychain.write_key(1, "synthetic_key_1234567890", runner=runner)


def test_flags_atomic_private_and_preserve_lines(tmp_path):
    target = tmp_path / "providers.env"
    target.write_text("# keep\nOTHER=value\nVC_TUTOR_CLOUD=0\nVC_TUTOR_CLOUD=0\n")
    keychain.write_provider_flags(target)
    text = target.read_text()
    assert "# keep\nOTHER=value\n" in text
    assert text.count("VC_TUTOR_CLOUD=1") == 1
    assert "VC_TUTOR_KILO=1" in text
    assert "kilo/nvidia/nemotron-3.5-super-vl:free" in text
    assert target.stat().st_mode & 0o777 == 0o600
    assert not list(tmp_path.glob(".providers-*"))
    assert "GEMINI_API_KEY" not in text


def test_flags_reject_symlink_and_symlink_parent(tmp_path):
    real = tmp_path / "real"
    real.mkdir()
    link = tmp_path / "link"
    link.symlink_to(real, target_is_directory=True)
    with pytest.raises(keychain.KeychainError):
        keychain.write_provider_flags(link / "providers.env")
    file = real / "original"
    file.write_text("preserved")
    target = real / "providers.env"
    target.symlink_to(file)
    with pytest.raises(keychain.KeychainError):
        keychain.write_provider_flags(target)
    assert file.read_text() == "preserved"


def test_setup_refuses_noninteractive_before_keychain(tmp_path):
    with pytest.raises(keychain.KeychainError, match="interactive"):
        keychain.setup(input_stream=io.StringIO(), provider_path=tmp_path / "flags", runner=lambda *a, **kw: pytest.fail("Non TTY"))
    assert not (tmp_path / "flags").exists()


class Terminal(io.StringIO):
    def isatty(self):
        return True


def test_setup_keep_existing_duplicate_warning_and_reload(tmp_path):
    runner = Store()
    secret = "synthetic_key_1234567890"
    runner.values = {f"ai.come.nage.gemini.{slot}": secret for slot in (1, 2, 3)}
    output = io.StringIO()
    prompts, reloads = [], []
    result = keychain.setup(
        runner=runner,
        keychain=tmp_path / "fake",
        provider_path=tmp_path / "flags",
        input_stream=Terminal(),
        prompt=lambda label: prompts.append(label) or "",
        output=output,
        reload_callback=lambda: reloads.append(True) or True,
    )
    assert result == 0
    assert len(prompts) == 3
    assert reloads == [True]
    assert "duplicate" in output.getvalue()
    assert "3 Gemini slots" in output.getvalue()
    assert secret not in output.getvalue()
    assert all(args[1] == "find-generic-password" for args, _ in runner.calls)


def test_failed_setup_never_writes_plaintext_or_flags(tmp_path):
    with pytest.raises(keychain.KeychainError):
        keychain.setup(
            runner=Store(), keychain=tmp_path / "fake", provider_path=tmp_path / "flags", input_stream=Terminal(), prompt=lambda label: ""
        )
    assert not (tmp_path / "flags").exists()


def test_reload_is_empty_local_post_without_inference():
    seen = []

    class Response:
        status = 200

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return None

    def opener(request, **kwargs):
        seen.append(request)
        return Response()

    assert keychain.reload_tutor(opener=opener)
    assert len(seen) == 1
    assert seen[0].full_url == "http://127.0.0.1:8765/api/vc/tutor/reload"
    assert seen[0].get_method() == "POST"
    assert seen[0].data == b"{}"


def test_status_only_counts_slots(monkeypatch, capsys):
    secret = "synthetic_key_1234567890"
    monkeypatch.setattr(keychain, "gemini_key_environment", lambda: {"GEMINI_API_KEY": secret})
    assert keychain.main(["--status"]) == 0
    output = capsys.readouterr().out
    assert "1/3" in output and "Slot 1: present" in output
    assert secret not in output


def test_platform_guard_has_no_plaintext_fallback(monkeypatch):
    monkeypatch.setattr(keychain, "_available", lambda: False)
    with pytest.raises(keychain.KeychainError, match="unavailable"):
        keychain.read_key(1)
