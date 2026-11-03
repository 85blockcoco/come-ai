"""Load and validate the original VC content packs."""

from __future__ import annotations

import json
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any, Iterable

from .cases import normalize_text
from .drills import parse_number
from .errors import ContentError
from .models import (
    CARD_STATUSES,
    ERROR_CATEGORIES,
    UNITS,
    CaseStudy,
    CourseTopic,
    ExamQuestion,
    Flashcard,
    FormulaDrill,
    GlossaryEntry,
)

CONTENT_SCHEMA_VERSION = 1
CONTENT_DIR = Path(__file__).resolve().parent / "content"


@dataclass
class ContentPack:
    schema_version: int
    topics: tuple[CourseTopic, ...]
    cards: tuple[Flashcard, ...] = ()
    drills: tuple[FormulaDrill, ...] = ()
    cases: tuple[CaseStudy, ...] = ()
    glossary: tuple[GlossaryEntry, ...] = ()
    exams: tuple[ExamQuestion, ...] = ()
    topic_by_id: dict[str, CourseTopic] = field(default_factory=dict)
    card_by_id: dict[str, Flashcard] = field(default_factory=dict)
    drill_by_id: dict[str, FormulaDrill] = field(default_factory=dict)
    case_by_id: dict[str, CaseStudy] = field(default_factory=dict)
    exam_by_id: dict[str, ExamQuestion] = field(default_factory=dict)

    def topic(self, topic_id: str) -> CourseTopic:
        try:
            return self.topic_by_id[topic_id]
        except KeyError as error:
            raise ContentError(f"Topic inconnu : {topic_id}") from error

    def card(self, card_id: str) -> Flashcard:
        try:
            return self.card_by_id[card_id]
        except KeyError as error:
            raise ContentError(f"Carte inconnue : {card_id}") from error

    def drill(self, drill_id: str) -> FormulaDrill:
        try:
            return self.drill_by_id[drill_id]
        except KeyError as error:
            raise ContentError(f"Drill inconnu : {drill_id}") from error

    def case(self, case_id: str) -> CaseStudy:
        try:
            return self.case_by_id[case_id]
        except KeyError as error:
            raise ContentError(f"Cas inconnu : {case_id}") from error

    def exam_question(self, question_id: str) -> ExamQuestion:
        try:
            return self.exam_by_id[question_id]
        except KeyError as error:
            raise ContentError(f"Question d'examen inconnue : {question_id}") from error

    def with_cards(self, cards: Iterable[Flashcard]) -> "ContentPack":
        """Return a copy that also exposes approved note cards.

        Original cards win on an identifier collision and only active cards are
        merged, so a rejected or incomplete proposal can never enter a session.
        """
        merged = list(self.cards)
        known = {card.id for card in merged}
        for card in cards:
            if card.status != "active" or card.id in known:
                continue
            merged.append(card)
            known.add(card.id)
        return replace(
            self,
            cards=tuple(merged),
            card_by_id={card.id: card for card in merged},
        )


def _read_json(path: Path) -> dict[str, Any]:
    try:
        with path.open("r", encoding="utf-8") as handle:
            payload = json.load(handle)
    except FileNotFoundError as error:
        raise ContentError(f"Fichier de contenu introuvable : {path.name}") from error
    except json.JSONDecodeError as error:
        raise ContentError(f"JSON invalide dans {path.name} : {error.msg}") from error
    except OSError as error:
        raise ContentError(f"Lecture impossible : {path.name}") from error
    if not isinstance(payload, dict):
        raise ContentError(f"Le pack {path.name} doit être un objet JSON.")
    version = payload.get("schema_version")
    if version != CONTENT_SCHEMA_VERSION:
        raise ContentError(
            f"Version de pack non supportée dans {path.name} : {version!r}."
        )
    return payload


def _items(payload: dict[str, Any], path: Path) -> list[dict[str, Any]]:
    items = payload.get("items")
    if not isinstance(items, list):
        raise ContentError(f"Le pack {path.name} doit contenir une liste 'items'.")
    for index, item in enumerate(items):
        if not isinstance(item, dict):
            raise ContentError(f"Item {index} invalide dans {path.name}.")
    return items


def _topic_id(item: dict[str, Any], path: Path) -> str:
    topic_id = item.get("topic_id")
    if not isinstance(topic_id, str) or not topic_id:
        raise ContentError(f"topic_id manquant dans {path.name}.")
    return topic_id


def _citation(item: dict[str, Any], path: Path) -> dict[str, str] | None:
    citation = item.get("citation")
    if citation is None:
        return None
    if not isinstance(citation, dict):
        raise ContentError(f"citation invalide dans {path.name}.")
    for key in ("source_id", "locator", "quote"):
        if not isinstance(citation.get(key), str) or not citation[key].strip():
            raise ContentError(f"citation incomplète dans {path.name}.")
    return {key: citation[key] for key in ("source_id", "locator", "quote")}


def _load_topics(path: Path) -> tuple[CourseTopic, ...]:
    payload = _read_json(path)
    raw = payload.get("topics")
    if not isinstance(raw, list) or not raw:
        raise ContentError("topics.json doit contenir une liste non vide 'topics'.")
    topics: list[CourseTopic] = []
    seen: set[str] = set()
    for item in raw:
        if not isinstance(item, dict):
            raise ContentError("Topic invalide dans topics.json.")
        topic = CourseTopic.from_dict(item)
        if topic.id in seen:
            raise ContentError(f"Topic dupliqué : {topic.id}")
        seen.add(topic.id)
        if not 0 <= topic.exam_weight <= 1:
            raise ContentError(f"exam_weight hors [0,1] pour {topic.id}.")
        topics.append(topic)
    return tuple(sorted(topics, key=lambda item: item.order))


def _load_cards(path: Path, topic_ids: set[str]) -> list[Flashcard]:
    payload = _read_json(path)
    cards: list[Flashcard] = []
    for item in _items(payload, path):
        if item.get("kind") != "card":
            raise ContentError(f"Item non-card dans {path.name}.")
        topic_id = _topic_id(item, path)
        if topic_id not in topic_ids:
            raise ContentError(f"Topic inconnu {topic_id} dans {path.name}.")
        card = Flashcard.from_dict(item)
        if card.status not in CARD_STATUSES:
            raise ContentError(f"Statut de carte invalide : {card.status} ({card.id}).")
        if card.status != "a_completer" and not card.answer.strip():
            raise ContentError(f"Réponse vide pour la carte {card.id}.")
        citation = _citation(item, path)
        if card.source_type == "user_note" and citation is None:
            raise ContentError(f"Citation obligatoire pour la carte importée {card.id}.")
        card = Flashcard(
            id=card.id,
            topic_id=card.topic_id,
            question=card.question,
            answer=card.answer,
            explanation=card.explanation,
            source_type=card.source_type,
            citation=citation,
            status=card.status,
            version=card.version,
            tags=card.tags,
        )
        cards.append(card)
    return cards


def _load_drills(path: Path, topic_ids: set[str]) -> list[FormulaDrill]:
    payload = _read_json(path)
    drills: list[FormulaDrill] = []
    for item in _items(payload, path):
        if item.get("kind") != "drill":
            raise ContentError(f"Item non-drill dans {path.name}.")
        topic_id = _topic_id(item, path)
        if topic_id not in topic_ids:
            raise ContentError(f"Topic inconnu {topic_id} dans {path.name}.")
        drill = FormulaDrill.from_dict(item)
        if drill.answer_unit not in UNITS:
            raise ContentError(f"Unité invalide pour {drill.id} : {drill.answer_unit}.")
        if drill.tolerance <= 0:
            raise ContentError(f"Tolérance invalide pour {drill.id}.")
        if not drill.steps:
            raise ContentError(f"Étapes manquantes pour {drill.id}.")
        for step in drill.steps:
            if not isinstance(step, dict) or not {"label", "expression", "result"} <= set(step):
                raise ContentError(f"Étape invalide pour {drill.id}.")
        for error_path in drill.error_paths:
            if error_path.get("category") not in ERROR_CATEGORIES:
                raise ContentError(f"Catégorie d'erreur invalide pour {drill.id}.")
        drills.append(drill)
    return drills


def _load_cases(path: Path, topic_ids: set[str]) -> list[CaseStudy]:
    payload = _read_json(path)
    cases: list[CaseStudy] = []
    for item in _items(payload, path):
        if item.get("kind") != "case":
            raise ContentError(f"Item non-case dans {path.name}.")
        topic_id = _topic_id(item, path)
        if topic_id not in topic_ids:
            raise ContentError(f"Topic inconnu {topic_id} dans {path.name}.")
        case = CaseStudy.from_dict(item)
        if not case.questions:
            raise ContentError(f"Aucune question pour le cas {case.id}.")
        total_weight = 0.0
        for question in case.questions:
            if not question.criteria:
                raise ContentError(f"Aucun critère pour {case.id}/{question.id}.")
            for criterion in question.criteria:
                total_weight += criterion.weight
                for expected in criterion.expected_numbers:
                    value = float(expected.get("value", 0))
                    if not any(abs(value - allowed) <= 1e-6 for allowed in case.allowed_numbers):
                        raise ContentError(
                            f"Nombre attendu {value} absent de allowed_numbers pour {case.id}."
                        )
        if abs(total_weight - 1.0) > 0.001:
            raise ContentError(f"Les poids du cas {case.id} ne somment pas à 1.0.")
        cases.append(case)
    return cases


def _load_glossary(path: Path, topic_ids: set[str]) -> list[GlossaryEntry]:
    payload = _read_json(path)
    entries: list[GlossaryEntry] = []
    for item in _items(payload, path):
        if item.get("kind") != "glossary":
            raise ContentError(f"Item non-glossary dans {path.name}.")
        topic_id = _topic_id(item, path)
        if topic_id not in topic_ids:
            raise ContentError(f"Topic inconnu {topic_id} dans {path.name}.")
        entry = GlossaryEntry.from_dict(item)
        if not entry.term_fr.strip() or not entry.term_en.strip():
            raise ContentError(f"Terme vide dans {path.name}.")
        entries.append(entry)
    return entries


def _load_exams(
    path: Path, topic_ids: set[str], card_ids: set[str]
) -> list[ExamQuestion]:
    payload = _read_json(path)
    questions: list[ExamQuestion] = []
    for item in _items(payload, path):
        if item.get("kind") != "exam_question":
            raise ContentError(f"Item non-exam_question dans {path.name}.")
        topic_id = _topic_id(item, path)
        if topic_id not in topic_ids:
            raise ContentError(f"Topic inconnu {topic_id} dans {path.name}.")
        question = ExamQuestion.from_dict(item)
        if question.format not in ("mcq", "numeric", "open"):
            raise ContentError(f"Format d'examen invalide pour {question.id}.")
        if not isinstance(question.points, int) or isinstance(question.points, bool):
            raise ContentError(f"Points non entiers pour {question.id}.")
        if not 1 <= question.points <= 100:
            raise ContentError(f"Points hors [1,100] pour {question.id}.")
        if len(question.question.strip()) < 8 or not question.answer.strip():
            raise ContentError(f"Question ou réponse vide pour {question.id}.")
        if question.source_card_id and question.source_card_id not in card_ids:
            raise ContentError(
                f"Carte source inconnue {question.source_card_id} pour {question.id}."
            )
        if question.format == "mcq":
            if len(question.choices) < 2:
                raise ContentError(f"QCM sans choix suffisants pour {question.id}.")
            if len(set(question.choices)) != len(question.choices):
                raise ContentError(f"Choix dupliqués pour {question.id}.")
            if question.answer not in question.choices:
                raise ContentError(
                    f"Réponse hors choix pour {question.id} : {question.answer!r}."
                )
        elif question.format == "numeric":
            if question.unit not in UNITS:
                raise ContentError(f"Unité d'examen invalide pour {question.id}.")
            if question.tolerance < 0:
                raise ContentError(f"Tolérance négative pour {question.id}.")
            try:
                parse_number(question.answer, question.unit)
            except ValueError as error:
                raise ContentError(
                    f"Réponse numérique invalide pour {question.id} : {question.answer!r}."
                ) from error
        else:
            if not question.keywords:
                raise ContentError(f"Mots-clés manquants pour {question.id}.")
            if any(not keyword.strip() for keyword in question.keywords):
                raise ContentError(f"Mot-clé vide pour {question.id}.")
            if not 1 <= question.min_keywords <= len(question.keywords):
                raise ContentError(
                    f"min_keywords hors bornes pour {question.id}."
                )
        questions.append(question)
    return questions


def _check_unique_glossary(entries: list[GlossaryEntry]) -> None:
    french: set[str] = set()
    english: set[str] = set()
    for entry in entries:
        term_fr = normalize_text(entry.term_fr)
        term_en = normalize_text(entry.term_en)
        if term_fr in french:
            raise ContentError(f"Terme FR dupliqué : {entry.term_fr}")
        if term_en in english:
            raise ContentError(f"Terme EN dupliqué : {entry.term_en}")
        french.add(term_fr)
        english.add(term_en)


def _check_unique(items: list[Any], label: str) -> None:
    seen: set[str] = set()
    for item in items:
        identifier = item.id if hasattr(item, "id") else item.get("id")
        if not identifier:
            raise ContentError(f"{label} sans identifiant.")
        if identifier in seen:
            raise ContentError(f"{label} dupliqué : {identifier}")
        seen.add(identifier)


def load_content(path: Path | None = None) -> ContentPack:
    directory = Path(path) if path is not None else CONTENT_DIR
    topics = _load_topics(directory / "topics.json")
    topic_ids = {topic.id for topic in topics}
    cards: list[Flashcard] = []
    drills: list[FormulaDrill] = []
    cases: list[CaseStudy] = []
    glossary: list[GlossaryEntry] = []
    exams: list[ExamQuestion] = []
    for file in sorted(directory.glob("cards_*.json")):
        cards.extend(_load_cards(file, topic_ids))
    for file in sorted(directory.glob("drills_*.json")):
        drills.extend(_load_drills(file, topic_ids))
    for file in sorted(directory.glob("cases_*.json")):
        cases.extend(_load_cases(file, topic_ids))
    for file in sorted(directory.glob("glossary_*.json")):
        glossary.extend(_load_glossary(file, topic_ids))
    card_ids = {card.id for card in cards}
    for file in sorted(directory.glob("exams_*.json")):
        exams.extend(_load_exams(file, topic_ids, card_ids))
    _check_unique(cards, "Carte")
    _check_unique(drills, "Drill")
    _check_unique(cases, "Cas")
    _check_unique(exams, "Question d'examen")
    _check_unique_glossary(glossary)
    return ContentPack(
        schema_version=CONTENT_SCHEMA_VERSION,
        topics=topics,
        cards=tuple(cards),
        drills=tuple(drills),
        cases=tuple(cases),
        glossary=tuple(glossary),
        exams=tuple(exams),
        topic_by_id={topic.id: topic for topic in topics},
        card_by_id={card.id: card for card in cards},
        drill_by_id={drill.id: drill for drill in drills},
        case_by_id={case.id: case for case in cases},
        exam_by_id={question.id: question for question in exams},
    )
