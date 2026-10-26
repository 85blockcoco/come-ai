"""Offer detail panel (synthetic offer, local preparation entry point)."""

from __future__ import annotations

from pages.base import BasePage


class OfferDetailPage(BasePage):
    def expect_facts(self, offer: dict[str, str]) -> None:
        detail = self.page.locator("#stagehunter-detail")
        detail.wait_for(state="visible")
        text = detail.text_content() or ""
        assert offer["title"] in text
        assert offer["company"] in text

    def open_preparation(self) -> None:
        detail = self.page.locator("#stagehunter-detail")
        detail.get_by_role("button", name="Préparer cette candidature").click()
        self.page.locator("#stagehunter-prep").wait_for(state="visible")
