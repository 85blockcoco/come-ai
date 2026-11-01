from pathlib import Path
import subprocess


ROOT = Path(__file__).resolve().parents[1]
JS = (ROOT / "career_static" / "career.js").read_text(encoding="utf-8")
CSS = (ROOT / "career_static" / "career.css").read_text(encoding="utf-8")


def test_application_controls_receive_accessible_names() -> None:
    assert "ensureApplicationAccessibility" in JS
    assert 'getAttribute("aria-label")' in JS
    assert 'control.closest("label")' in JS


def test_offer_and_application_lists_have_loading_skeletons() -> None:
    # Test the shared loader's actual success/failure/retry lifecycle, replacing
    # old string checks tied to the three duplicated skeleton calls.
    result = subprocess.run(
        ["node", "--test", str(ROOT / "tests/js/career_list_loading.test.cjs")],
        capture_output=True, text=True, timeout=15,
    )
    assert result.returncode == 0, result.stdout + result.stderr


def test_focus_motion_and_mobile_rules_are_present() -> None:
    assert ":focus-visible" in CSS
    assert "prefers-reduced-motion: reduce" in CSS
    assert "@media (max-width: 620px)" in CSS
    assert "overflow-wrap: anywhere" in CSS
