"""Stockage local borné du coach VC, hors dépôt et avec écritures atomiques."""

from __future__ import annotations

import json
import os
import tempfile
from datetime import date
from pathlib import Path
from typing import Any

from .models import Card, Review


def _safe_date(value: str | None) -> str:
    candidate = value or date.today().isoformat()
    date.fromisoformat(candidate[:10])
    return candidate[:10]


def _atomic_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    descriptor, temporary = tempfile.mkstemp(prefix=".vc-", dir=path.parent)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            json.dump(value, stream, ensure_ascii=False, indent=2)
            stream.flush()
            os.fsync(stream.fileno())
        os.chmod(temporary, 0o600)
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


class VCStore:
    """Cartes, réponses et échéances dans un dossier local dédié."""

    def __init__(self, root: str | Path | None = None):
        configured = root or os.environ.get("NAGE_VC_HOME") or (Path.home() / ".nage" / "vc")
        self.root = Path(configured).expanduser().absolute()
        self.root.mkdir(parents=True, exist_ok=True, mode=0o700)
        if self.root.is_symlink() or not self.root.is_dir():
            raise ValueError("Le stockage VC doit être un dossier local réel.")
        os.chmod(self.root, 0o700)
        self.cards_path = self.root / "deck.json"
        self.reviews_path = self.root / "reviews.json"
        self.exams_path = self.root / "exams.json"

    def save_cards(self, cards: list[Card]) -> None:
        seen: set[str] = set()
        payload = []
        for card in cards:
            if card.id in seen or not card.id.strip() or not card.front.strip() or not card.back.strip():
                raise ValueError("Chaque carte VC doit avoir un identifiant et un contenu uniques.")
            seen.add(card.id)
            payload.append({"id": card.id, "topic": card.topic, "front": card.front, "back": card.back,
                            "source": card.source, "approved": card.approved})
        _atomic_json(self.cards_path, payload)

    def load_cards(self) -> list[Card]:
        if not self.cards_path.is_file():
            return []
        payload = json.loads(self.cards_path.read_text(encoding="utf-8"))
        if not isinstance(payload, list):
            raise ValueError("Le paquet de cartes VC est invalide.")
        return [Card(**item) for item in payload if isinstance(item, dict)]

    def save_review(self, review: Review) -> None:
        reviews = self.load_reviews()
        reviews[review.card_id] = {
            "card_id": review.card_id, "quality": review.quality, "reviewed_on": _safe_date(review.reviewed_on),
            "due_on": _safe_date(review.due_on), "interval_days": review.interval_days,
            "repetitions": review.repetitions,
        }
        _atomic_json(self.reviews_path, reviews)

    def load_reviews(self) -> dict[str, dict[str, Any]]:
        if not self.reviews_path.is_file():
            return {}
        payload = json.loads(self.reviews_path.read_text(encoding="utf-8"))
        return payload if isinstance(payload, dict) else {}

    def save_exam(self, result: dict[str, Any]) -> None:
        exams = self.load_exams()
        exams.append(dict(result))
        _atomic_json(self.exams_path, exams[-100:])

    def load_exams(self) -> list[dict[str, Any]]:
        if not self.exams_path.is_file():
            return []
        payload = json.loads(self.exams_path.read_text(encoding="utf-8"))
        return [item for item in payload if isinstance(item, dict)] if isinstance(payload, list) else []
