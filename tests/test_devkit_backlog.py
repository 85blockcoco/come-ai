"""Integration du backlog FINAL dans le Dev Kit, hors modèle et hors données privées."""

from pathlib import Path

from devkit.backlog import import_backlog, parse_backlog
from devkit.evolution_store import EvolutionStore


ROOT = Path(__file__).resolve().parents[1]
BACKLOG = ROOT / "docs" / "NAGE_FINAL_200_MISSIONS.md"


def test_parse_backlog_has_two_hundred_ordered_entries():
    entries = parse_backlog(BACKLOG)
    assert len(entries) == 200
    assert entries[0].mission_id == "FINAL-001"
    assert entries[-1].mission_id == "FINAL-200"
    assert "Preuve attendue" in entries[0].acceptance


def test_backlog_dry_run_does_not_queue_or_run(tmp_path):
    store = EvolutionStore(tmp_path / "devkit")
    result = import_backlog(ROOT, store, BACKLOG, limit=3, dry_run=True)
    assert result["status"] == "preview"
    assert result["count"] == 3
    assert result["queued"] == 0
    assert store.list_tasks() == []


def test_backlog_import_is_bounded_and_persistent(tmp_path):
    store = EvolutionStore(tmp_path / "devkit")
    result = import_backlog(ROOT, store, BACKLOG, limit=4)
    assert result["status"] == "queued"
    assert result["queued"] == 4
    assert len(store.list_tasks(limit=10)) == 4
    restarted = EvolutionStore(tmp_path / "devkit")
    assert len(restarted.list_tasks(limit=10)) == 4
    again = import_backlog(ROOT, restarted, BACKLOG, limit=4)
    assert again["queued"] == 4
    assert len(restarted.list_tasks(limit=10)) == 4
