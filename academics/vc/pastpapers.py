"""Past EDHEC exam papers: load, present and grade.

The bank is a *derived* study pack.  Questions are condensed and paraphrased
from the course past papers; every numerical answer and every worked solution
is reproduced so the learner can check the method, not just the result.

The module is deliberately independent from the generic mock-exam engine:
past papers have real sections, multi-part cases and open questions, which the
generic ``ExamQuestion`` model does not represent well.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable

from .content import CONTENT_DIR
from .drills import normalize_to_unit, parse_number
from .errors import ContentError, InputError

PAPER_SCHEMA_VERSION = 1
PAPER_KINDS = ("mcq", "numeric", "open", "case")
PART_KINDS = ("numeric", "open")
LETTERS = ("A", "B", "C", "D", "E", "F")


def _as_float(value: Any, label: str) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError) as error:
        raise ContentError(f"{label} must be a number.") from error
    if number != number or number in (float("inf"), float("-inf")):
        raise ContentError(f"{label} must be a finite number.")
    return number


@dataclass(frozen=True)
class PaperChoice:
    label: str
    text: str

    @classmethod
    def from_dict(cls, payload: dict[str, Any], label: str) -> "PaperChoice":
        if not isinstance(payload, dict):
            raise ContentError(f"Choix {label} invalide.")
        return cls(label=label, text=str(payload.get("text", "")).strip())


@dataclass(frozen=True)
class PaperPart:
    id: str
    prompt: str
    kind: str
    points: float
    answer: str = ""
    unit: str = "ratio"
    tolerance: float = 0.0
    solution: str = ""

    @classmethod
    def from_dict(cls, payload: dict[str, Any], question_id: str, index: int) -> "PaperPart":
        if not isinstance(payload, dict):
            raise ContentError(f"Partie {index} invalide dans {question_id}.")
        part_id = str(payload.get("id") or f"{question_id}-{index}").strip()
        kind = str(payload.get("kind") or "open").strip()
        if kind not in PART_KINDS:
            raise ContentError(f"Unsupported part type in {part_id}: {kind!r}.")
        points = _as_float(payload.get("points", 0), f"Points de {part_id}")
        if points < 0:
            raise ContentError(f"Negative points in {part_id}.")
        unit = str(payload.get("unit") or "ratio")
        tolerance = _as_float(payload.get("tolerance", 0), f"Tolerance of {part_id}")
        return cls(
            id=part_id,
            prompt=str(payload.get("prompt", "")).strip(),
            kind=kind,
            points=points,
            answer="" if payload.get("answer") is None else str(payload["answer"]).strip(),
            unit=unit,
            tolerance=tolerance,
            solution=str(payload.get("solution", "")).strip(),
        )


@dataclass(frozen=True)
class PaperQuestion:
    id: str
    number: int
    section: str
    points: float
    kind: str
    topic_id: str
    prompt: str
    choices: tuple[PaperChoice, ...] = ()
    answer: str = ""
    unit: str = "ratio"
    tolerance: float = 0.0
    solution: str = ""
    parts: tuple[PaperPart, ...] = ()

    @classmethod
    def from_dict(cls, payload: dict[str, Any], paper_id: str) -> "PaperQuestion":
        if not isinstance(payload, dict):
            raise ContentError(f"Question invalide dans {paper_id}.")
        question_id = str(payload.get("id") or "").strip()
        if not question_id:
            raise ContentError(f"Question sans identifiant dans {paper_id}.")
        kind = str(payload.get("kind") or "open").strip()
        if kind not in PAPER_KINDS:
            raise ContentError(f"Unsupported question type in {question_id}: {kind!r}.")
        try:
            number = int(payload.get("number"))
        except (TypeError, ValueError) as error:
            raise ContentError(f"Invalid number in {question_id}.") from error
        points = _as_float(payload.get("points", 0), f"Points de {question_id}")
        if points <= 0:
            raise ContentError(f"Points invalides dans {question_id}.")
        raw_choices = payload.get("choices") or []
        if not isinstance(raw_choices, list):
            raise ContentError(f"Choix invalides dans {question_id}.")
        choices = tuple(
            PaperChoice.from_dict(item, LETTERS[index])
            for index, item in enumerate(raw_choices)
        )
        raw_parts = payload.get("parts") or []
        if not isinstance(raw_parts, list):
            raise ContentError(f"Parties invalides dans {question_id}.")
        parts = tuple(
            PaperPart.from_dict(item, question_id, index)
            for index, item in enumerate(raw_parts, start=1)
        )
        answer = "" if payload.get("answer") is None else str(payload["answer"]).strip()
        question = cls(
            id=question_id,
            number=number,
            section=str(payload.get("section") or "A").strip(),
            points=points,
            kind=kind,
            topic_id=str(payload.get("topic_id") or "VC20").strip(),
            prompt=str(payload.get("prompt", "")).strip(),
            choices=choices,
            answer=answer,
            unit=str(payload.get("unit") or "ratio"),
            tolerance=_as_float(payload.get("tolerance", 0), f"Tolerance of {question_id}"),
            solution=str(payload.get("solution", "")).strip(),
            parts=parts,
        )
        _validate_question(question)
        return question


def _validate_question(question: PaperQuestion) -> None:
    if question.kind == "mcq":
        if len(question.choices) < 2:
            raise ContentError(f"{question.id} : un QCM doit avoir au moins deux choix.")
        if question.answer.strip().upper() not in {choice.label for choice in question.choices}:
            raise ContentError(f"{question.id} : the answer matches no choice.")
        if not question.solution:
            raise ContentError(f"{question.id} : missing solution.")
        return
    if question.kind == "numeric":
        if not question.answer:
            raise ContentError(f"{question.id} : missing numeric answer.")
        if not question.solution:
            raise ContentError(f"{question.id} : missing solution.")
        return
    if question.kind == "case":
        if not question.parts:
            raise ContentError(f"{question.id} : un cas doit avoir au moins une partie.")
        for part in question.parts:
            if part.kind == "numeric" and not part.answer:
                raise ContentError(f"{part.id} : missing numeric answer.")
            if not part.solution:
                raise ContentError(f"{part.id} : missing solution.")
        return
    if not question.answer and not question.parts:
        raise ContentError(f"{question.id} : missing model answer.")


@dataclass(frozen=True)
class PastPaper:
    schema_version: int
    paper_id: str
    year: int
    title: str
    duration_minutes: int
    language: str
    source: str
    sections: tuple[dict[str, Any], ...]
    questions: tuple[PaperQuestion, ...]
    notice: str = ""
    question_by_id: dict[str, PaperQuestion] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, payload: dict[str, Any], *, topic_ids: set[str]) -> "PastPaper":
        version = payload.get("schema_version")
        if version != PAPER_SCHEMA_VERSION:
            raise ContentError(
                f"Unsupported paper version: {version!r} (expected {PAPER_SCHEMA_VERSION})."
            )
        paper_id = str(payload.get("paper_id") or "").strip()
        if not paper_id:
            raise ContentError("Sujet sans identifiant.")
        try:
            year = int(payload.get("year"))
        except (TypeError, ValueError) as error:
            raise ContentError(f"Invalid year in {paper_id}.") from error
        try:
            duration = int(payload.get("duration_minutes", 90))
        except (TypeError, ValueError) as error:
            raise ContentError(f"Invalid duration in {paper_id}.") from error
        raw_sections = payload.get("sections") or []
        if not isinstance(raw_sections, list) or not raw_sections:
            raise ContentError(f"Sections manquantes dans {paper_id}.")
        sections: list[dict[str, Any]] = []
        for index, item in enumerate(raw_sections):
            if not isinstance(item, dict):
                raise ContentError(f"Section {index} invalide dans {paper_id}.")
            section_id = str(item.get("id") or "").strip()
            if not section_id:
                raise ContentError(f"Section sans identifiant dans {paper_id}.")
            sections.append(
                {
                    "id": section_id,
                    "title": str(item.get("title", "")).strip(),
                    "points": _as_float(item.get("points", 0), f"Points de la section {section_id}"),
                }
            )
        raw_questions = payload.get("questions") or []
        if not isinstance(raw_questions, list) or not raw_questions:
            raise ContentError(f"Questions manquantes dans {paper_id}.")
        questions = tuple(PaperQuestion.from_dict(item, paper_id) for item in raw_questions)
        section_ids = {section["id"] for section in sections}
        seen_numbers: set[int] = set()
        seen_ids: set[str] = set()
        for question in questions:
            if question.section not in section_ids:
                raise ContentError(f"{question.id} : section inconnue {question.section!r}.")
            if question.number in seen_numbers:
                raise ContentError(f"{paper_id}: duplicate number {question.number}.")
            if question.id in seen_ids:
                raise ContentError(f"{paper_id}: duplicate id {question.id}.")
            if question.topic_id not in topic_ids:
                raise ContentError(f"{question.id} : topic inconnu {question.topic_id}.")
            seen_numbers.add(question.number)
            seen_ids.add(question.id)
        return cls(
            schema_version=PAPER_SCHEMA_VERSION,
            paper_id=paper_id,
            year=year,
            title=str(payload.get("title") or f"EDHEC VC {year}").strip(),
            duration_minutes=duration,
            language=str(payload.get("language") or "en").strip(),
            source=str(payload.get("source") or "").strip(),
            sections=tuple(sections),
            questions=questions,
            notice=str(payload.get("notice") or "").strip(),
            question_by_id={question.id: question for question in questions},
        )

    @property
    def points(self) -> float:
        return sum(question.points for question in self.questions)


def _topic_ids(directory: Path) -> set[str]:
    path = directory / "topics.json"
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as error:
        raise ContentError("topics.json introuvable pour valider les sujets.") from error
    except json.JSONDecodeError as error:
        raise ContentError(f"topics.json invalide : {error.msg}") from error
    topics = payload.get("topics") if isinstance(payload, dict) else None
    if not isinstance(topics, list):
        raise ContentError("topics.json doit contenir une liste 'topics'.")
    return {str(item.get("id")) for item in topics if isinstance(item, dict)}


def load_papers(directory: Path | None = None) -> tuple[PastPaper, ...]:
    base = Path(directory) if directory is not None else CONTENT_DIR
    allowed = _topic_ids(base)
    papers: list[PastPaper] = []
    for file in sorted(base.glob("paper_*.json")):
        try:
            payload = json.loads(file.read_text(encoding="utf-8"))
        except json.JSONDecodeError as error:
            raise ContentError(f"JSON invalide dans {file.name} : {error.msg}") from error
        except OSError as error:
            raise ContentError(f"Lecture impossible : {file.name}") from error
        if not isinstance(payload, dict):
            raise ContentError(f"The paper {file.name} must be a JSON object.")
        papers.append(PastPaper.from_dict(payload, topic_ids=allowed))
    if not papers:
        raise ContentError("No exam paper found.")
    papers.sort(key=lambda paper: paper.year)
    seen_years: set[int] = set()
    for paper in papers:
        if paper.year in seen_years:
            raise ContentError(f"Duplicate year: {paper.year}.")
        seen_years.add(paper.year)
    return tuple(papers)


def find_paper(year: int | str, papers: Iterable[PastPaper] | None = None) -> PastPaper:
    collection = tuple(papers) if papers is not None else load_papers()
    try:
        wanted = int(year)
    except (TypeError, ValueError) as error:
        raise InputError(f"Invalid year: {year!r}.") from error
    for paper in collection:
        if paper.year == wanted:
            return paper
    available = ", ".join(str(paper.year) for paper in collection)
    raise InputError(f"Sujet {wanted} introuvable. Disponibles : {available}.")


def paper_payload(paper: PastPaper, *, solutions: bool = False) -> dict[str, Any]:
    questions: list[dict[str, Any]] = []
    for question in paper.questions:
        item: dict[str, Any] = {
            "id": question.id,
            "number": question.number,
            "section": question.section,
            "points": question.points,
            "kind": question.kind,
            "topic_id": question.topic_id,
            "prompt": question.prompt,
            "unit": question.unit,
        }
        if question.choices:
            item["choices"] = [
                {"label": choice.label, "text": choice.text} for choice in question.choices
            ]
        if question.parts:
            item["parts"] = [
                {
                    "id": part.id,
                    "prompt": part.prompt,
                    "kind": part.kind,
                    "points": part.points,
                    "unit": part.unit,
                    **(
                        {"unit": part.unit, "answer": part.answer, "solution": part.solution}
                        if solutions
                        else {}
                    ),
                }
                for part in question.parts
            ]
        if solutions:
            item["answer"] = question.answer
            item["solution"] = question.solution
        questions.append(item)
    return {
        "paper_id": paper.paper_id,
        "year": paper.year,
        "title": paper.title,
        "duration_minutes": paper.duration_minutes,
        "language": paper.language,
        "source": paper.source,
        "notice": paper.notice,
        "sections": list(paper.sections),
        "total_points": paper.points,
        "questions": questions,
    }


def answer_template(paper: PastPaper) -> dict[str, str]:
    template: dict[str, str] = {}
    for question in paper.questions:
        if question.kind in ("mcq", "numeric"):
            template[question.id] = ""
        for part in question.parts:
            if part.kind == "numeric":
                template[part.id] = ""
    return template


def _lookup(answers: dict[str, Any], keys: Iterable[str]) -> Any:
    normalized = {str(key).strip().upper(): value for key, value in answers.items()}
    for key in keys:
        for candidate in (key, key.split("-")[-1], f"Q{key.split('-')[-1]}"):
            if candidate.strip().upper() in normalized:
                return normalized[candidate.strip().upper()]
    return None


def _normalize_letter(raw: Any) -> str:
    text = str(raw).strip().upper()
    for character in text:
        if character.isalpha():
            return character
    return text


def _grade_numeric(
    *, expected_raw: str, unit: str, tolerance: float, given_raw: Any
) -> dict[str, Any]:
    expected = float(expected_raw)
    margin = max(float(tolerance), abs(expected) * 0.01, 0.01)
    if given_raw is None or str(given_raw).strip() == "":
        return {
            "status": "missing",
            "given": None,
            "expected": expected,
            "unit": unit,
            "earned": 0.0,
            "message": "Missing answer.",
        }
    try:
        value, parsed_unit = parse_number(str(given_raw), unit)
        given = normalize_to_unit(value, parsed_unit, unit)
    except (ValueError, InputError) as error:
        return {
            "status": "incorrect",
            "given": str(given_raw),
            "expected": expected,
            "unit": unit,
            "earned": 0.0,
            "message": str(error),
        }
    correct = abs(given - expected) <= margin
    return {
        "status": "correct" if correct else "incorrect",
        "given": round(given, 6),
        "expected": expected,
        "unit": unit,
        "earned": 1.0 if correct else 0.0,
        "message": "Correct." if correct else f"Attendu {expected} {unit}.",
    }


def grade_paper(paper: PastPaper, answers: dict[str, Any]) -> dict[str, Any]:
    """Grade the auto-gradable items and expose the open items for self-review."""

    if not isinstance(answers, dict):
        raise InputError("Answers file must be a JSON object.")
    items: list[dict[str, Any]] = []
    auto_earned = 0.0
    auto_max = 0.0
    self_points = 0.0

    for question in paper.questions:
        base = {
            "question_id": question.id,
            "number": question.number,
            "section": question.section,
            "topic_id": question.topic_id,
            "kind": question.kind,
            "prompt": question.prompt,
        }
        if question.kind == "mcq":
            auto_max += question.points
            given = _lookup(answers, (question.id, str(question.number)))
            if given is None or str(given).strip() == "":
                status = "missing"
                earned = 0.0
            else:
                chosen = _normalize_letter(given)
                status = "correct" if chosen == question.answer.upper() else "incorrect"
                earned = question.points if status == "correct" else 0.0
            auto_earned += earned
            items.append(
                {
                    **base,
                    "status": status,
                    "earned": earned,
                    "max": question.points,
                    "given": None if given is None else str(given),
                    "expected": question.answer,
                    "model_answer": question.answer,
                    "solution": question.solution,
                }
            )
            continue

        if question.kind == "numeric":
            auto_max += question.points
            given = _lookup(answers, (question.id, str(question.number)))
            result = _grade_numeric(
                expected_raw=question.answer,
                unit=question.unit,
                tolerance=question.tolerance,
                given_raw=given,
            )
            earned = question.points * result["earned"]
            auto_earned += earned
            items.append(
                {
                    **base,
                    "status": result["status"],
                    "earned": earned,
                    "max": question.points,
                    "given": result["given"],
                    "expected": result["expected"],
                    "unit": result["unit"],
                    "message": result["message"],
                    "model_answer": question.answer,
                    "solution": question.solution,
                }
            )
            continue

        if question.kind == "case" and question.parts:
            for part in question.parts:
                if part.kind == "numeric":
                    auto_max += part.points
                    given = _lookup(answers, (part.id,))
                    result = _grade_numeric(
                        expected_raw=part.answer,
                        unit=part.unit,
                        tolerance=part.tolerance,
                        given_raw=given,
                    )
                    earned = part.points * result["earned"]
                    auto_earned += earned
                    items.append(
                        {
                            **base,
                            "question_id": part.id,
                            "parent_id": question.id,
                            "part_id": part.id,
                            "part_prompt": part.prompt,
                            "points": part.points,
                            "kind": "case-part",
                            "status": result["status"],
                            "earned": earned,
                            "max": part.points,
                            "given": result["given"],
                            "expected": result["expected"],
                            "unit": result["unit"],
                            "message": result["message"],
                            "model_answer": part.answer,
                            "solution": part.solution,
                        }
                    )
                else:
                    self_points += part.points
                    items.append(
                        {
                            **base,
                            "question_id": part.id,
                            "parent_id": question.id,
                            "part_id": part.id,
                            "part_prompt": part.prompt,
                            "points": part.points,
                            "kind": "case-part",
                            "status": "self_assess",
                            "earned": None,
                            "max": part.points,
                            "given": None,
                            "expected": None,
                            "model_answer": part.answer,
                            "solution": part.solution,
                        }
                    )
            continue

        self_points += question.points
        items.append(
            {
                **base,
                "status": "self_assess",
                "earned": None,
                "max": question.points,
                "given": None,
                "expected": None,
                "model_answer": question.answer,
                "solution": question.solution,
            }
        )

    percent = round(100.0 * auto_earned / auto_max, 2) if auto_max else None
    return {
        "paper_id": paper.paper_id,
        "year": paper.year,
        "title": paper.title,
        "auto_points": round(auto_earned, 2),
        "auto_max": round(auto_max, 2),
        "auto_percent": percent,
        "self_assessment_points": round(self_points, 2),
        "items": items,
        "notice": (
            "MCQs and calculations are graded automatically. "
            "Open questions and cases are self-assessed using the solution."
        ),
    }
