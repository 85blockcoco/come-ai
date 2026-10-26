"""Guards for SPEC-048 — desktop command palette and keyboard shortcuts.

The desktop shell is a CSP-locked, dependency-free page. These tests check the
shipped assets (no inline script/style, palette and shortcut wiring) and run the
real filtering functions extracted from ``desktop_static/app.js`` in Node.
The live-browser CDP journey lives in ``scripts/check_spec048_cdp.py``; it is
deliberately not part of the default pytest run because it needs Chrome.
"""

from __future__ import annotations

from pathlib import Path
import re
import shutil
import subprocess

import pytest

ROOT = Path(__file__).resolve().parents[1]
DESKTOP = ROOT / "desktop_static"


def _source(name: str) -> str:
    return (DESKTOP / name).read_text(encoding="utf-8")


def test_desktop_page_stays_csp_safe_and_links_palette_assets() -> None:
    html = _source("index.html")

    assert 'id="paletteBtn"' in html
    assert 'aria-keyshortcuts="Meta+K Control+K"' in html
    assert '<script src="/app-static/app.js"></script>' in html
    assert '<link rel="stylesheet" href="/app-static/app.css">' in html

    # CSP: script-src 'self' and style-src 'self' forbid inline execution/styles.
    assert re.search(r"<script(?![^>]*\bsrc=)[^>]*>", html) is None
    assert not re.search(r"\sstyle\s*=", html)
    assert not re.search(r"\son[a-z]+\s*=", html)


def test_palette_and_shortcuts_are_wired_in_app_js() -> None:
    source = _source("app.js")

    for marker in (
        "function openPalette",
        "function closePalette",
        "function togglePalette",
        "function renderPalette",
        "function openShortcuts",
        "function isTypingTarget",
        "function overlayOpen",
        'document.addEventListener("keydown"',
        "event.code === \"KeyK\"",
        "Digit[1-7]",
        "window.__nagePalette",
        "$(\"#paletteBtn\").addEventListener(\"click\", () => openPalette())",
    ):
        assert marker in source, marker

    # Mounting the palette must never echo user input as HTML.
    palette_body = source.split("function buildPalette()", 1)[1].split("\n  function renderPalette", 1)[0]
    assert "innerHTML" not in palette_body

    # Accessible name and live result count are part of the contract.
    assert '"aria-label": "Rechercher une commande"' in source
    assert 'role: "status", "aria-live": "polite"' in source

    # Typing in a field must not trigger single-key navigation.
    assert "overlayOpen() || isTypingTarget(event.target)" in source


def test_tracking_view_is_reachable_from_render_dispatch() -> None:
    source = _source("app.js")
    assert 'else if (view === "tracking") renderTracking();' in source


def test_palette_and_shortcut_styles_exist() -> None:
    css = _source("app.css")
    for selector in (".palette-overlay", ".palette-item.active", ".palette-main mark", ".shortcut-grid", ".palette-btn kbd"):
        assert selector in css, selector


def _node() -> str:
    executable = shutil.which("node")
    if executable:
        return executable
    for candidate in ("/usr/local/bin/node", "/opt/homebrew/bin/node"):
        if Path(candidate).is_file():
            return candidate
    pytest.skip("Node absent: palette filtering guards are not executable on this host")


def _extract(source: str, start: str, end: str) -> str:
    assert start in source, start
    return source.split(start, 1)[1].split(end, 1)[0]


def test_palette_filtering_is_accent_insensitive_and_ranked() -> None:
    source = _source("app.js")
    normalize = "const normalize =" + _extract(source, "const normalize =", "function commandEntries()")
    scoring = "function commandScore" + _extract(source, "function commandScore", "function highlightLabel")
    functions = normalize + "\n" + scoring

    script = r'''
const assert = require("assert");
FUNCTIONS
const entries = [
  {id:"nav-today", group:"Navigation", label:"Aujourd’hui", detail:"état du système", search:"vue today"},
  {id:"nav-applications", group:"Navigation", label:"Candidatures", detail:"chaque dossier", search:"vue applications"},
  {id:"nav-offers", group:"Navigation", label:"Offres", detail:"offres suivies", search:"vue offers"},
  {id:"nav-memory", group:"Navigation", label:"Mémoire", detail:"sources locales", search:"vue memory"},
  {id:"action-refresh", group:"Actions", label:"Actualiser les données", detail:"recharge", search:"refresh recharger"},
  {id:"action-filter", group:"Actions", label:"Filtrer les offres", detail:"filtre instantané", search:"recherche"},
];

assert.deepStrictEqual(filterCommands(entries, "").map(c => c.id), entries.map(c => c.id));
assert.strictEqual(filterCommands(entries, "offres")[0].id, "nav-offers");
assert.strictEqual(filterCommands(entries, "memoire")[0].id, "nav-memory");
assert.strictEqual(filterCommands(entries, "AUJOURD")[0].id, "nav-today");
assert.strictEqual(filterCommands(entries, "actu")[0].id, "action-refresh");
assert.strictEqual(filterCommands(entries, "zzzz")[0], undefined);
// Subsequence fallback still finds a command when no substring matches.
assert.ok(filterCommands(entries, "fltr").some(c => c.id === "action-filter"));
console.log("PALETTE_FILTER_OK");
'''.replace("FUNCTIONS", functions)

    completed = subprocess.run([_node(), "-e", script], text=True, capture_output=True, timeout=10)
    assert completed.returncode == 0, completed.stderr
    assert "PALETTE_FILTER_OK" in completed.stdout
