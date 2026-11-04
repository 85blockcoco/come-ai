from __future__ import annotations

import json
from pathlib import Path


MANIFEST = Path(__file__).parents[1] / "academics" / "vc" / "content" / "supplementary_sources.json"


def test_supplementary_sources_have_an_explicit_disposition() -> None:
    payload = json.loads(MANIFEST.read_text(encoding="utf-8"))
    sources = {item["file"]: item for item in payload["sources"]}
    assert sources["7017_69368.pdf"]["status"] == "duplicate_exam_source"
    assert sources["Team project 2027.pdf"]["status"] == "rubric_integrated"
    assert sources["Sessions 5-6 Venture Capital.pdf"]["status"] == "supplementary_lecture_deck"
    assert all(item.get("notes", "").strip() for item in sources.values())


def test_sessions_5_6_page_map_is_contiguous_and_topic_linked() -> None:
    payload = json.loads(MANIFEST.read_text(encoding="utf-8"))
    source = next(item for item in payload["sources"] if item["file"] == "Sessions 5-6 Venture Capital.pdf")
    ranges = []
    for item in source["page_map"]:
        start, end = (int(value) for value in item["pages"].split("-"))
        assert start <= end
        assert item["topics"]
        ranges.extend(range(start, end + 1))
    assert ranges == list(range(2, 65))

