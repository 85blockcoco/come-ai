"""Page Object du suivi des candidatures (pipeline)."""

from __future__ import annotations

from .base import CareerPage


class PipelinePage(CareerPage):
    def application_card(self, title: str):
        self.open_view("applications")
        self.page.wait_for_selector("#applications-list .application-card", timeout=20_000)
        return self.page.locator("#applications-list .application-card", has_text=title).first

    def assert_tracked(self, title: str) -> None:
        card = self.page.locator("#applications-list .application-card", has_text=title).first
        assert card.count() > 0, f"L'offre « {title} » n'apparaît pas dans le pipeline"
        assert title in card.locator("h3").inner_text(), "Titre du suivi incohérent"
        assert card.get_by_role("button", name="Ouvrir le kit de candidature").count() == 1

    def stage_label(self, title: str) -> str:
        card = self.page.locator("#applications-list .application-card", has_text=title).first
        chip = card.locator(".job-chip").first
        return chip.inner_text().strip()

    def kit_container(self, title: str):
        return self.page.locator(
            "#applications-list .application-kit", has_text=title
        ).first
