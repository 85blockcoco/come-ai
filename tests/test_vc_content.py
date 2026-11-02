from __future__ import annotations

import json
from pathlib import Path

import pytest

from academics.vc.content import load_content
from academics.vc.errors import ContentError


def test_mvp_content_counts_and_curriculum_order() -> None:
    content = load_content()
    assert len(content.topics) >= 20
    assert len(content.cards) >= 50
    assert len(content.drills) >= 24
    assert len(content.cases) >= 4
    assert len(content.glossary) >= 42

    orders = [topic.order for topic in content.topics]
    assert orders == sorted(orders)
    assert len({topic.id for topic in content.topics}) == len(content.topics)
    assert len({topic.code for topic in content.topics}) == len(content.topics)


def test_every_card_belongs_to_a_known_topic_and_has_content() -> None:
    content = load_content()
    for card in content.cards:
        assert card.topic_id in content.topic_by_id
        assert card.question.strip()
        if card.status != "a_completer":
            assert card.answer.strip()


def test_every_drill_has_computable_steps_matching_the_answer() -> None:
    content = load_content()
    for drill in content.drills:
        assert drill.topic_id in content.topic_by_id
        assert drill.steps
        assert drill.variables
        assert all(value is not None for value in drill.variables.values())
        for step in drill.steps:
            assert set(step) >= {"label", "expression", "result"}
            assert str(step["label"]).strip()
            assert str(step["expression"]).strip()
        assert abs(float(drill.steps[-1]["result"]) - float(drill.answer)) <= 1e-6


def test_every_case_has_questions_and_normalized_weights() -> None:
    content = load_content()
    for case in content.cases:
        assert case.topic_id in content.topic_by_id
        assert case.questions
        total = sum(
            criterion.weight
            for question in case.questions
            for criterion in question.criteria
        )
        assert total == pytest.approx(1.0, abs=0.001)
        assert case.model_answer.strip()


def test_glossary_terms_are_unique_and_non_empty() -> None:
    content = load_content()
    french = [entry.term_fr.strip() for entry in content.glossary]
    english = [entry.term_en.strip() for entry in content.glossary]
    assert all(french)
    assert all(english)
    assert all(entry.example.strip() for entry in content.glossary)
    assert len(french) == len(set(french))
    assert len(english) == len(set(english))


def test_lookup_helpers_raise_content_error() -> None:
    content = load_content()
    with pytest.raises(ContentError):
        content.topic("VC99")
    with pytest.raises(ContentError):
        content.card("VC99-C999")
    with pytest.raises(ContentError):
        content.drill("VC99-D999")
    with pytest.raises(ContentError):
        content.case("VC99-CASE99")


def test_unsupported_schema_version_is_rejected(tmp_path: Path) -> None:
    (tmp_path / "topics.json").write_text(
        json.dumps({"schema_version": 99, "topics": []}), encoding="utf-8"
    )
    with pytest.raises(ContentError):
        load_content(tmp_path)


def test_duplicate_glossary_term_is_rejected_at_load_time(tmp_path: Path) -> None:
    (tmp_path / "topics.json").write_text(
        json.dumps(
            {
                "schema_version": 1,
                "topics": [
                    {
                        "id": "VC01",
                        "code": "VC01",
                        "title_fr": "Test",
                        "title_en": "Test",
                        "order": 1,
                        "exam_weight": 0.1,
                        "description": "Topic de test.",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    entry = {
        "kind": "glossary",
        "id": "VC01-G001",
        "topic_id": "VC01",
        "term_fr": "Capital-risque",
        "term_en": "Venture capital",
        "definition": "Définition originale.",
        "example": "Exemple original.",
    }
    duplicate = {**entry, "id": "VC01-G002", "term_fr": "capital risque"}
    (tmp_path / "glossary_bad.json").write_text(
        json.dumps(
            {
                "schema_version": 1,
                "pack_id": "glossary-bad",
                "topic_id": "VC01",
                "language": "fr",
                "source_type": "original",
                "license": "Test",
                "items": [entry, duplicate],
            }
        ),
        encoding="utf-8",
    )
    with pytest.raises(ContentError):
        load_content(tmp_path)


def test_duplicate_topic_is_rejected(tmp_path: Path) -> None:
    topic = {
        "id": "VC01",
        "code": "VC01",
        "title_fr": "Test",
        "title_en": "Test",
        "order": 1,
        "exam_weight": 0.1,
        "description": "Topic de test.",
    }
    (tmp_path / "topics.json").write_text(
        json.dumps({"schema_version": 1, "topics": [topic, topic]}), encoding="utf-8"
    )
    with pytest.raises(ContentError):
        load_content(tmp_path)
