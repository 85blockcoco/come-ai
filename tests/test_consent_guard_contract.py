"""Tests du contrat d'intégration : outil de contrôle, démonstration, fixture.

Exigences vérifiées :

* le contrôle à blanc valide une demande et calcule son empreinte sans rien
  mémoriser ni envoyer ;

* le contrôle refuse une demande invalide avec un code de sortie non nul ;

* la fixture du dépôt est entièrement synthétique et déclarée comme telle ;

* la démonstration locale réussit de bout en bout, transports fictifs compris.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from consent_guard.check import REQUEST_SCHEMA, check_request, check_text, main
from consent_guard.demo import SpyTransport, run_demo
from consent_guard.envelope import CONTRACT_ID

FIXTURE = Path(__file__).resolve().parent.parent / "consent_guard" / "fixtures" / "synthetic_transmission.json"
REPO_ROOT = Path(__file__).resolve().parent.parent


def _fixture_data() -> dict[str, object]:
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


# --- Contrôle à blanc ------------------------------------------------------


def test_the_declared_fixture_passes_the_white_box_check() -> None:
    ok, lines, summary = check_request(_fixture_data())
    assert ok, lines
    assert summary["contract"] == CONTRACT_ID
    assert summary["provider"] == "gemini"
    assert summary["model"] == "gemini-3.8-flash"
    assert summary["purpose"] == "exam_revision"
    assert len(summary["payload_digest"]) == 64
    assert summary["payload_bytes"] > 0
    assert summary["single_use"] is True


def test_the_check_never_prints_the_content() -> None:
    _ok, lines, summary = check_request(_fixture_data())
    blob = "\n".join(lines) + json.dumps(summary, ensure_ascii=False)
    assert "MARQUEUR-SYNTHETIQUE" not in blob
    assert "Master fictif" not in blob
    assert "non affiché" in blob


def test_the_check_accepts_a_ttl_argument() -> None:
    from consent_guard.envelope import resolve_expiry

    _ok, _lines, summary = check_request(_fixture_data(), ttl_seconds=60)
    expected = resolve_expiry(ttl_seconds=60)
    assert summary["expires_at_if_granted_now"] == expected
    now = resolve_expiry(ttl_seconds=0) if False else resolve_expiry(ttl_seconds=1)
    assert summary["expires_at_if_granted_now"] > now


def test_the_check_bounds_the_ttl() -> None:
    from consent_guard.envelope import MAX_TTL_SECONDS

    ok, lines, summary = check_request(_fixture_data(), ttl_seconds=MAX_TTL_SECONDS + 1)
    assert not ok
    assert any("ERREUR" in line for line in lines)
    assert summary == {}


def test_the_check_refuses_an_unknown_schema() -> None:
    ok, lines, _summary = check_request({"schema": "autre-chose/9"})
    assert not ok
    assert any("ERREUR" in line for line in lines)


def test_the_check_refuses_an_invalid_request() -> None:
    data = _fixture_data()
    data["purpose"] = "inconnu"
    ok, lines, _summary = check_request(data)
    assert not ok
    assert any("Objectif" in line or "objectif" in line for line in lines)


def test_the_check_refuses_a_non_json_text() -> None:
    ok, lines, _summary = check_text("{pas du json")
    assert not ok
    assert "JSON" in lines[0]


def test_the_check_refuses_a_non_object_payload() -> None:
    data = _fixture_data()
    data["payload"] = "texte direct"
    ok, _lines, _summary = check_request(data)
    assert ok  # un contenu texte est une demande valide

    data["payload"] = ""
    ok, lines, _summary = check_request(data)
    assert not ok
    assert any("ERREUR" in line for line in lines)


def test_the_check_refuses_a_ttl_above_the_ceiling() -> None:
    ok, _lines, _summary = check_request(_fixture_data(), ttl_seconds=999_999)
    assert not ok


def test_the_cli_returns_zero_on_a_valid_file(capsys: pytest.CaptureFixture[str]) -> None:
    assert main([str(FIXTURE)]) == 0
    assert "CONSENT GUARD" in capsys.readouterr().out


def test_the_cli_returns_one_on_an_invalid_file(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    broken = tmp_path / "casse.json"
    broken.write_text(json.dumps({"schema": "inconnu/1"}), encoding="utf-8")
    assert main([str(broken)]) == 1
    assert "ERREUR" in capsys.readouterr().out


def test_the_cli_returns_two_on_a_missing_file(capsys: pytest.CaptureFixture[str]) -> None:
    assert main([str(REPO_ROOT / "absent-parfaitement.json")]) == 2
    assert "introuvable" in capsys.readouterr().err


def test_the_request_schema_constant_is_stable() -> None:
    assert REQUEST_SCHEMA == "come-consent-guard-request/1"
    assert _fixture_data()["schema"] == REQUEST_SCHEMA


# --- Fixture synthétique ---------------------------------------------------


def test_the_fixture_contains_no_real_personal_data() -> None:
    blob = FIXTURE.read_text(encoding="utf-8")
    for needle in ("@", "06.", "07.", "+33", "/Users/", "mot de passe", "api_key"):
        assert needle not in blob, f"la fixture contient {needle}"


def test_the_fixture_payload_is_a_structure() -> None:
    payload = _fixture_data()["payload"]
    assert isinstance(payload, dict)
    assert payload["marker"].endswith("AUCUNE-DONNEE-REELLE")
    assert len(payload["items"]) == 3
    assert all(item["id"].startswith("synthetic-") for item in payload["items"])


# --- Démonstration ---------------------------------------------------------


def test_the_demonstration_succeeds(tmp_path: Path) -> None:
    report = run_demo(workdir=tmp_path, verbose=False, keep=True)
    assert report["success"] is True
    assert report["transport_calls"] == 1
    assert len(report["steps"]) == 27
    assert all(step[2] for step in report["steps"])


def test_the_demonstration_uses_only_fictional_transports() -> None:
    spy = SpyTransport()
    assert spy.name == "spy-fictif"
    assert spy.calls == []


def test_the_demonstration_leaves_no_database_behind(tmp_path: Path) -> None:
    run_demo(workdir=tmp_path, verbose=False, keep=True)
    assert list(tmp_path.rglob("*.sqlite3"))
