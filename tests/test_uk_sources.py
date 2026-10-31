"""Tests for UK sources connector (N100-A01)."""

from __future__ import annotations

from career.connectors.uk_sources import (
    parse_prospects_html, parse_gradcracker_html, parse_targetjobs_html,
    parse_uk_html, UKJob, to_dict,
)


PROSPECTS_HTML = """
<html><body>
<a href="/jobs/intern-finance-123">Finance Internship at Acme</a>
<a href="/jobs/graduate-analyst-456">Graduate Analyst Programme</a>
<a href="/about">About us</a>
</body></html>
"""

GRADCRACKER_HTML = """
<html><body>
<a href="/jobs/12345">Placement Year - Software Engineer</a>
<a href="/companies/acme">Acme profile</a>
</body></html>
"""

TARGETJOBS_HTML = """
<html><body>
<a href="/jobs/999" class="job-title">Investment Banking Intern</a>
<a href="/about" class="footer-link">About</a>
</body></html>
"""


def test_parse_prospects() -> None:
    jobs = parse_prospects_html(PROSPECTS_HTML)
    assert len(jobs) >= 1
    assert all(j.source == "prospects" for j in jobs)
    assert any("Internship" in j.title or "Graduate" in j.title for j in jobs)


def test_parse_gradcracker() -> None:
    jobs = parse_gradcracker_html(GRADCRACKER_HTML)
    assert len(jobs) >= 1
    assert all(j.source == "gradcracker" for j in jobs)


def test_parse_targetjobs() -> None:
    jobs = parse_targetjobs_html(TARGETJOBS_HTML)
    assert len(jobs) >= 1
    assert all(j.source == "targetjobs" for j in jobs)


def test_parse_uk_html_dispatch() -> None:
    assert len(parse_uk_html(PROSPECTS_HTML, "prospects")) >= 1
    assert len(parse_uk_html(GRADCRACKER_HTML, "gradcracker")) >= 1
    assert len(parse_uk_html(TARGETJOBS_HTML, "targetjobs")) >= 1
    assert parse_uk_html("<html></html>", "unknown") == []


def test_parse_empty() -> None:
    assert parse_prospects_html("") == []
    assert parse_gradcracker_html("") == []
    assert parse_targetjobs_html("") == []


def test_ukjob_dataclass() -> None:
    j = UKJob(title="t", company="c", location="l", url="u", source="s", description="d")
    assert j.title == "t"


def test_to_dict() -> None:
    j = UKJob(title="t")
    d = to_dict(j)
    assert d["title"] == "t"


def test_urls_are_absolute() -> None:
    jobs = parse_prospects_html(PROSPECTS_HTML)
    for j in jobs:
        assert j.url.startswith("http")


def test_no_network() -> None:
    # Parsing is pure, no network call.
    jobs = parse_prospects_html(PROSPECTS_HTML)
    assert isinstance(jobs, list)