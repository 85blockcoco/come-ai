from __future__ import annotations

import time
from pathlib import Path

import pytest

from academics.vc.content import load_content
from academics.vc.models import CardProgress, ReviewEvent
from academics.vc.report import build_progress_report


def review(
    card_id: str,
    topic_id: str,
    day: str,
    correct: bool = True,
    session_id: str = "ses-1",
) -> ReviewEvent:
    return ReviewEvent(
        event_id=f"evt-{card_id}-{day}-{correct}",
        session_id=session_id,
        card_id=card_id,
        topic_id=topic_id,
        grade="good" if correct else "again",
        correct=correct,
        reviewed_at=f"{day}T00:00:00",
        due_before=day,
        due_after=day,
        ease_after=2.5,
    )


def test_coverage_counts_covered_and_untested_topics(tmp_path: Path) -> None:
    content = load_content()
    report = build_progress_report(
        content,
        [review("VC04-C001", "VC04", "2026-11-01"), review("VC09-C001", "VC09", "2026-11-02")],
        today="2026-11-02",
        days=30,
        output_dir=tmp_path,
    )
    assert report.coverage["covered_topics"] == 2
    assert report.coverage["total_topics"] == len(content.topics)
    assert report.coverage["ratio"] == pytest.approx(2 / len(content.topics), abs=1e-4)
    assert "VC04" not in report.coverage["untested"]
    assert "VC01" in report.coverage["untested"]


def test_retention_windows_from_review_events(tmp_path: Path) -> None:
    content = load_content()
    reviews = [
        review("VC04-C001", "VC04", "2026-10-01"),
        review("VC04-C001", "VC04", "2026-10-08"),
        review("VC04-C001", "VC04", "2026-11-07"),
    ]
    report = build_progress_report(
        content, reviews, today="2026-11-10", days=60, output_dir=tmp_path
    )
    assert report.retention["1d"]["opportunities"] == 2
    assert report.retention["1d"]["retained"] == 2
    assert report.retention["7d"]["rate"] == pytest.approx(1.0)
    assert report.retention["30d"]["opportunities"] == 1
    assert report.retention["30d"]["rate"] == pytest.approx(1.0)


def test_due_cards_and_weak_topics(tmp_path: Path) -> None:
    content = load_content()
    progress = {
        "VC04-C001": CardProgress(card_id="VC04-C001", due_date="2026-11-01"),
        "VC04-C002": CardProgress(card_id="VC04-C002", due_date="2026-11-02"),
        "VC09-C001": CardProgress(card_id="VC09-C001", due_date="2026-11-05"),
    }
    reviews = [review("VC04-C001", "VC04", "2026-11-01", correct=False) for _ in range(3)]
    report = build_progress_report(
        content,
        reviews,
        today="2026-11-02",
        days=30,
        output_dir=tmp_path,
        progress=progress,
    )
    assert report.due_cards == 2
    weak_ids = [item["topic_id"] for item in report.weak_topics]
    assert "VC04" in weak_ids
    assert any(item["status"] == "fragile" for item in report.weak_topics)


def test_recent_errors_and_next_actions(tmp_path: Path) -> None:
    content = load_content()
    reviews = [
        review("VC04-C001", "VC04", "2026-11-01", correct=False),
        review("VC04-C002", "VC04", "2026-11-01", correct=False),
        review("VC09-C001", "VC09", "2026-11-02", correct=True),
    ]
    report = build_progress_report(
        content, reviews, today="2026-11-02", days=30, output_dir=tmp_path
    )
    assert report.recent_errors[0] == {"category": "recall", "count": 2}
    assert report.next_actions
    assert all("minutes" in action and "reason" in action for action in report.next_actions)
    assert sum(action["minutes"] for action in report.next_actions) <= 60


def test_every_number_is_recomputable(tmp_path: Path) -> None:
    content = load_content()
    reviews = [
        review("VC04-C001", "VC04", "2026-11-01", correct=True),
        review("VC04-C001", "VC04", "2026-11-08", correct=False),
        review("VC09-C001", "VC09", "2026-11-02", correct=True),
    ]
    report = build_progress_report(
        content, reviews, today="2026-11-10", days=30, output_dir=tmp_path
    )
    assert report.coverage["covered_topics"] == len(report.coverage["covered"])
    assert report.coverage["ratio"] == pytest.approx(
        report.coverage["covered_topics"] / report.coverage["total_topics"], abs=1e-4
    )
    for window in ("1d", "7d", "30d"):
        data = report.retention[window]
        assert data["retained"] <= data["opportunities"]
        if data["opportunities"]:
            assert data["rate"] == pytest.approx(
                data["retained"] / data["opportunities"], abs=1e-4
            )
        else:
            assert data["rate"] is None


def test_untested_topics_are_listed(tmp_path: Path) -> None:
    content = load_content()
    report = build_progress_report(
        content, [], today="2026-11-02", days=30, output_dir=tmp_path
    )
    assert report.coverage["covered_topics"] == 0
    assert len(report.coverage["untested"]) == len(content.topics)
    assert report.due_cards == 0
    assert report.weak_topics == []


def test_empty_and_one_year_periods(tmp_path: Path) -> None:
    content = load_content()
    empty = build_progress_report(
        content, [], today="2026-11-02", days=30, output_dir=tmp_path
    )
    assert empty.period_start == "2026-10-04"
    assert empty.period_end == "2026-11-02"

    year = build_progress_report(
        content, [], today="2026-11-02", days=365, output_dir=tmp_path
    )
    assert year.period_start == "2025-11-03"
    assert year.retention["1d"]["rate"] is None


def test_period_filter_excludes_older_events(tmp_path: Path) -> None:
    content = load_content()
    reviews = [
        review("VC01-C001", "VC01", "2025-01-01"),
        review("VC04-C001", "VC04", "2026-11-01"),
    ]
    report = build_progress_report(
        content, reviews, today="2026-11-02", days=30, output_dir=tmp_path
    )
    assert "VC04" in report.coverage["covered"]
    assert "VC01" not in report.coverage["covered"]


def test_report_is_written_privately(tmp_path: Path) -> None:
    content = load_content()
    reviews = [review("VC04-C001", "VC04", "2026-11-02", correct=False)]
    report = build_progress_report(
        content, reviews, today="2026-11-02", days=30, output_dir=tmp_path
    )
    path = Path(report.markdown_path)
    assert path.exists()
    assert path.parent == tmp_path
    text = path.read_text(encoding="utf-8")
    assert "Rapport de progression" in text
    assert "Cartes dues" in text
    assert "Prochaines actions" in text
    assert str(tmp_path) not in text
    assert "réponse détaillée" not in text


def test_report_over_one_year_is_fast(tmp_path: Path) -> None:
    content = load_content()
    reviews = [
        review(
            "VC04-C{:03d}".format(index % 10 + 1),
            "VC04" if index % 2 else "VC09",
            f"2026-{index % 12 + 1:02d}-{index % 28 + 1:02d}",
            correct=index % 3 == 0,
        )
        for index in range(10_000)
    ]
    started = time.perf_counter()
    report = build_progress_report(
        content, reviews, today="2026-12-31", days=365, output_dir=tmp_path
    )
    assert time.perf_counter() - started < 1.0
    assert report.period_start == "2026-01-01"
