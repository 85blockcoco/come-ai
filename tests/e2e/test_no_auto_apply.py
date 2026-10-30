"""Parcours 4 — Zéro envoi : aucune requête externe ni action de candidature.

Le contexte navigateur avorte et journalise toute requête hors origine locale.
Le parcours complet (profil → offre → analyse → kit → pipeline) doit produire
zéro tentative externe, zéro écriture distante et aucun contrôle d'envoi.
"""

from __future__ import annotations

import re

from pages import build_pages
from utils import load_offer, load_profile

FORBIDDEN_CONTROLS = re.compile(r"^(envoyer|postuler|soumettre|candidater|transmettre)\b", re.IGNORECASE)


def test_no_auto_apply(career_app) -> None:
    offer = load_offer("jpm_ibd.json")
    profile = load_profile("senior_analyst.yaml")
    pages = build_pages(career_app)

    pages.profile.save_profile(profile)
    pages.offers.import_offer(offer)
    pages.detail.open_prep(offer["title"], offer["company"])
    pages.prep.generate_kit()
    pages.pipeline.assert_tracked(offer["title"])

    # 1. Aucune requête n'a quitté l'origine locale, même avortée.
    assert career_app.network.external_attempts == [], (
        "Des requêtes externes ont été tentées : " + ", ".join(career_app.network.external_attempts)
    )
    assert career_app.network.non_local_writes() == []

    # 2. L'API elle-même déclare l'absence de soumission automatique.
    health = pages.offers.health()
    assert health.get("automated_submission") is False

    # 3. L'interface ne propose aucun contrôle d'envoi et ne contient aucun mailto.
    controls = pages.offers.page.get_by_role("button").all_inner_texts()
    controls += pages.offers.page.get_by_role("link").all_inner_texts()
    forbidden = [label for label in controls if FORBIDDEN_CONTROLS.match(label.strip())]
    assert forbidden == [], f"Contrôles d'envoi détectés : {forbidden}"
    assert pages.offers.page.locator('a[href^="mailto:"]').count() == 0

    # 4. Le kit rappelle explicitement que l'envoi reste manuel.
    assert "envoi est strictement manuel" in pages.prep.kit_text()
    assert pages.offers.page.url.startswith(career_app.origin)
