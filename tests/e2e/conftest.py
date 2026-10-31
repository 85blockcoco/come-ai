"""Playwright fixtures for the Career browser E2E suite (SPEC-009).

The suite boots an isolated FastAPI instance on a random loopback port with an
in-memory-ish temporary SQLite database and synthetic data only. No real
provider, network connector or user data is touched.
"""

from __future__ import annotations

import socket
import threading
import time
from pathlib import Path
from typing import Iterator

import pytest
import pytest_asyncio
import uvicorn
from playwright.async_api import async_playwright

from career.service import CareerService
from come_ai_web import create_app


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


@pytest.fixture(scope="session")
def app(tmp_path_factory) -> str:
    base_dir = tmp_path_factory.mktemp("e2e-base")
    service = CareerService(base_dir, curated_sources=())
    fastapi_app = create_app(base_dir=base_dir, career_override=service)
    port = _free_port()
    config = uvicorn.Config(
        fastapi_app,
        host="127.0.0.1",
        port=port,
        log_level="warning",
        access_log=False,
    )
    server = uvicorn.Server(config)
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    base_url = f"http://127.0.0.1:{port}"
    deadline = time.time() + 15
    last_error: Exception | None = None
    while time.time() < deadline:
        try:
            import urllib.request

            with urllib.request.urlopen(base_url + "/api/health", timeout=1) as response:
                if response.status == 200:
                    break
        except Exception as error:  # pragma: no cover - startup race
            last_error = error
            time.sleep(0.1)
    else:  # pragma: no cover - startup failure
        server.should_exit = True
        thread.join(timeout=5)
        raise RuntimeError(f"FastAPI test server did not start: {last_error!r}")
    yield base_url
    server.should_exit = True
    thread.join(timeout=10)


@pytest_asyncio.fixture
async def page(app: str):
    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch()
        context = await browser.new_context(base_url=app)
        page = await context.new_page()
        yield page
        await context.close()
        await browser.close()


@pytest.hookimpl(tryfirst=True, hookwrapper=True)
def pytest_runtest_makereport(item, call):
    outcome = yield
    if call.when != "call" or not outcome.excinfo:
        return
    page = item.funcargs.get("page") if hasattr(item, "funcargs") else None
    if page is None:
        return
    try:
        import asyncio

        async def _shot() -> None:
            await page.screenshot(path=f"e2e_failure_{item.name}.png", full_page=True)

        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                loop.create_task(_shot())
            else:
                loop.run_until_complete(_shot())
        except Exception:
            pass
    except Exception:
        pass
"""