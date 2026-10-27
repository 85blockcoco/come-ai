"""Data models for the AI Arena (SPEC-017)."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

TaskType = Literal["keywords", "reformulate", "letter", "score", "research"]


@dataclass
class IARequest:
    """A request submitted to one or several AI providers."""

    task_type: TaskType
    input_payload: dict[str, Any]
    model_hint: str | None = None

    def __post_init__(self) -> None:
        if self.task_type not in {"keywords", "reformulate", "letter", "score", "research"}:
            raise ValueError("task_type inconnu pour l'arène IA.")
        if not isinstance(self.input_payload, dict):
            raise ValueError("input_payload doit être un dict.")
        if self.model_hint is not None and not isinstance(self.model_hint, str):
            raise ValueError("model_hint doit être une chaîne ou None.")


@dataclass
class IAResponse:
    """A single provider response."""

    provider: str
    model: str
    content: dict[str, Any] = field(default_factory=dict)
    latency_ms: float = 0.0
    cached: bool = False

    def __post_init__(self) -> None:
        if not isinstance(self.content, dict):
            if isinstance(self.content, (list, tuple)):
                self.content = {"items": list(self.content)}
            elif self.content is None:
                self.content = {}
            else:
                self.content = {"text": str(self.content)}
        if not isinstance(self.latency_ms, (int, float)):
            self.latency_ms = 0.0
        self.latency_ms = float(self.latency_ms)


@dataclass
class ArenaVerdict:
    """Aggregated result of an arena run."""

    winner: str
    merged_bullets: list[str] = field(default_factory=list)
    responses: list[IAResponse] = field(default_factory=list)
    jury_scores: dict[str, float] = field(default_factory=dict)
    disagreement: float = 0.0

    def __post_init__(self) -> None:
        self.disagreement = float(self.disagreement)
        self.jury_scores = {str(k): float(v) for k, v in (self.jury_scores or {}).items()}
        self.merged_bullets = [str(item) for item in (self.merged_bullets or [])]
        self.responses = list(self.responses or [])
