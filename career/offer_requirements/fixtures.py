"""Loader for the bundled synthetic multilingual offers (FR/EN/DE/IT/ES).

The fixtures are synthetic by construction: fake companies, fake offers, no
personal data and no real posting text.  They feed both the test suite and
the short benchmark shipped with this package.  Loader failures surface as
``ValueError`` rather than silently returning partial data: a benchmark run
on a truncated fixture set would understate coverage.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

FIXTURES_PATH = Path(__file__).resolve().parent / "fixtures" / "synthetic_offers.json"

MIN_FIXTURES = 35
FIXTURE_LANGUAGES = frozenset({"fr", "en", "de", "it", "es"})


def load_fixtures() -> list[dict[str, Any]]:
    """Return the synthetic offer fixtures, validated for count and language."""
    with FIXTURES_PATH.open("r", encoding="utf-8") as handle:
        fixtures = json.load(handle)
    if not isinstance(fixtures, list) or len(fixtures) < MIN_FIXTURES:
        raise ValueError(
            f"Le jeu de fixtures sous {FIXTURES_PATH.name} doit contenir "
            f"au moins {MIN_FIXTURES} offres synthétiques (lu : {len(fixtures) if isinstance(fixtures, list) else 'invalide'})."
        )
    languages: set[str] = set()
    seen_ids: set[str] = set()
    for fixture in fixtures:
        if not isinstance(fixture, dict) or not fixture.get("id"):
            raise ValueError("Chaque fixture doit être un objet avec un 'id'.")
        offer_id = str(fixture["id"])
        if offer_id in seen_ids:
            raise ValueError(f"Identifiant de fixture dupliqué : {offer_id}")
        seen_ids.add(offer_id)
        language = str(fixture.get("language") or fixture.get("lang", "")).lower()
        if language not in FIXTURE_LANGUAGES:
            raise ValueError(
                f"L'offre synthétique {offer_id} doit déclarer une langue parmi {sorted(FIXTURE_LANGUAGES)}."
            )
        languages.add(language)
    if languages != FIXTURE_LANGUAGES:
        raise ValueError(
            f"Le jeu de fixtures doit couvrir {sorted(FIXTURE_LANGUAGES)} (lu : {sorted(languages)})."
        )
    return fixtures
