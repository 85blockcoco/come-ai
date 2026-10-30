"""Fixtures Playwright pour les parcours navigateur Career (SPEC-009).

Chaque test tourne contre un serveur FastAPI réel, lancé dans un processus
séparé sur un port libre, avec un ``base_dir`` temporaire : ni la base SQLite,
ni les exports, ni le profil de la personne ne touchent les données réelles.
Le navigateur n'autorise que l'origine locale ; toute tentative vers un hôte
externe est avortée et enregistrée (garde-fou « aucun envoi automatique »).
"""

from __future__ import annotations

import html
import json
import os
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

import pytest

E2E_DIR = Path(__file__).resolve().parent
REPO_ROOT = E2E_DIR.parent.parent
SERVER_SCRIPT = E2E_DIR / "server.py"
ARTIFACTS_DIR = E2E_DIR / "artifacts"
STARTUP_TIMEOUT_SECONDS = 60

_RESULTS: list[dict[str, object]] = []


def _playwright_available() -> bool:
    try:
        import playwright.sync_api  # noqa: F401
    except Exception:
        return False
    return True


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _wait_for_health(origin: str, process: subprocess.Popen[str]) -> dict[str, object]:
    deadline = time.monotonic() + STARTUP_TIMEOUT_SECONDS
    last_error: Exception | None = None
    while time.monotonic() < deadline:
        if process.poll() is not None:
            _, stderr = process.communicate(timeout=5)
            raise RuntimeError(f"Serveur E2E arrêté au démarrage :\n{stderr[-4000:]}")
        try:
            with urllib.request.urlopen(f"{origin}/api/career/health", timeout=2) as response:
                return json.loads(response.read().decode("utf-8"))
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as error:
            last_error = error
            time.sleep(0.25)
    raise RuntimeError(f"Serveur E2E non prêt après {STARTUP_TIMEOUT_SECONDS}s : {last_error}")


@dataclass
class NetworkGuard:
    """Autorise l'origine locale et avorte tout le reste, preuve à l'appui."""

    origin: str
    external_attempts: list[str] = field(default_factory=list)
    requests: list[tuple[str, str]] = field(default_factory=list)

    def handle(self, route: object) -> None:
        request = route.request  # type: ignore[attr-defined]
        url = request.url
        self.requests.append((request.method, url))
        if url.startswith(self.origin) or url.startswith(("data:", "blob:", "about:")):
            route.continue_()  # type: ignore[attr-defined]
            return
        self.external_attempts.append(url)
        route.abort()  # type: ignore[attr-defined]

    def non_local_writes(self) -> list[tuple[str, str]]:
        return [
            (method, url)
            for method, url in self.requests
            if method in {"POST", "PUT", "PATCH", "DELETE"} and not url.startswith(self.origin)
        ]


@dataclass
class E2EApp:
    """Petit conteneur passé aux Page Objects."""

    page: object
    origin: str
    network: NetworkGuard
    downloads_dir: Path


@pytest.fixture(scope="session", autouse=True)
def _playwright_requirement() -> None:
    if not _playwright_available():
        pytest.skip(
            "Playwright n'est pas installé dans cet interpréteur : "
            "`python -m pip install playwright pytest-playwright && playwright install chromium`."
        )


@pytest.fixture(scope="session")
def app_server() -> str:
    """Serveur FastAPI isolé (base SQLite et exports temporaires)."""

    base_dir = ARTIFACTS_DIR / "server" / f"{int(time.time() * 1000)}"
    base_dir.mkdir(parents=True, exist_ok=True)
    port = _free_port()
    origin = f"http://127.0.0.1:{port}"

    env = os.environ.copy()
    env["PYTHONPATH"] = str(REPO_ROOT) + (os.pathsep + env["PYTHONPATH"] if env.get("PYTHONPATH") else "")
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    # Aucun test ne doit pouvoir appeler un fournisseur IA, même par mégarde.
    for secret in (
        "GEMINI_API_KEY",
        "GOOGLE_API_KEY",
        "OPENROUTER_API_KEY",
        "OPENAI_API_KEY",
        "ANTHROPIC_API_KEY",
        "MISTRAL_API_KEY",
    ):
        env.pop(secret, None)
    env["COME_AI_MEMORY_DIR"] = str(base_dir / "memory_data")

    process = subprocess.Popen(
        [sys.executable, str(SERVER_SCRIPT), str(base_dir), str(port)],
        cwd=str(REPO_ROOT),
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    try:
        _wait_for_health(origin, process)
        yield origin
    finally:
        process.terminate()
        try:
            process.wait(timeout=15)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=5)


@pytest.fixture(scope="session")
def chromium_browser() -> object:
    from playwright.sync_api import Error as PlaywrightError
    from playwright.sync_api import sync_playwright

    with sync_playwright() as playwright:
        try:
            browser = playwright.chromium.launch(headless=True)
        except PlaywrightError as error:
            pytest.skip(
                "Navigateur Chromium Playwright indisponible : "
                f"`playwright install chromium` requis ({error})."
            )
        try:
            yield browser
        finally:
            browser.close()


@pytest.fixture()
def career_app(app_server: str, chromium_browser: object, tmp_path: Path, request: pytest.FixtureRequest) -> E2EApp:
    from playwright.sync_api import Error as PlaywrightError

    network = NetworkGuard(origin=app_server)
    context = chromium_browser.new_context(  # type: ignore[attr-defined]
        accept_downloads=True,
        viewport={"width": 1440, "height": 1000},
        locale="fr-FR",
        timezone_id="Europe/Paris",
    )
    context.route("**/*", network.handle)
    page = context.new_page()
    page.set_default_timeout(20_000)
    downloads_dir = tmp_path / "downloads"
    downloads_dir.mkdir()
    request.node._e2e_page = page  # type: ignore[attr-defined]
    request.node._e2e_network = network  # type: ignore[attr-defined]
    try:
        yield E2EApp(page=page, origin=app_server, network=network, downloads_dir=downloads_dir)
    finally:
        try:
            context.close()
        except PlaywrightError:
            pass


@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_makereport(item: pytest.Item, call: pytest.CallInfo[None]) -> object:
    outcome = yield
    report = outcome.get_result()  # type: ignore[attr-defined]
    if report.when == "call" and report.failed:
        page = getattr(item, "_e2e_page", None)
        if page is not None:
            ARTIFACTS_DIR.mkdir(parents=True, exist_ok=True)
            screenshot = ARTIFACTS_DIR / f"FAILED-{item.name}.png"
            try:
                page.screenshot(path=str(screenshot), full_page=True)
                report.sections.append(("capture d'échec", str(screenshot)))
            except Exception:  # pragma: no cover - diagnostic seulement
                pass
    if report.when in {"setup", "call"}:
        _RESULTS.append(
            {
                "nodeid": report.nodeid,
                "when": report.when,
                "outcome": report.outcome,
                "duration": round(float(report.duration or 0), 2),
                "detail": (report.longreprtext or "")[:4000],
            }
        )


def pytest_sessionfinish(session: pytest.Session, exitstatus: int) -> None:
    if not _RESULTS:
        return
    ARTIFACTS_DIR.mkdir(parents=True, exist_ok=True)
    rows = []
    for result in _RESULTS:
        tone = {"passed": "#1a7f37", "failed": "#cf222e", "skipped": "#9a6700"}.get(
            str(result["outcome"]), "#57606a"
        )
        rows.append(
            "<tr>"
            f"<td>{html.escape(str(result['nodeid']))}</td>"
            f"<td style=\"color:{tone};font-weight:600\">{html.escape(str(result['outcome']))}</td>"
            f"<td>{result['duration']}s</td>"
            f"<td><pre>{html.escape(str(result['detail']))}</pre></td>"
            "</tr>"
        )
    generated = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    document = f"""<!doctype html>
<html lang="fr"><head><meta charset="utf-8"><title>Rapport E2E Career — SPEC-009</title>
<style>
body{{font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif;margin:2rem;color:#1f2328}}
table{{border-collapse:collapse;width:100%}}th,td{{border:1px solid #d0d7de;padding:.5rem;text-align:left;vertical-align:top}}
pre{{white-space:pre-wrap;margin:0;font-size:.8rem}}th{{background:#f6f8fa}}
</style></head><body>
<h1>Rapport E2E Career — SPEC-009</h1>
<p>Généré le {generated} · {len(_RESULTS)} étape(s) · code de sortie pytest : {exitstatus}</p>
<table><thead><tr><th>Test</th><th>Résultat</th><th>Durée</th><th>Détail</th></tr></thead>
<tbody>{''.join(rows)}</tbody></table>
</body></html>
"""
    (ARTIFACTS_DIR / "report.html").write_text(document, encoding="utf-8")
