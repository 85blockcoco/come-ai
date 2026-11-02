"""Rappel actif VC avec règle d'espacement explicite et déterministe."""

from __future__ import annotations

from datetime import date, timedelta
from uuid import uuid4

from .models import Card, Review, SessionSummary
from .storage import VCStore


def _today(value: str | None) -> date:
    result = date.fromisoformat((value or date.today().isoformat())[:10])
    return result


def grade_card(card_id: str, quality: int, reviewed_on: str, previous: dict | None = None) -> Review:
    """Grade 0–5; les réponses faibles reviennent le lendemain."""
    if not card_id.strip() or isinstance(quality, bool) or not isinstance(quality, int) or not 0 <= quality <= 5:
        raise ValueError("La qualité doit être un entier de 0 à 5.")
    current = _today(reviewed_on)
    previous = previous or {}
    repetitions = int(previous.get("repetitions", 0)) + 1
    interval = 1 if quality < 3 else {3: 2, 4: 4, 5: 8}[quality]
    return Review(card_id, quality, current.isoformat(), (current + timedelta(days=interval)).isoformat(), interval, repetitions)


def start_session(store: VCStore, *, today: str | None = None, limit: int = 10, seed: int = 0, topic: str | None = None) -> tuple[str, list[Card]]:
    if isinstance(limit, bool) or not 1 <= limit <= 100:
        raise ValueError("Une session VC doit contenir de 1 à 100 cartes.")
    current = _today(today).isoformat()
    reviews = store.load_reviews()
    cards = [card for card in store.load_cards() if card.approved]
    if topic:
        cards = [card for card in cards if card.topic.casefold() == topic.strip().casefold()]
    due = [card for card in cards if card.id not in reviews or str(reviews[card.id].get("due_on", "")) <= current]
    # Stable ordering with an optional deterministic rotation for equal workloads.
    due.sort(key=lambda card: (card.topic.casefold(), card.id))
    if due and seed:
        offset = seed % len(due)
        due = due[offset:] + due[:offset]
    return uuid4().hex, due[:limit]


def submit_review(store: VCStore, card: Card, quality: int, *, reviewed_on: str | None = None) -> Review:
    previous = store.load_reviews().get(card.id)
    review = grade_card(card.id, quality, reviewed_on or date.today().isoformat(), previous)
    store.save_review(review)
    return review


def summarize_session(store: VCStore, card_ids: list[str], *, today: str | None = None, session_id: str = "") -> SessionSummary:
    current = _today(today).isoformat()
    reviews = store.load_reviews()
    selected = [reviews[card_id] for card_id in card_ids if card_id in reviews]
    mastered = sum(int(item.get("quality", 0)) >= 4 for item in selected)
    to_review = sum(int(item.get("quality", 0)) < 4 for item in selected)
    remaining = sum(1 for item in reviews.values() if str(item.get("due_on", "")) <= current)
    return SessionSummary(session_id, len(card_ids), len(selected), mastered, to_review, remaining, card_ids=tuple(card_ids))
