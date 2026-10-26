#!/usr/bin/env python3
"""SPEC-048 live browser check: command palette + keyboard shortcuts.

Uses a real headless Chrome over the Chrome DevTools Protocol (CDP) via
Playwright's ``connect_over_cdp``. No external network: the page only talks to
the local NAGE server on 127.0.0.1.

Usage (from the repository root, with the local server already running):

    .venv/bin/python run_come_ai_v3.py --port 8899 --no-browser   # terminal 1
    .venv/bin/python scripts/check_spec048_cdp.py --base-url http://127.0.0.1:8899

The script starts headless Chrome itself on a throwaway profile and stops it at
the end. Nothing is submitted, no real data is read: the app creates empty local
stores on first run.
"""

from __future__ import annotations

import argparse
import subprocess
import sys
import tempfile
import time
import urllib.request
from pathlib import Path

try:
    from playwright.sync_api import sync_playwright
except ImportError:  # pragma: no cover - optional local tool
    print("SKIP: playwright is not installed in this venv", file=sys.stderr)
    raise SystemExit(2)

CHROME_CANDIDATES = (
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
    "/Applications/Chromium.app/Contents/MacOS/Chromium",
    "/usr/bin/google-chrome",
    "/usr/bin/chromium",
)


def cdp_available(cdp_url: str) -> bool:
    try:
        with urllib.request.urlopen(f"{cdp_url}/json/version", timeout=1.5) as response:
            return response.status == 200
    except Exception:
        return False


def launch_chrome(port: int) -> subprocess.Popen[bytes]:
    executable = next((path for path in CHROME_CANDIDATES if Path(path).is_file()), None)
    if not executable:
        raise SystemExit("SKIP: no Chrome/Chromium binary found for the CDP journey")
    profile = tempfile.mkdtemp(prefix="nage-spec048-cdp-")
    process = subprocess.Popen(
        [
            executable,
            "--headless=new",
            f"--remote-debugging-port={port}",
            f"--user-data-dir={profile}",
            "--no-first-run",
            "--no-default-browser-check",
            "--disable-gpu",
            "--disable-extensions",
            "about:blank",
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    deadline = time.time() + 15
    while time.time() < deadline:
        if cdp_available(f"http://127.0.0.1:{port}"):
            return process
        if process.poll() is not None:
            break
        time.sleep(0.2)
    process.terminate()
    raise SystemExit("Chrome did not expose a CDP endpoint")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default="http://127.0.0.1:8899")
    parser.add_argument("--port", type=int, default=9222)
    args = parser.parse_args()

    cdp_url = f"http://127.0.0.1:{args.port}"
    chrome = None if cdp_available(cdp_url) else launch_chrome(args.port)
    passed: list[str] = []
    failures: list[str] = []

    def check(name: str, condition: bool, detail: str = "") -> None:
        if condition:
            passed.append(name)
            print(f"PASS  {name}")
        else:
            failures.append(f"{name} {detail}".strip())
            print(f"FAIL  {name} {detail}".rstrip())

    try:
        with sync_playwright() as playwright:
            browser = playwright.chromium.connect_over_cdp(cdp_url)
            context = browser.contexts[0]
            page = context.pages[0] if context.pages else context.new_page()
            console_errors: list[str] = []
            page_errors: list[str] = []
            page.on(
                "console",
                lambda message: console_errors.append(message.text)
                if message.type == "error"
                else None,
            )
            page.on("pageerror", lambda error: page_errors.append(str(error)))

            page.goto(f"{args.base_url}/app", wait_until="domcontentloaded")
            page.wait_for_selector("#paletteBtn")
            page.wait_for_function("() => Boolean(window.__nagePalette) && Boolean(window.__appState)")

            # 1. Control+K opens the palette and focuses its input.
            page.keyboard.press("Control+k")
            check("Ctrl+K ouvre la palette", page.evaluate("window.__nagePalette.isOpen()"))
            check(
                "le focus entre dans le champ",
                page.evaluate("document.activeElement && document.activeElement.id") == "paletteInput",
            )
            check(
                "dialogue accessible (role/aria)",
                page.evaluate("""() => {
                    const overlay = document.querySelector('#paletteOverlay');
                    const dialog = overlay && overlay.querySelector('[role="dialog"]');
                    const input = document.querySelector('#paletteInput');
                    return Boolean(dialog && dialog.getAttribute('aria-modal') === 'true'
                        && input && input.getAttribute('role') === 'combobox'
                        && input.getAttribute('aria-controls') === 'paletteList');
                }"""),
            )

            # 2. Filtering is accent-insensitive and Enter navigates.
            page.keyboard.type("suivi")
            first_label = page.evaluate(
                "document.querySelector('.palette-item .palette-main strong')?.textContent || ''"
            )
            check("« suivi » filtre sur Suivi", "Suivi" in first_label, first_label)
            check(
                "le terme saisi est surligné",
                page.evaluate("Boolean(document.querySelector('.palette-main mark'))"),
            )
            page.keyboard.press("Enter")
            page.wait_for_function(
                """() => {
                    const view = document.querySelector('#view-tracking');
                    return view && !view.hidden && view.textContent.trim().length > 0;
                }"""
            )
            check("Entrée ouvre le Suivi", page.evaluate("location.hash") == "#tracking")

            # 3. Escape closes and restores focus.
            page.focus("#paletteBtn")
            page.keyboard.press("Control+k")
            page.keyboard.press("Escape")
            check("Échap ferme la palette", not page.evaluate("window.__nagePalette.isOpen()"))
            check(
                "le focus revient au déclencheur",
                page.evaluate("document.activeElement && document.activeElement.id") == "paletteBtn",
            )

            # 4. Arrow navigation + Enter runs the highlighted command.
            page.evaluate("window.__nagePalette.open()")
            page.keyboard.press("ArrowDown")
            page.keyboard.press("Enter")
            check(
                "↓ + Entrée exécute la 2e commande",
                page.evaluate("location.hash") == "#applications"
                and page.evaluate("!document.querySelector('#view-applications').hidden"),
            )

            # 5. Alt+number jumps straight to a view.
            page.keyboard.press("Alt+4")
            check(
                "Alt+4 ouvre les Offres",
                page.evaluate("location.hash") == "#offers"
                and page.evaluate("!document.querySelector('#view-offers').hidden"),
            )

            # 6. "/" focuses the offers filter, without typing a slash.
            page.keyboard.press("/")
            page.wait_for_function(
                "() => document.activeElement && document.activeElement.id === 'searchInput'",
                timeout=3000,
            )
            check(
                "« / » place le curseur dans le filtre",
                page.evaluate("document.activeElement && document.activeElement.id") == "searchInput"
                and page.evaluate("document.querySelector('#searchInput').value") == "",
            )

            # 7. "?" opens the shortcut reference; Escape closes it.
            page.evaluate("document.activeElement && document.activeElement.blur()")
            page.keyboard.press("Shift+Slash")
            page.wait_for_function("() => window.__nagePalette.shortcutsOpen()", timeout=3000)
            check("« ? » ouvre les raccourcis", page.evaluate("window.__nagePalette.shortcutsOpen()"))
            check(
                "les raccourcis listent la palette",
                "⌘K / Ctrl+K" in page.evaluate("document.querySelector('#shortcutsOverlay').textContent"),
            )
            page.keyboard.press("Escape")
            check("Échap ferme les raccourcis", not page.evaluate("window.__nagePalette.shortcutsOpen()"))

            # 8. "g" sequence navigation.
            page.keyboard.press("g")
            page.keyboard.press("m")
            check("G puis M ouvre les Missions", page.evaluate("location.hash") == "#missions")

            # 9. Public command inventory is complete and stable.
            commands = page.evaluate("window.__nagePalette.commands().map((command) => command.id)")
            expected = {"nav-today", "nav-applications", "nav-tracking", "nav-offers",
                        "nav-assistant", "nav-missions", "nav-memory", "action-refresh",
                        "action-filter", "action-shortcuts", "link-career", "link-v5", "link-v3"}
            check("toutes les commandes attendues sont présentes", expected.issubset(set(commands)))
            check(
                "filtrage sans accent via l'API publique",
                page.evaluate("window.__nagePalette.filter('memoire')[0]") == "nav-memory",
            )

            # 10. In-progress dossiers become filters, using synthetic state only.
            page.evaluate("""() => {
                window.__appState.pipeline = { pipeline: [{
                    job_id: 'spec048-test',
                    title: 'Dossier synthétique',
                    company: 'Entreprise fictive',
                    progress_percent: 40,
                    next_action_label: 'Relire la lettre',
                }] };
            }""")
            check(
                "les dossiers en cours deviennent des commandes",
                page.evaluate("window.__nagePalette.commands().some((c) => c.id === 'dossier-spec048-test')"),
            )
            check(
                "un dossier est filtrable par entreprise",
                page.evaluate("window.__nagePalette.filter('fictive').includes('dossier-spec048-test')"),
            )

            unexpected_console = [line for line in console_errors if "LOADER_FAIL" not in line]
            check("aucune erreur JavaScript", not page_errors, "; ".join(page_errors))
            check(
                "aucune erreur console inattendue",
                not unexpected_console,
                " | ".join(unexpected_console[:3]),
            )
            print(f"INFO  commandes exposées : {len(commands)}")
            browser.close()
    finally:
        if chrome is not None:
            chrome.terminate()
            try:
                chrome.wait(timeout=5)
            except subprocess.TimeoutExpired:
                chrome.kill()

    print(f"\n{len(passed)} PASS / {len(failures)} FAIL")
    if failures:
        print("FAILURES:")
        for failure in failures:
            print(f" - {failure}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
