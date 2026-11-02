from __future__ import annotations

import time

import pytest

from academics.vc.content import load_content
from academics.vc.mastery import build_study_plan, mastery_radar
from academics.vc.models import CardProgress, CaseAttempt, MasteryRecord, ReviewEvent


def review(topic_id: str, correct: bool, day: str = "2026-11-02", card_id: str | None = None) -> ReviewEvent:
    return ReviewEvent(
        event_id=f"evt-{topic_id}-{day}-{correct}-{card_id or 'x'}",
        session_id="ses-1",
        card_id=card_id or f"{topic_id}-C001",
        topic_id=topic_id,
        grade="good" if correct else "again",
        correct=correct,
        reviewed_at=f"{day}T00:00:00",
        due_before=day,
        due_after=day,
        ease_after=2.5,
    )


def test_untested_topic_has_null_accuracy() -> None:
    content = load_content()
    records = mastery_radar(content, [], today="2026-11-02")
    assert len(records) == len(content.topics)
    assert all(record.status == "untested" for record in records)
    assert all(record.accuracy is None for record in records)
    assert all(record.attempts == 0 for record in records)


def test_mastery_thresholds() -> None:
    content = load_content()
    developing = mastery_radar(
        content,
        [review("VC04", True), review("VC04", True), review("VC04", False)],
        today="2026-11-02",
    )
    vc04 = next(record for record in developing if record.topic_id == "VC04")
    assert vc04.attempts == 3
    assert vc04.accuracy == pytest.approx(0.6667)
    assert vc04.status == "developing"

    fragile = mastery_radar(
        content,
        [review("VC04", False), review("VC04", False), review("VC04", False)],
        today="2026-11-02",
    )
    assert next(record for record in fragile if record.topic_id == "VC04").status == "fragile"

    solid = mastery_radar(
        content,
        [review("VC04", True) for _ in range(4)] + [review("VC04", False)],
        today="2026-11-02",
    )
    assert next(record for record in solid if record.topic_id == "VC04").status == "solid"


def test_top_errors_are_ordered_by_frequency() -> None:
    content = load_content()
    attempt = CaseAttempt(
        attempt_id="case-1",
        case_id="VC04-CASE02",
        answers={},
        criteria_results=[],
        score=0.2,
        unsupported_numbers=[],
        submitted_at="2026-11-02T00:00:00",
    )
    records = mastery_radar(
        content,
        [review("VC04", False) for _ in range(3)],
        today="2026-11-02",
        case_attempts=[attempt, attempt],
    )
    vc04 = next(record for record in records if record.topic_id == "VC04")
    assert vc04.top_errors == ["rappel", "cas"]
    assert vc04.attempts == 5


def test_due_cards_are_counted_per_topic() -> None:
    content = load_content()
    progress = {
        "VC04-C001": CardProgress(card_id="VC04-C001", due_date="2026-11-01"),
        "VC04-C002": CardProgress(card_id="VC04-C002", due_date="2026-11-02"),
        "VC09-C001": CardProgress(card_id="VC09-C001", due_date="2026-11-05"),
        "VC09-C002": CardProgress(card_id="VC09-C002", due_date="2026-11-01", suspended=True),
    }
    records = mastery_radar(content, [], today="2026-11-02", progress=progress)
    by_topic = {record.topic_id: record for record in records}
    assert by_topic["VC04"].due_cards == 2
    assert by_topic["VC09"].due_cards == 0


def test_plan_never_exceeds_capacity() -> None:
    content = load_content()
    records = mastery_radar(content, [], today="2026-11-02")
    plan = build_study_plan(content, records, minutes=7, today="2026-11-02")
    assert plan.total_minutes <= 7
    assert sum(item["minutes"] for item in plan.activities) == plan.total_minutes
    assert all(item["reason"] for item in plan.activities)


def test_plan_prioritizes_weak_topic_near_exam() -> None:
    content = load_content()
    records = [
        MasteryRecord(
            topic_id="VC04",
            title="Pre-money",
            attempts=5,
            correct=2,
            accuracy=0.4,
            last_activity="2026-11-02",
            status="fragile",
            due_cards=0,
            top_errors=["rappel"],
        ),
        MasteryRecord(
            topic_id="VC09",
            title="Métriques",
            attempts=5,
            correct=5,
            accuracy=1.0,
            last_activity="2026-11-02",
            status="solid",
            due_cards=10,
            top_errors=[],
        ),
    ]
    plan = build_study_plan(
        content, records, minutes=60, today="2026-11-02", exam_date="2026-11-03"
    )
    assert plan.activities
    assert plan.activities[0]["topic_id"] == "VC04"
    assert plan.total_minutes <= 60


def test_plan_without_exam_date_or_weakness() -> None:
    content = load_content()
    records = [
        MasteryRecord(
            topic_id=topic.id,
            title=topic.title_fr,
            attempts=3,
            correct=3,
            accuracy=1.0,
            last_activity="2026-11-02",
            status="solid",
            due_cards=0,
            top_errors=[],
        )
        for topic in content.topics
    ]
    plan = build_study_plan(content, records, minutes=5, today="2026-11-02")
    assert plan.activities == []
    assert plan.total_minutes == 0


def test_plan_ignores_topic_without_content() -> None:
    content = load_content()
    records = [
        MasteryRecord(
            topic_id="VC99",
            title="Inconnu",
            attempts=3,
            correct=1,
            accuracy=0.33,
            last_activity="2026-11-02",
            status="fragile",
            due_cards=5,
            top_errors=["rappel"],
        )
    ]
    plan = build_study_plan(content, records, minutes=60, today="2026-11-02")
    assert all(item["topic_id"] != "VC99" for item in plan.activities)


def test_plan_is_deterministic_for_identical_inputs() -> None:
    content = load_content()
    records = mastery_radar(
        content,
        [review("VC04", False), review("VC04", False), review("VC09", True)],
        today="2026-11-02",
    )
    first = build_study_plan(
        content, records, minutes=40, today="2026-11-02", exam_date="2026-11-10"
    )
    second = build_study_plan(
        content, records, minutes=40, today="2026-11-02", exam_date="2026-11-10"
    )
    assert first.to_dict() == second.to_dict()


def test_radar_is_deterministic() -> None:
    content = load_content()
    reviews = [review("VC04", True), review("VC04", False), review("VC09", True)]
    first = [record.to_dict() for record in mastery_radar(content, reviews, today="2026-11-02")]
    second = [record.to_dict() for record in mastery_radar(content, reviews, today="2026-11-02")]
    assert first == second


def test_radar_over_ten_thousand_events_is_fast() -> None:
    content = load_content()
    reviews = [
        review("VC04" if index % 2 else "VC09", index % 3 == 0)
        for index in range(10_000)
    ]
    started = time.perf_counter()
    records = mastery_radar(content, reviews, today="2026-11-02")
    elapsed = time.perf_counter() - started
    assert len(records) == len(content.topics)
    assert elapsed < 0.5
