"""Local E2E backend recipe (N100-J01) — chaîne complète sur 10 offres synthétiques.

Offres -> fraîcheur / cache -> urgence -> dashboard -> lettre (render, check,
personalize, approve, export) -> kit (ATS fields + checklist) -> rapports.
Tout est local, déterministe, sans envoi ni donnée personnelle.
"""

from __future__ import annotations

from pathlib import Path

import career.letter_approval as letter_gate
from career.ats_fields import missing_required, prefill_fields
from career.dossier_checklist import checklist_for, completeness
from career.export_report import build_export_report
from career.letter_approval import decide
from career.letter_check import score_letter
from career.letter_export import export_letter
from career.letter_language import render_multilingual_letter
from career.letter_personalization import personalize_letter
from career.offer_cache import OfferCache
from career.offer_freshness import check_freshness, stale_offer_ids
from career.shortlist_dashboard import render_dashboard
from career.urgency_ranking import rank_by_urgency

TODAY = "2026-11-01"
ROLES = [
    ("s1", "Stage M&A", "Goldman Paris", "2026-11-03"),
    ("s2", "Stage Corporate Finance", "BNP", "2026-11-10"),
    ("s3", "Stage Audit", "KPMG", "2026-11-20"),
    ("s4", "Intern Finance", "Lazard London", "2026-12-05"),
    ("s5", "Stage Trading", "Société Générale", "2026-11-02"),
    ("s6", "Stage Private Equity", "EQT", ""),
    ("s7", "Stage Risk", "AXA", "2026-11-15"),
    ("s8", "Intern Asset Mgmt", "Amundi", "2026-10-20"),
    ("s9", "Stage Treasury", "HSBC", "2026-12-20"),
    ("s10", "Stage Equity Research", "Exane", "2026-11-08"),
]
EVIDENCE = [
    "BBA Finance obtenu en 2026, moyenne 15/20",
    "Stage de six mois en contrôle de gestion chez Airbus",
    "Excel avancé (index-equiv, power query) et VBA de niveau intermédiaire",
]


def _offers() -> list[dict]:
    return [{"id": i, "title": t, "company": c, "deadline": d, "score": 60 + idx * 2} for idx, (i, t, c, d) in enumerate(ROLES)]


def test_e2e_offers_to_shortlist(tmp_path: Path) -> None:
    offers = _offers()

    cache = OfferCache(tmp_path / "offers.json")
    for o in offers:
        cache.put({**o, "fetched_at": TODAY})
    assert cache.size() == 10

    stamped = [dict(o, fetched_at="2026-10-01") for o in offers]
    rows = check_freshness(stamped, today=TODAY)
    stale = stale_offer_ids(rows)
    assert len(stale) == 10  # toutes > 7 jours -> toutes consideration stale

    _, ordered = rank_by_urgency(offers, today=TODAY)
    # urgent_72h : s1 (2j) et s5 (1j), tie-break par id -> s1 d'abord ;
    # l'offre sans deadline (s6) est EN DERNIER, l'expirée (s8) juste avant.
    assert ordered[0]["id"] in ("s1", "s5")
    assert ordered[-1]["id"] == "s6"
    assert ordered[-2]["id"] == "s8"

    dashboard = render_dashboard(offers, today=TODAY)
    assert dashboard.rows == 10
    assert "SHORTLIST" in dashboard.text


def test_e2e_letter_pipeline(tmp_path: Path) -> None:
    letter_gate.set_registry_path(tmp_path / "approvals.jsonl")
    offers = _offers()
    target = offers[0]

    rendered = render_multilingual_letter(
        candidate_name="Étudiant BBA",
        role=target["title"],
        company=target["company"],
        evidence=EVIDENCE,
        language="fr",
        tone="formal",
    )
    assert "Stage M&A" in rendered.body and rendered.language == "fr"

    personalized = personalize_letter(rendered.body, company=target["company"], company_facts=["Leader en fusions-acquisitions en Europe"])
    assert "[À COMPLÉTER" not in personalized.personalized_body

    score = score_letter(personalized.personalized_body, EVIDENCE)
    assert score.completeness_score >= 40

    decide("letter-s1", approved=True, note="vérifié par le candidat")
    outcome = export_letter(
        letter_body=personalized.personalized_body,
        title="letter-s1",
        language="fr",
        target=tmp_path / "exports" / "letter-s1.txt",
        fmt="txt",
        approved=True,
    )
    assert outcome["ok"] is True
    assert (tmp_path / "exports" / "letter-s1.txt").exists()


def test_e2e_kit_and_reports(tmp_path: Path) -> None:
    fields = prefill_fields("workday", {"display_name": "Étudiant BBA", "contact_email": "etudiant@exemple.fr"})
    miss = missing_required(fields)
    assert "cv" in miss and "full_name" not in miss

    items = checklist_for("banque", ["cv", "lettre_motivation"])
    comp = completeness(items)
    assert comp["ok"] is False and "transcript_english" in comp["missing_required"]

    bundle = build_export_report(
        bundle_path=str(tmp_path / "kit.zip"),
        files=[("cv.pdf", 1200), ("letter-s1.txt", 900)],
    )
    assert bundle.file_count == 2 and bundle.total_bytes == 2100
