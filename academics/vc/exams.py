"""Deterministic mock exams, transparent grading and oral rehearsal."""

from __future__ import annotations

import random
import re
from datetime import datetime, timedelta
from typing import Any, Iterable, Sequence

from .cases import normalize_text
from .dates import new_id, now_iso
from .drills import normalize_to_unit, parse_number
from .errors import ContentError, InputError
from .models import ExamQuestion, ExamSession
from .storage import VcStore

NOTICE = "Correction déterministe, pas une note humaine."
PASS_THRESHOLD = 0.6

_TOPIC_FOLLOW_UPS: dict[str, tuple[str, ...]] = {
    "VC04": (
        "Refaites le calcul en distinguant explicitement pre-money et post-money.",
        "Que devient la part de l'investisseur si le montant levé double à pre-money constant ?",
        "Quelle erreur d'unité ou de base de calcul faut-il éviter ?",
    ),
    "VC05": (
        "Décrivez la cap table avant et après le tour, ligne par ligne.",
        "Pourquoi l'option pool est-il souvent créé avant l'entrée de l'investisseur ?",
        "Quelle différence faites-vous entre actions émises et fully diluted ?",
    ),
    "VC07": (
        "Déroulez le waterfall rang par rang et justifiez l'ordre.",
        "Quand l'investisseur préfère-t-il convertir en actions ordinaires ?",
        "Quel est l'effet d'un cap sur une préférence participating ?",
    ),
    "VC09": (
        "Distinguez le multiple brut du rendement annualisé.",
        "Quel flux faut-il actualiser pour calculer l'IRR ?",
        "Pourquoi un même MOIC peut-il cacher des IRR très différents ?",
    ),
}
_GENERIC_FOLLOW_UPS = (
    "Définissez les termes clés sans regarder vos notes.",
    "Donnez un exemple chiffré et explicitez chaque étape.",
    "Quelle erreur fréquente faut-il éviter sur cette notion ?",
    "Reliez cette notion à un term sheet ou à une décision d'investissement.",
)


def _compact(value: str) -> str:
    return re.sub(r"\s+", "", normalize_text(str(value)))


def _keyword_present(normalized: str, keyword: str) -> bool:
    needle = normalize_text(keyword)
    if not needle:
        return False
    if len(needle) <= 2:
        return re.search(rf"\b{re.escape(needle)}\b", normalized) is not None
    return needle in normalized


def _parse_clock(value: datetime | str | None) -> datetime:
    if value is None:
        return datetime.now().replace(microsecond=0)
    if isinstance(value, datetime):
        return value.replace(microsecond=0)
    try:
        return datetime.fromisoformat(str(value)).replace(microsecond=0)
    except ValueError as error:
        raise InputError(f"Horodatage invalide : {value!r}") from error


def _allocate_points(questions: Sequence[ExamQuestion]) -> list[int]:
    """Give every question at least one point and make the total exactly 100."""
    count = len(questions)
    if count > 100:
        raise InputError("Un examen ne peut pas dépasser 100 questions.")
    remaining = 100 - count
    total_weight = sum(max(1, question.points) for question in questions)
    raw = [max(1, question.points) / total_weight * remaining for question in questions]
    extras = [int(value) for value in raw]
    left = remaining - sum(extras)
    order = sorted(
        range(count),
        key=lambda index: (-(raw[index] - extras[index]), questions[index].id),
    )
    for index in order[:left]:
        extras[index] += 1
    return [1 + extra for extra in extras]


def build_exam(
    content,
    *,
    questions: int = 20,
    minutes: int = 30,
    seed: int = 0,
    topic_ids: Sequence[str] = (),
    suspended_card_ids: Iterable[str] = (),
    started_at: str | None = None,
) -> ExamSession:
    """Compose a deterministic exam from the original question bank."""
    if isinstance(questions, bool) or not isinstance(questions, int):
        raise InputError("Le nombre de questions doit être un entier.")
    if not 1 <= questions <= 100:
        raise InputError("Le nombre de questions doit être compris entre 1 et 100.")
    if isinstance(minutes, bool) or not isinstance(minutes, int) or minutes <= 0:
        raise InputError("La durée doit être un nombre de minutes positif.")
    selected_topics = sorted({str(topic_id) for topic_id in topic_ids})
    for topic_id in selected_topics:
        try:
            content.topic(topic_id)
        except ContentError as error:
            raise InputError(f"Topic inconnu : {topic_id}") from error
    suspended = {str(card_id) for card_id in suspended_card_ids}
    eligible = [
        question
        for question in content.exams
        if (not selected_topics or question.topic_id in selected_topics)
        and question.source_card_id not in suspended
    ]
    if len(eligible) < questions:
        raise InputError(
            f"Pas assez de questions disponibles : {len(eligible)} pour {questions} demandées."
        )
    eligible.sort(key=lambda question: question.id)
    random.Random(seed).shuffle(eligible)
    selected = eligible[:questions]
    points = _allocate_points(selected)
    refs = [
        {"kind": "exam_question", "ref_id": question.id, "points": point}
        for question, point in zip(selected, points)
    ]
    return ExamSession(
        exam_id=new_id("exam"),
        seed=seed,
        questions=refs,
        started_at=started_at or now_iso(),
        duration_minutes=minutes,
    )


def exam_deadline(exam: ExamSession) -> datetime:
    started = _parse_clock(exam.started_at)
    return started + timedelta(minutes=exam.duration_minutes)


def is_expired(exam: ExamSession, *, now: datetime | str | None = None) -> bool:
    return _parse_clock(now) >= exam_deadline(exam)


def remaining_seconds(exam: ExamSession, *, now: datetime | str | None = None) -> int:
    seconds = int((exam_deadline(exam) - _parse_clock(now)).total_seconds())
    return max(0, seconds)


def _mcq_result(question: ExamQuestion, raw: str) -> tuple[bool, dict[str, Any]]:
    text = raw.strip()
    if not text:
        return False, {"matched_choice": None}
    letters = "ABCD"
    upper = text.upper()
    if len(upper) == 1 and upper in letters[: len(question.choices)]:
        chosen = question.choices[letters.index(upper)]
        return _compact(chosen) == _compact(question.answer), {"matched_choice": chosen}
    expected = _compact(question.answer)
    return _compact(text) == expected, {"matched_choice": text}


def _numeric_result(question: ExamQuestion, raw: str) -> tuple[bool, dict[str, Any]]:
    try:
        value, unit = parse_number(raw, question.unit)
        expected, expected_unit = parse_number(question.answer, question.unit)
        normalized = normalize_to_unit(value, unit, expected_unit)
    except ValueError:
        return False, {"parsed": None}
    tolerance = max(0.0, float(question.tolerance)) + abs(expected) * 1e-6
    correct = abs(normalized - expected) <= tolerance
    if (
        not correct
        and expected_unit == "percent"
        and "%" not in raw
        and abs(value) <= 1
        and abs(expected) > 1
    ):
        correct = abs(value * 100 - expected) <= tolerance
    return correct, {
        "parsed": {"value": value, "unit": unit, "normalized": round(normalized, 6)},
        "expected": {"value": expected, "unit": expected_unit},
    }


def _open_result(question: ExamQuestion, raw: str) -> tuple[bool, dict[str, Any]]:
    normalized = normalize_text(raw)
    matched = [
        keyword for keyword in question.keywords if _keyword_present(normalized, keyword)
    ]
    return len(matched) >= question.min_keywords, {
        "matched_keywords": matched,
        "required_keywords": question.min_keywords,
    }


def _grade_question(
    question: ExamQuestion, raw: str
) -> tuple[bool, dict[str, Any]]:
    if question.format == "mcq":
        return _mcq_result(question, raw)
    if question.format == "numeric":
        return _numeric_result(question, raw)
    return _open_result(question, raw)


def _remediation(content, weak_topics: Sequence[str], scores: dict[str, float]) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for topic_id in weak_topics:
        cards = [card.id for card in content.cards if card.topic_id == topic_id][:3]
        drills = [drill.id for drill in content.drills if drill.topic_id == topic_id][:2]
        cases = [case.id for case in content.cases if case.topic_id == topic_id][:1]
        result.append(
            {
                "topic_id": topic_id,
                "cards": cards,
                "drills": drills,
                "case_id": cases[0] if cases else None,
                "reason": f"score {scores.get(topic_id, 0.0):.0%} < {PASS_THRESHOLD:.0%}",
            }
        )
    return result


def grade_exam(
    exam: ExamSession,
    content,
    *,
    now: datetime | str | None = None,
) -> dict[str, Any]:
    """Grade stored answers, mutate the session and return a transparent summary."""
    submitted = _parse_clock(now)
    started = _parse_clock(exam.started_at)
    expired = submitted >= started + timedelta(minutes=exam.duration_minutes)
    known_ids = {str(ref.get("ref_id")) for ref in exam.questions}
    unmatched = sorted(str(key) for key in exam.answers if str(key) not in known_ids)
    details: list[dict[str, Any]] = []
    per_topic: dict[str, dict[str, Any]] = {}
    earned_total = 0
    points_total = 0
    answered = 0
    for ref in exam.questions:
        question = content.exam_question(str(ref.get("ref_id")))
        points = int(ref.get("points", 0))
        raw = str(exam.answers.get(question.id, "") or "")
        is_answered = bool(raw.strip())
        answered += 1 if is_answered else 0
        correct, info = _grade_question(question, raw)
        earned = points if correct else 0
        earned_total += earned
        points_total += points
        bucket = per_topic.setdefault(
            question.topic_id,
            {"attempts": 0, "correct": 0, "earned": 0, "max": 0},
        )
        bucket["attempts"] += 1
        bucket["correct"] += 1 if correct else 0
        bucket["earned"] += earned
        bucket["max"] += points
        details.append(
            {
                "question_id": question.id,
                "topic_id": question.topic_id,
                "format": question.format,
                "points": points,
                "earned": earned,
                "correct": correct,
                "answered": is_answered,
                "expected_answer": question.answer,
                **info,
            }
        )
    for bucket in per_topic.values():
        bucket["score"] = (
            round(bucket["earned"] / bucket["max"], 4) if bucket["max"] else 0.0
        )
    weak_topics = sorted(
        (topic_id for topic_id, bucket in per_topic.items() if bucket["score"] < PASS_THRESHOLD),
        key=lambda topic_id: content.topic(topic_id).order,
    )
    scores = {topic_id: bucket["score"] for topic_id, bucket in per_topic.items()}
    score = round(earned_total / points_total, 4) if points_total else 0.0
    submitted_at = submitted.isoformat()
    elapsed_seconds = max(0, int((submitted - started).total_seconds()))
    exam.answers = {str(key): str(value) for key, value in exam.answers.items()}
    exam.score = score
    exam.per_topic = per_topic
    exam.status = "expired" if expired or exam.status == "expired" else "submitted"
    exam.submitted_at = submitted_at
    return {
        "exam_id": exam.exam_id,
        "seed": exam.seed,
        "status": exam.status,
        "expired": exam.status == "expired",
        "score": score,
        "points_earned": earned_total,
        "points_total": points_total,
        "answered": answered,
        "total_questions": len(exam.questions),
        "duration_minutes": exam.duration_minutes,
        "started_at": exam.started_at,
        "submitted_at": submitted_at,
        "elapsed_seconds": elapsed_seconds,
        "elapsed_minutes": round(elapsed_seconds / 60, 2),
        "per_topic": per_topic,
        "weak_topics": weak_topics,
        "remediation": _remediation(content, weak_topics, scores),
        "details": details,
        "unmatched_answers": unmatched,
        "notice": NOTICE,
    }


def history_entry(result: dict[str, Any]) -> dict[str, Any]:
    """Keep the durable history small while preserving mastery inputs."""
    keys = (
        "exam_id",
        "seed",
        "status",
        "score",
        "points_earned",
        "points_total",
        "answered",
        "total_questions",
        "duration_minutes",
        "started_at",
        "submitted_at",
        "elapsed_seconds",
        "per_topic",
        "weak_topics",
    )
    return {key: result.get(key) for key in keys}


def record_exam_result(store: VcStore, result: dict[str, Any]) -> None:
    """Persist the durable summary and close the active exam atomically."""
    store.append_exam_history(history_entry(result))
    store.clear_active_exam()


def exam_payload(exam: ExamSession, content, *, now: datetime | str | None = None) -> dict[str, Any]:
    """Return the active exam without answers or model corrections."""
    questions: list[dict[str, Any]] = []
    for ref in exam.questions:
        question = content.exam_question(str(ref.get("ref_id")))
        item = {
            "question_id": question.id,
            "topic_id": question.topic_id,
            "question": question.question,
            "format": question.format,
            "points": int(ref.get("points", 0)),
        }
        if question.choices:
            item["choices"] = list(question.choices)
        questions.append(item)
    return {
        "exam_id": exam.exam_id,
        "seed": exam.seed,
        "status": exam.status,
        "started_at": exam.started_at,
        "deadline": exam_deadline(exam).isoformat(),
        "duration_minutes": exam.duration_minutes,
        "remaining_seconds": remaining_seconds(exam, now=now),
        "expired": is_expired(exam, now=now),
        "total_questions": len(questions),
        "total_points": sum(item["points"] for item in questions),
        "answered": len(exam.answers),
        "questions": questions,
    }


def oral_questions(
    content,
    topic_id: str,
    count: int = 5,
    *,
    excluded_card_ids: Iterable[str] = (),
) -> list[dict[str, Any]]:
    """Build oral prompts and targeted follow-ups without revealing answers."""
    try:
        content.topic(topic_id)
    except ContentError as error:
        raise InputError(f"Topic inconnu : {topic_id}") from error
    if isinstance(count, bool) or not isinstance(count, int) or not 1 <= count <= 20:
        raise InputError("Le nombre de questions orales doit être compris entre 1 et 20.")
    excluded = {str(card_id) for card_id in excluded_card_ids}
    cards = [
        card
        for card in content.cards
        if card.topic_id == topic_id and card.status == "active" and card.id not in excluded
    ]
    cards.sort(key=lambda card: card.id)
    if not cards:
        raise InputError(f"Aucune carte active pour le topic {topic_id}.")
    follow_ups = _TOPIC_FOLLOW_UPS.get(topic_id, _GENERIC_FOLLOW_UPS)
    result: list[dict[str, Any]] = []
    for index, card in enumerate(cards[:count]):
        selected = [
            follow_ups[(index + offset) % len(follow_ups)] for offset in range(2)
        ]
        result.append(
            {
                "question_id": card.id,
                "topic_id": card.topic_id,
                "prompt": card.question,
                "follow_ups": selected,
            }
        )
    return result
