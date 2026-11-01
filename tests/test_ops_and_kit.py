"""Tests for A06 freshness, D06 evidence freshness, D09 merge, G06 ATS fields,
G07 checklist, G08 preview, H10 tracking, J06 regression registry, J07 smoke, C10 dashboard."""

from __future__ import annotations

import career.regression_registry as rr

# A06
from career.offer_freshness import age_days, check_freshness, stale_offer_ids

# D06
from career.evidence_freshness import classify_evidence_freshness, review_queue

# D09
from career.profile_merge import merge_profiles

# G06
from career.ats_fields import fields_for_platform, missing_required, prefill_fields

# G07
from career.dossier_checklist import checklist_for, completeness

# G08
from career.dossier_preview import build_preview

# H10
from career.tracking_report import build_tracking_report

# J07
from career.smoke_http import check_endpoint, run_smoke

# C10
from career.shortlist_dashboard import render_dashboard

OFFERS = [{"id": "j1", "fetched_at": "2026-10-01"}, {"id": "j2", "fetched_at": "2026-11-01"}, {"id": "j3", "fetched_at": "bogus"}]
TODAY = "2026-11-01"


# A06
def test_age_days() -> None:
    assert age_days("2026-10-01", today=TODAY) == 31
    assert age_days("bogus", today=TODAY) is None


def test_freshness_ttl() -> None:
    rows = check_freshness(OFFERS, today=TODAY, ttl_days=7)
    stale = stale_offer_ids(rows)
    assert "j1" in stale
    assert "j2" not in stale
    assert "j3" not in stale


def test_freshness_unknown_not_stale() -> None:
    rows = check_freshness([{"id": "j3", "fetched_at": "bogus"}], today=TODAY)
    assert rows[0].stale is False


# D06
def test_evidence_fresh_status() -> None:
    assert classify_evidence_freshness("2026-10-01", today=TODAY) == {"status": "fresh", "age_days": 31, "needs_review": False}


def test_evidence_stale_needs_review() -> None:
    r = classify_evidence_freshness("2025-01-01", today=TODAY)
    assert r["status"] == "stale" and r["needs_review"] is True


def test_evidence_queue(tmp_path) -> None:
    q = review_queue([{"id": "e1", "date": "2025-01-01"}, {"id": "e2", "date": "2026-10-01"}], today=TODAY)
    assert [e["evidence_id"] for e in q] == ["e1"]


# D09
def test_merge_union_lists() -> None:
    r = merge_profiles({"skills": ["excel"]}, {"skills": ["excel", "python"]})
    assert r.profile["skills"] == ["excel", "python"]
    assert r.conflicts == []


def test_merge_conflict_keeps_primary() -> None:
    r = merge_profiles({"city": "Paris"}, {"city": "London"})
    assert r.profile["city"] == "Paris"
    assert r.conflicts == ["city"]


def test_merge_secondary_wins() -> None:
    r = merge_profiles({}, {"city": "London"})
    assert r.profile["city"] == "London"
    assert r.fields_added == 1


def test_merge_prefer_secondary() -> None:
    r = merge_profiles({"city": "Paris"}, {"city": "London"}, prefer="secondary")
    assert r.profile["city"] == "London"


# G06
def test_fields_generic() -> None:
    f = fields_for_platform("generic")
    assert len(f) >= 6
    assert any(x.required for x in f)


def test_fields_unknown_platform() -> None:
    f = fields_for_platform("nosuch")
    assert f == fields_for_platform("generic")


def test_prefill_and_missing() -> None:
    fields = prefill_fields("workday", {"display_name": "Alice", "contact_email": "a@b.c"})
    flds = {x.name: x.value for x in fields}
    assert flds["full_name"] == "Alice"
    miss = missing_required(fields)
    assert "cv" in miss
    assert "full_name" not in miss


# G07
def test_checklist_stage() -> None:
    items = checklist_for("stage", ["cv", "lettre_motivation"])
    assert completeness(items)["ok"] is True


def test_checklist_missing_required() -> None:
    items = checklist_for("stage", ["cv"])
    c = completeness(items)
    assert c["ok"] is False and "lettre_motivation" in c["missing_required"]


def test_checklist_unknown_dossier_fallback() -> None:
    items = checklist_for("cuisine", [])
    assert items == checklist_for("stage", [])


# G08
def test_preview_full() -> None:
    p = build_preview(
        dossier_id="d1",
        documents=[("cv", "present"), ("lettre", "missing")],
        stage_summary="Stage finance London",
        letter_summary="Lettre 3 phrases",
    )
    assert p.document_count == 2
    assert any("[MANQUANT]" in l for l in p.lines)
    assert len(p.warnings) == 1


def test_preview_empty() -> None:
    p = build_preview(dossier_id="d2")
    assert p.warnings == ["aucun document fourni"]


# H10
APPS = [
    {"id": "a1", "status": "read", "sent_at": "2026-10-20"},
    {"id": "a2", "status": "interview", "sent_at": "2026-10-10", "responded_at": "2026-10-14"},
    {"id": "a3", "status": "rejected", "sent_at": "2026-10-05", "responded_at": "2026-10-06"},
    {"id": "a4", "status": "sent", "sent_at": "2026-10-30"},
    {"id": "a5", "status": "accepted", "sent_at": "2026-09-01", "responded_at": "2026-09-10"},
]


def test_tracking_counts() -> None:
    r = build_tracking_report(APPS, today=TODAY)
    assert r.total == 5
    assert r.by_status["rejected"] == 1
    assert r.avg_response_days == 4.7
    assert r.open_threads == 3


def test_tracking_response_rate() -> None:
    r = build_tracking_report(APPS, today=TODAY)
    assert r.response_rate == 60.0


def test_tracking_empty() -> None:
    r = build_tracking_report([], today=TODAY)
    assert r.total == 0 and r.response_rate == 0.0


# J06
def test_registry_lots_present() -> None:
    assert "letters" in rr.REGRESSION_FILES
    assert any(f.endswith("test_letter_check.py") for f in rr.all_registry_files())


def test_registry_selective() -> None:
    paths = rr.file_paths_for_lots(["connectors"])
    assert len(paths) == 4
    assert rr.file_paths_for_lots(["unknown"]) == []


# J07
def test_smoke_ok() -> None:
    r = check_endpoint("GET /", {"status": 200, "body": {"ok": True}})
    assert r.ok is True


def test_smoke_unexpected_status() -> None:
    r = check_endpoint("GET /", {"status": 500, "body": {}})
    assert r.ok is False
    assert "500" in r.error


def test_smoke_unknown_endpoint() -> None:
    r = check_endpoint("GET /secret", {"status": 200, "body": {}})
    assert r.ok is False and "inconnu" in r.error


def test_run_smoke_all() -> None:
    def fake_client(ep: str) -> dict:
        return {"status": 200, "body": {"ok": True}}

    results = run_smoke(fake_client)
    assert len(results) >= 4
    assert all(res.ok for res in results)


# C10
def test_dashboard_renders() -> None:
    offers = [
        {"id": "j1", "title": "Stage M&A", "deadline": "2026-11-03", "score": 88.0},
        {"id": "j2", "title": "Stage audit", "deadline": "2026-12-01", "score": 42.0},
    ]
    d = render_dashboard(offers, today=TODAY)
    assert d.rows == 2
    assert d.avg_score == 65.0
    assert "SHORTLIST" in d.text
    assert "urgent_72h" in d.text


def test_dashboard_empty() -> None:
    d = render_dashboard([], today=TODAY)
    assert d.rows == 0 and d.avg_score == 0.0
