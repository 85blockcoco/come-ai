"""Static wiring guards for the Révisions tab.

These checks tie together the three layers that must agree for the tab to
work: ``index.html`` (DOM), ``revisions.js`` (behaviour) and
``academics/vc/api.py`` (endpoints).  They catch a missing element id or a
renamed endpoint before anyone opens the app.
"""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
INDEX = ROOT / "v5_static" / "index.html"
REVISIONS_JS = ROOT / "v5_static" / "revisions.js"
V5_JS = ROOT / "v5_static" / "v5.js"
VC_API = ROOT / "academics" / "vc" / "api.py"


def test_nav_button_and_view_exist() -> None:
    html = INDEX.read_text(encoding="utf-8")
    assert 'data-view-target="revisionsView"' in html
    assert '<section id="revisionsView"' in html
    assert "/v5-static/revisions.js" in html


def test_view_is_registered_in_router() -> None:
    source = V5_JS.read_text(encoding="utf-8")
    assert '"revisionsView"' in source
    assert "revisionsView:" in source
    assert 'window.initRevisions' in source


def test_every_element_id_used_by_revisions_js_exists_in_html() -> None:
    html = INDEX.read_text(encoding="utf-8")
    js = REVISIONS_JS.read_text(encoding="utf-8")
    used = set(re.findall(r'revEl\("([A-Za-z0-9_]+)"\)', js))
    used |= set(re.findall(r'getElementById\("([A-Za-z0-9_]+)"\)', js))
    assert used, "expected revisions.js to reference element ids"
    # Ids rendered dynamically by revisions.js itself (template strings)
    # never appear in index.html.
    rendered = set(re.findall(r'id="([A-Za-z0-9_]+)"', js))
    missing = sorted(
        element_id
        for element_id in used
        if f'id="{element_id}"' not in html and element_id not in rendered
    )
    assert not missing, f"revisions.js references ids missing from index.html: {missing}"


def test_every_api_path_used_by_revisions_js_exists_in_router() -> None:
    js = REVISIONS_JS.read_text(encoding="utf-8")
    api = VC_API.read_text(encoding="utf-8")
    raw = re.findall(r'["`\'`](/api/vc/[A-Za-z0-9_/{}$?.=&-]+)', js)
    assert raw, "expected revisions.js to call /api/vc endpoints"
    missing = []
    for path in sorted(set(raw)):
        # Keep the static prefix before any template placeholder or query.
        stem = re.split(r"\$|\?", path)[0].rstrip("/")
        if not stem:
            continue
        # A literal year in a template resolves to /api/vc/papers/{year}.
        stem = re.sub(r"/papers/\d+$", "/papers/{year}", stem)
        if stem in api:
            continue
        prefix = stem.split("{")[0]
        if prefix and prefix in api:
            continue
        missing.append(path)
    assert not missing, f"revisions.js calls endpoints missing from api.py: {missing}"


def test_tutor_modes_used_in_ui_are_supported_by_backend() -> None:
    html = INDEX.read_text(encoding="utf-8")
    js = REVISIONS_JS.read_text(encoding="utf-8")
    tutor = (ROOT / "vc_tutor.py").read_text(encoding="utf-8")
    ui_modes = set(re.findall(r'data-tutor-mode="([a-z]+)"', html))
    ui_modes |= set(re.findall(r'data-tutor-mode="([a-z]+)"', js))
    assert ui_modes, "expected tutor mode buttons in index.html"
    for mode in sorted(ui_modes):
        assert f'"{mode}"' in tutor, f"mode {mode} not handled by VCTutor"
    assert 'mode = check ? "correct" : rev.tutorMode' in js


def test_content_is_english_in_vc_packs() -> None:
    """The student's courses and exam are English: pedagogical content must be."""
    import json

    content_dir = ROOT / "academics" / "vc" / "content"
    checked = 0
    for path in sorted(content_dir.glob("cards_vc*.json")):
        payload = json.loads(path.read_text(encoding="utf-8"))
        assert payload.get("language") == "en", f"{path.name} is not marked English"
        for item in payload.get("items", []):
            question = item.get("question", "")
            # A French-only starter would indicate mixed-language cards.
            french_starters = ("Qu'est-ce", "Comment fonctionne", "Pourquoi")
            assert not question.startswith(french_starters), (
                f"{path.name}:{item.get('id')} looks French: {question[:60]}"
            )
            checked += 1
    assert checked >= 170, f"expected at least 170 cards, checked {checked}"


def test_no_api_key_reference_in_frontend() -> None:
    for path in (INDEX, REVISIONS_JS, V5_JS):
        source = path.read_text(encoding="utf-8")
        assert "GEMINI_API_KEY" not in source, f"{path.name} must not name the key"
        assert "MISTRAL_API_KEY" not in source
        assert "AQ." not in source
        assert "mstrl_" not in source
