"""Parcours 3 — aucune compétence inventée dans le kit généré."""

from __future__ import annotations

import re

from pages.base import BasePage
from pages.offer_detail import OfferDetailPage
from pages.offer_list import OfferListPage
from pages.prep_wizard import PrepWizardPage
from utils import load_offer, load_profile

_CLAIMS = re.compile(
    r"(je maîtrise|j['’]ai (une )?(solide )?(expérience|compétence)|expert en|"
    r"compétence (avérée|reconnue) en)\s+(la\s+)?mod[ée]lisation",
    re.IGNORECASE,
)


def test_anti_invention(page, app) -> None:
    offer = load_offer("goldman_mna.json")
    BasePage(page, app).open().save_profile(load_profile("junior_mna.yaml"))

    offers = OfferListPage(page, app)
    offers.import_offer(offer)
    offers.open_saved_offer(offer["title"])
    OfferDetailPage(page, app).expect_facts(offer)

    wizard = PrepWizardPage(page, app)
    wizard.analyse(offer["title"])
    kit = wizard.prepare_kit("fr", "m_a")

    for document in (kit["cv"], kit["letter"]):
        assert not _CLAIMS.search(document), "Le kit affirme une compétence non prouvée."

    # Toute mention de modélisation doit rester attribuée à l'offre ou signalée
    # comme à vérifier, jamais présentée comme une compétence du candidat.
    cv_lower = kit["cv"].lower()
    assert "à vérifier" in cv_lower
    assert "modélisation" in cv_lower
    assert "sans prétendre" in kit["letter"].lower()
    assert "[à compléter" in kit["letter"].lower() or "à préciser" in kit["letter"].lower()

    checks = kit["checks"].lower()
    assert "à compléter avant usage" in checks
    assert "non trouvé dans ton profil" in checks
    assert "modélisation" in checks
    assert "aucun envoi automatique" in kit["disclaimer"].lower()
    assert "déposée par toi" in kit["disclaimer"].lower()
