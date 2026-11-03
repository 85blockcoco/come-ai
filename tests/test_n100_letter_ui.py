from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
APP = (ROOT / "desktop_static" / "app.js").read_text(encoding="utf-8")
CSS = (ROOT / "desktop_static" / "app.css").read_text(encoding="utf-8")


def test_letter_workflow_is_wired_to_human_controlled_routes() -> None:
    assert "Lettre de motivation" in APP
    assert "/api/career/letter/render" in APP
    assert "/api/career/letter/check" in APP
    assert "/api/career/letter/approve" in APP
    assert "/api/career/letter/export" in APP
    assert "n’envoie jamais" in APP


def test_letter_ui_has_accessible_labels_and_responsive_rules() -> None:
    assert '"aria-label": "Offre pour la lettre"' in APP
    assert '"aria-live": "polite"' in APP
    assert ".letter-studio textarea:focus-visible" in CSS
    assert "@media (max-width: 700px)" in CSS
