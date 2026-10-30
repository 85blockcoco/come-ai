"""Parcours 3 — Protection anti-invention sur un profil sans preuve.

Scénario adversarial : l'offre exige la modélisation, le profil ne la contient
pas. Le kit doit soit l'omettre, soit la présenter comme une lacune à vérifier ;
jamais comme une compétence acquise.
"""

from __future__ import annotations

import pytest

from pages import build_pages
from utils import assert_no_invention, load_offer, load_profile


@pytest.mark.parametrize("term", ["modélisation", "LBO"])
def test_anti_invention(career_app, term: str) -> None:
    offer = load_offer("goldman_mna.json")
    junior = load_profile("junior_mna.yaml")
    pages = build_pages(career_app)

    pages.profile.save_profile(junior)
    pages.offers.import_offer(offer)
    pages.detail.open_prep(offer["title"], offer["company"])
    assert pages.detail.has_unverified("Modélisation")

    pages.prep.generate_kit()

    # Aucun document ne peut affirmer le terme sans réserve explicite.
    assert_no_invention(pages.prep.cv_text(), term, "Le CV généré")
    assert_no_invention(pages.prep.letter_text(), term, "La lettre générée")

    # Le vérificateur de faits local doit exposer la lacune et les placeholders.
    fact_checks = pages.prep.fact_checks_text()
    assert "non trouvé dans ton profil" in fact_checks.casefold()
    assert "modélisation" in fact_checks.casefold()
    assert "À compléter avant usage" in fact_checks, (
        f"Aucun placeholder signalé dans le vérificateur : {fact_checks[:600]}"
    )
