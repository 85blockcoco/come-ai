"""Page Object de la liste des offres et de l'import manuel."""

from __future__ import annotations

from typing import Any

from .base import CareerPage

TEXT_FIELDS = (
    "source_id",
    "official_url",
    "city",
    "country",
    "posted_date",
    "deadline_date",
    "start_date",
    "end_date",
    "employment_type",
    "role_level",
    "requirements",
    "languages_required",
    "eligibility_requirement",
    "description_original",
)


class OfferListPage(CareerPage):
    def import_offer(self, offer: dict[str, Any]) -> "OfferListPage":
        """Importe une offre par le formulaire « Source manuelle » (vue Découvrir)."""

        self.open_view("discover")
        form = self.page.locator("#job-form")
        form.locator('input[name="company"]').fill(str(offer["company"]))
        form.locator('input[name="title"]').fill(str(offer["title"]))
        if offer.get("job_family"):
            select = self.page.locator("#job-family")
            try:
                select.select_option(label=str(offer["job_family"]))
            except Exception:
                # La liste dépend des préférences : la famille reste facultative.
                pass
        if offer.get("source_status"):
            form.locator('select[name="source_status"]').select_option(str(offer["source_status"]))
        if offer.get("duration_months"):
            form.locator('input[name="duration_months"]').fill(str(offer["duration_months"]))
        # Les champs détaillés vivent dans un <details> replié.
        details = form.locator("details")
        if "open" not in (details.get_attribute("open") or ""):
            details.locator("summary").click()
        for field in TEXT_FIELDS:
            value = offer.get(field)
            if not value:
                continue
            form.locator(f'[name="{field}"]').fill(str(value))
        form.locator('button[type="submit"]').click()
        self.page.wait_for_function(
            "() => /Offre (enregistrée|déjà connue)/.test(document.querySelector('#career-message')?.textContent || '')",
            timeout=15_000,
        )
        return self

    def offer_card(self, title: str):
        return self.page.locator("#jobs-list .job-card", has_text=title).first

    def has_offer(self, title: str) -> bool:
        card = self.offer_card(title)
        try:
            card.wait_for(state="visible", timeout=15_000)
        except Exception:
            return False
        return True
