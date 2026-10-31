"""Tests for US sources connector (N100-A04)."""

from __future__ import annotations

from career.connectors.us_sources import parse_handshake_html, parse_us_html, USJob, to_dict

HTML = """
<html><body>
<a href="/jobs/1">Finance Internship at Acme</a>
<a href="/jobs/2">Co-op Data Analyst</a>
<a href="/about">About</a>
</body></html>
"""


def test_parse() -> None:
    jobs = parse_handshake_html(HTML)
    assert len(jobs) >= 1
    assert all(j.source == "handshake" for j in jobs)


def test_dispatch() -> None:
    assert len(parse_us_html(HTML, "handshake")) >= 1
    assert parse_us_html("<html></html>", "unknown") == []


def test_empty() -> None:
    assert parse_handshake_html("") == []


def test_urls() -> None:
    for j in parse_handshake_html(HTML):
        assert j.url.startswith("http")


def test_to_dict() -> None:
    assert to_dict(USJob(title="t"))["title"] == "t"