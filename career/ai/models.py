"""Data models for the AI Arena."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal


TaskType = Literal["keywords", "reformulate", "letter", "score", "research"]


@dataclass
class IARequest:
    task_type: TaskType
    input_payload: dict
    model_hint: str | None = None


@dataclass
class IAResponse:
    provider: str
    model: str
    content: dict
    latency_ms: float
    cached: bool = False


@dataclass
class ArenaVerdict:
    winner: str
    merged_bullets: list[str] = field(default_factory=list)
    responses: list[IAResponse] = field(default_factory=list)
    jury_scores: dict[str, float] = field(default_factory=dict)
    disagreement: float = 0.0
