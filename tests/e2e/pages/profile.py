"""Page Object du profil local (formulaire « Mon profil »)."""

from __future__ import annotations

from typing import Any

from .base import CareerPage

FIELD_IDS = {
    "display_name": "#profile-display-name",
    "eligibility": "#profile-eligibility",
    "contact_email": "#profile-contact-email",
    "contact_phone": "#profile-contact-phone",
    "linkedin_url": "#profile-linkedin-url",
    "education": "#profile-education",
    "experience": "#profile-experience",
    "skills": "#profile-skills",
    "languages": "#profile-languages",
    "target_companies": "#profile-companies",
    "notes": "#profile-notes",
}


class ProfilePage(CareerPage):
    def save_profile(self, profile: dict[str, Any]) -> "ProfilePage":
        self.open_view("profile")
        for field, selector in FIELD_IDS.items():
            value = str(profile.get(field, "") or "")
            locator = self.page.locator(selector)
            if field == "eligibility":
                locator.select_option(value or "unknown")
            else:
                locator.fill(value)
        self.page.locator("#profile-form button[type=submit]").click()
        self.wait_message("Profil enregistré")
        return self
