"""Tests for letter export (N100-F07) + templates (F08) + approval (F09) + report (F10)."""

from __future__ import annotations

import json

# F07 — export
from career.letter_export import ALLOWED_FORMATS, export_letter

# F08 — templates
from career.letter_templates import TEMPLATES, describe_template, pick_letter_template, to_dict

# F09 — approval
import career.letter_approval as la

# F10 — report
from career.letter_report import LetterReport, build_letter_report, write_report
from career.letter_report import to_dict as report_to_dict


BODY = "Madame, Monsieur,\n\nStage analyse financière.\n\nCordialement,\nAlice"


def test_export_txt(tmp_path) -> None:
    p = tmp_path / "out" / "letter.txt"
    r = export_letter(letter_body=BODY, title="L1", language="fr", target=p, fmt="txt", approved=True)
    assert r["ok"] is True
    assert p.read_text(encoding="utf-8").startswith("Madame")


def test_export_md(tmp_path) -> None:
    p = tmp_path / "l.md"
    r = export_letter(letter_body=BODY, title="L1", language="fr", target=p, fmt="md", approved=True)
    assert r["ok"] is True
    assert "# L1" in p.read_text(encoding="utf-8")


def test_export_bad_format(tmp_path) -> None:
    r = export_letter(letter_body=BODY, title="L", language="fr", target=tmp_path / "x.html", fmt="html")
    assert r["ok"] is False
    assert "format" in r["error"]


def test_export_empty_body(tmp_path) -> None:
    r = export_letter(letter_body="", title="L", language="fr", target=tmp_path / "x.txt", fmt="txt")
    assert r["ok"] is False


def test_export_docx_blocked_without_approval(tmp_path) -> None:
    la.set_registry_path(tmp_path / "appr.jsonl")
    r = export_letter(letter_body=BODY, title="notApproved", language="fr", target=tmp_path / "l.docx", fmt="docx", approved=False)
    assert r["ok"] is False
    assert "approuvée" in r["error"]
    assert not (tmp_path / "l.docx").exists()


def test_export_docx_with_approval(tmp_path) -> None:
    la.set_registry_path(tmp_path / "appr.jsonl")
    la.decide("okId", approved=True, version=1)
    r = export_letter(letter_body=BODY, title="okId", language="fr", target=tmp_path / "l2.docx", fmt="docx", approved=True)
    assert r["ok"] is True
    assert (tmp_path / "l2.docx").exists()


def test_allowed_formats() -> None:
    assert set(ALLOWED_FORMATS) == {"docx", "pdf", "md", "txt"}


# F08 — templates


def test_pick_finance() -> None:
    t = pick_letter_template("Stage asset management en banque d'investissement")
    assert t.template_id == "finance"


def test_pick_consulting() -> None:
    t = pick_letter_template("Consulting strategy en conseil")
    assert t.template_id == "consulting"


def test_pick_tech() -> None:
    t = pick_letter_template("Développeur logiciel data")
    assert t.template_id == "tech"


def test_pick_default() -> None:
    t = pick_letter_template("Poste de vendeur pain")
    assert t.template_id == "default"


def test_describe_unknown() -> None:
    t = describe_template("cuisine")
    assert t.template_id == "default"
    assert t.focus


def test_templates_count() -> None:
    assert len(TEMPLATES) == 4


def test_template_to_dict() -> None:
    d = to_dict(describe_template("finance"))
    assert d["template_id"] == "finance"


# F09 — approval


def test_default_not_approved(tmp_path) -> None:
    la.set_registry_path(tmp_path / "appr.jsonl")
    assert la.is_approved("unknown") is False


def test_decide_and_persist(tmp_path) -> None:
    p = tmp_path / "appr.jsonl"
    la.set_registry_path(p)
    la.decide("l1", approved=True, version=1, note="vu et corrigé")
    assert la.is_approved("l1") is True
    d = la.get_decision("l1")
    assert d.note == "vu et corrigé"
    lines = p.read_text(encoding="utf-8").splitlines()
    assert json.loads(lines[0])["approved"] is True


def test_rejection(tmp_path) -> None:
    la.set_registry_path(tmp_path / "appr.jsonl")
    la.decide("l2", approved=False, note="faute")
    assert la.is_approved("l2") is False


def test_registry_reset(tmp_path) -> None:
    la.set_registry_path(tmp_path / "a.jsonl")
    la.decide("x", approved=True)
    la.set_registry_path(tmp_path / "b.jsonl")
    assert la.is_approved("x") is False


def test_decision_to_dict(tmp_path) -> None:
    la.set_registry_path(tmp_path / "appr.jsonl")
    dec = la.decide("l1", approved=True)
    assert la.to_dict(dec)["letter_id"] == "l1"


# F10 — report


def _report(**kw) -> LetterReport:
    base = dict(
        letter_id="l1", language="fr", tone="formal", template_id="finance",
        evidence_used=["a", "b"], evidence_missing=[], facts_score=90.0,
        completeness_score=85.0, approved=True, at="2026-11-01T10:00:00+00:00",
    )
    base.update(kw)
    return build_letter_report(**base)


def test_report_fields() -> None:
    r = _report()
    assert r.evidence_used == 2
    assert r.facts_score == 90.0
    assert r.approved is True


def test_report_warnings() -> None:
    r = _report(warnings=["salutation manquante"])
    assert r.warnings == ["salutation manquante"]


def test_write_report(tmp_path) -> None:
    p = write_report([_report()], tmp_path / "rep.json")
    data = json.loads(p.read_text(encoding="utf-8"))
    assert data[0]["letter_id"] == "l1"


def test_report_to_dict() -> None:
    d = report_to_dict(_report())
    assert d["completeness_score"] == 85.0
