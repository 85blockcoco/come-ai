"""A small, local Career intake conversation.

The intake is intentionally deterministic: it asks a finite sequence of
questions, stores only the replies that a person enters, and does not call an
LLM to infer personal characteristics.  This keeps the feature useful when a
provider is unavailable and makes every saved preference easy to review.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .models import clean_text
from workspace_core import UserFacingError


MAX_INTAKE_ANSWER_CHARS = 1_500


@dataclass(frozen=True)
class IntakeQuestion:
    key: str
    question: str
    help_text: str


QUESTIONS: tuple[IntakeQuestion, ...] = (
    IntakeQuestion(
        "target_roles",
        "Quels stages, rôles ou métiers recherches-tu en priorité ?",
        "Ex. analyste M&A, private equity, conseil, finance d’entreprise…",
    ),
    IntakeQuestion(
        "locations",
        "Dans quelles villes ou quels pays souhaites-tu chercher ?",
        "Indique aussi si tu es mobile ou si certaines zones sont exclues.",
    ),
    IntakeQuestion(
        "sectors_companies",
        "Quels secteurs, entreprises ou types d’employeurs t’attirent ?",
        "Tu peux citer des entreprises, mais aussi des critères comme taille, culture ou secteur.",
    ),
    IntakeQuestion(
        "missions",
        "Quelles missions veux-tu particulièrement retrouver dans un stage ?",
        "Ex. modélisation, analyse stratégique, marchés, opérations, data…",
    ),
    IntakeQuestion(
        "strengths",
        "Quelles expériences ou compétences réelles veux-tu mettre en avant ?",
        "N’écris que des éléments que tu peux assumer et expliquer en entretien.",
    ),
    IntakeQuestion(
        "constraints",
        "As-tu des priorités, contraintes ou éléments à vérifier avant de candidater ?",
        "Ex. période, durée, langue du dossier, mobilité, format de stage. Ne partage que ce qui t’est utile.",
    ),
)


def normalize_answers(value: Any) -> dict[str, str]:
    """Keep only known, non-empty answer keys with bounded, display-safe text."""
    if not isinstance(value, dict):
        return {}
    result: dict[str, str] = {}
    valid_keys = {question.key for question in QUESTIONS}
    for key, raw in value.items():
        if key not in valid_keys:
            continue
        answer = clean_text(raw, limit=MAX_INTAKE_ANSWER_CHARS)
        if answer:
            result[key] = answer
    return result


def next_question(step_index: int) -> IntakeQuestion | None:
    return QUESTIONS[step_index] if 0 <= step_index < len(QUESTIONS) else None


def answer_for_step(answers: dict[str, str], step_index: int, value: Any) -> tuple[dict[str, str], int]:
    """Save one answer and return the next step.

    A question can only be answered in sequence.  That gives the browser a
    small conversational flow without ambiguous free-form state transitions.
    """
    question = next_question(step_index)
    if question is None:
        raise UserFacingError("Le mini-entretien Career est déjà terminé. Réinitialise-le pour recommencer.")
    answer = clean_text(value, limit=MAX_INTAKE_ANSWER_CHARS)
    if not answer:
        raise UserFacingError("Écris une réponse avant de continuer l’entretien Career.")
    updated = dict(normalize_answers(answers))
    updated[question.key] = answer
    return updated, step_index + 1


def serialize_intake(*, step_index: int, answers: dict[str, str], updated_at: str) -> dict[str, Any]:
    safe_answers = normalize_answers(answers)
    bounded_step = min(max(int(step_index), 0), len(QUESTIONS))
    current = next_question(bounded_step)
    transcript = [
        {
            "key": question.key,
            "question": question.question,
            "help_text": question.help_text,
            "answer": safe_answers.get(question.key, ""),
        }
        for index, question in enumerate(QUESTIONS)
        if question.key in safe_answers or index == bounded_step
    ]
    return {
        "step_index": bounded_step,
        "total_steps": len(QUESTIONS),
        "completed": bounded_step >= len(QUESTIONS),
        "answers": safe_answers,
        "current_question": (
            {"key": current.key, "question": current.question, "help_text": current.help_text}
            if current
            else None
        ),
        "transcript": transcript,
        "updated_at": updated_at,
    }
