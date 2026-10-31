"""Page object for the Career offer list."""

from __future__ import annotations


class OfferListPage:
    def __init__(self, page):
        self.page = page

    async def wait_loaded(self) -> None:
        await self.page.wait_for_selector("#jobs-list, #stagehunter-matches", timeout=10000)
"""<|end|><|start|>write to=assistant<|channel|>analysis <|constrain|>xml<|message|><rfl:parameter name="path">
tests/e2e/pages/offer_detail.py