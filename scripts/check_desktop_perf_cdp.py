#!/usr/bin/env python3
"""Vérification CDP (Chrome headless) de la performance perçue de `/app`.

La mission SPEC-053 ajoute trois mécanismes : squelettes structurés, mises à
jour optimistes et préchargement au survol/focus.  Ce script démarre une
instance FastAPI isolée (répertoire temporaire, API simulées avec latence),
puis pilote Chrome via le protocole DevTools pour observer ces mécanismes en
conditions réelles.

Aucune donnée utilisateur n'est lue : les réponses API sont des constantes
locales, les URL pointent vers `example.invalid`.

Usage :
    python scripts/check_desktop_perf_cdp.py
    python scripts/check_desktop_perf_cdp.py --url http://127.0.0.1:8000
"""

from __future__ import annotations

import argparse
import asyncio
import json
import shutil
import subprocess
import sys
import tempfile
import threading
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
for path in (ROOT, SCRIPTS):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

# On réutilise les API simulées de la vérification d'accessibilité et on ajoute
# la latence d'envoi nécessaire pour observer la mise à jour optimiste.
from check_desktop_a11y_cdp import (  # noqa: E402
    MOCK_RESPONSES,
    Recorder,
    Step,
    _free_port,
    _wait_for_port,
    build_app,
    find_chrome,
    goto_app,
    new_context,
    start_chrome,
    wait_for_cdp,
    wait_loaded,
)

MOCK_RESPONSES["/api/career/send-confirmation/job-1"] = {"ok": True}

FAIL_SEND = {"paths": set()}
FAIL_DELAY = 0.5


def wrap_app():
    """Ajoute un interrupteur de panne (500 différé) au-dessus des mocks."""
    from fastapi.responses import JSONResponse

    app, base_dir = build_app()

    @app.middleware("http")
    async def perf_fault(request, call_next):
        if request.url.path in FAIL_SEND["paths"]:
            await asyncio.sleep(FAIL_DELAY)
            return JSONResponse({"detail": "panne simulée"}, status_code=500)
        return await call_next(request)

    return app, base_dir


def _dialog(page):
    page.wait_for_selector('[role="dialog"]', timeout=10_000)
    return page.locator('[role="dialog"]').first


def _close_dialog(page) -> None:
    page.keyboard.press("Escape")
    page.wait_for_selector('[role="dialog"]', state="detached", timeout=5_000)


def run_loading(browser, url: str, recorder: Recorder) -> None:
    """Squelettes et barre de progression pendant un chargement réel."""
    context = new_context(browser)
    page = context.new_page()
    errors: list[str] = []
    page.on("pageerror", lambda exc: errors.append(str(exc)))

    with Step(recorder, "01. squelette visible avant la réponse API") as step:
        goto_app(page, url)
        page.wait_for_selector(".skeleton-view", timeout=5_000)
        state = page.evaluate(
            """() => ({
                busy: document.querySelector('#main').getAttribute('aria-busy'),
                skeleton: document.querySelectorAll('.skeleton-view').length,
                label: document.querySelector('.skeleton-view')?.getAttribute('aria-label'),
            })"""
        )
        step.detail = json.dumps(state)
        assert state["busy"] == "true"
        assert state["skeleton"] == 1
        assert state["label"] == "Chargement des données"

    with Step(recorder, "02. barre de progression différée de 120 ms") as step:
        page.wait_for_timeout(320)
        visible = page.evaluate(
            "() => !document.querySelector('#progressBar').hidden"
        )
        step.detail = f"visible={visible}"
        assert visible, "la barre doit être visible pendant la latence simulée"

    with Step(recorder, "03. squelette structuré (lignes + KPI)") as step:
        shape = page.evaluate(
            """() => ({
                rows: document.querySelectorAll('.skeleton-row').length,
                kpis: document.querySelectorAll('.skeleton-view .skeleton-card, .skeleton-view .skeleton').length,
                hidden: document.querySelector('.skeleton-row')?.getAttribute('aria-hidden'),
            })"""
        )
        step.detail = json.dumps(shape)
        assert shape["rows"] >= 3
        assert shape["kpis"] >= 1
        assert shape["hidden"] == "true"

    with Step(recorder, "04. chargement terminé : squelette et barre disparus") as step:
        wait_loaded(page)
        page.wait_for_selector(".skeleton-view", state="detached", timeout=10_000)
        hidden = page.evaluate("() => document.querySelector('#progressBar').hidden")
        assert hidden is True

    with Step(recorder, "05. squelette spécifique à la vue Offres (6 lignes)") as step:
        page.evaluate("() => { window.__appState.jobs = null; }")
        page.locator('.nav-item[data-view="offers"]').click()
        rows = page.evaluate(
            "() => document.querySelectorAll('#view-offers .skeleton-row').length"
        )
        step.detail = f"lignes={rows}"
        assert rows == 6

    with Step(recorder, "06. aucune erreur JavaScript au chargement") as step:
        step.detail = json.dumps(errors, ensure_ascii=False)
        assert not errors

    context.close()


def run_prefetch(browser, url: str, recorder: Recorder) -> None:
    """Préchargement des fiches détail au survol, consommé une seule fois."""
    context = new_context(browser)
    page = context.new_page()
    requests: list[str] = []
    quick_requests: list[str] = []
    page.on(
        "request",
        lambda request: requests.append(request.url)
        if "/api/career/ats-guide/" in request.url
        else None,
    )
    page.on(
        "request",
        lambda request: quick_requests.append(request.url)
        if "/api/career/quick-answers/" in request.url
        else None,
    )
    goto_app(page, url)
    wait_loaded(page)

    with Step(recorder, "07. survol « guide » : requête avant le clic") as step:
        guide = page.locator('#view-today .pipeline-item button:has-text("guide")').first
        guide.hover()
        page.wait_for_timeout(450)
        step.detail = f"requêtes={len(requests)}"
        assert len(requests) == 1, f"le survol doit déclencher le préchargement ({requests})"

    with Step(recorder, "08. clic « guide » : préchargement consommé, pas dupliqué") as step:
        guide.click()
        dialog = _dialog(page)
        dialog.wait_for()
        page.wait_for_function(
            """() => document.querySelector('[role="dialog"]')?.textContent.includes('Ouvrir le formulaire officiel')""",
            timeout=10_000,
        )
        page.wait_for_timeout(200)
        title = page.locator('[role="dialog"] h2').first.inner_text()
        step.detail = f"requêtes={len(requests)} · titre={title!r}"
        assert len(requests) == 1, f"le clic doit réutiliser la requête préchargée ({requests})"
        assert "guide ats" in title.lower(), title

    with Step(recorder, "09. focus clavier : préchargement des « réponses »") as step:
        _close_dialog(page)
        quick = page.locator('#view-today .pipeline-item button:has-text("réponses")').first
        quick.focus()
        page.wait_for_timeout(450)
        step.detail = f"requêtes={len(quick_requests)}"
        assert len(quick_requests) >= 1, "le focus clavier doit aussi précharger"

    context.close()


def run_skeleton_dialog(browser, url: str, recorder: Recorder) -> None:
    """Le dialogue détail s'ouvre en squelette, avant la réponse API."""
    context = new_context(browser)
    page = context.new_page()
    goto_app(page, url)
    wait_loaded(page)
    page.locator('.nav-item[data-view="applications"]').click()
    page.wait_for_selector("#view-applications .pipeline-item", timeout=10_000)

    with Step(recorder, "10. « préparer » ouvre un dialogue squelette immédiat") as step:
        page.locator('#view-applications .pipeline-item button:has-text("préparer")').first.click()
        page.wait_for_selector('[role="dialog"].skeleton-dialog', timeout=3_000)
        busy = page.evaluate(
            "() => document.querySelector('.skeleton-dialog')?.getAttribute('aria-busy')"
        )
        step.detail = f"aria-busy={busy}"
        assert busy == "true"

    with Step(recorder, "11. le contenu réel remplace le squelette") as step:
        page.wait_for_function(
            """() => document.querySelector('[role="dialog"]')?.textContent.includes('Dossier prêt')""",
            timeout=10_000,
        )
        assert page.locator(".skeleton-dialog").count() == 0

    context.close()


def _mark_sent(page) -> None:
    page.locator('#view-applications .pipeline-item button:has-text("marqué envoyé")').first.click()
    dialog = _dialog(page)
    dialog.locator('button[type="submit"]').click()


def run_optimistic(browser, url: str, recorder: Recorder) -> None:
    """La candidature apparaît avant la réponse, puis se confirme ou s'annule."""
    context = new_context(browser)
    page = context.new_page()
    goto_app(page, url)
    wait_loaded(page)
    page.locator('.nav-item[data-view="applications"]').click()
    page.wait_for_selector("#view-applications .pipeline-item", timeout=10_000)

    with Step(recorder, "12. envoi : ligne optimiste avant la réponse API") as step:
        _mark_sent(page)
        page.wait_for_function(
            "() => window.__appState.tracker?.items?.[0]?.optimistic === true",
            timeout=2_000,
        )
        page.locator('.nav-item[data-view="tracking"]').click()
        page.wait_for_selector("#view-tracking .pipeline-item.optimistic", timeout=2_000)
        step.detail = "ligne optimiste + badge sync visibles"

    with Step(recorder, "13. confirmation : l'état optimiste disparaît") as step:
        page.wait_for_function(
            "() => window.__appState.tracker?.items?.[0]?.optimistic !== true",
            timeout=10_000,
        )
        page.wait_for_selector("#view-tracking .pipeline-item.optimistic", state="detached", timeout=5_000)
        assert "Envoi enregistré" in page.locator("#toast").inner_text()

    with Step(recorder, "14. échec API : la ligne est annulée") as step:
        FAIL_SEND["paths"].add("/api/career/send-confirmation/job-1")
        page.locator('.nav-item[data-view="applications"]').click()
        page.wait_for_selector("#view-applications .pipeline-item", timeout=10_000)
        _mark_sent(page)
        page.wait_for_function(
            "() => window.__appState.tracker?.items?.[0]?.optimistic === true",
            timeout=2_000,
        )
        page.wait_for_function(
            "() => window.__appState.tracker?.items?.[0]?.optimistic !== true",
            timeout=10_000,
        )
        page.wait_for_timeout(150)
        toast = page.locator("#toast").inner_text()
        step.detail = toast
        assert "annulée" in toast.lower()

    context.close()


def run_no_auto_submit(browser, url: str, recorder: Recorder) -> None:
    """Aucune requête d'envoi avant la confirmation humaine explicite."""
    context = new_context(browser)
    page = context.new_page()
    sends: list[str] = []
    page.on(
        "request",
        lambda request: sends.append(request.url)
        if "/api/career/send-confirmation/" in request.url
        else None,
    )
    goto_app(page, url)
    wait_loaded(page)
    page.locator('.nav-item[data-view="applications"]').click()
    page.wait_for_selector("#view-applications .pipeline-item", timeout=10_000)

    with Step(recorder, "15. aucun envoi automatique sans validation") as step:
        page.wait_for_timeout(800)
        step.detail = f"requêtes={len(sends)}"
        assert not sends, "aucune soumission ne doit partir sans confirmation"


def main() -> int:
    parser = argparse.ArgumentParser(description="Contrôles CDP performance perçue de /app")
    parser.add_argument("--url", help="serveur déjà lancé (sinon une instance isolée démarre)")
    parser.add_argument(
        "--report",
        default=str(ROOT / "reports" / "spec-053-perf-cdp.json"),
        help="chemin du rapport JSON",
    )
    args = parser.parse_args()

    recorder = Recorder()
    server = None
    server_thread = None
    chrome_process = None
    temp_dirs: list[Path] = []
    browser_label = ""
    url = args.url.rstrip("/") if args.url else ""

    try:
        from playwright.sync_api import sync_playwright

        if not url:
            import uvicorn

            app, base_dir = wrap_app()
            temp_dirs.append(base_dir)
            port = _free_port()
            config = uvicorn.Config(app, host="127.0.0.1", port=port, log_level="error", access_log=False)
            server = uvicorn.Server(config)
            server_thread = threading.Thread(target=server.run, daemon=True)
            server_thread.start()
            if not _wait_for_port(port, timeout=30.0):
                raise RuntimeError("Le serveur local n'a pas démarré.")
            url = f"http://127.0.0.1:{port}"

        chrome = find_chrome()
        cdp_port = _free_port()
        profile = Path(tempfile.mkdtemp(prefix="nage-perf-chrome-"))
        temp_dirs.append(profile)
        chrome_process = start_chrome(chrome, cdp_port, profile)
        browser_label = wait_for_cdp(cdp_port)

        with sync_playwright() as playwright:
            browser = playwright.chromium.connect_over_cdp(f"http://127.0.0.1:{cdp_port}")
            run_loading(browser, url, recorder)
            run_prefetch(browser, url, recorder)
            run_skeleton_dialog(browser, url, recorder)
            run_optimistic(browser, url, recorder)
            run_no_auto_submit(browser, url, recorder)
            browser.close()
    finally:
        FAIL_SEND["paths"].clear()
        if chrome_process and chrome_process.poll() is None:
            chrome_process.terminate()
            try:
                chrome_process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                chrome_process.kill()
        if server is not None:
            server.should_exit = True
        if server_thread is not None:
            server_thread.join(timeout=10)
        for directory in temp_dirs:
            shutil.rmtree(directory, ignore_errors=True)

    total = len(recorder.items)
    passed = recorder.passed
    failed = total - passed
    summary = {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "url": url,
        "browser": browser_label,
        "checks": recorder.items,
        "total": total,
        "passed": passed,
        "failed": failed,
    }
    report_path = Path(args.report)
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    print("")
    print(f"RÉSULTAT : {passed}/{total} contrôles réussis — rapport {report_path}")
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
