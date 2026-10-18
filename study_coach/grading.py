"""Deterministic corrections, with an explicit line between fact and opinion.

Three families can be checked locally and always explain themselves:

* ``qcm``       -- set comparison against the course wording;
* ``definition``-- keyword coverage against the course wording;
* ``numerique`` -- value + unit, with a declared tolerance.

Two families are **never** auto-graded here:

* ``ouverte``     -- a free answer is returned as ``non_evaluable`` with a model
  or a human validation required;
* a definition or a numeric answer the checker cannot read -- the score stays
  ``None``.  An unparsable answer is not a zero: it is an unanswered question
  about the learner's answer, and the engine says so instead of guessing.
"""

from __future__ import annotations

from typing import Any

from .errors import GradingError
from .models import (
    GRADING_VERSION,
    Correction,
    NumericAnswer,
    Question,
    QuestionStep,
    clean_text,
    format_number,
    keyword_overlap,
    parse_number,
    unit_family,
    unit_label,
)
from .numeric import find_numbers

FULL_SCORE = 1.0
HALF_SCORE = 0.5
DEFINITION_FULL_RATIO = 0.8
DEFINITION_PARTIAL_RATIO = 0.35
_SMALLEST_MEANINGFUL = 1e-9


def _correction(
    question: Question,
    *,
    status: str,
    validation: str,
    score: float | None,
    explanation: str,
    expected_answer: Any = None,
    errors: list[str] | None = None,
    revision_targets: list[str] | None = None,
) -> Correction:
    return Correction(
        question_id=question.id,
        notion_id=question.notion_id,
        status=status,
        validation=validation,
        score=score,
        max_score=FULL_SCORE,
        explanation=explanation,
        expected_answer=expected_answer,
        errors=list(errors or []),
        source_refs=list(question.source_refs),
        revision_targets=revision_targets if revision_targets is not None else _revision_targets(question, status),
    )


def _revision_targets(question: Question, status: str) -> list[str]:
    if status == "correct" or not question.notion_id:
        return []
    return [question.notion_id]


def _require_sourced(question: Question) -> None:
    if not question.has_sources():
        raise GradingError(
            f"La question {question.id} n'a aucune référence de cours : aucune correction ne peut être produite."
        )


# --------------------------------------------------------------------------- #
# QCM
# --------------------------------------------------------------------------- #


def _selected_ids(answer: Any) -> list[str]:
    if answer is None:
        return []
    if isinstance(answer, str):
        return [answer] if answer.strip() else []
    if isinstance(answer, (list, tuple, set)):
        return [str(item) for item in answer if str(item).strip()]
    if isinstance(answer, bool):
        return []
    if isinstance(answer, int):
        return [f"opt_{answer}"]
    return []


def grade_multiple_choice(question: Question, answer: Any) -> Correction:
    _require_sourced(question)
    if not question.correct_option_ids:
        return _correction(
            question,
            status="non_evaluable",
            validation="humain",
            score=None,
            explanation="Aucune bonne réponse n'est associée à cette question dans le cours : correction impossible.",
            errors=["QCM sans réponse de référence"],
        )

    selected = [option_id for option_id in _selected_ids(answer)]
    known = {option.id for option in question.options}
    unknown = [option_id for option_id in selected if option_id not in known]
    if unknown:
        return _correction(
            question,
            status="non_evaluable",
            validation="humain",
            score=None,
            explanation=f"Réponse illisible : option(s) inconnue(s) {', '.join(sorted(unknown))}.",
            errors=["Option inconnue"],
        )
    if not selected:
        return _correction(
            question,
            status="incorrect",
            validation="deterministe",
            score=0.0,
            explanation="Aucune réponse sélectionnée : la notion reste à réviser.",
            errors=["Aucune réponse sélectionnée"],
        )

    expected = set(question.correct_option_ids)
    chosen = set(selected)
    correct_label = next(
        (option.label for option in question.options if option.id in expected),
        "",
    )
    if chosen == expected:
        return _correction(
            question,
            status="correct",
            validation="deterministe",
            score=FULL_SCORE,
            explanation=f"{question.explanation_template} Bonne proposition : « {correct_label} ».",
            expected_answer=sorted(expected),
        )
    if chosen < expected:
        missing = sorted(expected - chosen)
        return _correction(
            question,
            status="partiel",
            validation="deterministe",
            score=HALF_SCORE,
            explanation=(
                f"Réponse incomplète : il manquait la proposition « {correct_label} » "
                f"(option {'/'.join(missing)}). La notion est à retravailler."
            ),
            expected_answer=sorted(expected),
            errors=["Réponse incomplète"],
        )
    wrong = sorted(chosen - expected)
    return _correction(
        question,
        status="incorrect",
        validation="deterministe",
        score=0.0,
        explanation=(
            f"Réponse incorrecte : la bonne proposition est « {correct_label} ». "
            f"Option(s) retenue(s) à tort : {'/'.join(wrong)}."
        ),
        expected_answer=sorted(expected),
        errors=[f"Option incorrecte : {option_id}" for option_id in wrong],
    )


# --------------------------------------------------------------------------- #
# Definition
# --------------------------------------------------------------------------- #


def grade_definition(question: Question, answer: Any) -> Correction:
    _require_sourced(question)
    reference = question.expected_text or ""
    keywords = question.expected_keywords or []
    given = clean_text(answer, limit=2_000)
    if not given:
        return _correction(
            question,
            status="incorrect",
            validation="deterministe",
            score=0.0,
            explanation="Aucune définition fournie : la notion reste à réviser.",
            errors=["Réponse vide"],
        )
    if not reference and not keywords:
        return _correction(
            question,
            status="non_evaluable",
            validation="humain",
            score=None,
            explanation="Le cours ne fournit pas de formulation de référence pour cette notion.",
            errors=["Référence de cours absente"],
        )

    overlap = keyword_overlap(reference, given)
    ratio = overlap["ratio"]
    expected_label = reference or " ".join(keywords)
    if ratio >= DEFINITION_FULL_RATIO:
        missing = overlap["missing"][:3]
        detail = "" if not missing else f" (mots du cours non cités : {', '.join(missing)})"
        return _correction(
            question,
            status="correct",
            validation="deterministe",
            score=FULL_SCORE,
            explanation=f"{question.explanation_template} Reprise fidèle de la formulation{detail}.",
            expected_answer=expected_label,
        )
    if ratio >= DEFINITION_PARTIAL_RATIO:
        missing = overlap["missing"][:5]
        return _correction(
            question,
            status="partiel",
            validation="deterministe",
            score=HALF_SCORE,
            explanation=(
                f"Définition partielle ({int(round(ratio * 100))} % des mots du cours). "
                f"À compléter : {', '.join(missing) if missing else 'formulation attendue'}."
            ),
            expected_answer=expected_label,
            errors=[f"Mot-clé manquant : {word}" for word in overlap["missing"][:5]],
        )
    if ratio <= 0.0:
        return _correction(
            question,
            status="non_evaluable",
            validation="humain",
            score=None,
            explanation=(
                "Aucun mot du cours n'a été retrouvé dans la réponse : elle peut être juste avec une "
                "autre formulation. Aucune note automatique n'est attribuée — validation humaine ou IA requise."
            ),
            expected_answer=expected_label,
            errors=["Recouvrement lexical nul : correction manuelle requise"],
        )
    return _correction(
        question,
        status="incorrect",
        validation="deterministe",
        score=0.0,
        explanation=(
            f"Définition incorrecte ({int(round(ratio * 100))} % des mots du cours). "
            f"Le cours attend : « {expected_label} »."
        ),
        expected_answer=expected_label,
        errors=[f"Mot-clé manquant : {word}" for word in overlap["missing"][:5]],
    )


# --------------------------------------------------------------------------- #
# Numeric
# --------------------------------------------------------------------------- #


def _units_compatible(expected: str | None, given: str | None) -> tuple[bool, str]:
    if expected is None or given is None:
        return True, ""
    if expected == given:
        return True, ""
    if unit_family(expected) != unit_family(given):
        return False, f"unité incompatible ({unit_label(expected)} attendu, {unit_label(given)} reçu)"
    return False, f"unité incohérente ({unit_label(expected)} attendu, {unit_label(given)} reçu)"


def grade_numeric(question: Question, answer: Any) -> Correction:
    _require_sourced(question)
    expected = question.expected_number
    if not isinstance(expected, NumericAnswer):
        return _correction(
            question,
            status="non_evaluable",
            validation="humain",
            score=None,
            explanation="Le cours ne fournit pas de valeur numérique de référence pour cette question.",
            errors=["Valeur de référence absente"],
        )

    given = parse_number(answer)
    if given is None:
        text = clean_text(answer, limit=120)
        reason = (
            "plusieurs nombres dans la réponse"
            if find_numbers(text)
            else "aucun nombre lisible dans la réponse"
        )
        return _correction(
            question,
            status="non_evaluable",
            validation="humain",
            score=None,
            explanation=(
                f"Réponse non vérifiable automatiquement ({reason}). "
                f"Valeur attendue : {format_number(expected.value, expected.unit)}."
            ),
            expected_answer=format_number(expected.value, expected.unit),
            errors=["Réponse numérique illisible"],
        )

    expected_text = format_number(expected.value, expected.unit)
    tolerance = max(abs(expected.value) * max(0.0, expected.tolerance_pct) / 100.0, _SMALLEST_MEANINGFUL)
    value_ok = abs(given["value"] - expected.value) <= tolerance
    units_ok, unit_error = _units_compatible(expected.unit, given["unit"])

    if value_ok and units_ok and given["unit"] is not None:
        return _correction(
            question,
            status="correct",
            validation="deterministe",
            score=FULL_SCORE,
            explanation=f"{question.explanation_template} Valeur et unité conformes : {expected_text}.",
            expected_answer=expected_text,
        )
    if value_ok and expected.unit and given["unit"] is None:
        return _correction(
            question,
            status="partiel",
            validation="deterministe",
            score=HALF_SCORE,
            explanation=(
                f"Valeur correcte ({expected_text}) mais unité non précisée. "
                "Les exercices de ce cours demandent l'unité."
            ),
            expected_answer=expected_text,
            errors=[f"Unité manquante : {unit_label(expected.unit)}"],
        )
    if value_ok and expected.unit and not units_ok:
        return _correction(
            question,
            status="incorrect",
            validation="deterministe",
            score=0.0,
            explanation=f"Valeur correcte mais {unit_error}. Le cours attend {expected_text}.",
            expected_answer=expected_text,
            errors=[unit_error],
        )
    if not value_ok:
        deviation = given["value"] - expected.value
        return _correction(
            question,
            status="incorrect",
            validation="deterministe",
            score=0.0,
            explanation=(
                f"Valeur incorrecte : le cours attend {expected_text} "
                f"(écart de {format_number(round(deviation, 6), None)})."
            ),
            expected_answer=expected_text,
            errors=["Valeur hors tolérance"],
        )
    return _correction(
        question,
        status="correct",
        validation="deterministe",
        score=FULL_SCORE,
        explanation=f"{question.explanation_template} Valeur conforme : {expected_text}.",
        expected_answer=expected_text,
    )


# --------------------------------------------------------------------------- #
# Open answer
# --------------------------------------------------------------------------- #


def grade_open(question: Question, answer: Any) -> Correction:
    _require_sourced(question)
    given = clean_text(answer, limit=4_000)
    checkpoints = list(question.reference_points)
    if not given:
        return _correction(
            question,
            status="non_evaluable",
            validation="humain",
            score=None,
            explanation="Aucune réponse fournie : rien à évaluer. Validation manuelle requise.",
            errors=["Réponse vide"],
        )
    return _correction(
        question,
        status="non_evaluable",
        validation=question.validation if question.validation != "deterministe" else "modele_ia",
        score=None,
        explanation=(
            "Question ouverte : la correction déterministe ne peut pas statuer. "
            "Le cours fournit des points de contrôle à faire vérifier par un modèle IA ou par une relecture humaine."
        ),
        expected_answer=None,
        errors=["Correction automatique impossible"],
        revision_targets=[question.notion_id] if question.notion_id else [],
    )


# --------------------------------------------------------------------------- #
# Progressive
# --------------------------------------------------------------------------- #


def grade_progressive(question: Question, answer: Any) -> Correction:
    _require_sourced(question)
    if not question.steps:
        return grade_open(question, answer)

    values = _step_values(question, answer)
    details: list[str] = []
    statuses: list[str] = []
    blocked = False
    total_weight = 0.0
    earned = 0.0
    errors: list[str] = []

    for step in question.steps:
        value = values.get(step.id)
        step_question = _step_as_question(question, step)
        result = _grade_step(step_question, step, value)
        statuses.append(result.status)
        weight = max(0.0, float(step.weight or 1.0))
        total_weight += weight
        if result.status == "non_evaluable":
            blocked = True
        elif result.score is not None:
            earned += result.score * weight
        errors.extend(f"{step.label} : {error}" for error in result.errors)
        details.append(
            f"{step.label} → {result.status}"
            + ("" if result.score is None else f" ({result.score}/{result.max_score:g})")
        )

    if blocked:
        return _correction(
            question,
            status="non_evaluable",
            validation="humain",
            score=None,
            explanation=(
                "Question progressive : une étape n'est pas vérifiable automatiquement. "
                + " | ".join(details)
            ),
            errors=errors or ["Étape non évaluable"],
        )
    ratio = (earned / total_weight) if total_weight else 0.0
    status = "correct" if ratio >= 1.0 - 1e-9 else ("partiel" if ratio > 0 else "incorrect")
    return _correction(
        question,
        status=status,
        validation="deterministe",
        score=round(ratio, 4),
        explanation=f"Question progressive. " + " | ".join(details),
        expected_answer={
            step.id: (step.expected.to_dict() if isinstance(step.expected, NumericAnswer) else step.expected)
            for step in question.steps
        },
        errors=errors,
    )


def _step_values(question: Question, answer: Any) -> dict[str, Any]:
    if isinstance(answer, dict):
        return {str(key): value for key, value in answer.items()}
    if isinstance(answer, (list, tuple)):
        return {question.steps[index].id: value for index, value in enumerate(answer) if index < len(question.steps)}
    if isinstance(answer, str) and len(question.steps) == 1:
        return {question.steps[0].id: answer}
    return {}


def _step_as_question(question: Question, step: QuestionStep) -> Question:
    expected_number = step.expected if isinstance(step.expected, NumericAnswer) else None
    return Question(
        id=step.id,
        question_type=step.question_type,
        prompt=f"{question.prompt} ({step.label})",
        notion_id=question.notion_id,
        source_refs=list(question.source_refs),
        expected_text=step.expected if isinstance(step.expected, str) else "",
        expected_keywords=list(step.keywords),
        expected_number=expected_number,
        explanation_template=question.explanation_template,
    )


def _grade_step(step_question: Question, step: QuestionStep, value: Any) -> Correction:
    if step.question_type == "numerique":
        return grade_numeric(step_question, value)
    if step.question_type == "qcm":
        return grade_multiple_choice(step_question, value)
    return grade_definition(step_question, value)


# --------------------------------------------------------------------------- #
# Entry point
# --------------------------------------------------------------------------- #

_GRADERS = {
    "qcm": grade_multiple_choice,
    "definition": grade_definition,
    "numerique": grade_numeric,
    "ouverte": grade_open,
    "progressif": grade_progressive,
}


def grade_answer(question: Question, answer: Any) -> Correction:
    """Correct one answer and always explain where the verdict comes from.

    The verdict only uses the course wording carried by the question, so the
    correction can be replayed and audited without re-reading the source.
    """

    grader = _GRADERS.get(question.question_type)
    if grader is None:
        raise GradingError(f"Type de question non géré : {question.question_type}.")
    if question.id == "":
        raise GradingError("La question doit avoir un identifiant.")
    correction = grader(question, answer)
    correction.grader = GRADING_VERSION
    return correction
