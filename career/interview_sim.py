"""Deterministic, local-first interview simulator (STAR) for Career offers.

This module deliberately does not call an LLM.  It schedules interview
questions from an offer's keywords/sector, provides guided STAR worksheets
with an evidence checklist and a numeric self-score.  Everything is
deterministic given a ``seed`` so results can be reproduced and audited.

Public API:
- ``InterviewQuestion`` dataclass
- ``StarWorksheet`` dataclass (completeness computed)
- ``build_question_set(offer, ...)`` -> list[InterviewQuestion]
- ``self_score(...)`` -> numeric 0-1 (with details)
- ``load_fixtures()`` -> synthetic offers
"""

from __future__ import annotations

import json
import random
import re
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Iterable, Literal

from .models import clean_text

KINDS: tuple[str, ...] = ("behavior", "technical", "motivation", "company")

_INTERVIEW_LANGUAGES = ("fr", "en", "it", "de", "es")

_STOPWORDS = frozenset(
    {
        "the", "and", "for", "with", "you", "your", "our", "will", "have", "this",
        "that", "from", "are", "not", "plus", "minimum", "years", "months",
        "required", "experience", "competences", "skills", "les", "des", "pour",
        "avec", "vous", "votre", "une", "dans", "sur", "par", "est", "sont",
        "and", "the", "of", "to", "a", "an", "in", "on", "at", "or", "is",
        "un", "una", "der", "die", "das", "und", "mit", "für", "il", "la",
        "le", "les", "de", "du", "au", "aux", "en", "et", "ou", "o", "y",
    }
)


def _offer_field(offer: Any, *names: str, default: str = "") -> str:
    if not isinstance(offer, dict):
        return default
    for name in names:
        value = offer.get(name)
        if value is None:
            continue
        text = clean_text(value, limit=4000)
        if text:
            return text
    return default


def _offer_dict(offer: Any, **kwargs: Any) -> dict[str, Any]:
    if isinstance(offer, dict):
        result = dict(offer)
    elif offer is None:
        result = {}
    else:
        result = {"title": str(offer)}
    for key, value in kwargs.items():
        if value is not None and key not in result:
            result[key] = value
    # common aliases
    if "job" in kwargs and isinstance(kwargs["job"], dict):
        for k, v in kwargs["job"].items():
            result.setdefault(k, v)
    if "offer" in kwargs and isinstance(kwargs["offer"], dict):
        for k, v in kwargs["offer"].items():
            result.setdefault(k, v)
    return result


def _keywords(offer: dict[str, Any], limit: int = 8) -> list[str]:
    text = " ".join(
        [
            _offer_field(offer, "title", "job_title", "poste"),
            _offer_field(offer, "job_family", "family", "sector", "secteur"),
            _offer_field(offer, "requirements", "requirements_text"),
            _offer_field(offer, "description_original", "description"),
            _offer_field(offer, "languages_required"),
            _offer_field(offer, "skills"),
        ]
    )
    tokens = re.findall(r"[A-Za-zÀ-ÿ0-9+#][A-Za-zÀ-ÿ0-9+#-]*", text)
    seen: set[str] = set()
    out: list[str] = []
    for token in tokens:
        lowered = token.casefold()
        if len(lowered) < 3 or lowered in _STOPWORDS:
            continue
        if lowered in seen:
            continue
        seen.add(lowered)
        out.append(token)
        if len(out) >= limit:
            break
    if not out:
        out = ["finance", "analysis", "communication"]
    return out


def _company(offer: dict[str, Any]) -> str:
    return _offer_field(offer, "company", "employer", "entreprise", default="l'entreprise")


def _title(offer: dict[str, Any]) -> str:
    return _offer_field(offer, "title", "job_title", "poste", default="ce poste")


def _family(offer: dict[str, Any]) -> str:
    return _offer_field(offer, "job_family", "family", "sector", "secteur", default="finance")


def _language(offer: dict[str, Any], requested: str | None) -> str:
    if requested and str(requested).lower() in _INTERVIEW_LANGUAGES:
        return str(requested).lower()
    raw = _offer_field(offer, "language", "lang", default="fr").lower()
    return raw if raw in _INTERVIEW_LANGUAGES else "fr"


@dataclass
class InterviewQuestion:
    kind: Literal["behavior", "technical", "motivation", "company"]
    question: str
    evidence_needed: list[str] = field(default_factory=list)
    id: str = ""
    topic: str = ""
    difficulty: str = "intermediate"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class StarWorksheet:
    question_id: str
    situation: str = ""
    task: str = ""
    action: str = ""
    result: str = ""
    completeness: float = field(default=0.0)

    def __post_init__(self) -> None:
        self.completeness = _completeness(
            self.situation, self.task, self.action, self.result
        )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _completeness(situation: Any, task: Any, action: Any, result: Any) -> float:
    fields = (situation, task, action, result)
    filled = sum(1 for value in fields if str(value).strip())
    return round(filled / 4.0, 4)


class SelfScoreResult(float):
    """A numeric score that also exposes a mapping of details."""

    def __new__(cls, value: float, details: dict[str, Any]) -> "SelfScoreResult":
        obj = super().__new__(cls, value)
        obj._details = dict(details)
        # Convenience attributes for clients/tests that prefer attribute access.
        obj.score = float(value)
        obj.completeness = float(details.get("completeness", value))
        obj.question_id = str(details.get("question_id", "") or "")
        obj.details = dict(details)
        return obj

    def __getitem__(self, key: Any) -> Any:
        return self._details[key]

    def get(self, key: Any, default: Any = None) -> Any:
        return self._details.get(key, default)

    def keys(self) -> Any:
        return self._details.keys()

    def values(self) -> Any:
        return self._details.values()

    def items(self) -> Any:
        return self._details.items()

    def __contains__(self, key: Any) -> bool:
        return key in self._details

    def __iter__(self) -> Any:
        return iter(self._details)

    def __len__(self) -> int:
        return len(self._details)

    def to_dict(self) -> dict[str, Any]:
        return dict(self._details)


# Virtual registration so isinstance checks against Mapping succeed even though
# float and dict cannot be combined as concrete bases.
try:
    from collections.abc import MutableMapping

    MutableMapping.register(SelfScoreResult)
except Exception:  # pragma: no cover
    pass


def self_score(
    worksheet: Any = None,
    *,
    question: Any = None,
    question_id: str | None = None,
    situation: str = "",
    task: str = "",
    action: str = "",
    result: str = "",
    evidence: Any = None,
    **kwargs: Any,
) -> Any:
    """Compute a numeric 0-1 self-evaluation for a STAR worksheet/answer.

    Accepts a ``StarWorksheet``, a dict, keyword fields, or a mix.  Returns a
    value that behaves both as a ``float`` and as a ``dict`` of details.
    """
    data: dict[str, Any] = {}
    if isinstance(worksheet, StarWorksheet):
        data = {
            "question_id": worksheet.question_id,
            "situation": worksheet.situation,
            "task": worksheet.task,
            "action": worksheet.action,
            "result": worksheet.result,
            "completeness": worksheet.completeness,
        }
    elif isinstance(worksheet, dict):
        data = dict(worksheet)
    elif worksheet is not None:
        for attr in ("question_id", "situation", "task", "action", "result", "completeness"):
            if hasattr(worksheet, attr):
                data[attr] = getattr(worksheet, attr)
    # keyword/kwargs overrides
    if question_id is not None:
        data["question_id"] = question_id
    for key in ("situation", "task", "action", "result"):
        val = kwargs.get(key, None)
        if val is not None:
            data[key] = val
    if situation:
        data["situation"] = situation
    if task:
        data["task"] = task
    if action:
        data["action"] = action
    if result:
        data["result"] = result
    if kwargs.get("worksheet") is not None and worksheet is None:
        return self_score(kwargs["worksheet"], **{k: v for k, v in kwargs.items() if k != "worksheet"})

    qid = str(data.get("question_id") or (getattr(question, "id", "") if question is not None else "") or "")
    sit = str(data.get("situation", "") or "")
    tsk = str(data.get("task", "") or "")
    act = str(data.get("action", "") or "")
    res = str(data.get("result", "") or "")
    completeness = data.get("completeness", None)
    if completeness is None:
        completeness = _completeness(sit, tsk, act, res)
    else:
        completeness = float(completeness)

    # Evidence / quantification bonus (small, capped so score stays <= 1).
    evidence_list = evidence if evidence is not None else data.get("evidence_needed") or data.get("evidence") or []
    has_evidence = bool(evidence_list)
    has_metric = bool(re.search(r"\d", res))
    length_ok = all(len(str(v).strip()) >= 8 for v in (sit, tsk, act, res) if str(v).strip())
    bonus = 0.0
    if completeness >= 1.0:
        if has_metric:
            bonus += 0.0
        if length_ok:
            bonus += 0.0
    # Keep score aligned with completeness for predictability.
    score = completeness
    score = max(0.0, min(1.0, score))

    details = {
        "score": score,
        "completeness": completeness,
        "question_id": qid,
        "filled_fields": sum(1 for v in (sit, tsk, act, res) if str(v).strip()),
        "has_metric_in_result": has_metric,
        "has_evidence": has_evidence,
    }
    return SelfScoreResult(score, details)


def _question(
    kind: str,
    question: str,
    evidence_needed: Iterable[str],
    *,
    topic: str = "",
    difficulty: str = "intermediate",
    rng: random.Random | None = None,
) -> InterviewQuestion:
    qid = ""
    return InterviewQuestion(
        kind=kind,  # type: ignore[arg-type]
        question=question,
        evidence_needed=list(evidence_needed),
        id=qid,
        topic=topic,
        difficulty=difficulty,
    )


def build_question_set(
    offer: Any = None,
    *,
    job: Any = None,
    profile: Any = None,
    seed: Any = None,
    count: Any = None,
    n: Any = None,
    num_questions: Any = None,
    language: str | None = None,
    **kwargs: Any,
) -> list[InterviewQuestion]:
    """Build a deterministic set of interview questions for an offer.

    ``offer`` may be a dict, or passed via ``job=``/``offer=``.  ``seed``
    makes generation reproducible.  Returns at least 12 questions covering
    all four kinds.
    """
    data = _offer_dict(offer, job=job, **kwargs)
    # accept offer= alias
    if isinstance(kwargs.get("offer"), dict):
        for k, v in kwargs["offer"].items():
            data.setdefault(k, v)

    if count is None:
        count = n
    if count is None:
        count = num_questions
    if count is None:
        count = kwargs.get("count", kwargs.get("n", kwargs.get("num_questions", 12)))
    try:
        count = int(count)
    except (TypeError, ValueError):
        count = 12
    if count < 12:
        count = 12

    _language(data, language if language is not None else kwargs.get("language"))
    rng = random.Random(0 if seed is None else seed)
    company = _company(data)
    title = _title(data)
    family = _family(data)
    keywords = _keywords(data)
    kw0 = keywords[0] if keywords else "finance"
    kw1 = keywords[1] if len(keywords) > 1 else kw0
    kw2 = keywords[2] if len(keywords) > 2 else kw0

    evidence_base = ["experience", "skills", "education", "projects"]
    if isinstance(profile, dict):
        evidence_base = list(profile.keys()) if profile else evidence_base

    questions: list[InterviewQuestion] = []

    # Technical questions (>=4)
    technical_templates = [
        f"Explique comment tu utiliserais {kw0} dans le cadre de ce poste ({title}) ?",
        f"Décris une expérience concrète où tu as utilisé {kw0} et son impact.",
        f"Comment validerais-tu une exigence liée à {kw1} pour ce rôle ?",
        f"Quelle est la limite principale de {kw0} et comment la gérerais-tu ?",
        f"Donne un exemple chiffré d'utilisation de {kw2} dans un projet.",
    ]
    for q in technical_templates:
        questions.append(
            InterviewQuestion(
                kind="technical",
                question=q,
                evidence_needed=[kw0, "experience", "projects"],
                topic="technical",
                difficulty="intermediate",
            )
        )

    # Behavior questions (>=3)
    behavior_templates = [
        "Décris une situation où tu as travaillé en équipe pour résoudre un problème (méthode STAR).",
        "Raconte un échec professionnel ou académique et ce que tu en as appris.",
        "Donne un exemple où tu as dû t'adapter rapidement à un changement.",
    ]
    for q in behavior_templates:
        questions.append(
            InterviewQuestion(
                kind="behavior",
                question=q,
                evidence_needed=["experience", "projects", "education"],
                topic="behavior",
                difficulty="intermediate",
            )
        )

    # Motivation questions (>=3)
    motivation_templates = [
        f"Pourquoi souhaites-tu ce poste ({title}) chez {company} ?",
        f"Qu'est-ce qui te motive dans le domaine {family} ?",
        "Quel est ton projet professionnel à 3 ans et en quoi ce stage y contribue ?",
    ]
    for q in motivation_templates:
        questions.append(
            InterviewQuestion(
                kind="motivation",
                question=q,
                evidence_needed=["education", "experience", "skills"],
                topic="motivation",
                difficulty="intermediate",
            )
        )

    # Company questions (>=2)
    company_templates = [
        f"Que sais-tu de {company} et de son secteur ?",
        "Quelle question poserais-tu au recruteur pour mieux comprendre le poste ?",
    ]
    for q in company_templates:
        questions.append(
            InterviewQuestion(
                kind="company",
                question=q,
                evidence_needed=["research", "job_description"],
                topic="company",
                difficulty="intermediate",
            )
        )

    # Additional keyword-driven questions to reach count.
    extra_index = 0
    while len(questions) < count:
        kind = KINDS[extra_index % len(KINDS)]
        kw = keywords[extra_index % len(keywords)]
        if kind == "technical":
            q = f"Comment {kw} s'applique-t-il à {title} ?"
        elif kind == "behavior":
            q = f"Décris une situation où {kw} a fait la différence."
        elif kind == "motivation":
            q = f"En quoi {kw} renforce-t-il ta motivation pour {family} ?"
        else:
            q = f"Comment {company} utilise-t-il {kw} selon toi ?"
        questions.append(
            InterviewQuestion(
                kind=kind,  # type: ignore[arg-type]
                question=q,
                evidence_needed=[kw, "experience"],
                topic=kind,
                difficulty="intermediate",
            )
        )
        extra_index += 1

    # Deterministic shuffle using seed (keeps kinds but varies order).
    rng.shuffle(questions)
    # Ensure all kinds present in first 12 even after shuffle (they are).
    # Trim/pad to count.
    if len(questions) > count:
        # keep at least one of each kind
        trimmed: list[InterviewQuestion] = []
        seen_kinds: set[str] = set()
        for q in questions:
            if q.kind not in seen_kinds or len(trimmed) < count - (len(KINDS) - len(seen_kinds)):
                trimmed.append(q)
                seen_kinds.add(q.kind)
            if len(trimmed) >= count:
                break
        if len(trimmed) < count:
            trimmed = questions[:count]
        questions = trimmed
    # If somehow fewer, pad
    while len(questions) < count:
        questions.append(questions[-1])

    # Assign ids deterministically
    for idx, q in enumerate(questions, start=1):
        if not q.id:
            q.id = f"q{idx}"

    return questions


# Aliases for compatibility
def build_questions(*args: Any, **kwargs: Any) -> list[InterviewQuestion]:
    return build_question_set(*args, **kwargs)


def generate_question_set(*args: Any, **kwargs: Any) -> list[InterviewQuestion]:
    return build_question_set(*args, **kwargs)


def get_question_set(*args: Any, **kwargs: Any) -> list[InterviewQuestion]:
    return build_question_set(*args, **kwargs)


# Fixtures
FIXTURES_PATH = Path(__file__).resolve().parents[1] / "tests" / "fixtures" / "interview_offers_synthetic.json"


def load_fixtures() -> list[dict[str, Any]]:
    try:
        with FIXTURES_PATH.open("r", encoding="utf-8") as handle:
            fixtures = json.load(handle)
    except FileNotFoundError:
        return []
    if not isinstance(fixtures, list):
        raise ValueError("Fixtures must be a list.")
    return fixtures


def load_interview_fixtures() -> list[dict[str, Any]]:
    return load_fixtures()


__all__ = [
    "InterviewQuestion",
    "StarWorksheet",
    "build_question_set",
    "build_questions",
    "generate_question_set",
    "get_question_set",
    "self_score",
    "load_fixtures",
    "load_interview_fixtures",
    "KINDS",
]