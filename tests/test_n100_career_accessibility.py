from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
JS = (ROOT / "career_static" / "career.js").read_text(encoding="utf-8")
CSS = (ROOT / "career_static" / "career.css").read_text(encoding="utf-8")


def test_application_controls_receive_accessible_names() -> None:
    assert "ensureApplicationAccessibility" in JS
    assert 'getAttribute("aria-label")' in JS
    assert 'control.closest("label")' in JS


def test_offer_and_application_lists_have_loading_skeletons() -> None:
    assert "renderListSkeleton(elements.jobs)" in JS
    assert "renderListSkeleton(elements.shortlist" in JS
    assert "renderListSkeleton(elements.applications)" in JS
    assert 'setAttribute("aria-busy", "true")' in JS


def test_focus_motion_and_mobile_rules_are_present() -> None:
    assert ":focus-visible" in CSS
    assert "prefers-reduced-motion: reduce" in CSS
    assert "@media (max-width: 620px)" in CSS
    assert "overflow-wrap: anywhere" in CSS
