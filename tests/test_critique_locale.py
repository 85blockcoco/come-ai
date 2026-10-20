"""Tests du critique locale bornée (Ollama, hôte local uniquement)."""
from __future__ import annotations

import json
import urllib.request
from pathlib import Path

import pytest

from scripts import critique_locale


class FakeResponse:
    def __init__(self, payload: dict) -> None:
        self._payload = payload

    def read(self, *_args: int) -> bytes:
        return json.dumps(self._payload).encode("utf-8")

    def __enter__(self) -> "FakeResponse":
        return self

    def __exit__(self, *_args: object) -> None:
        return None


def test_local_url_accepts_localhost_only() -> None:
    assert critique_locale.local_url("http://127.0.0.1:11434/") == "http://127.0.0.1:11434"
    assert critique_locale.local_url("http://localhost:11434") == "http://localhost:11434"
    with pytest.raises(ValueError):
        critique_locale.local_url("http://example.com:11434")
    with pytest.raises(ValueError):
        critique_locale.local_url("http://192.168.1.10:11434")


@pytest.mark.parametrize(("response", "expected"), [
    ("OUI\nLa date figure bien dans le texte.", "OUI"),
    ("NON : le texte ne mentionne aucun salaire.", "NON"),
    ("INCERTAIN, l'information n'est pas fournie.", "INCERTAIN"),
    ("Je ne peux pas répondre.", "INCERTAIN"),
])
def test_ask_local_model_parses_verdicts(monkeypatch, response: str, expected: str) -> None:
    captured: dict = {}

    def fake_urlopen(request, timeout):  # noqa: ANN001
        captured.update(json.loads(request.data.decode("utf-8")), timeout=timeout)
        captured["url"] = request.full_url
        return FakeResponse({"response": response})

    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)
    verdict = critique_locale.ask_local_model(
        question="Le texte mentionne-t-il une date ?", text="Clôture le 31 mars.",
        url="http://127.0.0.1:11434", model="qwen3.5:2b-q4_K_M", timeout=5,
    )
    assert verdict["verdict"] == expected
    assert captured["url"] == "http://127.0.0.1:11434/api/generate"
    assert captured["model"] == "qwen3.5:2b-q4_K_M"
    assert captured["stream"] is False
    assert "INCERTAIN" in captured["system"]
    assert "Clôture le 31 mars." in captured["prompt"]


def test_main_writes_verdict_file(monkeypatch, tmp_path: Path, capsys) -> None:
    monkeypatch.setattr(urllib.request, "urlopen",
                        lambda request, timeout: FakeResponse({"response": "NON\nAucune date présente."}))
    output = tmp_path / "verdict.json"
    code = critique_locale.main([
        "--question", "Y a-t-il une date ?", "--text", "Aucun calendrier.",
        "--output", str(output),
    ])
    assert code == 0
    saved = json.loads(output.read_text(encoding="utf-8"))
    assert saved["verdict"] == "NON"
    assert "Aucune date" in capsys.readouterr().out


def test_main_refuses_empty_text_and_reports_errors(monkeypatch, capsys) -> None:
    assert critique_locale.main(["--question", "Q ?", "--text", "   "]) == 2

    def broken(request, timeout):  # noqa: ANN001
        raise OSError("modèle local injoignable")

    monkeypatch.setattr(urllib.request, "urlopen", broken)
    assert critique_locale.main(["--question", "Q ?", "--text", "du texte"]) == 2
    assert "injoignable" in capsys.readouterr().err
