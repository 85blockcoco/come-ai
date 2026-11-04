"""Dataclasses shared by the VC revision coach.

The models are deliberately small and serializable.  Content is immutable
(frozen dataclasses); learner state is mutable and persisted by ``VcStore``.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field, fields
from typing import Any


GRADES = ("again", "hard", "good", "easy")
CARD_STATUSES = ("proposed", "active", "rejected", "a_completer", "suspended")
UNITS = ("eur", "k_eur", "m_eur", "dollars", "millions of dollars", "percent", "ratio", "years", "shares", "months", "scenario", "percent of loan")
ERROR_CATEGORIES = ("formula", "order", "unit", "missing_data", "convention")


def _filtered(cls: type, payload: dict[str, Any]) -> dict[str, Any]:
    names = {item.name for item in fields(cls)}
    return {key: value for key, value in payload.items() if key in names}


@dataclass(frozen=True)
class CourseTopic:
    id: str
    code: str
    title_fr: str
    title_en: str
    order: int
    exam_weight: float
    description: str = ""
    prerequisites: tuple[str, ...] = ()

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "CourseTopic":
        data = _filtered(cls, payload)
        data["prerequisites"] = tuple(data.get("prerequisites") or ())
        return cls(**data)


@dataclass(frozen=True)
class Concept:
    id: str
    topic_id: str
    term_fr: str
    term_en: str
    definition: str
    source_type: str = "original"
    citation: dict[str, str] | None = None


@dataclass
class Flashcard:
    id: str
    topic_id: str
    question: str
    answer: str
    explanation: str = ""
    source_type: str = "original"
    citation: dict[str, str] | None = None
    status: str = "active"
    version: int = 1
    tags: tuple[str, ...] = ()

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "Flashcard":
        data = _filtered(cls, payload)
        data["tags"] = tuple(data.get("tags") or ())
        return cls(**data)

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["tags"] = list(self.tags)
        return data


@dataclass
class CardProgress:
    card_id: str
    ease: float = 2.5
    interval_days: int = 0
    repetitions: int = 0
    due_date: str = ""
    last_grade: str = ""
    last_review: str = ""
    lapses: int = 0
    suspended: bool = False

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "CardProgress":
        return cls(**_filtered(cls, payload))

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class ReviewEvent:
    event_id: str
    session_id: str
    card_id: str
    topic_id: str
    grade: str
    correct: bool
    reviewed_at: str
    due_before: str
    due_after: str
    ease_after: float
    duration_seconds: int = 0

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "ReviewEvent":
        return cls(**_filtered(cls, payload))

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class ReviewSession:
    session_id: str
    mode: str
    started_at: str
    target_minutes: int
    today: str
    card_ids: list[str] = field(default_factory=list)
    cursor: int = 0
    answered: list[ReviewEvent] = field(default_factory=list)
    status: str = "active"
    completed_at: str = ""

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "ReviewSession":
        data = _filtered(cls, payload)
        data["answered"] = [ReviewEvent.from_dict(item) for item in data.get("answered") or ()]
        data["card_ids"] = list(data.get("card_ids") or ())
        return cls(**data)

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["answered"] = [item.to_dict() for item in self.answered]
        return data


@dataclass(frozen=True)
class FormulaDrill:
    id: str
    topic_id: str
    prompt: str
    variables: dict[str, Any]
    answer: float
    answer_unit: str
    tolerance: float
    steps: tuple[dict[str, Any], ...]
    error_paths: tuple[dict[str, Any], ...] = ()
    alternative_conventions: tuple[dict[str, Any], ...] = ()
    difficulty: int = 1
    notice: str = "Synthetic practice exercise."

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "FormulaDrill":
        data = _filtered(cls, payload)
        data["steps"] = tuple(data.get("steps") or ())
        data["error_paths"] = tuple(data.get("error_paths") or ())
        data["alternative_conventions"] = tuple(data.get("alternative_conventions") or ())
        return cls(**data)


@dataclass(frozen=True)
class CaseCriterion:
    id: str
    label: str
    weight: float
    required_keywords: tuple[str, ...] = ()
    any_keywords: tuple[str, ...] = ()
    expected_numbers: tuple[dict[str, float], ...] = ()
    model_answer: str = ""

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "CaseCriterion":
        data = _filtered(cls, payload)
        data["required_keywords"] = tuple(data.get("required_keywords") or ())
        data["any_keywords"] = tuple(data.get("any_keywords") or ())
        data["expected_numbers"] = tuple(data.get("expected_numbers") or ())
        return cls(**data)


@dataclass(frozen=True)
class CaseQuestion:
    id: str
    prompt: str
    criteria: tuple[CaseCriterion, ...]

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "CaseQuestion":
        data = _filtered(cls, payload)
        data["criteria"] = tuple(CaseCriterion.from_dict(item) for item in data.get("criteria") or ())
        return cls(**data)


@dataclass(frozen=True)
class CaseStudy:
    id: str
    topic_id: str
    title: str
    context: str
    facts: tuple[dict[str, Any], ...]
    questions: tuple[CaseQuestion, ...]
    model_answer: str
    allowed_numbers: tuple[float, ...]
    difficulty: int = 1
    source_type: str = "course_grounded"
    source_ref: str = ""

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "CaseStudy":
        data = _filtered(cls, payload)
        data["facts"] = tuple(data.get("facts") or ())
        data["questions"] = tuple(CaseQuestion.from_dict(item) for item in data.get("questions") or ())
        data["allowed_numbers"] = tuple(float(item) for item in data.get("allowed_numbers") or ())
        return cls(**data)


@dataclass
class CaseAttempt:
    attempt_id: str
    case_id: str
    answers: dict[str, str]
    criteria_results: list[dict[str, Any]]
    score: float
    unsupported_numbers: list[float]
    submitted_at: str
    penalty: float = 0.0
    model_answer: str = ""
    notice: str = "Criterion-based grading, not a human grade."

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "CaseAttempt":
        return cls(**_filtered(cls, payload))

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class DrillAttempt:
    """One answered formula drill, kept outside the SM-2 schedule."""

    attempt_id: str
    drill_id: str
    topic_id: str
    answer: str
    accepted: bool
    expected: float
    expected_unit: str
    given_value: float | None
    diagnostic: str | None
    submitted_at: str
    message: str = ""

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "DrillAttempt":
        return cls(**_filtered(cls, payload))

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class PaperAttempt:
    """One past-paper submission, stored per topic for the mastery radar."""

    attempt_id: str
    paper_id: str
    year: int
    submitted_at: str
    auto_points: float
    auto_max: float
    auto_percent: float | None
    per_topic: dict[str, dict[str, float]]
    self_assessment_points: float = 0.0
    notice: str = "Auto-graded items only; open questions are self-assessed."

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "PaperAttempt":
        return cls(**_filtered(cls, payload))

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class ExamQuestion:
    id: str
    topic_id: str
    question: str
    answer: str
    points: int
    format: str = "open"
    choices: tuple[str, ...] = ()
    keywords: tuple[str, ...] = ()
    min_keywords: int = 0
    unit: str = "eur"
    tolerance: float = 0.0
    source_card_id: str = ""

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "ExamQuestion":
        data = _filtered(cls, payload)
        data["choices"] = tuple(data.get("choices") or ())
        data["keywords"] = tuple(data.get("keywords") or ())
        return cls(**data)


@dataclass
class ExamSession:
    exam_id: str
    seed: int
    questions: list[dict[str, Any]]
    started_at: str
    duration_minutes: int
    answers: dict[str, str] = field(default_factory=dict)
    score: float | None = None
    per_topic: dict[str, Any] = field(default_factory=dict)
    status: str = "active"
    submitted_at: str = ""

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "ExamSession":
        return cls(**_filtered(cls, payload))

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class MasteryRecord:
    topic_id: str
    title: str
    attempts: int
    correct: int
    accuracy: float | None
    last_activity: str
    status: str
    due_cards: int
    top_errors: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class StudyPlan:
    date: str
    capacity_minutes: int
    activities: list[dict[str, Any]]
    total_minutes: int
    exam_date: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class NoteSource:
    source_id: str
    filename: str
    kind: str
    imported_at: str
    sha256: str
    line_count: int
    status: str = "imported"

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "NoteSource":
        return cls(**_filtered(cls, payload))

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class ProposedCard:
    proposal_id: str
    source_id: str
    topic_id: str
    question: str
    answer: str | None
    citation: dict[str, str]
    status: str = "proposed"

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "ProposedCard":
        return cls(**_filtered(cls, payload))

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class GlossaryEntry:
    term_fr: str
    term_en: str
    definition: str
    topic_id: str
    example: str = ""
    source_type: str = "original"

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "GlossaryEntry":
        return cls(**_filtered(cls, payload))


@dataclass
class ProgressReport:
    generated_at: str
    period_start: str
    period_end: str
    coverage: dict[str, Any]
    retention: dict[str, Any]
    due_cards: int
    weak_topics: list[dict[str, Any]]
    recent_errors: list[dict[str, Any]]
    next_actions: list[dict[str, Any]]
    markdown_path: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
