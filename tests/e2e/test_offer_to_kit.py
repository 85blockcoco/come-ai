"""Parcours 1 — Offre importée → analyse → variante → kit → pipeline.

Toutes les données sont synthétiques (fixtures locales) et le navigateur ne
peut joindre que l'origine FastAPI locale.
"""

from __future__ import annotations

from pathlib import Path

from pages import build_pages
from utils import assert_synthetic_offer, load_offer


def test_offer_to_kit(career_app) -> None:
    offer = load_offer("goldman_mna.json")
    assert_synthetic_offer(offer)
    pages = build_pages(career_app)

    # 1-2. Importer l'offre par le formulaire officiel, puis la retrouver.
    pages.offers.import_offer(offer)
    assert pages.offers.has_offer(offer["title"]), "L'offre importée n'apparaît pas dans la liste"

    # 3. Lancer la préparation locale depuis Stage Hunter.
    pages.detail.open_prep(offer["title"], offer["company"])
    assert pages.detail.recommended_variant(), "Aucune variante recommandée affichée"
    assert pages.detail.coverage_percent() >= 0
    assert "Couverture obligatoire" in pages.detail.prep_text()

    # 4-6. Consulter la variante recommandée, puis en choisir une autre à la main
    # et vérifier que les couvertures par variante restent visibles.
    options = pages.detail.variant_options()
    assert "m_a" in options and "markets" in options and "corporate_finance" in options
    pages.prep.choose_variant("markets")

    # 7-8. Générer le kit et télécharger les documents (CV + lettre, Word + PDF).
    pages.prep.generate_kit()
    kit_text = pages.prep.kit_text()
    assert offer["company"] in kit_text
    persisted = pages.prep.persisted_kit()
    assert persisted["draft"]["variant"] == "markets", "La variante choisie n'a pas été appliquée au dossier"
    artifacts = pages.prep.targeted_artifacts()
    assert set(artifacts) == {"cv", "cover_letter", "prep_sheet"}, artifacts
    assert all(Path(path).is_file() for path in artifacts.values()), artifacts
    downloaded = pages.prep.download_documents()
    suffixes = {path.suffix.lower() for path in downloaded}
    assert suffixes == {".docx", ".pdf"}, f"Exports incomplets : {downloaded}"
    assert len(downloaded) >= 4, f"CV et lettre doivent être exportés en Word et PDF : {downloaded}"

    # 9. Le suivi est créé et visible dans le pipeline, sans aucune soumission.
    pages.pipeline.assert_tracked(offer["title"])
    assert pages.pipeline.stage_label(offer["title"])
    assert career_app.network.external_attempts == [], (
        f"Appels externes inattendus : {career_app.network.external_attempts}"
    )
