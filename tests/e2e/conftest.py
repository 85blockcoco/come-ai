"""Shared fixtures for the isolated Playwright end-to-end suite.

The FastAPI application runs on a random local port with a throw-away
``base_dir``: SQLite database, exports and logs never touch the real Career
data. Only synthetic offers and profiles are used.
"""

from __future__ import annotations

import html
import importlib.util
import socket
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterator

import pytest
import uvicorn

from career.service import CareerService
from come_ai_web import create_app

try:  # Playwright is optional on machines that only run the Python suite.
    from playwright.sync_api import Browser, Page, sync_playwright
except ImportError:  # pragma: no cover - the E2E modules are then not collected
    Browser = Any  # type: ignore[assignment,misc]
    Page = Any  # type: ignore[assignment,misc]
    sync_playwright = None  # type: ignore[assignment]
    collect_ignore_glob = ["test_*.py"]

E2E_ROOT = Path(__file__).resolve().parent
FIXTURES = E2E_ROOT / "fixtures"
ARTIFACTS = E2E_ROOT / "artifacts"


def pytest_addoption(parser: pytest.Parser) -> None:
    """Support the mission's ``--html=PATH`` without requiring pytest-html.

    The installed validation environment does not ship the ``pytest-html``
    plugin, so the option is declared here and served by the small standalone
    report writer below. When pytest-html *is* available, its own ``--html``
    option wins and the report is written to the same requested path.
    """
    if importlib.util.find_spec("pytest_html") is None:
        parser.addoption(
            "--html",
            action="store",
            dest="e2e_html",
            default="e2e-report.html",
            metavar="PATH",
            help="Écrit le rapport E2E autonome dans PATH (défaut : e2e-report.html).",
        )


def _report_path(config: pytest.Config) -> Path:
    for option in ("e2e_html", "htmlpath"):
        try:
            value = config.getoption(option)
        except (AttributeError, ValueError):
            continue
        if value:
            return Path(str(value))
    return Path("e2e-report.html")


@dataclass(frozen=True)
class AppServer:
    base_url: str
    base_dir: Path


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.bind(("127.0.0.1", 0))
        return int(probe.getsockname()[1])


@pytest.fixture()
def app(tmp_path: Path) -> Iterator[AppServer]:
    """Start an isolated FastAPI server on a random port for one test."""
    service = CareerService(tmp_path)
    application = create_app(base_dir=tmp_path, career_override=service)
    port = _free_port()
    server = uvicorn.Server(
        uvicorn.Config(application, host="127.0.0.1", port=port, log_level="error", access_log=False)
    )
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    deadline = time.monotonic() + 20
    while not server.started and time.monotonic() < deadline:
        time.sleep(0.05)
    if not server.started:
        server.should_exit = True
        raise RuntimeError("Le serveur E2E FastAPI n’a pas démarré.")
    try:
        yield AppServer(base_url=f"http://127.0.0.1:{port}", base_dir=tmp_path)
    finally:
        server.should_exit = True
        thread.join(timeout=10)


@pytest.fixture(scope="session")
def browser() -> Iterator[Browser]:
    pytest.importorskip("playwright.sync_api", reason="Playwright n’est pas installé")
    with sync_playwright() as playwright:  # type: ignore[union-attr]
        try:
            instance = playwright.chromium.launch()
        except Exception as error:  # pragma: no cover - machine without browsers
            pytest.skip(f"Chromium Playwright indisponible : {error}")
        try:
            yield instance
        finally:
            instance.close()


@pytest.fixture()
def page(browser: Browser) -> Iterator[Page]:
    context = browser.new_context(accept_downloads=True, viewport={"width": 1440, "height": 1000})
    current = context.new_page()
    current.set_default_timeout(15_000)
    try:
        yield current
    finally:
        context.close()


# --- Failure screenshots and a dependency-free HTML report -------------------

_RESULTS: list[dict[str, Any]] = []


@pytest.hookimpl(tryfirst=True, hookwrapper=True)
def pytest_runtest_makereport(item: pytest.Item, call: pytest.CallInfo[Any]):
    outcome = yield
    report = outcome.get_result()
    # This conftest is loaded for the whole session: when the complete test
    # suite runs, only the browser journeys belong in the E2E report.
    if not item.nodeid.startswith("tests/e2e/"):
        return
    if report.when == "call":
        _RESULTS.append(
            {
                "nodeid": item.nodeid,
                "outcome": report.outcome,
                "duration": report.duration,
                "longrepr": str(report.longrepr or ""),
            }
        )
    if report.when == "call" and report.failed:
        current = item.funcargs.get("page") if hasattr(item, "funcargs") else None
        if current is not None:
            ARTIFACTS.mkdir(parents=True, exist_ok=True)
            screenshot = ARTIFACTS / f"e2e_failure_{item.name}.png"
            try:
                current.screenshot(path=str(screenshot), full_page=True)
            except Exception:  # pragma: no cover - best effort only
                pass


def pytest_sessionfinish(session: pytest.Session, exitstatus: int) -> None:
    if not _RESULTS:
        return
    rows = "\n".join(
        "<tr class='{outcome}'><td>{nodeid}</td><td>{outcome}</td><td>{duration:.2f}s</td></tr>".format(
            outcome=html.escape(result["outcome"]),
            nodeid=html.escape(result["nodeid"]),
            duration=result["duration"],
        )
        for result in _RESULTS
    )
    details = "\n".join(
        f"<h2>{html.escape(result['nodeid'])}</h2><pre>{html.escape(result['longrepr'])}</pre>"
        for result in _RESULTS
        if result["outcome"] != "passed" and result["longrepr"]
    )
    document = f"""<!doctype html>
<html lang="fr"><head><meta charset="utf-8"><title>Rapport E2E Career</title>
<style>body{{font-family:system-ui,sans-serif;margin:2rem}}table{{border-collapse:collapse}}
td,th{{border:1px solid #ccc;padding:.4rem .8rem}}.passed{{background:#e8f5e9}}
.failed{{background:#ffebee}}.skipped{{background:#fff8e1}}pre{{white-space:pre-wrap}}</style>
</head><body><h1>Rapport E2E Career — Playwright</h1>
<p>{len(_RESULTS)} test(s) exécuté(s).</p>
<table><thead><tr><th>Test</th><th>Résultat</th><th>Durée</th></tr></thead>
<tbody>{rows}</tbody></table>{details}</body></html>"""
    report_path = _report_path(session.config)
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(document, encoding="utf-8")
    _RESULTS.clear()
