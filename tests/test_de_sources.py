"""Tests for DE sources connector (N100-A02)."""

from __future__ import annotations

from career.connectors.de_sources import (
    parse_absolventa_html, parse_stepstone_html, parse_de_html, DEJob, to_dict,
)

ABSOLVENTA_HTML = """
<html><body>
<a href="/jobs/123">Praktikum Finance bei Acme</a>
<a href="/jobs/456">Trainee Program Banking</a>
<a href="/about">About</a>
</body></html>
"""

STEPSTONE_HTML = """
<html><body>
<a href="/jobs/999" class="job-title">Werkstudent Data Analytics</a>
<a href="/about" class="footer-link">About</a>
</body></html>
"""


def test_parse_absolventa() -> None:
    jobs = parse_absolventa_html(ABSOLVENTA_HTML)
    assert len(jobs) >= 1
    assert all(j.source == "absolventa" for j in jobs)


def test_parse_stepstone() -> None:
    jobs = parse_stepstone_html(STEPSTONE_HTML)
    assert len(jobs) >= 1
    assert all(j.source == "stepstone" for j in jobs)


def test_parse_de_dispatch() -> None:
    assert len(parse_de_html(ABSOLVENTA_HTML, "absolventa")) >= 1
    assert len(parse_de_html(STEPSTONE_HTML, "stepstone")) >= 1
    assert parse_de_html("<html></html>", "unknown") == []


def test_parse_empty() -> None:
    assert parse_absolventa_html("") == []
    assert parse_stepstone_html("") == []


def test_urls_absolute() -> None:
    for j in parse_absolventa_html(ABSOLVENTA_HTML):
        assert j.url.startswith("http")


def test_to_dict() -> None:
    j = DEJob(title="t")
    assert to_dict(j)["title"] == "t"