"""Gardes de performance perçue pour l'interface bureau `/app` (SPEC-053).

Tests purement statiques : ils lisent le shell HTML, la feuille de style et le
script livrés, sans réseau ni données réelles.  Ils verrouillent les trois
mécanismes de la mission — squelettes, mises à jour optimistes, préchargement —
et vérifient que la syntaxe JavaScript reste valide avec Node.
"""

from __future__ import annotations

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


@pytest.fixture(scope="module")
def html() -> str:
    return HTML_PATH.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def css() -> str:
    return CSS_PATH.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def script() -> str:
    return JS_PATH.read_text(encoding="utf-8")


def _function_body(script: str, name: str) -> str:
    """Extrait le corps d'une fonction JS déclarée par `function name(`."""
    start = script.index(f"function {name}(")
    depth = 0
    opened = False
    for index in range(start, len(script)):
        char = script[index]
        if char == "{":
            depth += 1
            opened = True
        elif char == "}":
            depth -= 1
            if opened and depth == 0:
                return script[start:index + 1]
    raise AssertionError(f"fonction {name} non fermée")


# ---------- Squelettes ----------


def test_progress_bar_is_non_blocking_and_accessible(html: str) -> None:
    match = re.search(r'<div class="progress-bar"[^>]*>', html)
    assert match, "la barre de progression globale est requise"
    tag = match.group(0)
    assert 'id="progressBar"' in tag
    assert 'role="progressbar"' in tag
    assert 'aria-label="Chargement en cours"' in tag
    assert "hidden" in tag
    assert "aria-valuetext" in tag


def test_css_defines_structured_skeleton_shapes(css: str) -> None:
    for selector in (
        ".skeleton-view", ".skeleton-line", ".skeleton-row",
        ".skeleton-kpi", ".skeleton-dialog", "@keyframes shimmer",
    ):
        assert selector in css, f"squelette structuré manquant : {selector}"
    # Les squelettes ne doivent pas créer de saut de mise en page.
    assert "background-size: 220% 100%" in css


def test_reduced_motion_neutralises_new_animations(css: str) -> None:
    reduced = css[css.index("@media (prefers-reduced-motion: reduce)"):]
    assert "animation-duration: 0.001ms !important" in reduced
    assert "transition-duration: 0.001ms !important" in reduced


def test_js_exposes_structure_aware_skeletons(script: str) -> None:
    for helper in ("skeletonCard", "skeletonRow", "skeletonList", "loading"):
        assert f"function {helper}(" in script, f"squelette manquant : {helper}"
    loading = _function_body(script, "loading")
    assert 'role: "status"' in loading
    assert '"aria-live": "polite"' in loading
    # Les blocs visuels sont décoratifs, l'annonce passe par role=status.
    assert '"aria-hidden": "true"' in loading


def test_each_view_renders_its_own_skeleton(script: str) -> None:
    expected = {
        "renderToday": 'loading("today")',
        "renderApplications": 'loading("applications")',
        "renderTracking": 'loading("tracking")',
        "renderOffers": 'loading("offers")',
        "renderMissions": 'loading("missions")',
        "renderMemory": 'loading("memory")',
    }
    for function, call in expected.items():
        assert call in _function_body(script, function), f"{function} doit utiliser {call}"


def test_detail_dialogs_open_a_skeleton_before_fetching(script: str) -> None:
    assert "function skeletonDialog(" in script
    for function in ("showApplyKit", "showAtsGuide", "showQuickAnswers"):
        body = _function_body(script, function)
        assert "skeletonDialog(" in body, f"{function} doit ouvrir un squelette"
        assert body.index("skeletonDialog(") < body.index("await "), (
            f"{function} doit afficher le squelette avant la requête"
        )
        assert '"aria-busy": "true"' in _function_body(script, "skeletonDialog")


# ---------- Mises à jour optimistes ----------


def test_mark_sent_updates_tracker_before_network(script: str) -> None:
    body = _function_body(script, "markSent")
    optimistic_at = body.index("state.tracker.items = [optimisticItem")
    network_at = body.index("await api(`/api/career/send-confirmation/")
    assert optimistic_at < network_at, "la ligne doit apparaître avant la réponse API"
    assert "optimistic: true" in body


def test_mark_sent_rolls_back_on_failure(script: str) -> None:
    body = _function_body(script, "markSent")
    assert "structuredClone(state.tracker)" in body
    rollback = body[body.index("catch (e) {"):]
    assert "state.tracker = previousTracker" in rollback
    assert "Modification annulée" in rollback


def test_optimistic_row_is_visually_marked(css: str, script: str) -> None:
    assert ".pipeline-item.optimistic" in css
    assert 'class: `pipeline-item${it.optimistic ? " optimistic" : ""}`' in script
    assert 'el("span", { class: "chip amber" }, "sync")' in script


def test_human_confirmation_still_required(script: str) -> None:
    body = _function_body(script, "markSent")
    assert body.index("await askChannel(title)") < body.index("optimisticItem")
    assert "Aucun envoi automatique" in script


# ---------- Préchargement ----------


def test_prefetch_cache_is_bounded_by_ttl(script: str) -> None:
    assert "PREFETCH_TTL_MS = 30000" in script
    cache = _function_body(script, "prefetchJson")
    assert "Date.now() - hit.at < PREFETCH_TTL_MS" in cache
    assert "prefetchCache.delete(path)" in cache, "une erreur ne doit pas rester en cache"


def test_prefetch_wired_to_pointer_and_keyboard_focus(script: str) -> None:
    for path in ("/api/career/ats-guide/", "/api/career/quick-answers/"):
        assert f"prefetchDetail(`{path}${{item.job_id}}`)" in script
    assert "onpointerenter: () => prefetchDetail(" in script
    assert "onfocus: () => prefetchDetail(" in script
    nav = script[script.index('for (const button of document.querySelectorAll(".nav-item"))'):]
    assert 'addEventListener("pointerenter", () => prefetchView(' in nav
    assert 'addEventListener("focus", () => prefetchView(' in nav


def test_navigation_prefetch_does_not_duplicate_requests(script: str) -> None:
    body = _function_body(script, "prefetchView")
    assert "if (state[name] || prefetchedLoaders.has(name)) continue;" in body
    assert "prefetchedLoaders.add(name);" in body
    assert "prefetchedLoaders.delete(name);" in body


def test_detail_fetch_consumes_prefetch_once(script: str) -> None:
    assert "async function apiCached(" in script
    assert "prefetchCache.delete(path);" in _function_body(script, "apiCached")
    for function in ("showAtsGuide", "showQuickAnswers"):
        assert "apiCached(" in _function_body(script, function)


# ---------- Progression globale ----------


def test_progress_bar_appears_only_after_delay(script: str) -> None:
    begin = _function_body(script, "beginProgress")
    assert "setTimeout(" in begin
    assert "}, 120);" in begin, "la barre doit attendre 120 ms pour éviter le clignotement"
    api = _function_body(script, "api")
    assert "beginProgress();" in api and "endProgress();" in api


# ---------- Hygiène ----------


def test_no_external_network_added(script: str, css: str, html: str) -> None:
    combined = script + css + html
    assert "http://" not in combined
    assert "https://" not in combined


def test_javascript_syntax_is_valid() -> None:
    node = shutil.which("node")
    if node is None:
        pytest.skip("Node.js absent : contrôle de syntaxe ignoré")
    result = subprocess.run(
        [node, "--check", str(JS_PATH)],
        capture_output=True, text=True, cwd=ROOT, check=False,
    )
    assert result.returncode == 0, result.stderr
