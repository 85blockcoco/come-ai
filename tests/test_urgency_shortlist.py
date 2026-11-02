"""Tests for C08 urgency ranking + C09 shortlist export."""

from __future__ import annotations

import csv
import json

from career.shortlist_export import (
    DEFAULT_FIELDS, export_shortlist_csv, export_shortlist_json, shortlist_to_dicts,
)
from career.urgency_ranking import classify_urgency, rank_by_urgency

OFFERS = [
    {"id": "o1", "deadline": "2026-11-03", "title": "Stage urgence"},
    {"id": "o2", "deadline": "2026-12-01", "title": "Stage lointain"},
    {"id": "o3", "deadline": "2026-11-10", "title": "Stage 14j"},
    {"id": "o4", "title": "Sans deadline"},
    {"id": "o5", "deadline": "2026-10-01", "title": "Expirée"},
]
TODAY = "2026-11-01"


# C08 — urgency


def test_classify_urgent() -> None:
    assert classify_urgency("2026-11-03", today=TODAY) == "urgent_72h"


def test_classify_soon() -> None:
    assert classify_urgency("2026-11-10", today=TODAY) == "soon_14d"


def test_classify_normal_and_expired() -> None:
    assert classify_urgency("2026-12-01", today=TODAY) == "normal"
    assert classify_urgency("2026-10-01", today=TODAY) == "expired"


def test_classify_unknown() -> None:
    assert classify_urgency("", today=TODAY) == "unknown"
    assert classify_urgency("pas-une-date", today=TODAY) == "unknown"


def test_rank_orders_urgent_first() -> None:
    _, ordered = rank_by_urgency(OFFERS, today=TODAY)
    assert ordered[0]["id"] == "o1"
    assert ordered[1]["id"] == "o3"


def test_rank_unknown_last() -> None:
    _, ordered = rank_by_urgency(OFFERS, today=TODAY)
    assert ordered[-1]["id"] == "o4"


def test_rank_days_left_is_computed() -> None:
    rows, _ = rank_by_urgency(OFFERS, today=TODAY)
    by_id = {row.job_id: row for row in rows}
    assert by_id["o1"].days_left == 2
    assert by_id["o5"].days_left == -31
    assert by_id["o4"].days_left is None


def test_rank_ties_deterministic() -> None:
    same = [{"id": "b", "deadline": "2026-11-03"}, {"id": "a", "deadline": "2026-11-03"}]
    _, ordered = rank_by_urgency(same, today=TODAY)
    assert [o["id"] for o in ordered] == ["a", "b"]


# C09 — shortlist export


def test_export_json(tmp_path) -> None:
    p = tmp_path / "sl.json"
    r = export_shortlist_json(OFFERS, p)
    assert r.format == "json" and r.rows == 5
    assert json.loads(p.read_text(encoding="utf-8"))[0]["id"] == "o1"


def test_export_csv(tmp_path) -> None:
    p = tmp_path / "sl.csv"
    r = export_shortlist_csv(OFFERS, p)
    assert r.format == "csv" and r.rows == 5
    lines = p.read_text(encoding="utf-8").splitlines()
    assert lines[0].startswith("id,")


def test_export_csv_custom_fields(tmp_path) -> None:
    p = tmp_path / "sl.csv"
    export_shortlist_csv(OFFERS, p, fields=("id", "title"))
    reader = csv.DictReader(p.open(encoding="utf-8"))
    row = next(reader)
    assert set(row) == {"id", "title"}


def test_export_empty(tmp_path) -> None:
    p = tmp_path / "empty.json"
    r = export_shortlist_json([], p)
    assert r.rows == 0
    assert json.loads(p.read_text(encoding="utf-8")) == []


def test_shortlist_to_dicts() -> None:
    d = shortlist_to_dicts(OFFERS[:1])
    assert d[0]["id"] == "o1"


def test_default_fields() -> None:
    assert "score" in DEFAULT_FIELDS
