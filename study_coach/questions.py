"""Deterministic question generation, always attached to a course passage.

Five question families are supported:

===============  ==========================================================
``definition``   "Définis X." — graded by keyword coverage of the course wording
``qcm``          multiple choice built from the course wording + other notions
``numerique``    a figure the course states, asked with its unit and its source
``ouverte``      free answer — never auto-graded, needs a model or a human
``progressif``   several deterministic steps on the same notion
===============  ==========================================================

No question is produced without a :class:`~study_coach.models.SourceRef`: the
generators raise :class:`~study_coach.errors.QuestionError` instead of inventing
a citation.
"""

from __future__ import annotations

import hashlib
from typing import Iterable

from .errors import QuestionError
from .models import (
    DETERMINISTIC_TYPES,
    Notion,
    NumericAnswer,
    Question,
    QuestionOption,
    QuestionStep,
    Syllabus,
    clean_text,
    content_words,
    normalize_text,
    unit_label,
)
from .numeric import BLANK

QUESTION_FAMILIES = ("definition", "qcm", "numerique", "progressif", "ouverte")
DEFAULT_FAMILIES = ("definition", "qcm", "numerique", "progressif")
MAX_OPTION_CHARS = 220
MAX_NUMERIC_QUESTIONS_PER_NOTION = 2


def _stable_digest(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _truncate(value: str, limit: int = MAX_OPTION_CHARS) -> str:
    text = clean_text(value, limit=limit + 1)
    if len(text) <= limit:
        return text
    return text[:limit].rsplit(" ", 1)[0] + "…"


def _require_source(notion: Notion) -> None:
    if not notion.source_refs or not all(ref.excerpt for ref in notion.source_refs):
        raise QuestionError(
            f"La notion « {notion.title or notion.id} » n'a aucune référence de source : "
            "aucune question ne peut être générée sans passage vérifiable."
        )


def _question_id(notion: Notion, family: str, index: int = 0) -> str:
    suffix = f"_{index + 1}" if index else ""
    return f"q_{notion.id}_{family}{suffix}"


def _explanation(notion: Notion, lead: str) -> str:
    reference = notion.source_refs[0].citation_label if notion.source_refs else "cours"
    return f"{lead} (source : {reference})"


# --------------------------------------------------------------------------- #
# Question families
# --------------------------------------------------------------------------- #


def _notion_prompt(notion: Notion, *, explicit: str, fallback: str) -> str:
    """Ask about a named concept, or about the cited statement when unnamed."""

    if notion.explicit_term and notion.title:
        return explicit.format(title=notion.title)
    return fallback.format(statement=_truncate(notion.statement, 160))


def definition_question(notion: Notion, *, prompt_prefix: str = "Définis") -> Question:
    """Ask for the definition of a notion, graded against the course wording."""

    _require_source(notion)
    return Question(
        id=_question_id(notion, "definition"),
        question_type="definition",
        prompt=_notion_prompt(
            notion,
            explicit=f"{prompt_prefix} « {{title}} » d'après le cours.",
            fallback="Reformule l'idée du cours suivante : « {statement} ».",
        ),
        notion_id=notion.id,
        source_refs=list(notion.source_refs),
        expected_text=notion.statement,
        expected_keywords=list(notion.keywords),
        reference_points=[notion.statement],
        explanation_template=_explanation(notion, "La réponse attendue reprend la formulation du cours"),
        validation="deterministe",
        difficulty=1,
    )


def multiple_choice_question(notion: Notion, syllabus: Syllabus, *, distractors: int = 3) -> Question | None:
    """Build a QCM whose correct option is the course wording of the notion.

    Distractors are the wordings of *other* notions of the same course: real,
    plausible and non-invented.  ``None`` is returned when the course has too few
    other notions to make a usable question.
    """

    _require_source(notion)
    correct_label = _truncate(notion.statement)
    if len(correct_label) < 20:
        return None

    pool: list[str] = []
    seen = {normalize_text(correct_label)}
    for other in syllabus.notions:
        if other.id == notion.id:
            continue
        label = _truncate(other.statement)
        key = normalize_text(label)
        if len(label) < 20 or key in seen:
            continue
        seen.add(key)
        pool.append(label)
    if not pool:
        return None

    pool.sort(key=_stable_digest)
    chosen = pool[: max(2, min(int(distractors or 3), 4))]
    options = [QuestionOption(id=f"opt_{index + 1}", label=label) for index, label in enumerate(chosen)]
    options.append(QuestionOption(id=f"opt_{len(options) + 1}", label=correct_label))
    options.sort(key=lambda option: _stable_digest(f"{notion.id}|{option.label}"))
    correct_ids = [option.id for option in options if option.label == correct_label]

    return Question(
        id=_question_id(notion, "qcm"),
        question_type="qcm",
        prompt=_notion_prompt(
            notion,
            explicit="Selon le cours, qu'est-ce que « {title} » ?",
            fallback="Selon le cours, quelle affirmation est exacte ? « {statement} »",
        ),
        notion_id=notion.id,
        source_refs=list(notion.source_refs),
        options=options,
        correct_option_ids=correct_ids,
        reference_points=[notion.statement],
        explanation_template=_explanation(
            notion, "La bonne proposition est celle qui reprend la définition du cours"
        ),
        validation="deterministe",
        difficulty=2,
        metadata={"options_count": len(options), "distractors": len(options) - 1},
    )


def numeric_questions(notion: Notion) -> list[Question]:
    """Ask the figures the course states, with their unit and their sentence.

    The expected value is copied from the course; the engine never computes an
    exercise whose result is absent from the source.
    """

    _require_source(notion)
    questions: list[Question] = []
    seen_values: set[tuple[float, str | None]] = set()
    for fact in notion.numeric_facts[:MAX_NUMERIC_QUESTIONS_PER_NOTION]:
        value = float(fact.get("value") or 0.0)
        unit = fact.get("unit")
        key = (value, unit)
        if key in seen_values:
            continue
        seen_values.add(key)
        blanked = str(fact.get("blanked_sentence") or notion.statement)
        unit_text = unit_label(unit)
        questions.append(
            Question(
                id=_question_id(notion, "numerique", len(questions)),
                question_type="numerique",
                prompt=(
                    f"Extrait du cours : « {blanked} ». "
                    f"Quelle valeur remplace « {BLANK} »"
                    f"{f' (en {unit_text})' if unit_text else ''} ?"
                ),
                notion_id=notion.id,
                source_refs=list(notion.source_refs),
                expected_number=NumericAnswer(value=value, unit=unit, tolerance_pct=1.0),
                reference_points=[str(fact.get("sentence") or notion.statement)],
                explanation_template=_explanation(
                    notion, "La valeur attendue est celle écrite dans le cours"
                ),
                validation="deterministe",
                difficulty=3,
                metadata={"unit": unit, "blanked_sentence": blanked},
            )
        )
    return questions


def progressive_question(notion: Notion) -> Question | None:
    """Chain a definition and a figure so the recall builds up step by step."""

    _require_source(notion)
    numeric = numeric_questions(notion)
    if not numeric:
        return None
    steps = [
        QuestionStep(
            id=f"{notion.id}_step1",
            label="Étape 1 — nommer la notion",
            question_type="definition",
            expected=notion.statement,
            keywords=list(notion.keywords),
            weight=1.0,
        ),
        QuestionStep(
            id=f"{notion.id}_step2",
            label="Étape 2 — retrouver le chiffre du cours",
            question_type="numerique",
            expected=numeric[0].expected_number,
            keywords=[],
            weight=1.0,
        ),
    ]
    return Question(
        id=_question_id(notion, "progressif"),
        question_type="progressif",
        prompt=_notion_prompt(
            notion,
            explicit="Reconstruis « {title} » : d'abord sa définition, puis le chiffre du cours.",
            fallback=(
                "Reconstruis l'idée du cours « {statement} » : d'abord son sens, puis le chiffre annoncé."
            ),
        ),
        notion_id=notion.id,
        source_refs=list(notion.source_refs),
        steps=steps,
        reference_points=[notion.statement],
        explanation_template=_explanation(notion, "Chaque étape se corrige sur le cours"),
        validation="deterministe",
        difficulty=3,
    )


def open_question(notion: Notion) -> Question:
    """A free-answer question: explicitely not auto-gradable."""

    _require_source(notion)
    keywords = content_words(notion.statement, limit=8)
    return Question(
        id=_question_id(notion, "ouverte"),
        question_type="ouverte",
        prompt=_notion_prompt(
            notion,
            explicit="Explique « {title} » à partir du cours, puis donne un exemple.",
            fallback="Explique avec tes mots l'idée du cours « {statement} », puis donne un exemple.",
        ),
        notion_id=notion.id,
        source_refs=list(notion.source_refs),
        expected_text="",
        expected_keywords=list(keywords),
        reference_points=[notion.statement, *[f"mot-clé attendu : {word}" for word in keywords[:5]]],
        explanation_template=(
            "Réponse ouverte : à valider par un modèle IA ou par une relecture humaine"
        ),
        validation="modele_ia",
        difficulty=3,
    )


# --------------------------------------------------------------------------- #
# Orchestration
# --------------------------------------------------------------------------- #


def build_questions_for_notion(
    notion: Notion,
    syllabus: Syllabus,
    *,
    families: Iterable[str] = DEFAULT_FAMILIES,
    distractors: int = 3,
) -> list[Question]:
    """Every question a single notion can support, in family order."""

    _require_source(notion)
    wanted = [family for family in families if family in QUESTION_FAMILIES]
    questions: list[Question] = []
    for family in wanted:
        if family == "definition":
            questions.append(definition_question(notion))
        elif family == "qcm":
            qcm = multiple_choice_question(notion, syllabus, distractors=distractors)
            if qcm:
                questions.append(qcm)
        elif family == "numerique":
            questions.extend(numeric_questions(notion))
        elif family == "progressif":
            progressive = progressive_question(notion)
            if progressive:
                questions.append(progressive)
        elif family == "ouverte":
            questions.append(open_question(notion))
    for question in questions:
        if not question.has_sources():
            raise QuestionError(f"Question {question.id} générée sans passage source : génération refusée.")
    return questions


def _rotate(families: tuple[str, ...], offset: int) -> tuple[str, ...]:
    if not families:
        return ()
    shift = offset % len(families)
    return families[shift:] + families[:shift]


def build_session_questions(
    syllabus: Syllabus,
    notion_ids: Iterable[str],
    *,
    target_size: int = 8,
    per_notion: int = 2,
    families: Iterable[str] = DEFAULT_FAMILIES,
    distractors: int = 3,
) -> list[Question]:
    """Pick a varied, deterministic set of questions for one review session.

    Every notion keeps its first (rotated) question, so a session always starts
    with the most important notions while the question types alternate.
    """

    ordered_families = tuple(family for family in families if family in QUESTION_FAMILIES)
    selected: list[Question] = []
    target = max(1, int(target_size or 8))
    per_notion = max(1, min(int(per_notion or 2), 4))

    for offset, notion_id in enumerate(notion_ids):
        notion = syllabus.notion(notion_id)
        if notion is None:
            raise QuestionError(f"Notion inconnue : {notion_id}.")
        produced = build_questions_for_notion(
            notion, syllabus, families=_rotate(ordered_families, offset), distractors=distractors
        )
        selected.extend(produced[:per_notion])
        if len(selected) >= target * per_notion:
            break

    if not selected:
        raise QuestionError(
            "Aucune question n'a pu être générée : le cours ne contient pas de notions exploitables."
        )
    return selected[:target]


def deterministic_only(questions: list[Question]) -> list[Question]:
    """Filter used by the offline mode: no question that needs a model."""

    return [question for question in questions if question.question_type in DETERMINISTIC_TYPES]
