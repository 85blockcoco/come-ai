"""Base page object for the Career browser E2E suite."""

from __future__ import annotations


class BasePage:
    def __init__(self, page, base_url: str):
        self.page = page
        self.base_url = base_url

    async def goto_career(self) -> None:
        await self.page.goto(self.base_url + "/career")
        await self.page.wait_for_load_state("networkidle")
"""