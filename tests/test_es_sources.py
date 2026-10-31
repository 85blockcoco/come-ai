"""Tests for ES sources connector (N100-A03)."""

from __future__ import annotations

from career.connectors.es_sources import parse_infojobs_html, parse_es_html, ESJob, to_dict

HTML = """
<html><body>
<a href="/jobs/1">Prácticas Finance en Madrid</a>
<a href="/jobs/2">Becario Data</a>
<a href="/about">About</a>
</body></html>
"""


def test_parse() -> None:
    jobs = parse_infojobs_html(HTML)
    assert len(jobs) >= 1
    assert all(j.source == "infojobs" for j in jobs)


def test_dispatch() -> None:
    assert len(parse_es_html(HTML, "infojobs")) >= 1
    assert parse_es_html("<html></html>", "unknown") == []


def test_empty() -> None:
    assert parse_infojobs_html("") == []


def test_urls() -> None:
    for j in parse_infojobs_html(HTML):
        assert j.url.startswith("http")


def test_to_dict() -> None:
    assert to_dict(ESJob(title="t"))["title"] == "t"