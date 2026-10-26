"""Base page object: navigation and the shared Career shell."""

from __future__ import annotations

from playwright.sync_api import Page

from conftest import AppServer


class BasePage:
    def __init__(self, page: Page, app: AppServer) -> None:
        self.page = page
        self.app = app

    def open(self) -> "BasePage":
        self.page.goto(f"{self.app.base_url}/career", wait_until="networkidle")
        self.page.wait_for_selector("#career-message", state="attached")
        return self

    def show(self, view: str) -> None:
        self.page.locator(f'.career-tab[data-view="{view}"]').click()
        self.page.locator(f"#view-{view}").wait_for(state="visible")

    def message(self) -> str:
        return self.page.locator("#career-message").inner_text()

    def wait_message(self, fragment: str) -> None:
        self.page.wait_for_function(
            "(fragment) => document.querySelector('#career-message')?.textContent?.includes(fragment)",
            arg=fragment,
            timeout=15_000,
        )

    def save_profile(self, profile: dict[str, str]) -> None:
        self.show("profile")
        fields = {
            "display_name": profile.get("display_name", ""),
            "contact_email": profile.get("contact_email", ""),
            "education": profile.get("education", ""),
            "experience": profile.get("experience", ""),
            "skills": profile.get("skills", ""),
            "languages": profile.get("languages", ""),
        }
        for name, value in fields.items():
            self.page.locator(f'#profile-form [name="{name}"]').fill(value)
        self.page.locator('#profile-form button[type="submit"]').click()
        self.wait_message("Profil enregistré")
