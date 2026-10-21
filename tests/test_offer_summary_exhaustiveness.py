"""Test de non-régression : l'exhaustivité des résumés d'offres ne doit pas baisser."""
from __future__ import annotations

import pytest
from pathlib import Path

# Never import code or open a private database from another checkout.  The
# guard is meaningful only against the code and optional test database of the
# worktree that pytest is currently validating.
PROJECT_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = PROJECT_ROOT / "scripts" / "measure_exhaustiveness.py"
DB = PROJECT_ROOT / "career_data" / "career.sqlite3"

# SEUIL DE NON-RÉGRESSION = baseline actuelle (2026-10-20) pour que la CI passe.
# Ce seuil SERA MONTE après chaque mission de la vague 2 :
# - après O1 (exhaustivité du résumé) : cible 35 %
# - après O2 (scoring préférences + exclusion France) : cible 55 %
# - objectif final (vague 2 complète) : >= 70 %
NON_REGRESSION_THRESHOLD = 10.5  # baseline 2026-10-20, ne pas baisser


def test_exhaustivity_guard():
    if not SCRIPT.is_file() or not DB.is_file():
        pytest.skip("script ou base absents")
    from scripts.measure_exhaustiveness import measure
    report = measure(DB, threshold=NON_REGRESSION_THRESHOLD)
    if report.get("error"):
        pytest.skip("base locale du worktree sans offre mesurable")
    # Seuil de non-régression : l'exhaustivité globale 'fiche' ne doit pas
    # descendre sous la baseline (10,5 % au 2026-10-20). Ce seuil montera
    # après chaque mission de la vague 2 (voir commentaire ci-dessus).
    assert report["global"]["fiche_pct"] >= NON_REGRESSION_THRESHOLD, (
        f"RÉGRESSION : exhaustivité globale fiche = {report['global']['fiche_pct']:.1f}% "
        f"< {NON_REGRESSION_THRESHOLD:.1f}% (baseline). "
        f"Gap vs page : {report['global']['gap']:.1f} pts. "
        f"Champs sous la baseline : "
        + ", ".join(f"{k} ({v['fiche_pct']:.1f}%)" for k, v in report["per_field"].items() if v["fiche_pct"] < NON_REGRESSION_THRESHOLD)
    )


if __name__ == "__main__":
    import pytest
    pytest.main([__file__, "-v"])
