"""Pipeline panel: the tracked application must appear after kit generation."""

from __future__ import annotations

from pages.base import BasePage


class PipelinePage(BasePage):
    def refresh(self) -> None:
        self.show("stagehunter")
        self.page.locator("#stagehunter-pipeline-refresh").click()
        self.page.locator("#stagehunter-pipeline .pipeline-row").first.wait_for(state="visible")

    def expect_application(self, company: str, variant_label: str) -> None:
        rows = self.page.locator("#stagehunter-pipeline .pipeline-row")
        matching = rows.filter(has_text=company)
        assert matching.count() == 1, f"Candidature {company!r} absente du pipeline."
        text = matching.first.inner_text()
        assert variant_label in text
        assert "Aucun envoi automatique" in self.page.locator("#stagehunter-pipeline").inner_text() or "Préparer" in text
