"""Parcours 2 — Profil incomplet → preuve ajoutée → couverture qui progresse."""

from __future__ import annotations

from pages import build_pages
from utils import load_offer, load_profile


def test_profile_incomplete_then_evidence(career_app) -> None:
    offer = load_offer("goldman_mna.json")
    junior = load_profile("junior_mna.yaml")
    senior = load_profile("senior_analyst.yaml")
    pages = build_pages(career_app)

    # 1. Profil volontairement incomplet (aucune preuve de modélisation).
    pages.profile.save_profile(junior)

    # 2-3. Analyser une offre exigeant la modélisation : la lacune est visible.
    pages.offers.import_offer(offer)
    pages.detail.open_prep(offer["title"], offer["company"])
    initial_coverage = pages.detail.coverage_percent()
    assert pages.detail.has_unverified("Modélisation"), (
        "La modélisation non étayée doit apparaître dans « Non trouvé dans ton profil »"
    )
    assert not pages.detail.has_matched("Modélisation"), "Aucune preuve ne doit être inventée"

    # 4. Ajouter une preuve factuelle dans Mon profil (saisie utilisateur).
    pages.profile.save_profile(senior)

    # 5-6. Relancer l'analyse : la couverture progresse et la preuve est liée.
    pages.detail.open_prep(offer["title"], offer["company"])
    improved_coverage = pages.detail.coverage_percent()
    assert improved_coverage > initial_coverage, (
        f"Couverture inchangée après ajout de preuve ({initial_coverage}% → {improved_coverage}%)"
    )
    assert pages.detail.has_matched("Modélisation"), (
        "La preuve ajoutée doit être citée dans « Éléments pertinents de ton profil »"
    )
    assert not pages.detail.has_unverified("Modélisation"), (
        "La modélisation ne doit plus être listée comme non trouvée"
    )
    assert "0 à vérifier" in pages.detail.coverage_detail()
