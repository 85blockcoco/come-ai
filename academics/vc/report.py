"""Offline progress report with recomputable numbers."""

from __future__ import annotations

import os
from collections import Counter, defaultdict
from datetime import date
from pathlib import Path
from typing import Any, Mapping, Sequence

from .dates import now_iso, parse_date
from .mastery import build_study_plan, coverage_summary, mastery_radar
from .models import (
    CardProgress,
    CaseAttempt,
    ProgressReport,
    ReviewEvent,
)


def _retention(reviews: Sequence[ReviewEvent]) -> dict[str, Any]:
    by_card: dict[str, list[ReviewEvent]] = defaultdict(list)
    for event in reviews:
        by_card[event.card_id].append(event)
    windows = (1, 7, 30)
    result: dict[str, Any] = {}
    for window in windows:
        opportunities = 0
        retained = 0
        for events in by_card.values():
            ordered = sorted(events, key=lambda item: item.reviewed_at)
            for previous, following in zip(ordered, ordered[1:]):
                try:
                    gap = (
                        date.fromisoformat(following.reviewed_at[:10])
                        - date.fromisoformat(previous.reviewed_at[:10])
                    ).days
                except ValueError:
                    continue
                if gap >= window:
                    opportunities += 1
                    if following.correct:
                        retained += 1
        result[f"{window}d"] = {
            "retained": retained,
            "opportunities": opportunities,
            "rate": round(retained / opportunities, 4) if opportunities else None,
        }
    return result


def _markdown(report: ProgressReport) -> str:
    lines = [
        "# Rapport de progression — Venture Capital",
        "",
        f"Period: {report.period_start} → {report.period_end}",
        f"Generated on: {report.generated_at}",
        "",
        "## Couverture",
        "",
        f"- Topics couverts : {report.coverage['covered_topics']} / {report.coverage['total_topics']} "
        f"({report.coverage['ratio']:.0%})",
        f"- Untested: {', '.join(report.coverage['untested']) or 'none'}",
        "",
        "## Retention",
        "",
    ]
    for window, data in report.retention.items():
        rate = "n/a" if data["rate"] is None else f"{data['rate']:.0%}"
        lines.append(
            f"- {window} : {rate} ({data['retained']} / {data['opportunities']} occasions)"
        )
    lines.extend(
        [
            "",
            "## Cartes dues",
            "",
            f"- {report.due_cards} carte(s) due(s) aujourd'hui.",
            "",
            "## Topics fragiles",
            "",
        ]
    )
    if report.weak_topics:
        for item in report.weak_topics:
            lines.append(
                f"- {item['topic_id']} — {item['title']} : {item['status']}, "
                f"success {item['accuracy']:.0%}" if item["accuracy"] is not None else
                f"- {item['topic_id']} — {item['title']} : {item['status']}"
            )
    else:
        lines.append("- No fragile topic over the period.")
    lines.extend(["", "## Recent errors", ""])
    if report.recent_errors:
        for item in report.recent_errors:
            lines.append(f"- {item['category']} : {item['count']}")
    else:
        lines.append("- No error recorded.")
    lines.extend(["", "## Prochaines actions", ""])
    if report.next_actions:
        for action in report.next_actions:
            lines.append(
                f"- {action['kind']} {action['topic_id']} — {action['minutes']} min : "
                f"{action['reason']}"
            )
    else:
        lines.append("- No action needed: continue regular revision.")
    lines.extend(
        [
            "",
            "> Local report. It contains no raw notes or detailed answers.",
            "",
        ]
    )
    return "\n".join(lines)


def build_progress_report(
    content,
    reviews: Sequence[ReviewEvent],
    *,
    today: str,
    days: int = 30,
    output_dir: Path | None = None,
    case_attempts: Sequence[CaseAttempt] = (),
    exam_results: Sequence[dict[str, Any]] = (),
    drill_attempts: Sequence[Any] = (),
    paper_attempts: Sequence[Any] = (),
    progress: Mapping[str, CardProgress] | None = None,
) -> ProgressReport:
    parse_date(today)
    if days < 1:
        raise ValueError("The period must be at least one day.")
    start = date.fromisoformat(today).toordinal() - days + 1
    period_start = date.fromordinal(start).isoformat()
    filtered = [
        event
        for event in reviews
        if period_start <= event.reviewed_at[:10] <= today
    ]
    period_cases = [
        attempt
        for attempt in case_attempts
        if period_start <= attempt.submitted_at[:10] <= today
    ]
    period_drills = [
        attempt
        for attempt in drill_attempts
        if period_start <= attempt.submitted_at[:10] <= today
    ]
    period_papers = [
        attempt
        for attempt in paper_attempts
        if period_start <= attempt.submitted_at[:10] <= today
    ]
    period_exams = [
        result
        for result in exam_results
        if period_start <= str(result.get("submitted_at", ""))[:10] <= today
    ]
    radar = mastery_radar(
        content,
        filtered,
        today=today,
        case_attempts=period_cases,
        exam_results=period_exams,
        drill_attempts=period_drills,
        paper_attempts=period_papers,
        progress=progress,
    )
    coverage = coverage_summary(radar)
    weak = [
        {
            "topic_id": record.topic_id,
            "title": record.title,
            "status": record.status,
            "accuracy": record.accuracy,
        }
        for record in radar
        if record.status in ("fragile", "developing")
    ]
    errors: Counter[str] = Counter()
    for event in filtered:
        if not event.correct:
            errors["recall"] += 1
    for attempt in case_attempts:
        if attempt.score < 0.6:
            errors["case"] += 1
    for result in period_exams:
        per_topic = result.get("per_topic")
        if not isinstance(per_topic, dict):
            continue
        for bucket in per_topic.values():
            if isinstance(bucket, dict) and float(bucket.get("score", 0.0)) < 0.6:
                errors["exam"] += 1
    plan = build_study_plan(content, radar, minutes=60, today=today)
    due = 0
    if progress:
        due = sum(
            1
            for item in progress.values()
            if not item.suspended and item.due_date and item.due_date <= today
        )
    report = ProgressReport(
        generated_at=now_iso(),
        period_start=period_start,
        period_end=today,
        coverage=coverage,
        retention=_retention(filtered),
        due_cards=due,
        weak_topics=weak,
        recent_errors=[
            {"category": category, "count": count}
            for category, count in sorted(errors.items(), key=lambda item: (-item[1], item[0]))
        ],
        next_actions=plan.activities,
        markdown_path="",
    )
    directory = Path(output_dir) if output_dir is not None else Path.home() / ".nage" / "vc" / "reports"
    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    os.chmod(directory, 0o700)
    destination = directory / f"{today}-progress.md"
    temporary = destination.with_name(f"{destination.name}.tmp")
    temporary.write_text(_markdown(report), encoding="utf-8")
    os.replace(temporary, destination)
    os.chmod(destination, 0o600)
    report.markdown_path = str(destination)
    return report
