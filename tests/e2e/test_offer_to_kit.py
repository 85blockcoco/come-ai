"""Parcours 1 — importer une offre, l'analyser et produire un kit complet."""

from __future__ import annotations

from pathlib import Path

from pages.base import BasePage
from pages.offer_detail import OfferDetailPage
from pages.offer_list import OfferListPage
from pages.pipeline import PipelinePage
from pages.prep_wizard import PrepWizardPage
from utils import load_offer, load_profile


def test_offer_to_kit(page, app) -> None:
    offer = load_offer("goldman_mna.json")
    BasePage(page, app).open().save_profile(load_profile("senior_analyst.yaml"))

    offers = OfferListPage(page, app)
    offers.import_offer(offer)
    offers.open_saved_offer(offer["title"])

    detail = OfferDetailPage(page, app)
    detail.expect_facts(offer)

    wizard = PrepWizardPage(page, app)
    wizard.analyse(offer["title"])
    assert "M&A" in wizard.recommended_variant()
    assert wizard.mandatory_coverage() >= 0
    wizard.assert_gap_with_source("M&A")

    kit = wizard.prepare_kit("fr", "corporate_finance")
    assert "Camille" in kit["cv"]
    assert "Goldman Sachs" in kit["letter"]
    assert set(kit["artifacts"]) == {"CV ciblé DOCX", "Lettre ciblée DOCX", "Fiche de préparation"}, (
        kit["artifacts"], wizard.kit().inner_text()
    )
    for path in kit["artifacts"].values():
        artifact = Path(path)
        assert artifact.is_file(), f"Artefact manquant : {path}"
        assert artifact.stat().st_size > 0, f"Artefact vide : {path}"

    assert wizard.download_cv_docx().endswith(".docx")
    assert wizard.download_letter_docx().endswith(".docx")
    assert wizard.download_prep_sheet().endswith(".md")
    assert "Corporate Finance" in kit["payload"]["variant_label"]

    pipeline = PipelinePage(page, app)
    pipeline.refresh()
    pipeline.expect_application(offer["company"], "Corporate Finance / FP&A")
