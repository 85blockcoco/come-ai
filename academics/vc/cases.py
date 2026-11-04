"""Original VC cases with a transparent, per-criterion rubric."""

from __future__ import annotations

import re
import unicodedata
from typing import Any, Mapping

from .dates import new_id, now_iso
from .models import CaseAttempt, CaseCriterion, CaseStudy

NUMBER_RE = re.compile(r"-?\d+(?:[.,]\d+)?")


def normalize_text(value: str) -> str:
    decomposed = unicodedata.normalize("NFKD", value)
    ascii_text = "".join(char for char in decomposed if not unicodedata.combining(char))
    return " ".join(ascii_text.lower().split())


def extract_numbers(text: str) -> list[float]:
    numbers: list[float] = []
    for raw in NUMBER_RE.findall(text):
        try:
            numbers.append(float(raw.replace(",", ".")))
        except ValueError:
            continue
    return numbers


def _contains_keyword(normalized: str, keyword: str) -> bool:
    needle = normalize_text(keyword)
    if not needle:
        return False
    if len(needle) <= 2:
        return re.search(rf"\b{re.escape(needle)}\b", normalized) is not None
    return needle in normalized


def _keywords_match(criterion: CaseCriterion, text: str) -> bool:
    normalized = normalize_text(text)
    if criterion.required_keywords:
        if not all(_contains_keyword(normalized, word) for word in criterion.required_keywords):
            return False
    if criterion.any_keywords:
        if not any(_contains_keyword(normalized, word) for word in criterion.any_keywords):
            return False
    return True


def _numbers_match(criterion: CaseCriterion, text: str) -> bool:
    if not criterion.expected_numbers:
        return True
    found = extract_numbers(text)
    for expected in criterion.expected_numbers:
        value = float(expected.get("value", 0))
        tolerance = float(expected.get("tolerance", 0)) + abs(value) * 1e-6
        if any(abs(number - value) <= tolerance for number in found):
            return True
    return False


def _allowed_numbers(case: CaseStudy) -> list[float]:
    allowed = [float(value) for value in case.allowed_numbers]
    for question in case.questions:
        for criterion in question.criteria:
            allowed.extend(float(item.get("value", 0)) for item in criterion.expected_numbers)
    return allowed


def unsupported_numbers(case: CaseStudy, text: str) -> list[float]:
    allowed = _allowed_numbers(case)
    result: list[float] = []
    for number in extract_numbers(text):
        if abs(number) <= 1:
            continue
        if any(abs(number - value) <= max(1e-6, abs(value) * 0.001) for value in allowed):
            continue
        rounded = round(number, 6)
        if rounded not in result:
            result.append(rounded)
    return result


def evaluate_case(
    case: CaseStudy,
    answers: Mapping[str, str],
    *,
    today: str | None = None,
    attempt_id: str | None = None,
) -> CaseAttempt:
    results: list[dict[str, Any]] = []
    total_weight = 0.0
    earned_weight = 0.0
    for question in case.questions:
        answer = str(answers.get(question.id, "") or "")
        for criterion in question.criteria:
            total_weight += criterion.weight
            keyword_ok = _keywords_match(criterion, answer)
            number_ok = _numbers_match(criterion, answer)
            matched = bool(answer.strip()) and keyword_ok and number_ok
            if not criterion.required_keywords and not criterion.any_keywords and not criterion.expected_numbers:
                matched = bool(answer.strip())
            earned = criterion.weight if matched else 0.0
            earned_weight += earned
            results.append(
                {
                    "question_id": question.id,
                    "criterion_id": criterion.id,
                    "label": criterion.label,
                    "earned": round(earned, 4),
                    "max": criterion.weight,
                    "matched": matched,
                    "keyword_ok": keyword_ok,
                    "number_ok": number_ok,
                    "model_answer": criterion.model_answer,
                }
            )
    raw_score = round(earned_weight / total_weight, 4) if total_weight else 0.0
    unsupported = unsupported_numbers(case, " ".join(str(value) for value in answers.values()))
    # Hardening: an invented number that is not in the case data is not a
    # rounding slip, it is a fabrication.  Each one costs a penalty weighted by
    # the heaviest criterion, so a fabricated figure cannot be hidden behind a
    # minor criterion.  The penalty is capped at 1.0.
    max_weight = max((criterion.weight for q in case.questions for criterion in q.criteria), default=0.0)
    per_number = 0.1 + 0.1 * max_weight
    penalty = min(1.0, per_number * len(unsupported))
    score = round(max(0.0, raw_score - penalty), 4)
    return CaseAttempt(
        attempt_id=attempt_id or new_id("case"),
        case_id=case.id,
        answers={str(key): str(value) for key, value in answers.items()},
        criteria_results=results,
        score=score,
        unsupported_numbers=unsupported,
        submitted_at=now_iso() if today is None else f"{today}T00:00:00",
        penalty=penalty,
        model_answer=case.model_answer,
    )


def case_payload(case: CaseStudy, *, include_model: bool = False) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "case_id": case.id,
        "topic_id": case.topic_id,
        "title": case.title,
        "context": case.context,
        "facts": [dict(fact) for fact in case.facts],
        "questions": [
            {"question_id": question.id, "prompt": question.prompt}
            for question in case.questions
        ],
        "difficulty": case.difficulty,
    }
    if include_model:
        payload["model_answer"] = case.model_answer
    return payload


def case_result_payload(attempt: CaseAttempt) -> dict[str, Any]:
    return {
        "case_id": attempt.case_id,
        "score": attempt.score,
        "penalty": attempt.penalty,
        "criteria": attempt.criteria_results,
        "unsupported_numbers": attempt.unsupported_numbers,
        "model_answer": attempt.model_answer,
        "notice": attempt.notice,
        "submitted_at": attempt.submitted_at,
    }
