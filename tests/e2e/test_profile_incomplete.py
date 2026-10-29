"""Parcours 2 — profil incomplet, ajout d'une preuve, couverture améliorée."""

from __future__ import annotations

from pages.base import BasePage
from pages.offer_detail import OfferDetailPage
from pages.offer_list import OfferListPage
from pages.prep_wizard import PrepWizardPage
from utils import load_offer, load_profile


def test_profile_incomplete_then_evidence_improves_coverage(page, app) -> None:
    offer = load_offer("goldman_mna.json")
    profile = load_profile("junior_mna.yaml")
    BasePage(page, app).open().save_profile(profile)

    offers = OfferListPage(page, app)
    offers.import_offer(offer)
    offers.open_saved_offer(offer["title"])
    OfferDetailPage(page, app).expect_facts(offer)

    wizard = PrepWizardPage(page, app)
    wizard.analyse(offer["title"])
    before = wizard.mandatory_coverage()
    assert before < 100
    prep_before = wizard.prep_text()
    assert "Non trouvé dans ton profil" in prep_before
    assert "Modélisation financière" in prep_before
    assert "Modélisation financière" in prep_before.split("Non trouvé dans ton profil", 1)[1]

    profile["experience"] = (
        profile["experience"].rstrip()
        + "\nStage M&A (synthetic, 2025) : modélisation financière (DCF), "
        "valorisation par comparables et note de deal rationale."
    )
    BasePage(page, app).save_profile(profile)

    wizard.analyse(offer["title"])
    after = wizard.mandatory_coverage()
    assert after > before, f"Couverture inchangée : {before} % → {after} %"

    prep_after = wizard.prep_text()
    matched = prep_after.split("Éléments pertinents de ton profil", 1)[1]
    assert "Modélisation financière" in matched
    assert "modélisation financière (DCF)" in matched
