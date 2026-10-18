"""Deterministic data model for the Côme AI Study Coach engine.

Every object is a plain dataclass with ``to_dict`` / ``from_dict`` so that the
engine stays storage-agnostic and exports as JSON without leaking a private
path.  Nothing here contacts a network, a model or a credential.

Vocabulary reused from the existing Côme AI contracts:

* ``SourceRef.to_citation_dict()`` mirrors the citation shape returned by
  ``personal_memory.PersonalMemoryStore.search()``:
  ``{source_id, title, page, line_start, line_end, label}``.
* Personal-memory domains already include ``ETUDES``; study facts recorded by
  the engine can therefore reuse that vocabulary when Codex wires the profile.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

# --------------------------------------------------------------------------- #
# Versions and stable vocabularies
# --------------------------------------------------------------------------- #

SCHEMA_VERSION = 1
SYLLABUS_VERSION = "heuristic-v1"
QUESTION_VERSION = "deterministic-v1"
GRADING_VERSION = "deterministic-v1"
SCHEDULE_VERSION = "ladder-v1"

QUESTION_TYPES = ("qcm", "ouverte", "definition", "numerique", "progressif")
DETERMINISTIC_TYPES = ("qcm", "definition", "numerique", "progressif")

GRADING_STATUSES = ("correct", "partiel", "incorrect", "non_evaluable")
VALIDATION_KINDS = ("deterministe", "modele_ia", "humain")
NOTION_STATUSES = ("extraite", "ambigue")
GAP_KINDS = ("information_absente", "information_ambigue")
SESSION_STATUSES = ("preparee", "en_cours", "terminee")
SESSION_MODES = ("revision_initiale", "revision_espacee")

STUDY_DOMAIN = "ETUDES"


# --------------------------------------------------------------------------- #
# Text helpers (French-tolerant, deterministic)
# --------------------------------------------------------------------------- #

_STOPWORDS = frozenset(
    """
    a au aux avec ce ces dans de des du elle en et eux il je la le les leur lui ma mais me meme mes moi
    mon ne nos notre nous on ou par pas pour qu que qui sa se ses son sur ta te tes toi ton tu un une vos
    votre vous c d j l a m n s t y ete etee etees etes etant suis es est sommes etes sont sera seront
    plus moins tout tous toute toutes autre autres ainsi cela celui celle donc alors entre selon lors
    lorsque tant fois peu tres bien suret
    the a an of and or to in for on with by is are was were be been this that these those it its as at from
    """.split()
)

_UNICODE_NUMBER_SPACES = ("\u00a0", "\u202f", "\u2009", "\u2007")


def utc_now() -> str:
    """UTC timestamp used for every stored event (sortable, timezone-aware)."""

    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def clean_text(value: Any, *, limit: int = 20_000) -> str:
    """Strip control characters and hard-limit a free-form string."""

    text = str(value if value is not None else "").replace("\x00", "")
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    return text.strip()[:limit]


def normalize_text(value: Any) -> str:
    """Lower-case, de-accent and collapse to single-spaced words."""

    text = unicodedata.normalize("NFKD", clean_text(value).lower())
    text = "".join(character for character in text if not unicodedata.combining(character))
    return re.sub(r"[^a-z0-9]+", " ", text).strip()


def tokenize(value: Any) -> list[str]:
    """Return the normalized word tokens of a value."""

    return [token for token in normalize_text(value).split(" ") if token]


def content_words(value: Any, *, limit: int = 12) -> list[str]:
    """Return meaningful tokens (stopwords and 1-letter noise removed)."""

    words = [token for token in tokenize(value) if len(token) > 2 and token not in _STOPWORDS]
    unique: list[str] = []
    for word in words:
        if word not in unique:
            unique.append(word)
        if len(unique) >= limit:
            break
    return unique


def keyword_overlap(expected: str, given: str) -> dict[str, Any]:
    """Deterministic keyword coverage used by definition grading.

    Returns the matched and missing content words plus a 0..1 ratio.  The ratio
    is a *coverage indicator*, never a grade by itself: the caller decides what
    an unmatchable answer means.
    """

    expected_words = content_words(expected, limit=40)
    given_words = set(tokenize(given))
    if not expected_words:
        return {"ratio": 0.0, "matched": [], "missing": [], "expected": []}
    matched = [word for word in expected_words if word in given_words]
    missing = [word for word in expected_words if word not in given_words]
    return {
        "ratio": round(len(matched) / len(expected_words), 4),
        "matched": matched,
        "missing": missing,
        "expected": expected_words,
    }


# --------------------------------------------------------------------------- #
# Numbers with units
# --------------------------------------------------------------------------- #

NUMBER_RE = re.compile(r"([-+]?\d[\d\s.,]*)\s*([%]|[k€m]?€|euros?|pourcents?|ans?|annees?|mois|fois|points?|unites?)?", re.IGNORECASE)

UNIT_ALIASES = {
    "€": "eur",
    "euro": "eur",
    "euros": "eur",
    "k€": "k_eur",
    "m€": "m_eur",
    "%": "pct",
    "pourcent": "pct",
    "pourcents": "pct",
    "an": "annee",
    "ans": "annee",
    "annee": "annee",
    "annees": "annee",
    "mois": "mois",
    "fois": "ratio",
    "point": "points",
    "points": "points",
    "unite": "unite",
    "unites": "unite",
}

UNIT_LABELS = {
    "eur": "€",
    "k_eur": "k€",
    "m_eur": "M€",
    "pct": "%",
    "annee": "an(s)",
    "mois": "mois",
    "ratio": "x",
    "points": "points",
    "unite": "unité(s)",
}


def to_float(raw: str) -> float | None:
    text = raw
    for space in _UNICODE_NUMBER_SPACES:
        text = text.replace(space, " ")
    text = text.strip().replace(" ", "")
    if not text:
        return None
    if "," in text and "." in text:
        # French convention: the last separator is the decimal one.
        if text.rfind(",") > text.rfind("."):
            text = text.replace(".", "").replace(",", ".")
        else:
            text = text.replace(",", "")
    elif "," in text:
        integer, _, decimals = text.partition(",")
        text = f"{integer}.{decimals}" if len(decimals) in (1, 2) else integer
    try:
        return float(text)
    except ValueError:
        return None


def canonical_unit(raw: str | None) -> str | None:
    """Map a unit alias to its canonical key, or ``None`` when unknown."""

    if not raw:
        return None
    key = re.sub(r"\s+", "", str(raw).lower())
    return UNIT_ALIASES.get(key)


def unit_family(unit: str | None) -> str | None:
    """Return the family of a canonical unit (``eur``/``k_eur`` -> ``money``)."""

    if not unit:
        return None
    if unit in {"eur", "k_eur", "m_eur"}:
        return "money"
    if unit in {"pct", "points"}:
        return "ratio"
    if unit in {"annee", "mois"}:
        return "duration"
    if unit == "ratio":
        return "multiple"
    return "count"


def unit_label(unit: str | None) -> str:
    return UNIT_LABELS.get(unit or "", "")


def parse_number(value: Any) -> dict[str, Any] | None:
    """Parse a human numeric answer such as ``"12 500 €"`` or ``"5,5 %"``.

    Returns ``{"value": float, "unit": str | None}`` or ``None`` when the value
    holds no usable number.  Ambiguous strings (several numbers) are refused so
    that grading never picks one silently.
    """

    text = clean_text(value, limit=200)
    if not text:
        return None
    matches = list(NUMBER_RE.finditer(text))
    numbers = []
    for match in matches:
        parsed = to_float(match.group(1))
        if parsed is not None:
            numbers.append((parsed, match.group(2)))
    if not numbers:
        return None
    if len(numbers) > 1:
        # A single answer may not contain several competing numbers.
        return None
    value_number, unit_raw = numbers[0]
    return {"value": value_number, "unit": canonical_unit(unit_raw), "unit_raw": unit_raw}


def format_number(value: float, unit: str | None) -> str:
    """Render a number the way the course writes it (French formatting)."""

    if abs(value - round(value)) < 1e-9:
        rendered = f"{int(round(value)):,}".replace(",", "\u202f")
    else:
        rendered = f"{value:,.2f}".replace(",", " ").replace(".", ",")
    label = unit_label(unit)
    return f"{rendered} {label}".strip()


# --------------------------------------------------------------------------- #
# Core objects
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class SourceRef:
    """A verifiable pointer to a passage of the course.

    ``excerpt`` is copied verbatim from the ingested text.  ``locator`` keeps
    **two** coordinate systems, never mixed:

    * the *source* coordinates (``line_start``, ``line_end``, ``page``,
      ``chunk_id``) describe the original Côme AI document, exactly as the
      personal-memory citation contract returns them;
    * the *document* coordinates (``document_line_start``,
      ``document_line_end``, ``char_start``, ``char_end``) describe the
      reconstructed Study Coach text and are what the excerpt is verified
      against.

    When the course comes from raw text, both refer to the same lines.
    """

    source_id: str
    title: str
    excerpt: str
    locator: dict[str, Any] = field(default_factory=dict)

    @property
    def document_line_start(self) -> int | None:
        value = self.locator.get("document_line_start", self.locator.get("line_start"))
        return int(value) if isinstance(value, (int, float)) else None

    @property
    def document_line_end(self) -> int | None:
        value = self.locator.get("document_line_end", self.locator.get("line_end"))
        return int(value) if isinstance(value, (int, float)) else None

    @property
    def page(self) -> int | None:
        value = self.locator.get("page")
        return int(value) if isinstance(value, (int, float)) else None

    @property
    def citation_label(self) -> str:
        """Label shown to the learner, built from the *source* coordinates."""

        locator = self.locator or {}
        raw_label = str(locator.get("label") or "").strip()
        title = self.title.strip()
        if raw_label and raw_label.lower().startswith(title.lower()):
            # The document store already prefixed the label with its own title.
            return raw_label
        page = self.page
        line_start = locator.get("line_start")
        line_end = locator.get("line_end")
        details: list[str] = []
        if page:
            details.append(f"p.{page}")
        if isinstance(line_start, (int, float)):
            details.append(
                f"l.{int(line_start)}"
                if line_end in (None, line_start)
                else f"l.{int(line_start)}-{int(line_end or line_start)}"
            )
        suffix = " ".join(details)
        if suffix:
            return f"{title} ({suffix})"
        return raw_label or title

    def matches_text(self, text: str) -> bool:
        """True when the excerpt is a verbatim slice of ``text``.

        This is the anti-hallucination check: a reference that does not match
        the ingested course is a broken reference.
        """

        start = self.locator.get("char_start")
        end = self.locator.get("char_end")
        if not isinstance(start, int) or not isinstance(end, int):
            return False
        return text[start:end] == self.excerpt

    def to_citation_dict(self) -> dict[str, Any]:
        """Return the citation shape used by ``PersonalMemoryStore.search``."""

        locator = self.locator or {}
        return {
            "source_id": self.source_id,
            "title": self.title,
            "page": locator.get("page"),
            "line_start": locator.get("line_start"),
            "line_end": locator.get("line_end"),
            "label": self.citation_label,
        }

    def to_locator_dict(self) -> dict[str, Any]:
        """Both coordinate systems, for an integration that needs them."""

        return {
            "source": self.to_citation_dict(),
            "document_line_start": self.document_line_start,
            "document_line_end": self.document_line_end,
            "char_start": self.locator.get("char_start"),
            "char_end": self.locator.get("char_end"),
            "chunk_id": self.locator.get("chunk_id"),
        }

    def to_dict(self) -> dict[str, Any]:
        return {
            "source_id": self.source_id,
            "title": self.title,
            "excerpt": self.excerpt,
            "locator": dict(self.locator or {}),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "SourceRef":
        return cls(
            source_id=str(data.get("source_id") or ""),
            title=str(data.get("title") or ""),
            excerpt=str(data.get("excerpt") or ""),
            locator=dict(data.get("locator") or {}),
        )


@dataclass
class Notion:
    """An important idea extracted from the course, always cited."""

    id: str
    title: str
    statement: str
    source_refs: list[SourceRef] = field(default_factory=list)
    keywords: list[str] = field(default_factory=list)
    importance: int = 2
    status: str = "extraite"
    ambiguity_note: str = ""
    section: str = ""
    explicit_term: bool = True
    numeric_facts: list[dict[str, Any]] = field(default_factory=list)

    @property
    def is_ambiguous(self) -> bool:
        return self.status == "ambigue"

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "title": self.title,
            "statement": self.statement,
            "source_refs": [ref.to_dict() for ref in self.source_refs],
            "keywords": list(self.keywords),
            "importance": self.importance,
            "status": self.status,
            "ambiguity_note": self.ambiguity_note,
            "section": self.section,
            "explicit_term": self.explicit_term,
            "numeric_facts": [dict(fact) for fact in self.numeric_facts],
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Notion":
        return cls(
            id=str(data.get("id") or ""),
            title=str(data.get("title") or ""),
            statement=str(data.get("statement") or ""),
            source_refs=[SourceRef.from_dict(item) for item in data.get("source_refs") or []],
            keywords=list(data.get("keywords") or []),
            importance=int(data.get("importance") or 2),
            status=str(data.get("status") or "extraite"),
            ambiguity_note=str(data.get("ambiguity_note") or ""),
            section=str(data.get("section") or ""),
            explicit_term=bool(data.get("explicit_term", True)),
            numeric_facts=[dict(fact) for fact in data.get("numeric_facts") or []],
        )


@dataclass
class Gap:
    """A missing or ambiguous piece of information the engine refuses to fill."""

    id: str
    kind: str
    topic: str
    reason: str
    clarification_question: str = ""
    source_refs: list[SourceRef] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "kind": self.kind,
            "topic": self.topic,
            "reason": self.reason,
            "clarification_question": self.clarification_question,
            "source_refs": [ref.to_dict() for ref in self.source_refs],
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Gap":
        return cls(
            id=str(data.get("id") or ""),
            kind=str(data.get("kind") or "information_absente"),
            topic=str(data.get("topic") or ""),
            reason=str(data.get("reason") or ""),
            clarification_question=str(data.get("clarification_question") or ""),
            source_refs=[SourceRef.from_dict(item) for item in data.get("source_refs") or []],
        )


@dataclass
class StudyDocument:
    """A course text ready to be turned into a revision programme."""

    document_id: str
    title: str
    text: str
    source_id: str = ""
    base_line: int = 1
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def lines(self) -> list[str]:
        return self.text.split("\n")

    def line_number(self, index: int) -> int:
        return self.base_line + index

    def to_dict(self) -> dict[str, Any]:
        return {
            "document_id": self.document_id,
            "title": self.title,
            "text": self.text,
            "source_id": self.source_id,
            "base_line": self.base_line,
            "metadata": dict(self.metadata or {}),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "StudyDocument":
        return cls(
            document_id=str(data.get("document_id") or ""),
            title=str(data.get("title") or ""),
            text=str(data.get("text") or ""),
            source_id=str(data.get("source_id") or ""),
            base_line=int(data.get("base_line") or 1),
            metadata=dict(data.get("metadata") or {}),
        )


@dataclass
class Syllabus:
    """Notions + review programme + reported gaps for one course."""

    id: str
    document_id: str
    title: str
    notions: list[Notion] = field(default_factory=list)
    gaps: list[Gap] = field(default_factory=list)
    program: list[dict[str, Any]] = field(default_factory=list)
    created_at: str = ""
    syllabus_version: str = SYLLABUS_VERSION

    def notion(self, notion_id: str) -> Notion | None:
        return next((notion for notion in self.notions if notion.id == notion_id), None)

    @property
    def ambiguous_notions(self) -> list[Notion]:
        return [notion for notion in self.notions if notion.is_ambiguous]

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "document_id": self.document_id,
            "title": self.title,
            "notions": [notion.to_dict() for notion in self.notions],
            "gaps": [gap.to_dict() for gap in self.gaps],
            "program": [dict(step) for step in self.program],
            "created_at": self.created_at,
            "syllabus_version": self.syllabus_version,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Syllabus":
        return cls(
            id=str(data.get("id") or ""),
            document_id=str(data.get("document_id") or ""),
            title=str(data.get("title") or ""),
            notions=[Notion.from_dict(item) for item in data.get("notions") or []],
            gaps=[Gap.from_dict(item) for item in data.get("gaps") or []],
            program=[dict(step) for step in data.get("program") or []],
            created_at=str(data.get("created_at") or ""),
            syllabus_version=str(data.get("syllabus_version") or SYLLABUS_VERSION),
        )


# --------------------------------------------------------------------------- #
# Questions
# --------------------------------------------------------------------------- #


@dataclass
class QuestionOption:
    """A choice of a multiple-choice question."""

    id: str
    label: str

    def to_dict(self) -> dict[str, Any]:
        return {"id": self.id, "label": self.label}

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "QuestionOption":
        return cls(id=str(data.get("id") or ""), label=str(data.get("label") or ""))


@dataclass
class NumericAnswer:
    """A numeric reference answer, copied from the course, never invented."""

    value: float
    unit: str | None = None
    tolerance_pct: float = 1.0

    def to_dict(self) -> dict[str, Any]:
        return {"value": self.value, "unit": self.unit, "tolerance_pct": self.tolerance_pct}

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "NumericAnswer":
        return cls(
            value=float(data.get("value") or 0.0),
            unit=data.get("unit"),
            tolerance_pct=float(data.get("tolerance_pct") or 0.0),
        )


@dataclass
class QuestionStep:
    """One step of a progressive question."""

    id: str
    label: str
    question_type: str
    expected: Any = None
    options: list[QuestionOption] = field(default_factory=list)
    weight: float = 1.0
    keywords: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        expected = self.expected.to_dict() if isinstance(self.expected, NumericAnswer) else self.expected
        return {
            "id": self.id,
            "label": self.label,
            "question_type": self.question_type,
            "expected": expected,
            "options": [option.to_dict() for option in self.options],
            "weight": self.weight,
            "keywords": list(self.keywords),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "QuestionStep":
        expected = data.get("expected")
        if isinstance(expected, dict):
            expected = NumericAnswer.from_dict(expected)
        return cls(
            id=str(data.get("id") or ""),
            label=str(data.get("label") or ""),
            question_type=str(data.get("question_type") or "definition"),
            expected=expected,
            options=[QuestionOption.from_dict(item) for item in data.get("options") or []],
            weight=float(data.get("weight") or 1.0),
            keywords=list(data.get("keywords") or []),
        )


@dataclass
class Question:
    """A question attached to its course passage and to its grading rule."""

    id: str
    question_type: str
    prompt: str
    notion_id: str
    source_refs: list[SourceRef] = field(default_factory=list)
    options: list[QuestionOption] = field(default_factory=list)
    correct_option_ids: list[str] = field(default_factory=list)
    expected_text: str = ""
    expected_keywords: list[str] = field(default_factory=list)
    expected_number: NumericAnswer | None = None
    steps: list[QuestionStep] = field(default_factory=list)
    reference_points: list[str] = field(default_factory=list)
    explanation_template: str = ""
    validation: str = "deterministe"
    difficulty: int = 2
    created_by: str = QUESTION_VERSION
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def requires_model(self) -> bool:
        return self.validation != "deterministe"

    @property
    def is_deterministic(self) -> bool:
        return self.validation == "deterministe"

    def has_sources(self) -> bool:
        return bool(self.source_refs) and all(ref.excerpt for ref in self.source_refs)

    def to_public_dict(self) -> dict[str, Any]:
        """Question as shown to the learner: no answer key, no explanation."""

        return {
            "id": self.id,
            "question_type": self.question_type,
            "prompt": self.prompt,
            "notion_id": self.notion_id,
            "options": [option.to_dict() for option in self.options],
            "steps": [
                {"id": step.id, "label": step.label, "question_type": step.question_type, "weight": step.weight}
                for step in self.steps
            ],
            "difficulty": self.difficulty,
            "validation": self.validation,
            "sources": [ref.to_citation_dict() for ref in self.source_refs],
        }

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "question_type": self.question_type,
            "prompt": self.prompt,
            "notion_id": self.notion_id,
            "source_refs": [ref.to_dict() for ref in self.source_refs],
            "options": [option.to_dict() for option in self.options],
            "correct_option_ids": list(self.correct_option_ids),
            "expected_text": self.expected_text,
            "expected_keywords": list(self.expected_keywords),
            "expected_number": self.expected_number.to_dict() if self.expected_number else None,
            "steps": [step.to_dict() for step in self.steps],
            "reference_points": list(self.reference_points),
            "explanation_template": self.explanation_template,
            "validation": self.validation,
            "difficulty": self.difficulty,
            "created_by": self.created_by,
            "metadata": dict(self.metadata or {}),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Question":
        expected_number = data.get("expected_number")
        return cls(
            id=str(data.get("id") or ""),
            question_type=str(data.get("question_type") or "ouverte"),
            prompt=str(data.get("prompt") or ""),
            notion_id=str(data.get("notion_id") or ""),
            source_refs=[SourceRef.from_dict(item) for item in data.get("source_refs") or []],
            options=[QuestionOption.from_dict(item) for item in data.get("options") or []],
            correct_option_ids=list(data.get("correct_option_ids") or []),
            expected_text=str(data.get("expected_text") or ""),
            expected_keywords=list(data.get("expected_keywords") or []),
            expected_number=NumericAnswer.from_dict(expected_number) if expected_number else None,
            steps=[QuestionStep.from_dict(item) for item in data.get("steps") or []],
            reference_points=list(data.get("reference_points") or []),
            explanation_template=str(data.get("explanation_template") or ""),
            validation=str(data.get("validation") or "deterministe"),
            difficulty=int(data.get("difficulty") or 2),
            created_by=str(data.get("created_by") or QUESTION_VERSION),
            metadata=dict(data.get("metadata") or {}),
        )


# --------------------------------------------------------------------------- #
# Answers, corrections, sessions
# --------------------------------------------------------------------------- #


@dataclass
class AnswerRecord:
    """One learner answer, stored verbatim with its correction status."""

    id: str
    session_id: str
    question_id: str
    notion_id: str
    value: Any = None
    answered_at: str = ""
    status: str = ""
    score: float | None = None
    validation: str = "deterministe"
    syllabus_id: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "session_id": self.session_id,
            "question_id": self.question_id,
            "notion_id": self.notion_id,
            "value": self.value,
            "answered_at": self.answered_at,
            "status": self.status,
            "score": self.score,
            "validation": self.validation,
            "syllabus_id": self.syllabus_id,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "AnswerRecord":
        return cls(
            id=str(data.get("id") or ""),
            session_id=str(data.get("session_id") or ""),
            question_id=str(data.get("question_id") or ""),
            notion_id=str(data.get("notion_id") or ""),
            value=data.get("value"),
            answered_at=str(data.get("answered_at") or ""),
            status=str(data.get("status") or ""),
            score=data.get("score"),
            validation=str(data.get("validation") or "deterministe"),
            syllabus_id=str(data.get("syllabus_id") or ""),
        )


@dataclass
class Correction:
    """A verifiable correction.

    ``score`` is ``None`` whenever the answer cannot be evaluated objectively;
    ``status`` is then ``non_evaluable`` and ``validation`` says who must
    finish the job (a model or a human).  The engine never fabricates a grade.
    """

    question_id: str
    notion_id: str
    status: str
    validation: str
    score: float | None
    max_score: float
    explanation: str
    expected_answer: Any = None
    errors: list[str] = field(default_factory=list)
    source_refs: list[SourceRef] = field(default_factory=list)
    revision_targets: list[str] = field(default_factory=list)
    grader: str = GRADING_VERSION

    @property
    def is_objective(self) -> bool:
        return self.status != "non_evaluable"

    def to_dict(self) -> dict[str, Any]:
        return {
            "question_id": self.question_id,
            "notion_id": self.notion_id,
            "status": self.status,
            "validation": self.validation,
            "score": self.score,
            "max_score": self.max_score,
            "explanation": self.explanation,
            "expected_answer": self.expected_answer,
            "errors": list(self.errors),
            "source_refs": [ref.to_dict() for ref in self.source_refs],
            "revision_targets": list(self.revision_targets),
            "grader": self.grader,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Correction":
        return cls(
            question_id=str(data.get("question_id") or ""),
            notion_id=str(data.get("notion_id") or ""),
            status=str(data.get("status") or "non_evaluable"),
            validation=str(data.get("validation") or "humain"),
            score=data.get("score"),
            max_score=float(data.get("max_score") or 1.0),
            explanation=str(data.get("explanation") or ""),
            expected_answer=data.get("expected_answer"),
            errors=list(data.get("errors") or []),
            source_refs=[SourceRef.from_dict(item) for item in data.get("source_refs") or []],
            revision_targets=list(data.get("revision_targets") or []),
            grader=str(data.get("grader") or GRADING_VERSION),
        )


@dataclass
class ReviewSession:
    """A review session: a planned list of questions plus its progress."""

    id: str
    syllabus_id: str
    title: str
    mode: str = "revision_initiale"
    status: str = "preparee"
    questions: list[Question] = field(default_factory=list)
    current_index: int = 0
    created_at: str = ""
    updated_at: str = ""
    completed_at: str = ""

    @property
    def question_ids(self) -> list[str]:
        return [question.id for question in self.questions]

    @property
    def notion_ids(self) -> list[str]:
        seen: list[str] = []
        for question in self.questions:
            if question.notion_id not in seen:
                seen.append(question.notion_id)
        return seen

    def pending_questions(self) -> list[Question]:
        return self.questions[self.current_index:]

    def question(self, question_id: str) -> Question | None:
        return next((question for question in self.questions if question.id == question_id), None)

    def to_public_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "syllabus_id": self.syllabus_id,
            "title": self.title,
            "mode": self.mode,
            "status": self.status,
            "total": len(self.questions),
            "answered": self.current_index,
            "questions": [question.to_public_dict() for question in self.questions],
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "syllabus_id": self.syllabus_id,
            "title": self.title,
            "mode": self.mode,
            "status": self.status,
            "questions": [question.to_dict() for question in self.questions],
            "current_index": self.current_index,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "completed_at": self.completed_at,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ReviewSession":
        return cls(
            id=str(data.get("id") or ""),
            syllabus_id=str(data.get("syllabus_id") or ""),
            title=str(data.get("title") or ""),
            mode=str(data.get("mode") or "revision_initiale"),
            status=str(data.get("status") or "preparee"),
            questions=[Question.from_dict(item) for item in data.get("questions") or []],
            current_index=int(data.get("current_index") or 0),
            created_at=str(data.get("created_at") or ""),
            updated_at=str(data.get("updated_at") or ""),
            completed_at=str(data.get("completed_at") or ""),
        )


@dataclass
class ScheduleEntry:
    """Spaced-repetition state of one reviewable item."""

    item_key: str
    kind: str = "notion"
    rung: int = 0
    ease: float = 2.5
    due_at: str = ""
    streak: int = 0
    lapses: int = 0
    last_status: str = ""
    updated_at: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "item_key": self.item_key,
            "kind": self.kind,
            "rung": self.rung,
            "ease": self.ease,
            "due_at": self.due_at,
            "streak": self.streak,
            "lapses": self.lapses,
            "last_status": self.last_status,
            "updated_at": self.updated_at,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ScheduleEntry":
        return cls(
            item_key=str(data.get("item_key") or ""),
            kind=str(data.get("kind") or "notion"),
            rung=int(data.get("rung") or 0),
            ease=float(data.get("ease") or 2.5),
            due_at=str(data.get("due_at") or ""),
            streak=int(data.get("streak") or 0),
            lapses=int(data.get("lapses") or 0),
            last_status=str(data.get("last_status") or ""),
            updated_at=str(data.get("updated_at") or ""),
        )


@dataclass
class DifficultNotion:
    """A notion the learner keeps missing; drives the recommended revision."""

    notion_id: str
    title: str
    seen: int
    correct: int
    incorrect: int
    accuracy: float
    last_seen_at: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "notion_id": self.notion_id,
            "title": self.title,
            "seen": self.seen,
            "correct": self.correct,
            "incorrect": self.incorrect,
            "accuracy": self.accuracy,
            "last_seen_at": self.last_seen_at,
        }
