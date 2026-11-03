from __future__ import annotations

import time
from pathlib import Path

import pytest

from academics.vc.content import ContentPack, load_content
from academics.vc.errors import InputError
from academics.vc.models import CardProgress, Flashcard, ReviewEvent, ReviewSession
from academics.vc.scheduler import (
    abandon_session,
    answer_session,
    card_reason,
    due_cards,
    grade_card,
    resume_session,
    select_session_cards,
    session_summary,
    start_session,
)
from academics.vc.storage import VcStore


def card(card_id: str, topic_id: str = "VC04", status: str = "active") -> Flashcard:
    return Flashcard(
        id=card_id,
        topic_id=topic_id,
        question=f"Question {card_id}",
        answer=f"Réponse {card_id}",
        status=status,
    )


def progress(card_id: str, due_date: str, **kwargs) -> CardProgress:
    return CardProgress(card_id=card_id, due_date=due_date, **kwargs)


def event(topic_id: str, correct: bool, day: str = "2026-11-02") -> ReviewEvent:
    return ReviewEvent(
        event_id=f"evt-{topic_id}-{correct}-{day}",
        session_id="ses-test",
        card_id=f"{topic_id}-C001",
        topic_id=topic_id,
        grade="good" if correct else "again",
        correct=correct,
        reviewed_at=f"{day}T00:00:00",
        due_before=day,
        due_after=day,
        ease_after=2.5,
    )


def test_due_selection_excludes_future_and_suspended() -> None:
    cards = [card("VC04-C001"), card("VC04-C002"), card("VC04-C003")]
    state = {
        "VC04-C001": progress("VC04-C001", "2026-11-01"),
        "VC04-C002": progress("VC04-C002", "2026-11-05"),
        "VC04-C003": progress("VC04-C003", "2026-11-01", suspended=True),
    }
    selected = select_session_cards(cards, state, today="2026-11-02", limit=10)
    assert [item.id for item in selected] == ["VC04-C001"]


def test_new_cards_are_introduced_in_curriculum_order() -> None:
    cards = [card("VC05-C001", "VC05"), card("VC04-C002", "VC04"), card("VC04-C001", "VC04")]
    selected = select_session_cards(cards, {}, today="2026-11-02", limit=10)
    assert [item.id for item in selected] == ["VC04-C001", "VC04-C002", "VC05-C001"]


def test_four_grade_transitions() -> None:
    start = CardProgress(card_id="VC04-C001", due_date="2026-11-02")
    again, again_event = grade_card(start, "again", "2026-11-02")
    assert again.interval_days == 0
    assert again.repetitions == 0
    assert again.lapses == 1
    assert again.ease == 2.3
    assert again.due_date == "2026-11-02"
    assert again_event.correct is False

    hard, _ = grade_card(start, "hard", "2026-11-02")
    assert hard.interval_days == 1
    assert hard.repetitions == 1
    assert hard.ease == 2.35

    good, good_event = grade_card(start, "good", "2026-11-02")
    assert good.interval_days == 1
    assert good.repetitions == 1
    assert good.due_date == "2026-11-03"
    assert good_event.correct is True

    second, _ = grade_card(good, "good", "2026-11-03")
    assert second.interval_days == 3
    assert second.repetitions == 2

    third, _ = grade_card(second, "good", "2026-11-06")
    assert third.interval_days == 8
    assert third.repetitions == 3

    easy, easy_event = grade_card(start, "easy", "2026-11-02")
    assert easy.interval_days == 2
    assert easy.ease == 2.65
    assert easy_event.correct is True


def test_ease_clamping_and_interval_cap() -> None:
    low = CardProgress(card_id="c", ease=1.35, due_date="2026-11-02")
    clamped, _ = grade_card(low, "again", "2026-11-02")
    assert clamped.ease == 1.3

    high = CardProgress(card_id="c", ease=2.95, due_date="2026-11-02")
    raised, _ = grade_card(high, "easy", "2026-11-02")
    assert raised.ease == 3.0

    long = CardProgress(
        card_id="c", ease=3.0, interval_days=360, repetitions=5, due_date="2026-11-02"
    )
    capped, _ = grade_card(long, "good", "2026-11-02")
    assert capped.interval_days == 365


def test_invalid_grade_and_date_are_rejected() -> None:
    with pytest.raises(InputError):
        grade_card(CardProgress(card_id="c", due_date="2026-11-02"), "perfect", "2026-11-02")
    with pytest.raises(ValueError):
        grade_card(CardProgress(card_id="c", due_date="2026-11-02"), "good", "02/11/2026")


def test_deterministic_due_ordering() -> None:
    cards = [
        card("VC05-C001", "VC05"),
        card("VC04-C002", "VC04"),
        card("VC09-C001", "VC09"),
        card("VC03-C001", "VC03"),
    ]
    state = {
        "VC05-C001": progress("VC05-C001", "2026-11-01"),
        "VC04-C002": progress("VC04-C002", "2026-11-01"),
        "VC09-C001": progress("VC09-C001", "2026-10-31"),
    }
    selected = select_session_cards(cards, state, today="2026-11-02", limit=10)
    assert [item.id for item in selected] == [
        "VC09-C001",
        "VC04-C002",
        "VC05-C001",
        "VC03-C001",
    ]


def test_resuming_preserves_cursor_and_answers(tmp_path: Path) -> None:
    store = VcStore(tmp_path / "vc")
    content = load_content()
    session = start_session(store, content, minutes=10, today="2026-11-02")
    first = session.card_ids[0]
    session, first_event = answer_session(store, content, session, "good")
    assert session.cursor == 1
    assert first_event.card_id == first

    restored = resume_session(store)
    assert restored is not None
    assert restored.session_id == session.session_id
    assert restored.cursor == 1
    assert [item.card_id for item in restored.answered] == [first]


def test_session_summary_counts() -> None:
    session = ReviewSession(
        session_id="ses-1",
        mode="quick",
        started_at="2026-11-02T10:00:00",
        target_minutes=10,
        today="2026-11-02",
        card_ids=["a", "b", "c"],
        cursor=2,
        answered=[
            ReviewEvent(
                event_id="e1",
                session_id="ses-1",
                card_id="a",
                topic_id="VC04",
                grade="good",
                correct=True,
                reviewed_at="2026-11-02T10:00:00",
                due_before="2026-11-02",
                due_after="2026-11-03",
                ease_after=2.5,
                duration_seconds=30,
            ),
            ReviewEvent(
                event_id="e2",
                session_id="ses-1",
                card_id="b",
                topic_id="VC04",
                grade="again",
                correct=False,
                reviewed_at="2026-11-02T10:01:00",
                due_before="2026-11-02",
                due_after="2026-11-02",
                ease_after=2.3,
                duration_seconds=30,
            ),
        ],
    )
    summary = session_summary(session)
    assert summary["seen"] == 2
    assert summary["correct"] == 1
    assert summary["to_consolidate"] == 1
    assert summary["due_tomorrow"] == 1
    assert summary["minutes"] == 1.0
    assert summary["topics"]["VC04"] == {"seen": 2, "correct": 1}


def test_session_limits_by_mode(tmp_path: Path) -> None:
    content = load_content()
    quick = start_session(VcStore(tmp_path / "q"), content, minutes=10, mode="quick", today="2026-11-02")
    assert len(quick.card_ids) == 20

    long = start_session(VcStore(tmp_path / "l"), content, minutes=45, mode="long", today="2026-11-02")
    assert len(long.card_ids) == len(content.cards)

    custom = start_session(VcStore(tmp_path / "c"), content, minutes=3, mode="custom", today="2026-11-02")
    assert len(custom.card_ids) == 6


def test_exam_eve_prioritizes_weak_topics(tmp_path: Path) -> None:
    store = VcStore(tmp_path / "vc")
    content = load_content()
    weak_reviews = [event("VC04", False) for _ in range(3)]
    for item in weak_reviews:
        store.append_review(item)
    state = {
        "VC09-C001": progress("VC09-C001", "2026-10-31"),
        "VC04-C001": progress("VC04-C001", "2026-11-01"),
    }
    store.save_progress(state)
    session = start_session(store, content, minutes=10, mode="exam_eve", today="2026-11-02")
    assert session.card_ids[0].startswith("VC04")


def test_no_duplicate_card_in_one_session() -> None:
    cards = [card(f"VC04-C{index:03d}") for index in range(1, 21)]
    selected = select_session_cards(cards, {}, today="2026-11-02", limit=50)
    ids = [item.id for item in selected]
    assert len(ids) == len(set(ids))


def test_empty_deck_returns_empty_session(tmp_path: Path) -> None:
    store = VcStore(tmp_path / "vc")
    content = ContentPack(schema_version=1, topics=())
    session = start_session(store, content, minutes=10, today="2026-11-02")
    assert session.card_ids == []
    summary = session_summary(session)
    assert summary["seen"] == 0
    assert summary["total"] == 0


def test_date_boundary_changes_due_selection() -> None:
    cards = [card("VC04-C001")]
    state = {"VC04-C001": progress("VC04-C001", "2026-11-03")}
    assert select_session_cards(cards, state, today="2026-11-02", limit=5) == []
    selected = select_session_cards(cards, state, today="2026-11-03", limit=5)
    assert [item.id for item in selected] == ["VC04-C001"]

    graded, _ = grade_card(state["VC04-C001"], "good", "2026-11-03")
    assert graded.due_date == "2026-11-04"


def test_abandon_keeps_events_and_does_not_lose_cards(tmp_path: Path) -> None:
    store = VcStore(tmp_path / "vc")
    content = load_content()
    session = start_session(store, content, minutes=10, today="2026-11-02")
    answered_ids: list[str] = []
    for _ in range(5):
        session, event = answer_session(store, content, session, "good")
        answered_ids.append(event.card_id)
    abandon_session(store, session)
    assert len(store.load_reviews()) == 5

    second = start_session(store, content, minutes=10, today="2026-11-02")
    assert not set(answered_ids) & set(second.card_ids)
    assert session.card_ids[5] in second.card_ids


def test_good_and_easy_never_shorten_a_mature_interval() -> None:
    base = CardProgress(
        card_id="c", ease=2.5, interval_days=10, repetitions=4, due_date="2026-11-02"
    )
    good, _ = grade_card(base, "good", "2026-11-02")
    easy, _ = grade_card(base, "easy", "2026-11-02")
    assert good.interval_days >= base.interval_days
    assert easy.interval_days >= base.interval_days


def test_due_cards_and_reason() -> None:
    state = {
        "a": progress("a", "2026-11-01"),
        "b": progress("b", "2026-11-05"),
        "c": progress("c", "2026-11-01", suspended=True),
    }
    assert due_cards(state, "2026-11-02") == 1
    assert card_reason(None, "2026-11-02") == "nouvelle carte"
    assert card_reason(progress("a", "2026-11-01"), "2026-11-02") == "carte due"
    assert card_reason(progress("a", "2026-11-03", last_grade="again"), "2026-11-02") == (
        "carte à revoir après un oubli"
    )


def test_selection_of_one_thousand_cards_is_fast() -> None:
    cards = [card(f"VC04-C{index:04d}") for index in range(1, 1001)]
    state = {
        item.id: progress(item.id, "2026-11-01" if index % 2 else "2026-11-05")
        for index, item in enumerate(cards)
    }
    started = time.perf_counter()
    selected = select_session_cards(cards, state, today="2026-11-02", limit=50)
    elapsed = time.perf_counter() - started
    assert len(selected) == 50
    assert elapsed < 0.3
