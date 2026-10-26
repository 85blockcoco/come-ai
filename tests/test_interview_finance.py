"""Offline contract tests for the finance interview bank and rubric (CVBOOST-76)."""

from __future__ import annotations

import pytest

from career import finance_lexicon as lex
from career import interview_finance as bank


def test_bank_version_is_declared() -> None:
    assert bank.BANK_VERSION


def test_bank_has_at_least_120_questions() -> None:
    assert len(bank.QUESTION_BANK) >= 120


def test_question_ids_are_unique() -> None:
    ids = [question.id for question in bank.QUESTION_BANK]
    assert len(ids) == len(set(ids))


def test_every_family_has_at_least_twenty_questions() -> None:
    for family in bank.FAMILIES:
        count = len(bank.filter_questions(family=family))
        assert count >= 20, (family, count)


def test_every_question_is_wellformed() -> None:
    for question in bank.QUESTION_BANK:
        assert question.family in bank.FAMILIES, question.id
        assert question.seniority in bank.SENIORITY_LEVELS, question.id
        assert question.prompt_fr and question.prompt_en, question.id
        assert len(question.keyword_groups) >= 2, question.id
        assert question.reference_points, question.id


def test_every_family_covers_all_seniority_levels() -> None:
    for family in bank.FAMILIES:
        levels = {question.seniority for question in bank.filter_questions(family=family)}
        assert set(bank.SENIORITY_LEVELS) <= levels, family


def test_filter_questions_by_topic_is_deterministic() -> None:
    dcf = bank.filter_questions(family="corporate", topic="dcf")
    assert dcf == bank.filter_questions(family="corporate", topic="DCF")
    assert all(question.topic == "dcf" for question in dcf)


def test_filter_questions_rejects_unknown_family() -> None:
    with pytest.raises(ValueError):
        bank.filter_questions(family="cuisine")


def test_filter_questions_rejects_unknown_seniority() -> None:
    with pytest.raises(ValueError):
        bank.filter_questions(seniority="ceo")


def test_draw_sequence_is_deterministic_for_same_seed() -> None:
    first = bank.draw_sequence(role="M&A Analyst", seniority="analyst", count=5, seed=42)
    second = bank.draw_sequence(role="M&A Analyst", seniority="analyst", count=5, seed=42)
    assert first == second


def test_draw_sequence_without_seed_is_stable_across_calls() -> None:
    role, seniority, count = "Risk Analyst", "analyst", 4
    first = bank.draw_sequence(role=role, seniority=seniority, count=count)
    second = bank.draw_sequence(role=role, seniority=seniority, count=count)
    assert first == second


def test_draw_sequence_never_exceeds_requested_seniority() -> None:
    ceiling = bank._SENIORITY_RANK["stage"]
    for question in bank.draw_sequence(role=None, seniority="stage", count=15):
        assert bank._SENIORITY_RANK[question.seniority] <= ceiling


def test_draw_sequence_orders_easy_to_hard() -> None:
    sequence = bank.draw_sequence(role="FP&A", seniority="associate", count=8)
    ranks = [bank._SENIORITY_RANK[question.seniority] for question in sequence]
    assert ranks == sorted(ranks)


def test_draw_sequence_returns_requested_count_when_available() -> None:
    assert len(bank.draw_sequence(role="M&A Analyst", seniority="associate", count=10)) == 10


def test_draw_sequence_respects_role_family_mapping() -> None:
    for question in bank.draw_sequence(role="M&A Analyst", seniority="associate", count=20):
        assert question.family == "corporate"


def test_draw_sequence_broadens_pool_for_unknown_role() -> None:
    questions = bank.draw_sequence(role="Paléontologue", seniority="stage", count=3)
    assert len(questions) == 3


def test_draw_sequence_rejects_negative_count() -> None:
    with pytest.raises(ValueError):
        bank.draw_sequence(count=-1)


def test_draw_sequence_rejects_unknown_seniority() -> None:
    with pytest.raises(ValueError):
        bank.draw_sequence(seniority="vice_president")


def test_draw_sequence_with_explicit_seed_changes_selection() -> None:
    first = bank.draw_sequence(seniority="analyst", count=10, seed=1)
    second = bank.draw_sequence(seniority="analyst", count=10, seed=999)
    assert [question.id for question in first] != [question.id for question in second]


def test_score_answer_zero_on_empty_answer() -> None:
    question = bank.QUESTION_BANK[0]
    score = bank.score_answer(question, "")
    assert score["overall"] == 0
    assert score["too_short"] is True


def test_score_answer_handles_none_answer() -> None:
    score = bank.score_answer(bank.QUESTION_BANK[0], None)
    assert score["overall"] == 0
    assert score["feedback"]


def test_score_answer_full_reference_answer_scores_well() -> None:
    question = bank.filter_questions(family="corporate", topic="dcf", seniority="stage")[0]
    strong = " ".join(question.reference_points) + " Ensuite donc donc, conclusion : environ 60%."
    score = bank.score_answer(question, strong)
    assert score["completeness"] == 100
    assert score["overall"] >= 70


def test_score_answer_is_deterministic() -> None:
    question = bank.QUESTION_BANK[5]
    answer = "Premier point : les flux. Ensuite l'actualisation, donc la valeur terminale."
    assert bank.score_answer(question, answer) == bank.score_answer(question, answer)


def test_score_answer_reports_missing_reference_ideas() -> None:
    question = bank.QUESTION_BANK[0]
    score = bank.score_answer(question, "Je ne sais pas trop quoi répondre ici honnêtement, désolé.")
    assert score["missing_keywords"]
    assert any("manquantes" in message for message in score["feedback"])


def test_score_answer_stays_within_bounds() -> None:
    question = bank.QUESTION_BANK[1]
    for answer in ("", "x" * 3, "flux actualisation wacc terminale entreprise dette nette " * 12):
        score = bank.score_answer(question, answer)
        assert 0 <= score["overall"] <= 100
        assert 0 <= score["completeness"] <= 100
        assert 0 <= score["structure"] <= 100
        assert 0 <= score["precision"] <= 100


def test_score_answer_structure_markers_lift_structure_axis() -> None:
    question = bank.QUESTION_BANK[2]
    flat = "le taux d actualisation mesure le cout du capital risque prime incertitude temps horizon " * 4
    structured = "D'abord le taux, ensuite le risque, donc la prime, enfin la conclusion. " + flat
    assert bank.score_answer(question, structured)["structure"] > bank.score_answer(question, flat)["structure"]


def test_rubric_weights_are_fixed_and_sum_to_one() -> None:
    assert bank.RUBRIC_WEIGHTS == {"completeness": 0.5, "structure": 0.3, "precision": 0.2}
    assert sum(bank.RUBRIC_WEIGHTS.values()) == pytest.approx(1.0)


def test_no_network_module_is_imported() -> None:
    source = open(bank.__file__).read()
    for forbidden in ("import requests", "import socket", "urllib", "http.client", "api_key"):
        assert forbidden not in source


def test_faq_entries_are_flat_records() -> None:
    entries = bank.faq_entries()
    assert len(entries) == len(bank.QUESTION_BANK)
    assert set(entries[0]) == {
        "id",
        "family",
        "topic",
        "seniority",
        "prompt_fr",
        "prompt_en",
    }


def test_faq_entries_filter_by_topic() -> None:
    entries = bank.faq_entries(topic="fx")
    assert entries
    assert all(entry["topic"] == "fx" for entry in entries)


def test_role_to_family_mapping_covers_every_lexicon_family() -> None:
    assert set(bank.ROLE_QUESTION_FAMILIES) == set(lex.FAMILIES)
    assert set(bank.ROLE_QUESTION_FAMILIES.values()) <= set(bank.FAMILIES)


def test_draw_sequence_and_lexicon_integration() -> None:
    canonical = lex.resolve_role("Stage fusions-acquisitions")
    assert canonical == "M&A Analyst"
    questions = bank.draw_sequence(role=canonical, seniority="stage", count=5, seed=3)
    assert questions
    first_score = bank.score_answer(questions[0], " ".join(questions[0].reference_points) * 6)
    assert first_score["overall"] >= 0
