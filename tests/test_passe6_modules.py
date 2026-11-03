"""Tests for I10 reliability report, A09 offer cache, G10 export report."""

from __future__ import annotations

import json

from career.ai_reliability_report import (  # I10
    build_reliability_report, to_dict, write_reliability_report,
)
from career.export_report import build_export_report  # G10
from career.offer_cache import OfferCache  # A09

# I10


def test_report_success_rates() -> None:
    r = build_reliability_report(
        [{"provider": "beam", "calls": 10, "failures": 1}, {"provider": "mimo", "calls": 5, "failures": 3}],
        cache_hits=10, cache_misses=40, at="2026-11-01T00:00:00+00:00",
    )
    assert r.total_calls == 15
    assert r.global_success_rate == 73.3  # (15-4)/15
    assert r.providers[0]["success_rate"] == 90.0  # (10-1)/10
    assert r.cache_hit_rate == 20.0


def test_report_recommendations_bad_provider() -> None:
    r = build_reliability_report([{"provider": "mimo", "calls": 5, "failures": 3}])
    assert any("mimo" in rec for rec in r.recommendations)


def test_report_all_green() -> None:
    r = build_reliability_report(
        [{"provider": "beam", "calls": 10, "failures": 0}], cache_hits=50, cache_misses=10
    )
    assert r.recommendations == ["Aucune anomalie détectée"]


def test_report_empty() -> None:
    r = build_reliability_report([])
    assert r.total_calls == 0 and r.global_success_rate == 0.0


def test_write_report(tmp_path) -> None:
    p = write_reliability_report(build_reliability_report([]), tmp_path / "rep.json")
    data = json.loads(p.read_text(encoding="utf-8"))
    assert "total_calls" in data


def test_report_to_dict() -> None:
    assert isinstance(to_dict(build_reliability_report([])), dict)


# A09


def test_put_get_roundtrip(tmp_path) -> None:
    c = OfferCache(tmp_path / "cache.json")
    offer = {"id": "j1", "url": "https://x/y", "title": "Stage"}
    key = c.put(offer)
    assert c.get(offer) == offer
    assert key and len(key) == 16
    assert c.size() == 1


def test_invalidate_and_clear(tmp_path) -> None:
    c = OfferCache(tmp_path / "cache.json")
    offer = {"id": "j1", "url": "https://x/y"}
    c.put(offer)
    c.invalidate(offer)
    assert c.get(offer) is None
    c.put(offer)
    c.clear()
    assert c.size() == 0


def test_ttl_expiry(tmp_path) -> None:
    c = OfferCache(tmp_path / "cache.json", ttl_seconds=0)
    offer = {"id": "j0", "url": "https://x/z"}
    c.put(offer)
    assert c.get(offer) is None


def test_purge_expired(tmp_path) -> None:
    c = OfferCache(tmp_path / "cache.json", ttl_seconds=0)
    c.put({"id": "a", "url": "1://a"})
    c.put({"id": "b", "url": "1://b"})
    assert c.purge_expired() == 2
    assert c.size() == 0


def test_persistence(tmp_path) -> None:
    p = tmp_path / "cache.json"
    OfferCache(p).put({"id": "j2", "url": "https://z"})
    c2 = OfferCache(p)
    assert c2.size() == 1


def test_key_stable_no_url_uses_title(tmp_path) -> None:
    c = OfferCache(tmp_path / "c.json")
    o = {"title": "Stage finance"}
    k1 = c.put(o)
    k2 = c.put(dict(o))
    assert k1 == k2


# G10


def test_export_report_counts() -> None:
    r = build_export_report(
        bundle_path="kit.zip",
        files=[("cv.pdf", 1000), ("letter.docx", 500), ("README.md", 100)],
    )
    assert r.file_count == 3
    assert r.total_bytes == 1600
    assert r.formats == {"pdf": 1, "docx": 1, "md": 1}


def test_export_report_empty_warning() -> None:
    r = build_export_report(bundle_path="b.zip")
    assert "bundle vide" in r.warnings[0]


def test_export_report_no_ext() -> None:
    r = build_export_report(bundle_path="b.zip", files=[("LICENSE", 10)])
    assert r.formats == {"none": 1}


def test_export_report_to_dict() -> None:
    d = build_export_report(bundle_path="b", files=[("a.txt", 1)])
    assert to_dict(d)["file_count"] == 1
