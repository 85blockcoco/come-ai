"""Persistent configuration tests use fictitious values only."""
import getpass
import ssl
import warnings
from urllib.error import HTTPError, URLError
from urllib.request import HTTPSHandler, ProxyHandler

import pytest

from devkit.exporting import KitError
from workspace_core import read_dotenv


def test_dotenv_accepts_terminal_export_and_utf8_bom(tmp_path):
    path = tmp_path / ".env"
    path.write_text("export GEMINI_API_KEY='fixture-value'\nCOME_AI_GEMINI_FREE_PROJECT_CONFIRMED=true\n", encoding="utf-8-sig")
    values = read_dotenv(path)
    assert values["GEMINI_API_KEY"] == "fixture-value"
    assert values["COME_AI_GEMINI_FREE_PROJECT_CONFIRMED"] == "true"


def test_hidden_entry_persists_key_without_printing_it(tmp_path, monkeypatch, capsys):
    from devkit.credentials import configure_gemini
    token = "AIza" + "x" * 35
    path = tmp_path / ".env"
    path.write_text("OTHER_SETTING=preserved\nCOME_AI_GEMINI_FREE_PROJECT_CONFIRMED=true\n", encoding="utf-8")
    monkeypatch.setattr("devkit.credentials.getpass.getpass", lambda message: token)
    assert configure_gemini(tmp_path)["configured"] is True
    assert read_dotenv(path)["GEMINI_API_KEY"] == token
    assert read_dotenv(path)["OTHER_SETTING"] == "preserved"
    assert path.stat().st_mode & 0o777 == 0o600
    assert token not in capsys.readouterr().out


def test_unmasked_terminal_fallback_is_refused_before_reading_key(tmp_path, monkeypatch, capsys):
    from devkit.credentials import configure_gemini

    path = tmp_path / ".env"
    original = "OTHER_SETTING=preserved\nCOME_AI_GEMINI_FREE_PROJECT_CONFIRMED=true\n"
    path.write_text(original, encoding="utf-8")
    reached_echo = []

    def unmasked_fallback(message):
        warnings.warn("Cannot control echo on the terminal.", getpass.GetPassWarning)
        reached_echo.append(True)
        return "AIza" + "x" * 35

    monkeypatch.setattr("devkit.credentials.getpass.getpass", unmasked_fallback)
    with pytest.raises(KitError, match="Saisie masquée indisponible"):
        configure_gemini(tmp_path)
    assert reached_echo == []
    assert path.read_text(encoding="utf-8") == original
    captured = capsys.readouterr()
    assert captured.out == captured.err == ""


@pytest.mark.parametrize("value", ["GEMINI_API_KEY=" + "x" * 35, "x" * 257, "x" * 25 + "#"])
def test_malformed_credential_never_changes_existing_configuration(tmp_path, monkeypatch, value):
    from devkit.credentials import configure_gemini

    path = tmp_path / ".env"
    original = "OTHER_SETTING=preserved\nCOME_AI_GEMINI_FREE_PROJECT_CONFIRMED=true\n"
    path.write_text(original, encoding="utf-8")
    monkeypatch.setattr("devkit.credentials.getpass.getpass", lambda message: value)
    with pytest.raises(KitError, match="mal formée"):
        configure_gemini(tmp_path)
    assert path.read_text(encoding="utf-8") == original


def test_hidden_openrouter_entry_preserves_settings_and_is_loadable(tmp_path, monkeypatch, capsys):
    from devkit.credentials import configure_openrouter
    from devkit.evolution_providers import ProviderSettings, _credential, status_provider

    token = "sk-or-v1-" + "a1" * 32
    path = tmp_path / ".env"
    path.write_text("# Preserve the configuration\nOTHER_SETTING=preserved\n"
                    "export OPENROUTER_API_KEY=obsolete\nOPENROUTER_API_KEY=duplicate\n"
                    "COME_AI_GEMINI_FREE_PROJECT_CONFIRMED=true\n", encoding="utf-8-sig")
    monkeypatch.setattr("devkit.credentials.getpass.getpass", lambda message: token)
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    result = configure_openrouter(tmp_path)
    assert result == {"configured": True, "configuration_loadable": True, "authentication_verified": False}
    assert _credential(tmp_path, "OPENROUTER_API_KEY") == token
    settings = ProviderSettings("openrouter", "fictional/model:free", allow_remote=True)
    status = status_provider(tmp_path, settings)
    assert status["configured"] is True
    assert status["availability"] == "unknown"
    assert token not in str(status) + str(result)
    assert read_dotenv(path)["OTHER_SETTING"] == "preserved"
    assert read_dotenv(path)["COME_AI_GEMINI_FREE_PROJECT_CONFIRMED"] == "true"
    assert path.read_text().count("OPENROUTER_API_KEY=") == 1
    assert "# Preserve the configuration" in path.read_text()
    assert path.stat().st_mode & 0o777 == 0o600
    captured = capsys.readouterr()
    assert captured.out == captured.err == ""


@pytest.mark.parametrize("value", ["", "sk-or-v1-" + "a" * 63,
                                   "sk-or-v1-" + "z" * 64,
                                   "OPENROUTER_API_KEY=" + "a" * 64,
                                   "sk-or-v1-" + "a" * 64 + "\nOTHER=value"])
def test_malformed_openrouter_entry_leaves_existing_file_unchanged(tmp_path, monkeypatch, value):
    from devkit.credentials import configure_openrouter

    path = tmp_path / ".env"
    original = "OTHER_SETTING=preserved\n"
    path.write_text(original)
    monkeypatch.setattr("devkit.credentials.getpass.getpass", lambda message: value)
    with pytest.raises(KitError, match="mal formée"):
        configure_openrouter(tmp_path)
    assert path.read_text() == original


def test_openrouter_refuses_unmasked_terminal_without_mutation(tmp_path, monkeypatch):
    from devkit.credentials import configure_openrouter

    path = tmp_path / ".env"
    path.write_text("OTHER_SETTING=preserved\n")
    echoed = []

    def fallback(message):
        warnings.warn("Cannot control echo on the terminal.", getpass.GetPassWarning)
        echoed.append(True)
        return "sk-or-v1-" + "a" * 64

    monkeypatch.setattr("devkit.credentials.getpass.getpass", fallback)
    with pytest.raises(KitError, match="Saisie masquée indisponible"):
        configure_openrouter(tmp_path)
    assert echoed == []
    assert path.read_text() == "OTHER_SETTING=preserved\n"


def test_credential_configuration_refuses_symlink_before_reading_input(tmp_path, monkeypatch):
    from devkit.credentials import configure_openrouter

    other = tmp_path / "private-file"
    other.write_text("OTHER_SETTING=preserved\n")
    (tmp_path / ".env").symlink_to(other)
    monkeypatch.setattr("devkit.credentials.getpass.getpass", lambda message: pytest.fail("input must not be read"))
    with pytest.raises(KitError, match="lien symbolique"):
        configure_openrouter(tmp_path)
    assert other.read_text() == "OTHER_SETTING=preserved\n"


def test_configure_openrouter_cli_does_not_send_cloud_request_or_echo_key(tmp_path, monkeypatch, capsys):
    from devkit.__main__ import main

    token = "sk-or-v1-" + "ab" * 32
    monkeypatch.setattr("devkit.credentials.getpass.getpass", lambda message: token)
    monkeypatch.setattr("devkit.evolution_providers.bounded_json_transport", lambda *args: pytest.fail("no network"))
    assert main(["--project", str(tmp_path), "configure-openrouter"]) == 0
    assert read_dotenv(tmp_path / ".env")["OPENROUTER_API_KEY"] == token
    output = capsys.readouterr()
    assert token not in output.out + output.err
    assert "Aucun appel API" in output.out


def test_https_transport_uses_verified_certifi_context_and_keeps_no_proxy_or_redirect(monkeypatch):
    import devkit.evolution_providers as providers

    captured = {}

    class Response:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def read(self, limit):
            assert limit == providers.MAX_RESPONSE_BYTES + 1
            return b'{"data": []}'

    class Opener:
        def open(self, request, timeout):
            captured["timeout"] = timeout
            return Response()

    def opener(*handlers):
        captured["handlers"] = handlers
        return Opener()

    monkeypatch.setattr(providers, "build_opener", opener)
    assert providers.bounded_json_transport("GET", providers.OPENROUTER_MODELS_URL, {}, None, 5) == {"data": []}
    handlers = captured["handlers"]
    https = next(handler for handler in handlers if isinstance(handler, HTTPSHandler))
    assert https._context.verify_mode == ssl.CERT_REQUIRED
    assert https._context.check_hostname is True
    assert https._context.cert_store_stats()["x509_ca"] > 0
    assert next(handler for handler in handlers if isinstance(handler, ProxyHandler)).proxies == {}
    assert any(isinstance(handler, providers._NoRedirect) for handler in handlers)
    assert captured["timeout"] == 5


def test_loopback_transport_does_not_require_certifi_context(monkeypatch):
    import devkit.evolution_providers as providers

    class Response:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def read(self, limit):
            return b'{"models": []}'

    class Opener:
        def open(self, *args, **kwargs):
            return Response()

    monkeypatch.setattr(providers, "build_opener", lambda *args: Opener())
    monkeypatch.setattr(providers.ssl, "create_default_context", lambda **kwargs: pytest.fail("offline transport must not load TLS"))
    assert providers.bounded_json_transport("GET", "http://127.0.0.1:11434/api/tags", {}, None, 5) == {"models": []}


@pytest.mark.parametrize("error_kind", ["tls", "http"])
def test_transport_errors_never_expose_upstream_details_or_body(monkeypatch, error_kind):
    import devkit.evolution_providers as providers

    sensitive = "fictional-credential-" + "x" * 30
    body_read = []

    class UnsafeBody:
        def read(self, *args):
            body_read.append(True)
            return sensitive.encode()

        def close(self):
            pass

    class Opener:
        def open(self, *args, **kwargs):
            if error_kind == "tls":
                raise URLError(sensitive)
            raise HTTPError(providers.OPENROUTER_MODELS_URL, 401, sensitive, {}, UnsafeBody())

    monkeypatch.setattr(providers, "build_opener", lambda *args: Opener())
    with pytest.raises(providers.ProviderUnavailable) as failure:
        providers.bounded_json_transport("GET", providers.OPENROUTER_MODELS_URL, {}, None, 5)
    assert sensitive not in str(failure.value)
    assert body_read == []
