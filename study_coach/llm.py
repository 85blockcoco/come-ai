"""Optional seam for a free model, kept out of the default path.

The engine is fully usable offline: every question it generates and every
correction it produces are deterministic.  This module only defines *where* a
model would plug in, and it refuses loudly by default so that no study session
can ever trigger a network call the user did not ask for.

A real integration (Codex can reuse ``free_ai_router`` / ``hybrid_chat``) simply
implements :class:`QuestionGenerator` and passes it to
``StudyCoach(..., generator=..., allow_model_calls=True)``.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable

from .errors import OfflineViolation
from .models import clean_text


@dataclass(frozen=True)
class GenerationRequest:
    """What a model would be allowed to see: course passages, nothing else."""

    course_title: str
    notion_title: str
    notion_statement: str
    source_excerpt: str
    families: tuple[str, ...] = ("ouverte",)
    max_questions: int = 3
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "course_title": self.course_title,
            "notion_title": self.notion_title,
            "notion_statement": self.notion_statement,
            "source_excerpt": self.source_excerpt,
            "families": list(self.families),
            "max_questions": self.max_questions,
            "metadata": dict(self.metadata),
        }


@runtime_checkable
class QuestionGenerator(Protocol):
    """Contract of an optional external generator."""

    name: str

    def generate_questions(self, request: GenerationRequest) -> list[dict[str, Any]]:
        """Return question payloads **with** their source excerpt, or an empty list."""


class NullQuestionGenerator:
    """Default generator: refuses, so nothing can leave the machine."""

    name = "aucun"

    def generate_questions(self, request: GenerationRequest) -> list[dict[str, Any]]:
        raise OfflineViolation(
            "Aucun générateur de questions n'est configuré : le mode hors ligne reste actif."
        )


class DisabledModelCall(OfflineViolation):
    """Raised when model calls are explicitly disabled but requested."""


def ensure_model_calls_allowed(generator: Any, allowed: bool) -> None:
    """Refuse a model call unless it was both configured and authorised."""

    if not allowed:
        raise DisabledModelCall(
            "Les appels modèle sont désactivés (StudyCoach.allow_model_calls=False) : "
            "seule la correction déterministe est disponible."
        )
    if generator is None:
        raise DisabledModelCall(
            "Aucun générateur de questions n'est fourni : passe un générateur conforme "
            "à study_coach.llm.QuestionGenerator."
        )


def sanitize_request_text(value: Any, *, limit: int = 2_000) -> str:
    """Last line of defence before anything leaves the machine."""

    return clean_text(value, limit=limit)
