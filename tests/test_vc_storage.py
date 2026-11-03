from __future__ import annotations

import os
from pathlib import Path

import pytest

from academics.vc.errors import InputError, StorageError
from academics.vc.models import CardProgress, ReviewEvent
from academics.vc.storage import CONFIRMATION_PHRASE, VcStore, default_vc_home


def _event(card_id: str = "VC04-C001") -> ReviewEvent:
    return ReviewEvent(
        event_id="evt-1",
        session_id="ses-1",
        card_id=card_id,
        topic_id="VC04",
        grade="good",
        correct=True,
        reviewed_at="2026-11-02T00:00:00",
        due_before="2026-11-02",
        due_after="2026-11-03",
        ease_after=2.5,
    )


def test_progress_roundtrip_and_atomic_write(tmp_path: Path) -> None:
    store = VcStore(tmp_path / "vc")
    progress = {
        "VC04-C001": CardProgress(
            card_id="VC04-C001", ease=2.6, interval_days=3, repetitions=2, due_date="2026-11-05"
        )
    }
    store.save_progress(progress)
    loaded = store.load_progress()
    assert loaded["VC04-C001"].interval_days == 3
    assert loaded["VC04-C001"].due_date == "2026-11-05"
    assert not (store.home / "progress.json.tmp").exists()


def test_review_jsonl_is_append_only(tmp_path: Path) -> None:
    store = VcStore(tmp_path / "vc")
    store.append_review(_event("VC04-C001"))
    store.append_review(_event("VC04-C002"))
    reviews = store.load_reviews()
    assert [item.card_id for item in reviews] == ["VC04-C001", "VC04-C002"]


def test_malformed_jsonl_line_is_skipped(tmp_path: Path) -> None:
    store = VcStore(tmp_path / "vc")
    store.append_review(_event())
    with (store.home / "reviews.jsonl").open("a", encoding="utf-8") as handle:
        handle.write("{not json}\n")
    assert len(store.load_reviews()) == 1
    assert any("Ligne ignorée" in warning for warning in store.warnings)


def test_corrupt_progress_is_backed_up(tmp_path: Path) -> None:
    store = VcStore(tmp_path / "vc")
    (store.home / "progress.json").write_text("{broken", encoding="utf-8")
    assert store.load_progress() == {}
    assert list(store.home.glob("progress.json.corrupt-*"))


def test_session_roundtrip(tmp_path: Path) -> None:
    from academics.vc.models import ReviewSession

    store = VcStore(tmp_path / "vc")
    session = ReviewSession(
        session_id="ses-1",
        mode="quick",
        started_at="2026-11-02T10:00:00",
        target_minutes=10,
        today="2026-11-02",
        card_ids=["VC04-C001"],
    )
    store.save_active_session(session)
    loaded = store.load_active_session()
    assert loaded is not None
    assert loaded.card_ids == ["VC04-C001"]
    store.clear_active_session()
    assert store.load_active_session() is None


def test_delete_requires_exact_phrase_and_only_vc_home(tmp_path: Path) -> None:
    store = VcStore(tmp_path / "vc")
    with pytest.raises(InputError):
        store.delete_all("supprimer")
    assert store.home.exists()
    assert store.delete_all(CONFIRMATION_PHRASE) is True
    assert not store.home.exists()


def test_export_import_progress(tmp_path: Path) -> None:
    store = VcStore(tmp_path / "vc")
    store.save_progress(
        {"VC04-C001": CardProgress(card_id="VC04-C001", due_date="2026-11-05")}
    )
    destination = tmp_path / "export.json"
    store.export_progress(destination)
    other = VcStore(tmp_path / "vc2")
    assert other.import_progress(destination) == 1
    assert other.load_progress()["VC04-C001"].due_date == "2026-11-05"


def test_default_home_respects_environment(tmp_path: Path, monkeypatch) -> None:
    target = tmp_path / "custom-vc"
    monkeypatch.setenv("NAGE_VC_HOME", str(target))
    assert default_vc_home() == target


def test_default_home_rejects_relative_environment(monkeypatch) -> None:
    monkeypatch.setenv("NAGE_VC_HOME", "relative/path")
    with pytest.raises(StorageError):
        default_vc_home()


def test_symlinked_home_is_refused(tmp_path: Path) -> None:
    target = tmp_path / "real-vc"
    target.mkdir()
    link = tmp_path / "link-vc"
    link.symlink_to(target, target_is_directory=True)
    with pytest.raises(StorageError):
        VcStore(link)
    assert not (target / ".nage-vc").exists()


def test_permissions_are_private(tmp_path: Path) -> None:
    store = VcStore(tmp_path / "vc")
    store.save_progress({})
    mode = os.stat(store.home).st_mode & 0o777
    assert mode == 0o700
    file_mode = os.stat(store.home / "progress.json").st_mode & 0o777
    assert file_mode == 0o600


def test_exam_active_roundtrip_and_history(tmp_path: Path) -> None:
    from academics.vc.models import ExamSession

    store = VcStore(tmp_path / "vc")
    exam = ExamSession(
        exam_id="exam-1",
        seed=7,
        questions=[{"kind": "exam_question", "ref_id": "VC04-E001", "points": 100}],
        started_at="2026-11-02T10:00:00",
        duration_minutes=30,
    )
    store.save_active_exam(exam)
    loaded = store.load_active_exam()
    assert loaded is not None
    assert loaded.exam_id == "exam-1"
    assert loaded.questions[0]["ref_id"] == "VC04-E001"
    store.append_exam_history({"exam_id": "exam-1", "score": 0.5})
    assert store.load_exam_history() == [{"exam_id": "exam-1", "score": 0.5}]
    store.clear_active_exam()
    assert store.load_active_exam() is None


def test_note_index_text_and_deck_roundtrip(tmp_path: Path) -> None:
    from academics.vc.models import Flashcard

    store = VcStore(tmp_path / "vc")
    index = {
        "schema_version": 1,
        "sources": {"src-1": {"source_id": "src-1", "filename": "cours.md"}},
        "proposals": {"prop-1": {"proposal_id": "prop-1"}},
        "rejected_signatures": ["sig-1"],
    }
    store.save_note_index(index)
    loaded = store.load_note_index()
    assert loaded["sources"] == index["sources"]
    assert loaded["proposals"] == index["proposals"]
    assert loaded["rejected_signatures"] == ["sig-1"]

    store.save_note_text("src-1", "Post-money : définition locale.\n")
    assert store.load_note_text("src-1") == "Post-money : définition locale.\n"
    assert (store.path("notes", "src-1.txt").stat().st_mode & 0o777) == 0o600

    card = Flashcard(
        id="vcnote-1",
        topic_id="VC04",
        question="Que signifie « post-money » ?",
        answer="La valorisation après le cash.",
        source_type="user_note",
        citation={"source_id": "src-1", "locator": "ligne 1", "quote": "Post-money"},
        status="active",
    )
    store.save_deck([card])
    assert store.load_deck() == [card]

    store.remove_note_text("src-1")
    assert store.load_note_text("src-1") is None
