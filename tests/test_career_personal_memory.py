"""Offline tests for SPEC-023 personal style memory.

Everything runs against temporary directories: no provider, no network, no
real profile data.  The file lives at ``tests/test_career_personal_memory.py``
instead of the mission's ``tests/test_personal_memory.py`` because that exact
path already belongs to the V5 chat-memory suite in this repository.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from career.memory_report import build_report, render_markdown
from career.personal_memory import (
    MemoryCorruptionError,
    MemoryStoreError,
    StyleMemoryStore,
    inject_constraints,
)
from come_ai_web import create_app

ROOT = Path(__file__).resolve().parents[1]


def make_store(tmp_path: Path) -> StyleMemoryStore:
    return StyleMemoryStore(tmp_path / "style_memory")


def option(verb: str = "conçu", tone: str = "direct", length: str = "court") -> dict:
    return {
        "action_verb": verb,
        "tone": tone,
        "length": length,
        "variant_id": "variant-1",
        "score": 42,
        "job_id": "offer_123",
    }


def test_empty_store_has_no_preference_and_no_choice(tmp_path: Path) -> None:
    store = make_store(tmp_path)
    assert store.list_preferences() == []
    assert store.list_choices() == []
    assert store.constraints(5) == []
    assert store.stats()["preferences_count"] == 0


def test_three_identical_choices_reach_automatic_application(tmp_path: Path) -> None:
    store = make_store(tmp_path)
    for _ in range(3):
        store.record_choice("bullet_reformulate:offer_123", option(), evidence_refs=["offer_123"])

    preferences = {item.key: item for item in store.list_preferences()}
    verb = preferences["js-action-verb"]
    assert verb.value == "conçu"
    assert verb.occurrences == 3
    assert verb.confidence >= 0.8
    assert verb.auto_applied is True
    assert preferences["tone-length"].value == "direct / court"

    constraints = store.constraints(5)
    applied = [item for item in constraints if item["key"] == "js-action-verb"]
    assert applied and applied[0]["auto_applied"] is True
    assert "js-action-verb = conçu" in store.format_constraints(5)
    # Identifiers, scores and evidence must never become preferences.
    assert "job_id" not in preferences and "score" not in preferences and "variant_id" not in preferences


def test_undo_recomputes_confidence_and_keeps_the_audit_trail(tmp_path: Path) -> None:
    store = make_store(tmp_path)
    choices = [
        store.record_choice("bullet_reformulate:offer_123", option(), evidence_refs=["offer_123"])["choice"]
        for _ in range(3)
    ]
    events_before = len(store.export_envelope()["events"])
    store.undo_choice(choices[0]["id"])

    verb = {item.key: item for item in store.list_preferences()}["js-action-verb"]
    assert verb.occurrences == 2
    assert verb.confidence < 0.8
    assert verb.auto_applied is False

    history = {item.id: item for item in store.list_choices()}
    assert history[choices[0]["id"]].undone is True
    assert history[choices[1]["id"]].undone is False
    # Undo is an appended event: history is never deleted.
    assert len(store.export_envelope()["events"]) == events_before + 1
    with pytest.raises(MemoryStoreError):
        store.undo_choice(choices[0]["id"])


def test_export_import_round_trip_is_lossless_and_idempotent(tmp_path: Path) -> None:
    store = make_store(tmp_path)
    store.record_preference("formality", "sobre", source="manual")
    store.record_choice(
        "bullet_reformulate:offer_123",
        option(),
        rejected=[{"action_verb": "optimisé"}],
        evidence_refs=["offer_123", "proof-1"],
    )
    payload = store.export_envelope()

    restored = StyleMemoryStore(tmp_path / "restored")
    first = restored.import_envelope(payload)
    assert first["imported"] == len(payload["events"])
    assert [item.to_dict() for item in restored.list_preferences()] == [
        item.to_dict() for item in store.list_preferences()
    ]
    assert [item.to_dict() for item in restored.list_choices()] == [
        item.to_dict() for item in store.list_choices()
    ]

    second = restored.import_envelope(payload)
    assert second["imported"] == 0
    assert second["skipped"] == len(payload["events"])


def test_import_rejects_unknown_version_without_touching_the_store(tmp_path: Path) -> None:
    store = make_store(tmp_path)
    store.record_preference("tone", "direct")
    before = store.path.read_bytes()

    payload = store.export_envelope()
    payload["version"] = 99
    with pytest.raises(MemoryStoreError):
        store.import_envelope(payload)
    assert store.path.read_bytes() == before


def test_corrupted_memory_fails_closed_without_silent_reset(tmp_path: Path) -> None:
    store = make_store(tmp_path)
    store.record_preference("tone", "direct")
    corrupted = b"{ceci n'est pas du JSON"
    store.path.write_bytes(corrupted)

    with pytest.raises(MemoryCorruptionError):
        store.list_preferences()
    with pytest.raises(MemoryCorruptionError):
        store.record_choice("bullet_reformulate:offer_123", option())

    degraded = inject_constraints(store, 5)
    assert degraded["degraded"] is True
    assert degraded["generation_allowed"] is False
    assert degraded["constraints"] == []
    # The damaged bytes are preserved so a human can inspect or re-import.
    assert store.path.read_bytes() == corrupted
    report = build_report(store)
    assert report["degraded"] is True and report["generation_allowed"] is False


def test_purge_is_auditable_and_does_not_delete_history(tmp_path: Path) -> None:
    store = make_store(tmp_path)
    store.record_preference("tone", "direct")
    assert store.purge_preference("tone", reason="Retrait volontaire") is True
    assert store.list_preferences() == []
    assert store.purge_preference("tone") is False

    events = store.export_envelope()["events"]
    purges = [event for event in events if event["type"] == "preference_purged"]
    assert len(purges) == 1 and purges[0]["reason"] == "Retrait volontaire"
    store.record_preference("tone", "sobre")
    assert [item.value for item in store.list_preferences()] == ["sobre"]


def test_manual_preference_wins_over_inferred_choices(tmp_path: Path) -> None:
    store = make_store(tmp_path)
    store.record_preference("tone", "sobre", source="manual")
    for _ in range(3):
        store.record_choice("bullet_reformulate:offer_123", option(tone="direct"))
    tone = {item.key: item for item in store.list_preferences()}["tone"]
    assert tone.value == "sobre"
    assert tone.source == "manual"
    assert tone.auto_applied is True


def test_glossary_and_report_are_derived_from_choices(tmp_path: Path) -> None:
    store = make_store(tmp_path)
    store.record_choice(
        "bullet_reformulate:offer_123",
        {"action_verb": "conçu", "glossary": [{"term": "ML", "definition": "Machine learning"}]},
        evidence_refs=["offer_123"],
    )
    glossary = store.glossary()
    assert len(glossary) == 1 and glossary[0].term == "ML"
    report = build_report(store)
    assert report["degraded"] is False
    assert report["stats"]["glossary_count"] == 1
    markdown = render_markdown(report)
    assert "ML" in markdown and "Machine learning" in markdown


def test_store_file_and_directory_are_private(tmp_path: Path) -> None:
    store = make_store(tmp_path)
    store.record_preference("tone", "direct")
    assert (store.path.stat().st_mode & 0o077) == 0
    assert (store.data_dir.stat().st_mode & 0o077) == 0


def test_memory_http_api_round_trip(tmp_path: Path) -> None:
    app = create_app(tmp_path, agent_override=object())
    client = TestClient(app)

    assert client.get("/memory/prefs").json()["preferences"] == []
    created = client.post("/memory/prefs", json={"key": "js-action-verb", "value": "conçu"})
    assert created.status_code == 201
    assert created.json()["preference"]["source"] == "manual"

    for _ in range(3):
        response = client.post(
            "/memory/back",
            json={"context": "bullet_reformulate:offer_123", "chosen": option(), "evidence_refs": ["offer_123"]},
        )
        assert response.status_code == 201
    back = client.get("/memory/back").json()["choices"]
    assert len(back) == 3

    constraints = client.get("/memory/constraints").json()
    assert constraints["generation_allowed"] is True
    assert any(item["auto_applied"] for item in constraints["constraints"])

    undone = client.post(f"/memory/back/{back[0]['id']}/undo")
    assert undone.status_code == 200
    assert undone.json()["choice"]["undone"] is True

    exported = client.post("/memory/export")
    assert exported.status_code == 200
    assert "attachment" in exported.headers["content-disposition"]
    payload = exported.json()
    imported = client.post("/memory/import", json=payload)
    assert imported.status_code == 200
    assert imported.json()["imported"] == 0

    report = client.get("/memory/report").json()
    assert report["generation_allowed"] is True
    assert client.get("/memory/report?format=markdown").json()["markdown"].startswith("# Mémoire personnelle")

    removed = client.delete("/memory/prefs/js-action-verb")
    assert removed.status_code == 200
    assert client.delete("/memory/prefs/inconnue").status_code == 404


def test_memory_http_api_reports_corruption_as_conflict(tmp_path: Path) -> None:
    app = create_app(tmp_path, agent_override=object())
    client = TestClient(app, raise_server_exceptions=False)
    client.post("/memory/prefs", json={"key": "tone", "value": "direct"})
    app.state.style_memory.path.write_text("{invalide", encoding="utf-8")

    assert client.get("/memory/prefs").status_code == 409
    degraded = client.get("/memory/constraints").json()
    assert degraded["degraded"] is True and degraded["generation_allowed"] is False
    assert client.get("/memory/report").json()["degraded"] is True


def test_memory_panel_static_assets_are_wired() -> None:
    script = (ROOT / "career_static" / "js" / "memory-panel.js").read_text(encoding="utf-8")
    html = (ROOT / "career_static" / "index.html").read_text(encoding="utf-8")
    assert "/career-static/js/memory-panel.js" in html
    assert 'const BASE = "/memory"' in script
    for endpoint in ("/prefs", "/back", "/export", "/import", "/report"):
        assert f"${{BASE}}{endpoint}" in script
    assert "textContent" in script
    assert "window.prompt(" not in script
    assert "Annuler ce choix" in script
