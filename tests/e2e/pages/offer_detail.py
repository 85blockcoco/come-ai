"""Page Object de la fiche offre / analyse de préparation (Stage Hunter)."""

from __future__ import annotations

from .base import CareerPage


class OfferDetailPage(CareerPage):
    def open_prep(self, title: str, company: str) -> "OfferDetailPage":
        """Ouvre Stage Hunter, sélectionne l'offre et lance l'analyse locale."""

        self.open_view("stagehunter")
        self.page.wait_for_function(
            "() => document.querySelectorAll('#stagehunter-prep-job option').length > 1",
            timeout=20_000,
        )
        select = self.page.locator("#stagehunter-prep-job")
        option_label = f"{title} — {company}"
        try:
            select.select_option(label=option_label)
        except Exception:
            select.select_option(label=title)
        self.page.click("#stagehunter-prep-submit")
        self.page.wait_for_selector("#stagehunter-prep .cv-coverage-card", timeout=20_000)
        self.page.wait_for_selector("#stagehunter-prep .variant-specific", timeout=20_000)
        return self

    # -- lecture de l'analyse ------------------------------------------
    def prep_text(self) -> str:
        return self.page.locator("#stagehunter-prep").inner_text()

    def coverage_percent(self) -> int:
        text = self.page.locator("#stagehunter-prep .cv-coverage-card strong").inner_text()
        number = "".join(character for character in text if character.isdigit())
        assert number, f"Couverture CV illisible : {text!r}"
        return int(number)

    def coverage_detail(self) -> str:
        return self.page.locator("#stagehunter-prep .cv-coverage-card").inner_text()

    def recommended_variant(self) -> str:
        return self.page.locator("#stagehunter-prep .variant-specific .application-meta").first.inner_text()

    def section_text(self, heading: str) -> str:
        sections = self.page.locator("#stagehunter-prep section.stagehunter-prep-section")
        for index in range(sections.count()):
            section = sections.nth(index)
            if section.locator("h4").inner_text().strip() == heading:
                return section.inner_text()
        return ""

    def unverified_text(self) -> str:
        return self.section_text("Non trouvé dans ton profil")

    def matched_text(self) -> str:
        return self.section_text("Éléments pertinents de ton profil")

    def has_unverified(self, term: str) -> bool:
        return term.casefold() in self.unverified_text().casefold()

    def has_matched(self, term: str) -> bool:
        return term.casefold() in self.matched_text().casefold()

    def variant_options(self) -> dict[str, str]:
        select = self.page.locator("#stagehunter-prep .kit-variant-select")
        options: dict[str, str] = {}
        for index in range(select.locator("option").count()):
            option = select.locator("option").nth(index)
            options[str(option.get_attribute("value"))] = option.inner_text().strip()
        return options
