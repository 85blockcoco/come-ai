"""Parcours 4 — zéro envoi, zéro contact externe non consenti."""

from __future__ import annotations

from urllib.parse import urlparse

from pages.base import BasePage
from pages.offer_detail import OfferDetailPage
from pages.offer_list import OfferListPage
from pages.prep_wizard import PrepWizardPage
from utils import load_offer, load_profile


def test_no_auto_apply(page, app) -> None:
    offer = load_offer("jpm_ibd.json")
    base_host = urlparse(app.base_url).netloc
    requests: list[tuple[str, str]] = []
    page.on("request", lambda request: requests.append((request.method, request.url)))

    BasePage(page, app).open().save_profile(load_profile("senior_analyst.yaml"))
    offers = OfferListPage(page, app)
    offers.import_offer(offer)
    offers.open_saved_offer(offer["title"])
    OfferDetailPage(page, app).expect_facts(offer)

    wizard = PrepWizardPage(page, app)
    wizard.analyse(offer["title"])
    kit = wizard.prepare_kit("en", "m_a")

    external = [
        (method, url)
        for method, url in requests
        if url.startswith(("http://", "https://")) and urlparse(url).netloc != base_host
    ]
    assert external == [], f"Appels externes inattendus : {external}"
    assert not any(url.startswith(("mailto:", "tel:")) for _, url in requests)
    assert not any("linkedin.com" in url for _, url in requests)

    applications = page.request.get(f"{app.base_url}/api/career/applications").json()["applications"]
    assert applications, "Le suivi local aurait dû être créé."
    assert all(item["stage"] != "submitted" for item in applications)
    assert all(not item.get("approved_for_manual_submission") for item in applications)

    kit_text = wizard.kit().inner_text().lower()
    assert "ne poste rien" in kit["disclaimer"].lower() or "ne poste rien" in kit_text
    assert "kit de candidature local" in kit_text
    assert not page.locator(".application-kit").get_by_role(
        "button", name="Envoyer ma candidature"
    ).count()
    assert not page.locator(".application-kit form[action^='http']").count()
