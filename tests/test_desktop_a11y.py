"""Gardes d'accessibilité et de responsive pour l'interface bureau `/app`.

Les tests sont purement statiques : ils lisent le shell HTML, la feuille de
style et le script livrés, sans réseau ni données réelles.  Le dernier test
vérifie la syntaxe JavaScript avec Node quand il est disponible.
"""

from __future__ import annotations

from html.parser import HTMLParser
from pathlib import Path
import re
import shutil
import subprocess

import pytest


ROOT = Path(__file__).resolve().parents[1]
STATIC = ROOT / "desktop_static"
HTML_PATH = STATIC / "index.html"
CSS_PATH = STATIC / "app.css"
JS_PATH = STATIC / "app.js"


class _ShellParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.tags: list[tuple[str, dict[str, str]]] = []
        self.ids: list[str] = []
        self.labels: list[tuple[dict[str, str], str]] = []
        self._label_stack: list[dict[str, str]] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attributes = {key: (value or "") for key, value in attrs}
        self.tags.append((tag, attributes))
        if "id" in attributes:
            self.ids.append(attributes["id"])
        if tag == "label":
            self._label_stack.append(attributes)
        if tag == "input" and self._label_stack:
            self.labels.append((self._label_stack[-1], attributes))

    def handle_endtag(self, tag: str) -> None:
        if tag == "label" and self._label_stack:
            self._label_stack.pop()


@pytest.fixture(scope="module")
def html() -> str:
    return HTML_PATH.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def parsed(html: str) -> _ShellParser:
    parser = _ShellParser()
    parser.feed(html)
    return parser


@pytest.fixture(scope="module")
def css() -> str:
    return CSS_PATH.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def script() -> str:
    return JS_PATH.read_text(encoding="utf-8")


def _attrs(parsed: _ShellParser, tag: str) -> list[dict[str, str]]:
    return [attrs for name, attrs in parsed.tags if name == tag]


def test_shell_declares_language_viewport_and_landmarks(parsed: _ShellParser) -> None:
    html_tags = _attrs(parsed, "html")
    assert html_tags and html_tags[0].get("lang") == "fr"
    viewport = [attrs for attrs in _attrs(parsed, "meta") if attrs.get("name") == "viewport"]
    assert viewport and "width=device-width" in viewport[0].get("content", "")
    assert _attrs(parsed, "main"), "un repère <main> est requis"
    assert _attrs(parsed, "nav"), "la navigation principale doit être un <nav>"
    nav = _attrs(parsed, "nav")[0]
    assert nav.get("aria-label")


def test_skip_link_targets_a_focusable_main(parsed: _ShellParser) -> None:
    links = [attrs for attrs in _attrs(parsed, "a") if attrs.get("class") == "skip-link"]
    assert len(links) == 1
    assert links[0].get("href") == "#main"
    main = _attrs(parsed, "main")[0]
    assert main.get("id") == "main"
    assert main.get("tabindex") == "-1", "le lien d'évitement doit pouvoir déplacer le focus"


def test_navigation_exposes_accessible_names_and_current_page(parsed: _ShellParser) -> None:
    buttons = [attrs for attrs in _attrs(parsed, "button") if "nav-item" in attrs.get("class", "")]
    assert len(buttons) == 7
    for button in buttons:
        assert button.get("type") == "button"
    current = [attrs for attrs in buttons if attrs.get("aria-current") == "page"]
    assert len(current) == 1
    assert current[0].get("data-view") == "today"
    # Les libellés sont dans le HTML (pas seulement une icône décorative).
    labels = re.findall(
        r'<button[^>]*class="nav-item"[^>]*>.*?<span>(.*?)</span>',
        HTML_PATH.read_text(encoding="utf-8"),
        re.S,
    )
    assert len(labels) == 7
    assert all(label.strip() for label in labels)


def test_live_regions_and_status_are_present(parsed: _ShellParser) -> None:
    live = [attrs for attrs in _attrs(parsed, "div") if attrs.get("aria-live")]
    assert len(live) >= 2, "annonce globale + notification non bloquante attendues"
    assert any(attrs.get("id") == "srAnnounce" and attrs.get("role") == "status" for attrs in live)
    assert any(attrs.get("id") == "toast" and attrs.get("role") == "status" for attrs in live)
    status = [attrs for attrs in _attrs(parsed, "div") if attrs.get("id") == "statusDot"]
    assert status and status[0].get("role") == "status"
    assert status[0].get("aria-live") == "polite"


def test_search_input_has_an_explicit_label(parsed: _ShellParser) -> None:
    inputs = [attrs for attrs in _attrs(parsed, "input") if attrs.get("id") == "searchInput"]
    assert len(inputs) == 1
    assert any(label.get("class") == "search" for label, _ in parsed.labels), (
        "le champ de recherche doit être enveloppé par un <label> nommé"
    )
    assert "Filtrer les offres" in HTML_PATH.read_text(encoding="utf-8")


def test_each_view_is_a_labelled_region(parsed: _ShellParser) -> None:
    sections = [attrs for attrs in _attrs(parsed, "section") if "view" in attrs.get("class", "")]
    assert len(sections) == 7
    for section in sections:
        assert section.get("role") == "region"
        assert section.get("aria-label")
    hidden = [section for section in sections if "hidden" in section]
    assert len(hidden) == 6, "une seule vue doit être visible à la fois"


def test_ids_are_unique_and_no_positive_tabindex(parsed: _ShellParser, html: str) -> None:
    assert len(parsed.ids) == len(set(parsed.ids)), "les identifiants doivent rester uniques"
    assert not re.search(r'tabindex="[1-9]\d*"', html), "tabindex positif interdit (ordre de focus naturel)"


def test_css_ships_screen_reader_and_focus_utilities(css: str) -> None:
    assert ".sr-only" in css
    assert ".skip-link" in css
    assert ":focus-visible" in css
    assert "outline: 3px solid var(--green-2)" in css
    assert ".modal-box:focus-visible" in css


def test_css_ships_touch_targets_and_mobile_breakpoints(css: str) -> None:
    assert "min-height: 44px" in css
    assert "@media (pointer: coarse)" in css
    assert "@media (max-width: 720px)" in css
    assert "@media (max-width: 480px)" in css
    assert "grid-template-rows: auto minmax(0, 1fr)" in css
    assert "100dvh" in css
    assert "overflow-x: auto" in css


def test_css_respects_reduced_motion_contrast_and_forced_colors(css: str) -> None:
    assert "@media (prefers-reduced-motion: reduce)" in css
    assert "@media (prefers-contrast: more)" in css
    assert "@media (forced-colors: active)" in css
    # Les libellés de navigation restent lisibles par les lecteurs d'écran
    # quand la barre latérale est réduite à ses icônes.
    assert "clip-path: inset(50%)" in css


def test_dialogs_trap_focus_and_close_on_escape(script: str) -> None:
    assert 'box.setAttribute("role", "dialog")' in script
    assert 'box.setAttribute("aria-modal", "true")' in script
    assert 'box.setAttribute("aria-labelledby", titleId)' in script
    assert 'event.key === "Escape"' in script
    assert 'event.key !== "Tab"' in script
    assert "focusablesIn(box)" in script
    assert "previous.focus()" in script, "le focus doit revenir au déclencheur"
    assert 'class: "modal-overlay"' in script


def test_keyboard_activation_and_progress_semantics(script: str) -> None:
    assert 'event.key === "Enter" || event.key === " "' in script
    assert 'role: "progressbar"' in script
    assert '"aria-valuenow"' in script
    assert '"aria-pressed"' in script
    assert '"aria-busy"' in script
    assert 'role: "log"' in script
    assert "announce(" in script


def test_no_blocking_native_dialogs(script: str) -> None:
    for call in ("alert(", "prompt(", "confirm("):
        assert call not in script, f"{call} bloque le fil d'accessibilité"


def test_javascript_parses_with_node() -> None:
    executable = shutil.which("node")
    if not executable:
        for candidate in ("/usr/local/bin/node", "/opt/homebrew/bin/node"):
            if Path(candidate).is_file():
                executable = candidate
                break
    if not executable:
        pytest.skip("Node absent : contrôle de syntaxe ignoré")
    result = subprocess.run(
        [executable, "--check", str(JS_PATH)],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
