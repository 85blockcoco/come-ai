"""SK-11 — bounded live read of one real public Greenhouse board.

This file is deliberately separated from the synthetic corpus of
``test_geo_filter_connectors.py``.  It contacts one public board, reads it
once, and proves on real published wording that:

* the country filter removes the postings published in an excluded country
  before they are qualified (``filtered_geo_count > 0``);
* no kept posting is published only in an excluded country;
* a posting published in several countries, one of which is excluded, stays
  visible.

The test never writes anything, never follows an arbitrary URL and never
sends an application.  It is skipped unless ``CAREER_LIVE_TESTS=1`` is set,
so the default suite stays offline.

Run it with::

    CAREER_LIVE_TESTS=1 .venv/bin/python -m pytest -q tests/test_geo_filter_connectors_live.py
"""

from __future__ import annotations

import os

import pytest

from career.discovery import GreenhouseBoard, GreenhouseJobBoardConnector
from career.geo import country_codes_in
from career.stage_search import default_brief


LIVE = os.environ.get("CAREER_LIVE_TESTS") == "1"

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(not LIVE, reason="lecture live d'un board public : CAREER_LIVE_TESTS=1"),
]

# A public board that publishes both French and non-French postings.
BOARD = GreenhouseBoard(id="live-public-board", company="Datadog", board_token="datadog")
EXCLUDED = ("FR",)


def _published_codes(job: dict) -> set[str]:
    """Every country the board published for one posting."""
    codes = set(country_codes_in(job.get("city", "")))
    codes.update(country_codes_in(job.get("country", "")))
    return codes


def test_a_real_board_drops_the_postings_published_only_in_an_excluded_country() -> None:
    payload = GreenhouseJobBoardConnector().discover_internships(
        BOARD, selection_brief=default_brief(), countries_exclude=list(EXCLUDED),
    )
    assert payload.raw_count > 0
    # The board really publishes French postings: the filter has work to do.
    assert payload.filtered_geo_count > 0
    assert payload.filtered_geo_count <= payload.excluded_count
    # The counters stay coherent after the country filter.
    assert payload.raw_count == payload.evaluated_count + payload.invalid_count
    assert payload.evaluated_count == payload.confirmed_count + payload.uncertain_count + payload.excluded_count
    # No kept posting is published only in an excluded country.
    for job in payload.jobs:
        codes = _published_codes(job)
        assert not (codes and codes.issubset(set(EXCLUDED))), job


def test_a_real_board_read_without_the_filter_keeps_its_french_postings() -> None:
    """The connector called without the parameter behaves as before."""
    payload = GreenhouseJobBoardConnector().discover_internships(
        BOARD, selection_brief=default_brief(),
    )
    assert payload.filtered_geo_count == 0
    french = [job for job in payload.jobs if _published_codes(job) == {"FR"}]
    assert french, "the board is expected to publish French postings"
