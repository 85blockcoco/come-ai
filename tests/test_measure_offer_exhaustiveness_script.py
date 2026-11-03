"""Tests du script de mesure SK-20 (scripts/measure_offer_exhaustiveness.py).

Vérifie le contrat critical du script : il mesure un corpus qui lui est
passé, il échoue explicitement (exit 1 + message JSON) au lieu d'inventer
une donnée quand la base locale est absente, et --check applique le seuil.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = PROJECT_ROOT / "scripts" / "measure_offer_exhaustiveness.py"


def _run(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run([sys.executable, str(SCRIPT), *args],
                          capture_output=True, text=True, cwd=PROJECT_ROOT)


def test_fixture_corpus_measures_without_check_passes():
    result = _run("--fixtures")
    assert result.returncode == 0, result.stderr
    report = json.loads(result.stdout)
    assert report["jobs"] >= 15          # la mission exige 15+ fixtures mesurées
    assert report["distribution"].keys() >= {"green", "orange", "red", "gray"}
    assert 0 <= report["average"] <= 100


def test_missing_db_fails_explicitly_never_invents():
    # Pas mention du --check : le script doit refuser de mesurer sans base.
    missing = PROJECT_ROOT / "career_data" / "career_do_not_create.sqlite3"
    result = _run("--db", str(missing))
    assert result.returncode == 1
    payload = json.loads(result.stdout)
    assert "error" in payload and "Aucune" not in payload  # message lisible fourni
    assert "introuvable" in payload["error"]


def test_check_flag_enforces_threshold():
    above = _run("--fixtures", "--check", "10")
    below = _run("--fixtures", "--check", "90")
    assert above.returncode == 0
    assert below.returncode == 1
    assert "sous le seuil" in below.stderr


if __name__ == "__main__":  # pragma: no cover
    import pytest
    pytest.main([__file__, "-v"])
