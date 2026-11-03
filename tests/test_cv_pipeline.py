"""Tests for E07 diff, E08 versions, E09 approval, E10 CV report."""

from __future__ import annotations

import json

import career.cv_approval as ca
from career.cv_diff import diff_cvs, explain_changes, to_dict
from career.cv_report import CvReport, build_cv_report, write_reports
from career.cv_versions import CvVersionStore

ORIG = "EDUCATION\nBBA Finance\nEXPERIENCE\nStage audit 6 mois"
VAR = "EDUCATION\nBBA Finance\nEXPERIENCE\nStage audit 6 mois\nStage finance 6 mois"


# E07 — diff


def test_diff_detects_addition() -> None:
    d = diff_cvs(ORIG, VAR)
    assert d.added == ["Stage finance 6 mois"]
    assert d.removed == []
    assert "ajoutée(s)" in d.summary


def test_diff_detects_removal() -> None:
    d = diff_cvs(VAR, ORIG)
    assert d.removed == ["Stage finance 6 mois"]


def test_diff_identical() -> None:
    d = diff_cvs(ORIG, ORIG)
    assert d.is_empty is True
    assert "Aucune différence" in d.summary


def test_diff_replacement() -> None:
    d = diff_cvs("Ligne A\nLigne B", "Ligne A\nLigne B2")
    assert d.added == ["Ligne B2"]
    assert d.removed == ["Ligne B"]


def test_diff_empty_inputs() -> None:
    d = diff_cvs("", "")
    assert d.is_empty is True


def test_explain_changes() -> None:
    lines = explain_changes(diff_cvs(ORIG, VAR))
    assert len(lines) == 1
    assert lines[0].startswith("- ")


def test_diff_to_dict() -> None:
    d = to_dict(diff_cvs(ORIG, VAR))
    assert "added" in d and "summary" in d


# E08 — versioning


def test_version_id_sequence(tmp_path) -> None:
    s = CvVersionStore(tmp_path / "vers.jsonl")
    v1 = s.add("cv1", "B", note="n1")
    v2 = s.add("cv1", "B2", note="n2")
    assert v1.version_id == "cv1-v1"
    assert v2.version_id == "cv1-v2"


def test_history_persisted(tmp_path) -> None:
    p = tmp_path / "vers.jsonl"
    s1 = CvVersionStore(p)
    s1.add("cv1", "body-A")
    s1.add("cv1", "body-B")
    assert len(p.read_text(encoding="utf-8").splitlines()) == 2


def test_get_and_latest(tmp_path) -> None:
    s = CvVersionStore()
    s.add("cv1", "A")
    s.add("cv1", "B")
    assert s.get("cv1", "cv1-v1").body == "A"
    assert s.latest("cv1").body == "B"
    assert s.get("cv1", "nope") is None
    assert s.latest("unknown") is None


def test_restore(tmp_path) -> None:
    s = CvVersionStore()
    s.add("cv1", "A")
    s.add("cv1", "B")
    restored = s.restore("cv1", "cv1-v1")
    assert restored.body == "A"


def test_versions_isolated_per_cv(tmp_path) -> None:
    s = CvVersionStore()
    s.add("cv1", "A")
    s.add("cv2", "B")
    assert len(s.history("cv1")) == 1
    assert len(s.history("cv2")) == 1


# E09 — approval


def test_default_not_approved(tmp_path) -> None:
    ca.set_registry_path(tmp_path / "appr.jsonl")
    assert ca.is_approved("cv1", "cv1-v1") is False


def test_decide_persist_reset(tmp_path) -> None:
    p = tmp_path / "appr.jsonl"
    ca.set_registry_path(p)
    ca.decide("cv1", "cv1-v1", approved=True, note="ok")
    assert ca.is_approved("cv1", "cv1-v1") is True
    assert json.loads(p.read_text(encoding="utf-8").splitlines()[0])["approved"] is True
    ca.set_registry_path(tmp_path / "other.jsonl")
    assert ca.is_approved("cv1", "cv1-v1") is False


def test_reject(tmp_path) -> None:
    ca.set_registry_path(tmp_path / "appr.jsonl")
    ca.decide("cvX", "v1", approved=False)
    assert ca.is_approved("cvX", "v1") is False


def test_cv_approval_to_dict(tmp_path) -> None:
    ca.set_registry_path(tmp_path / "appr.jsonl")
    d = ca.decide("cv1", "v1", approved=True)
    assert ca.to_dict(d)["version_id"] == "v1"


# E10 — report


def _report(**kw) -> CvReport:
    base = dict(
        cv_id="cv1", variant_id="cv1-v2", target_role="Stage finance", language="fr",
        evidence_used=["a"], gaps_reported=["langue allemande"], quality_score=80.0,
        approved=True, diff_added=1, diff_removed=0, at="2026-11-01T10:00:00+00:00",
    )
    base.update(kw)
    return build_cv_report(**base)


def test_cv_report_fields() -> None:
    r = _report()
    assert r.evidence_used == 1
    assert r.gaps_reported == 1


def test_write_cv_reports(tmp_path) -> None:
    p = write_reports([_report()], tmp_path / "rep.json")
    data = json.loads(p.read_text(encoding="utf-8"))
    assert data[0]["variant_id"] == "cv1-v2"


def test_cv_report_to_dict() -> None:
    r = _report()
    d = build_cv_report(**{
        "cv_id": r.cv_id, "variant_id": r.variant_id, "target_role": r.target_role,
        "language": r.language, "evidence_used": ["x"], "gaps_reported": [],
        "quality_score": 70.0, "approved": False, "diff_added": 0, "diff_removed": 0,
    })
    from career.cv_report import to_dict
    assert to_dict(d)["approved"] is False
