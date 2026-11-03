"""Deterministic spaced repetition and resumable review sessions."""

from __future__ import annotations

from collections import defaultdict
from typing import Iterable, Mapping, Sequence

from .dates import add_days, new_id, now_iso, parse_date, stable_id, today_iso
from .errors import InputError
from .models import CardProgress, Flashcard, ReviewEvent, ReviewSession
from .storage import VcStore

MODES = ("quick", "long", "exam_eve", "custom")
MAX_INTERVAL_DAYS = 365
MIN_EASE = 1.3
MAX_EASE = 3.0


def _validate_grade(grade: str) -> None:
    if grade not in ("again", "hard", "good", "easy"):
        raise InputError("Note attendue : again, hard, good ou easy.")


def grade_card(
    progress: CardProgress,
    grade: str,
    today: str,
    *,
    event_id: str = "",
    session_id: str = "",
    duration_seconds: int = 0,
) -> tuple[CardProgress, ReviewEvent]:
    """Apply the SM-2-inspired rule and return the new state and event."""
    _validate_grade(grade)
    parse_date(today)
    due_before = progress.due_date or today
    ease = max(MIN_EASE, min(MAX_EASE, float(progress.ease)))
    interval = max(0, int(progress.interval_days))
    repetitions = max(0, int(progress.repetitions))
    lapses = max(0, int(progress.lapses))

    if grade == "again":
        repetitions = 0
        interval = 0
        ease = max(MIN_EASE, ease - 0.20)
        lapses += 1
    elif grade == "hard":
        repetitions += 1
        interval = max(1, round(interval * 1.2)) if interval else 1
        ease = max(MIN_EASE, ease - 0.15)
    elif grade == "good":
        repetitions += 1
        if repetitions == 1:
            interval = 1
        elif repetitions == 2:
            interval = 3
        else:
            interval = max(1, round(interval * ease))
    else:  # easy
        repetitions += 1
        if repetitions == 1:
            interval = 2
        elif repetitions == 2:
            interval = 5
        else:
            interval = max(1, round(interval * ease * 1.3))
        ease = min(MAX_EASE, ease + 0.15)

    interval = min(MAX_INTERVAL_DAYS, max(0, interval))
    due_after = add_days(today, interval)
    updated = CardProgress(
        card_id=progress.card_id,
        ease=round(ease, 2),
        interval_days=interval,
        repetitions=repetitions,
        due_date=due_after,
        last_grade=grade,
        last_review=today,
        lapses=lapses,
        suspended=progress.suspended,
    )
    event = ReviewEvent(
        event_id=event_id or stable_id("evt", progress.card_id, today, grade, repetitions),
        session_id=session_id or "standalone",
        card_id=progress.card_id,
        topic_id="",
        grade=grade,
        correct=grade in ("good", "easy"),
        reviewed_at=f"{today}T00:00:00",
        due_before=due_before,
        due_after=due_after,
        ease_after=updated.ease,
        duration_seconds=max(0, int(duration_seconds)),
    )
    return updated, event


def select_session_cards(
    cards: Sequence[Flashcard],
    progress: Mapping[str, CardProgress],
    *,
    today: str,
    limit: int = 20,
    mode: str = "quick",
    weak_topic_ids: Iterable[str] = (),
) -> list[Flashcard]:
    """Select due cards then new cards in a deterministic order."""
    if mode not in MODES:
        raise InputError(f"Mode inconnu : {mode}.")
    if limit <= 0:
        return []
    parse_date(today)
    weak = set(weak_topic_ids)
    active = [card for card in cards if card.status == "active"]
    due: list[tuple[str, str, str, Flashcard]] = []
    new: list[tuple[str, str, Flashcard]] = []
    for card in active:
        item = progress.get(card.id)
        if item is not None:
            if item.suspended:
                continue
            if item.due_date and item.due_date <= today:
                due.append((item.due_date, card.topic_id, card.id, card))
        else:
            new.append((card.topic_id, card.id, card))
    due.sort(key=lambda item: (item[0], item[1], item[2]))
    new.sort(key=lambda item: (item[0], item[1]))

    if mode == "exam_eve":
        weak_due = [item for item in due if item[3].topic_id in weak]
        other_due = [item for item in due if item[3].topic_id not in weak]
        weak_new = [item for item in new if item[2].topic_id in weak]
        other_new = [item for item in new if item[2].topic_id not in weak]
        ordered = weak_due + other_due + weak_new + other_new
        return [item[-1] for item in ordered[:limit]]

    ordered_cards = [item[-1] for item in due] + [item[-1] for item in new]
    return ordered_cards[:limit]


def _weak_topic_ids(reviews: Sequence[ReviewEvent]) -> list[str]:
    stats: dict[str, list[bool]] = defaultdict(list)
    for event in reviews:
        if event.topic_id:
            stats[event.topic_id].append(event.correct)
    weak: list[str] = []
    for topic_id, results in sorted(stats.items()):
        if len(results) >= 3 and sum(results) / len(results) < 0.6:
            weak.append(topic_id)
    return weak


def _limit_for(minutes: int, mode: str) -> int:
    if minutes <= 0:
        raise InputError("La durée doit être positive.")
    if mode == "quick":
        return max(5, min(20, minutes * 2))
    if mode == "long":
        return max(10, min(60, minutes * 2))
    if mode == "exam_eve":
        return max(5, min(30, minutes * 2))
    return max(1, min(100, minutes * 2))


def start_session(
    store: VcStore,
    content,
    *,
    minutes: int = 10,
    mode: str = "quick",
    today: str | None = None,
) -> ReviewSession:
    active = store.load_active_session()
    if active is not None and active.status == "active":
        return active
    if mode not in MODES:
        raise InputError(f"Mode inconnu : {mode}.")
    day = today or today_iso()
    parse_date(day)
    progress = store.load_progress()
    reviews = store.load_reviews()
    weak = _weak_topic_ids(reviews) if mode == "exam_eve" else []
    cards = select_session_cards(
        content.cards,
        progress,
        today=day,
        limit=_limit_for(minutes, mode),
        mode=mode,
        weak_topic_ids=weak,
    )
    session = ReviewSession(
        session_id=new_id("ses"),
        mode=mode,
        started_at=now_iso(),
        target_minutes=minutes,
        today=day,
        card_ids=[card.id for card in cards],
    )
    store.save_active_session(session)
    return session


def resume_session(store: VcStore) -> ReviewSession | None:
    return store.load_active_session()


def current_card(store: VcStore, content, session: ReviewSession) -> Flashcard | None:
    if session.cursor >= len(session.card_ids):
        return None
    return content.card(session.card_ids[session.cursor])


def card_reason(progress: CardProgress | None, today: str) -> str:
    if progress is None:
        return "nouvelle carte"
    if progress.last_grade == "again":
        return "carte à revoir après un oubli"
    if progress.last_grade == "hard":
        return "carte difficile à consolider"
    if progress.due_date and progress.due_date <= today:
        return "carte due"
    return "révision programmée"


def answer_session(
    store: VcStore,
    content,
    session: ReviewSession,
    grade: str,
    *,
    duration_seconds: int = 0,
) -> tuple[ReviewSession, ReviewEvent]:
    if session.status != "active":
        raise InputError("Cette session est déjà terminée.")
    if session.cursor >= len(session.card_ids):
        raise InputError("Aucune carte à noter dans cette session.")
    card = content.card(session.card_ids[session.cursor])
    progress = store.load_progress()
    current = progress.get(card.id) or CardProgress(card_id=card.id, due_date=session.today)
    updated, event = grade_card(
        current,
        grade,
        session.today,
        event_id=new_id("evt"),
        session_id=session.session_id,
        duration_seconds=duration_seconds,
    )
    event = ReviewEvent(
        event_id=event.event_id,
        session_id=event.session_id,
        card_id=event.card_id,
        topic_id=card.topic_id,
        grade=event.grade,
        correct=event.correct,
        reviewed_at=event.reviewed_at,
        due_before=event.due_before,
        due_after=event.due_after,
        ease_after=event.ease_after,
        duration_seconds=event.duration_seconds,
    )
    progress[card.id] = updated
    store.save_progress(progress)
    store.append_review(event)
    session.answered.append(event)
    session.cursor += 1
    if session.cursor >= len(session.card_ids):
        session.status = "completed"
        session.completed_at = now_iso()
        store.append_session_history(session_summary(session))
        store.clear_active_session()
    else:
        store.save_active_session(session)
    return session, event


def abandon_session(store: VcStore, session: ReviewSession) -> ReviewSession:
    if session.status == "active":
        session.status = "abandoned"
        session.completed_at = now_iso()
        store.append_session_history(session_summary(session))
        store.clear_active_session()
    return session


def session_summary(session: ReviewSession) -> dict:
    seen = len(session.answered)
    correct = sum(1 for event in session.answered if event.correct)
    topics: dict[str, dict[str, int]] = {}
    due_tomorrow = 0
    tomorrow = add_days(session.today, 1)
    for event in session.answered:
        bucket = topics.setdefault(event.topic_id, {"seen": 0, "correct": 0})
        bucket["seen"] += 1
        if event.correct:
            bucket["correct"] += 1
        if event.due_after == tomorrow:
            due_tomorrow += 1
    return {
        "session_id": session.session_id,
        "mode": session.mode,
        "status": session.status,
        "total": len(session.card_ids),
        "done": session.cursor,
        "seen": seen,
        "correct": correct,
        "to_consolidate": seen - correct,
        "minutes": round(sum(event.duration_seconds for event in session.answered) / 60, 1),
        "due_tomorrow": due_tomorrow,
        "topics": topics,
    }


def due_cards(progress: Mapping[str, CardProgress], today: str) -> int:
    parse_date(today)
    return sum(
        1
        for item in progress.values()
        if not item.suspended and item.due_date and item.due_date <= today
    )


def session_status(session: ReviewSession, content) -> dict:
    card = current_card_from_ids(session, content)
    return {
        "session_id": session.session_id,
        "mode": session.mode,
        "status": session.status,
        "cursor": session.cursor,
        "total": len(session.card_ids),
        "done": len(session.answered),
        "current": None if card is None else _card_payload(card, session.today, None),
        "summary": session_summary(session) if session.status != "active" else None,
    }


def current_card_from_ids(session: ReviewSession, content) -> Flashcard | None:
    if session.cursor >= len(session.card_ids):
        return None
    return content.card(session.card_ids[session.cursor])


def _card_payload(card: Flashcard, today: str, progress: CardProgress | None) -> dict:
    return {
        "card_id": card.id,
        "topic_id": card.topic_id,
        "question": card.question,
        "due_date": progress.due_date if progress else today,
        "reason": card_reason(progress, today),
    }


def session_payload(
    session: ReviewSession,
    content,
    progress: Mapping[str, CardProgress] | None = None,
    *,
    reveal: bool = False,
) -> dict:
    card = current_card_from_ids(session, content)
    payload = {
        "session_id": session.session_id,
        "mode": session.mode,
        "target_minutes": session.target_minutes,
        "cursor": session.cursor,
        "total": len(session.card_ids),
        "done": len(session.answered),
        "current": None,
        "summary": None,
    }
    if card is not None:
        item = _card_payload(card, session.today, (progress or {}).get(card.id))
        if reveal:
            item["answer"] = card.answer
            item["explanation"] = card.explanation
        payload["current"] = item
    else:
        payload["summary"] = session_summary(session)
    return payload
