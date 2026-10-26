"""Fixtures E2E : serveur applicatif réel + page navigateur (SPEC-007)."""

from __future__ import annotations

import os
import socket
import sys
import threading
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))

from utils import BrowserPage, HttpPage  # noqa: E402


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.bind(("127.0.0.1", 0))
        return int(probe.getsockname()[1])


@pytest.fixture(scope="session")
def base_url(tmp_path_factory: pytest.TempPathFactory) -> str:
    """Lance l'application F08 sur un répertoire de données synthétique."""
    import httpx
    import uvicorn

    from come_ai_web import create_app

    base_dir = tmp_path_factory.mktemp("e2e-base")
    port = _free_port()
    config = uvicorn.Config(
        create_app(base_dir=base_dir),
        host="127.0.0.1",
        port=port,
        log_level="error",
        lifespan="off",
    )
    server = uvicorn.Server(config)
    server.install_signal_handlers = lambda: None  # type: ignore[method-assign]
    thread = threading.Thread(target=server.run, daemon=True, name="career-e2e-server")
    thread.start()

    url = f"http://127.0.0.1:{port}"
    deadline = time.monotonic() + 30
    last_error: Exception | None = None
    while time.monotonic() < deadline:
        try:
            response = httpx.get(f"{url}/api/career/health", timeout=1.0)
            if response.status_code == 200:
                break
        except Exception as error:  # pragma: no cover - attente de démarrage
            last_error = error
        time.sleep(0.1)
    else:  # pragma: no cover - le serveur ne démarre pas
        server.should_exit = True
        pytest.fail(f"le serveur E2E n'a pas démarré : {last_error}")

    yield url

    server.should_exit = True
    thread.join(timeout=10)


@pytest.fixture
def page(base_url: str):
    """Page Playwright si disponible, sinon repli HTTP (même scénario)."""
    require_browser = os.environ.get("E2E_REQUIRE_BROWSER") == "1"
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        if require_browser:
            pytest.fail("E2E_REQUIRE_BROWSER=1 mais playwright n'est pas installé")
        with HttpPage(base_url) as fallback:
            yield fallback
        return

    manager = sync_playwright().start()
    try:
        browser = manager.chromium.launch()
    except Exception:
        manager.stop()
        if require_browser:
            raise
        with HttpPage(base_url) as fallback:
            yield fallback
        return

    context = browser.new_context()
    browser_page = context.new_page()
    try:
        yield BrowserPage(browser_page, base_url)
    finally:
        context.close()
        browser.close()
        manager.stop()
