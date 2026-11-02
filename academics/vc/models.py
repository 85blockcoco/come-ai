"""Modèles immuables du rappel actif Venture Capital."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class Card:
    id: str
    topic: str
    front: str
    back: str
    source: str = "VC core"
    approved: bool = True


@dataclass(frozen=True)
class Review:
    card_id: str
    quality: int
    reviewed_on: str
    due_on: str
    interval_days: int
    repetitions: int


@dataclass(frozen=True)
class SessionSummary:
    session_id: str
    offered: int
    answered: int
    mastered: int
    to_review: int
    remaining_due: int
    interrupted: bool = False
    card_ids: tuple[str, ...] = field(default_factory=tuple)
