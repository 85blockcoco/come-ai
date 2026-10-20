"""Static guards for the UX decisions: inline note editor and V5 hash routing."""
from pathlib import Path

CAREER_JS = Path(__file__).resolve().parents[1] / "career_static" / "career.js"
V5_JS = Path(__file__).resolve().parents[1] / "v5_static" / "v5.js"


def test_career_note_editing_is_inline_not_window_prompt() -> None:
    source = CAREER_JS.read_text(encoding="utf-8")
    # Exactly one remaining window.prompt: the typed destructive-data
    # confirmation, which is a safety feature, not a note input.
    assert source.count("window.prompt") == 1
    assert "SUPPRIMER MES DONNÉES CAREER" in source
    assert "function openNoteEditor" in source
    assert 'editor.remove();\n    onSaved(input.value);' in source
    assert "Escape" in source


def test_v5_has_hash_routing_like_career() -> None:
    source = V5_JS.read_text(encoding="utf-8")
    assert "function requestedHashView" in source
    assert 'window.location.hash = `v5/${id}`' in source
    assert "internalHashChange" in source
    assert 'window.addEventListener("hashchange"' in source
