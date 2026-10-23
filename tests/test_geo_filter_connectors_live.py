"""SK-11 — Contrôle réel borné du filtre pays (opt-in).

Ce module est séparé de la suite synthétique : il contacte **un** board
Greenhouse public et vérifie que le filtre pays tient sur les faits publiés
par la source.  Il est ignoré par défaut.

    CAREER_GEO_LIVE=1 .venv/bin/python -m pytest -q tests/test_geo_filter_connectors_live.py

Le contrôle est borné : un seul board, un seul appel réseau, aucune écriture
locale.  Il ne modifie aucune donnée et ne crée aucun dossier.
"""

from __future__ import annotations

import os

import pytest

from career.discovery import GreenhouseBoard, GreenhouseJobBoardConnector
from career.stage_search import default_brief

LIVE_BOARD = ("lincolninternational", "Lincoln International")
ENV_FLAG = "CAREER_GEO_LIVE"

pytestmark = pytest.mark.skipif(
    os.environ.get(ENV_FLAG, "") != "1",
    reason=f"contrôle réseau ignoré :Exporter {ENV_FLAG}=1 pour le lancer",
)


def test_a_real_board_never_returns_a_french_offer():
    """Un board réel : zéro offre française, et le filtre compte ses refus."""
    token, company = LIVE_BOARD
    connector = GreenhouseJobBoardConnector()
    payload = connector.discover_internships(
        GreenhouseBoard(f"live:{token}", company, token),
        selection_brief=default_brief(),
        countries_exclude=["FR"],
    )
    kept_countries = {str(job.get("country_canonical") or "") for job in payload.jobs}
    assert "FR" not in kept_countries
    assert payload.offers_filtered_geo == payload.country_excluded_count
    # The board publishes French postings: the filter must have refused some.
    assert payload.offers_filtered_geo > 0, payload.excluded_by_country
    assert payload.excluded_by_country.get("FR", 0) == payload.offers_filtered_geo


def test_a_real_board_can_be_read_without_the_filter():
    """The same board without the filter shows what the filter refused."""
    token, company = LIVE_BOARD
    connector = GreenhouseJobBoardConnector()
    payload = connector.discover_internships(
        GreenhouseBoard(f"live:{token}", company, token),
        selection_brief=default_brief(),
        countries_exclude=[],
    )
    assert payload.offers_filtered_geo == 0
    assert payload.excluded_by_country == {}
