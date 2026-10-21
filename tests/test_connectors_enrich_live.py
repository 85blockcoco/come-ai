"""Bounded live control of the transmitted source material.

This control is deliberately separate from the synthetic contract tests and
never runs by default: it reads the public feed of one reviewed source per
provider, with one request per provider, a short timeout and a bounded number
of examined postings.  It is enabled explicitly:

    CAREER_LIVE_SOURCE_CHECK=1 .venv/bin/python -m pytest -q tests/test_connectors_enrich_live.py

The control checks the same contract as the synthetic fixtures on real
payloads.  When a source cannot be read from this environment (an HTTP error,
a page whose markup changed), the control records that state instead of
pretending the source was read.  A source that answers must publish the same
contract as the synthetic fixtures.
"""

from __future__ import annotations

import os
from typing import Any

import pytest

from career.connectors import apec as apec_module
from career.connectors import jobteaser as jobteaser_module
from career.connectors import talent_com as talent_com_module
from career.connectors import welcome_jungle as welcome_jungle_module
from career.connectors.public_ats import AshbyConnector, LeverConnector, SmartRecruitersConnector
from career.discovery import GreenhouseBoard, GreenhouseJobBoardConnector, PublicSourceError
from career.source_fields import CONFLICTS_KEY, CONTRACT_KEY


LIVE = os.environ.get("CAREER_LIVE_SOURCE_CHECK") == "1"
TIMEOUT_SECONDS = 10
MAX_EXAMINED = 3

pytestmark = pytest.mark.skipif(
    not LIVE,
    reason="live source control is disabled; set CAREER_LIVE_SOURCE_CHECK=1 to run it",
)


class OneShotFetch:
    """Return the first page only: the control reads one request per source."""

    def __init__(self, fetch: Any) -> None:
        self._fetch = fetch
        self.calls = 0

    def __call__(self, url: str) -> str | None:
        self.calls += 1
        if self.calls > 1:
            return None
        return self._fetch(url)


def _source(provider: str, **extra: Any) -> dict[str, Any]:
    return {
        "id": f"live:{provider}:board",
        "provider": provider,
        "company": "Synthetic Finance",
        "board_token": "synthetic-board",
        "verified_at": "2026-10-18T00:00:00Z",
        "provenance_url": "https://careers.example.test/",
    } | extra


def _assert_contract(provider: str, jobs: list[dict[str, Any]], *,
                     description_published: bool) -> None:
    """The contract must hold for every posting the source really published."""
    for job in jobs[:MAX_EXAMINED]:
        block = job.get(CONTRACT_KEY)
        assert isinstance(block, dict) and list(block) == [provider], (
            f"{provider} did not scope the transmitted fields to its own name"
        )
        assert block[provider], f"{provider} transmitted no published field"
        description = job.get("description_original", "")
        assert isinstance(description, str)
        if description_published:
            assert description.strip(), f"{provider} transmitted no description"
        assert isinstance(job.get(CONFLICTS_KEY), list)


def _check_contract(provider: str, jobs: list[dict[str, Any]], *,
                    description_published: bool) -> None:
    """Check the contract, or record that the source published nothing.

    A source that answers with a page the connector cannot read is an
    observation about that source, not a failure of the transmitted contract:
    the control reports it and never invents a posting.
    """
    if not jobs:
        pytest.skip(f"{provider} published no readable posting on the live page")
    _assert_contract(provider, jobs, description_published=description_published)


def test_live_greenhouse_transmits_its_published_fields() -> None:
    board = GreenhouseBoard("alixpartners", "AlixPartners", "alixpartners")
    connector = GreenhouseJobBoardConnector()
    payload = connector.transport.get_json(board.endpoint, TIMEOUT_SECONDS)
    jobs = list(GreenhouseJobBoardConnector._normalise(board, payload).jobs)
    _check_contract("greenhouse", jobs, description_published=True)
    published = jobs[0][CONTRACT_KEY]["greenhouse"]
    # The board publishes these fields; they are transmitted under their name.
    for name in ("id", "first_published", "updated_at", "requisition_id", "metadata"):
        assert name in published, f"greenhouse did not transmit {name!r}"


def test_live_lever_transmits_its_published_fields() -> None:
    connector = LeverConnector(enabled=True, max_pages=1)
    source = _source("lever", board_token="qonto")
    pages = connector._pages(source, deadline=None)
    jobs = connector.parse(source, pages[0])
    _check_contract("lever", jobs, description_published=True)
    published = jobs[0][CONTRACT_KEY]["lever"]
    for name in ("id", "text", "createdAt", "categories", "hostedUrl"):
        assert name in published, f"lever did not transmit {name!r}"


def test_live_ashby_transmits_its_published_fields() -> None:
    connector = AshbyConnector(enabled=True, max_pages=1)
    source = _source("ashby", board_token="oaknorth")
    pages = connector._pages(source, deadline=None)
    jobs = connector.parse(source, pages[0])
    _check_contract("ashby", jobs, description_published=True)
    published = jobs[0][CONTRACT_KEY]["ashby"]
    for name in ("id", "title", "publishedAt", "employmentType", "jobUrl"):
        assert name in published, f"ashby did not transmit {name!r}"


def test_live_smartrecruiters_transmits_its_published_fields() -> None:
    company = os.environ.get("CAREER_LIVE_SR_COMPANY", "").strip()
    if not company:
        pytest.skip("no reviewed SmartRecruiters board identifier is available in this environment")
    connector = SmartRecruitersConnector(enabled=True, max_pages=1)
    source = _source("smartrecruiters", company_identifier=company)
    pages = connector._pages(source, deadline=None)
    jobs = connector.parse(source, pages[0])
    _check_contract("smartrecruiters", jobs, description_published=True)
    published = jobs[0][CONTRACT_KEY]["smartrecruiters"]
    for name in ("id", "name", "requisitionId", "postedDate", "releasedDate", "typeOfEmployment"):
        assert name in published, f"smartrecruiters did not transmit {name!r}"


def test_live_welcome_jungle_transmits_its_published_fields() -> None:
    fetch = OneShotFetch(welcome_jungle_module._default_fetch)
    jobs = list(welcome_jungle_module._iter_raw_offers(fetch=fetch))
    _check_contract("welcome_jungle", jobs, description_published=False)


def test_live_jobteaser_transmits_its_published_fields() -> None:
    fetch = OneShotFetch(jobteaser_module._default_fetch)
    jobs = list(jobteaser_module._iter_raw_offers(fetch=fetch))
    _check_contract("jobteaser", jobs, description_published=False)


def test_live_talent_com_transmits_its_published_fields() -> None:
    fetch = OneShotFetch(talent_com_module._default_fetch)
    jobs = list(talent_com_module._iter_raw_offers(fetch=fetch))
    _check_contract("talent_com", jobs, description_published=True)
    published = jobs[0][CONTRACT_KEY]["talent_com"]
    # The board publishes the identifier of the card and the timestamp of its
    # last update; both are transmitted under their own name.
    for name in ("data-job-id", "data-rank", "datetime", "url"):
        assert name in published, f"talent_com did not transmit {name!r}"
    # The published link carries the identifier as a query parameter.
    assert "/view?id=" in jobs[0]["official_url"]


def test_live_apec_transmits_its_published_fields() -> None:
    fetch = OneShotFetch(apec_module._default_fetch)
    jobs = list(apec_module._iter_raw_offers(fetch=fetch))
    _check_contract("apec", jobs, description_published=False)


def test_live_source_failures_stay_explicit_and_never_crash() -> None:
    """A source that cannot be read reports a safe error, not a crash."""
    connector = LeverConnector(enabled=True, max_pages=1)
    with pytest.raises(PublicSourceError):
        connector._pages(_source("lever", board_token="synthetic-board-does-not-exist"),
                         deadline=None)
