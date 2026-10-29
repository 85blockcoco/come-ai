"""Offer list and synthetic manual import through the real browser form."""

from __future__ import annotations

from typing import Any

from pages.base import BasePage


class OfferListPage(BasePage):
    def import_offer(self, offer: dict[str, Any]) -> None:
        self.show("discover")
        form = "#job-form"
        self.page.locator(f'{form} [name="company"]').fill(offer["company"])
        self.page.locator(f'{form} [name="title"]').fill(offer["title"])
        self.page.locator(f'{form} [name="official_url"]').fill(offer["official_url"])
        self.page.locator(f'{form} [name="city"]').fill(offer.get("city", ""))
        self.page.locator(f'{form} [name="country"]').fill(offer.get("country", ""))
        self.page.locator(f"{form} details").evaluate("(element) => { element.open = true; }")
        self.page.locator(f'{form} [name="requirements"]').fill(offer.get("requirements", ""))
        self.page.locator(f'{form} [name="description_original"]').fill(
            offer.get("description_original", "")
        )
        self.page.locator(f"{form} button[type=\"submit\"]").click()
        self.wait_message("Offre enregistrée localement")

    def open_saved_offer(self, title: str) -> None:
        self.show("stagehunter")
        card = self.page.locator(".stagehunter-match", has_text=title).first
        card.wait_for(state="visible")
        card.get_by_role("button", name="Voir la fiche complète", exact=True).click()
        self.page.locator("#stagehunter-detail", has_text=title).wait_for(state="visible")
