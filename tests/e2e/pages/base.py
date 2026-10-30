"""Socle des Page Objects E2E Career."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:  # pragma: no cover - typage uniquement
    from playwright.sync_api import Locator, Page

    from ..conftest import NetworkGuard


class CareerPage:
    """Accès commun à l'application Career servie par FastAPI."""

    def __init__(self, page: "Page", origin: str, network: "NetworkGuard", downloads_dir: Path):
        self.page = page
        self.origin = origin
        self.network = network
        self.downloads_dir = downloads_dir

    # -- navigation -----------------------------------------------------
    def open(self) -> "CareerPage":
        self.page.goto(f"{self.origin}/career", wait_until="domcontentloaded")
        self.page.wait_for_selector("#career-health")
        self.page.wait_for_function(
            "() => document.querySelector('#career-loading')?.hidden === true",
            timeout=30_000,
        )
        return self

    def open_view(self, view: str) -> "CareerPage":
        self.page.click(f"#tab-{view}")
        self.page.wait_for_selector(f"#view-{view}:not([hidden])")
        return self

    def show_view(self, view: str) -> "CareerPage":
        """Pour les vues sans onglet (studio) : déclencheur data-view-action."""

        self.page.locator(f'[data-view-action="{view}"]').first.click()
        self.page.wait_for_selector(f"#view-{view}:not([hidden])")
        return self

    # -- messages -------------------------------------------------------
    @property
    def message(self) -> str:
        return self.page.locator("#career-message").inner_text()

    def wait_message(self, fragment: str, timeout: int = 15_000) -> str:
        self.page.wait_for_function(
            "(fragment) => (document.querySelector('#career-message')?.textContent || '').includes(fragment)",
            arg=fragment,
            timeout=timeout,
        )
        return self.message

    def health(self) -> dict[str, object]:
        response = self.page.request.get(f"{self.origin}/api/career/health")
        assert response.ok, f"Health Career indisponible : {response.status}"
        return response.json()

    def wait_for_jobs(self, expected: int = 1) -> "Locator":
        card = self.page.locator("#jobs-list .job-card").first
        self.page.wait_for_function(
            "(count) => document.querySelectorAll('#jobs-list .job-card').length >= count",
            arg=expected,
            timeout=15_000,
        )
        return card
