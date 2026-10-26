"""SPEC-027 — deterministic STAR interview simulator (local only)."""

from __future__ import annotations

import ast
import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from career.interview_sim import (
    KINDS,
    MIN_QUESTIONS,
    InterviewQuestion,
    StarWorksheet,
    build_question_set,
    build_questions,
    build_worksheet,
    evidence_checklist,
    generate_question_set,
    get_question_set,
    load_fixtures,
    self_score,
)
from come_ai_web import create_app


FIXTURES = Path(__file__).parent / "fixtures"
MODULE_PATH = Path(__file__).resolve().parents[1] / "career" / "interview_sim.py"

FULL_STAR = {
    "situation": "Lors de mon stage de six mois dans une banque, l’équipe devait préparer un dossier client synthétique en trois jours.",
    "task": "Je devais produire la partie valorisation du dossier et vérifier les données comptables transmises par un autre service.",
    "action": "J’ai construit le modèle DCF, contrôlé les écarts avec le fichier source et présenté les hypothèses à l’associé.",
    "result": "Le dossier a été livré avec 2 jours d’avance et le client a validé la recommandation sans correction majeure.",
}


def _offers() -> list[dict]:
    return json.loads((FIXTURES / "interview_offers_synthetic.json").read_text(encoding="utf-8"))["offers"]


def _offer(fixture_id: str) -> dict:
    return next(offer for offer in _offers() if offer["id"] == fixture_id)


class _FakeAgent:
    def provider_status(self) -> dict[str, object]:
        return {
            "gemini": {"configured": False, "primary_model": "fake", "fallback_models": []},
            "ollama": {"configured": False, "model": None},
            "request_timeout_seconds": 30,
            "retry_attempts": 1,
        }

    def ask(self, message: str, *, allow_writes: bool) -> dict[str, object]:
        return {"answer": "sans appel fournisseur", "tool_events": [], "provider": "Faux modèle"}


def _client(tmp_path: Path) -> TestClient:
    return TestClient(create_app(tmp_path, agent_override=_FakeAgent()))


def _import_offer(client: TestClient, offer: dict) -> dict:
    payload = {
        "company": offer["company"],
        "title": offer["title"],
        "source_name": "manual",
        "city": offer["city"],
        "country": offer["country"],
        "requirements": offer["requirements"],
        "description_original": offer["description_original"],
    }
    response = client.post("/api/career/jobs/import", json=payload)
    assert response.status_code == 201
    return response.json()


# ---------------------------------------------------------------------------
# Question scheduling
# ---------------------------------------------------------------------------


def test_every_synthetic_offer_gets_at_least_twelve_questions_and_four_kinds() -> None:
    for offer in _offers():
        questions = build_question_set(offer)
        assert len(questions) >= MIN_QUESTIONS
        assert {question.kind for question in questions} == set(KINDS)
        assert all(question.question.strip() for question in questions)
        assert len({question.id for question in questions}) == len(questions)


def test_question_generation_is_deterministic_for_a_given_seed() -> None:
    offer = _offer("finance-ma")
    first = build_question_set(offer, seed=7)
    second = build_question_set(offer, seed=7)
    assert first == second
    assert [question.id for question in first] == [question.id for question in second]


def test_seed_changes_order_without_dropping_a_kind() -> None:
    offer = _offer("data-intern")
    first = build_question_set(offer, seed=0)
    second = build_question_set(offer, seed=5)
    assert [question.id for question in first] != [question.id for question in second]
    assert {question.kind for question in first} == {question.kind for question in second} == set(KINDS)


def test_mapping_insertion_order_does_not_change_questions() -> None:
    offer = _offer("consulting-intern")
    reordered = dict(reversed(list(offer.items())))
    assert build_question_set(offer, seed=3) == build_question_set(reordered, seed=3)


def test_technical_questions_reuse_offer_keywords() -> None:
    questions = build_question_set(_offer("data-intern"), seed=0)
    technical = [question.question for question in questions if question.kind == "technical"]
    assert any("Python" in text for text in technical)
    assert any(question.kind == "technical" and "SQL" in question.question for question in questions)


def test_empty_or_unknown_offer_still_produces_a_complete_set() -> None:
    for offer in (None, {}, {"title": None, "requirements": []}, "not-a-mapping"):
        questions = build_question_set(offer)  # type: ignore[arg-type]
        assert len(questions) >= MIN_QUESTIONS
        assert {question.kind for question in questions} == set(KINDS)


def test_limit_is_bounded_and_never_drops_below_the_contract() -> None:
    assert len(build_question_set(_offer("finance-ma"), limit=1)) >= MIN_QUESTIONS
    assert len(build_question_set(_offer("finance-ma"), limit=999)) <= 40


def test_evidence_prompts_are_unique_and_concrete() -> None:
    for question in build_question_set(_offer("finance-ma")):
        assert 2 <= len(question.evidence_needed) <= 4
        assert len(set(question.evidence_needed)) == len(question.evidence_needed)
        assert all(len(item) >= 12 for item in question.evidence_needed)


def test_questions_are_available_in_english_with_stable_ids() -> None:
    offer = _offer("consulting-intern")
    french = build_question_set(offer, seed=2, language="fr")
    english = build_question_set(offer, seed=2, language="en")
    assert [question.id for question in french] == [question.id for question in english]
    assert any("What do you know about" in question.question for question in english)
    assert any("Que sais-tu de" in question.question for question in french)


def test_adversarial_offer_values_are_bounded_and_never_injected() -> None:
    hostile = {
        "title": "Stagiaire <script>alert(1)</script>\x00" + "x" * 50_000,
        "company": {"nested": "value"},
        "requirements": ["Excel", {"unexpected": "python"}, None, 42],
        "description_original": "Étude de marché " * 5_000,
    }
    questions = build_question_set(hostile, seed=-9)
    assert len(questions) >= MIN_QUESTIONS
    for question in questions:
        assert "\x00" not in question.question
        assert len(question.question) < 1_000
        assert question.kind in KINDS


# ---------------------------------------------------------------------------
# STAR worksheets and self-assessment
# ---------------------------------------------------------------------------


def test_blank_worksheet_has_zero_completeness() -> None:
    question = build_question_set(_offer("finance-ma"))[0]
    worksheet = build_worksheet(question)
    assert worksheet.completeness == 0.0
    assert self_score(worksheet)["score"] == 0
    assert self_score(worksheet)["label"] == "À compléter"


def test_complete_worksheet_reaches_full_completeness() -> None:
    question = build_question_set(_offer("finance-ma"))[0]
    worksheet = build_worksheet(question, **FULL_STAR)
    assert worksheet.completeness == 1.0
    assert self_score(worksheet)["completeness"] == 1.0


def test_partial_worksheet_is_bounded_and_monotonic() -> None:
    question = build_question_set(_offer("finance-ma"))[0]
    short = build_worksheet(question, situation="Un stage.")
    medium = build_worksheet(question, situation=FULL_STAR["situation"], action=FULL_STAR["action"])
    assert 0.0 < short.completeness < medium.completeness < 1.0
    assert 0 < self_score(short)["score"] < self_score(medium)["score"] <= 100


def test_self_score_is_transparent_and_bounded() -> None:
    question = build_question_set(_offer("finance-ma"))[0]
    worksheet = build_worksheet(question, **FULL_STAR)
    assessment = self_score(worksheet, question=question)
    assert assessment["score"] == 100
    assert assessment["label"] == "Structure solide"
    assert set(assessment["parts"]) == {"situation", "task", "action", "result"}
    assert sum(part["max_points"] for part in assessment["parts"].values()) == 90
    assert all(0 <= part["points"] <= part["max_points"] for part in assessment["parts"].values())
    assert assessment["quality_flags"] == {"quantified_result": True, "personal_action": True}
    assert assessment["disclaimer"]
    assert 0 <= assessment["score"] <= 100


def test_self_score_flags_missing_numbers_and_personal_ownership() -> None:
    question = build_question_set(_offer("finance-ma"))[0]
    worksheet = build_worksheet(
        question,
        situation="Pendant un projet d’école, nous devions analyser une entreprise cotée sur plusieurs années.",
        task="Le groupe devait rendre une note de synthèse avant la fin du semestre universitaire.",
        action="Le groupe a construit le modèle puis a présenté les conclusions au professeur référent.",
        result="La note a été rendue dans les délais et le professeur a souligné la clarté du raisonnement.",
    )
    assessment = self_score(worksheet)
    assert assessment["quality_flags"] == {"quantified_result": False, "personal_action": False}
    assert any("résultat chiffré" in item for item in assessment["advice"])
    assert any("personnellement" in item for item in assessment["advice"])


def test_evidence_checklist_tracks_coverage_without_inventing_proof() -> None:
    question = build_question_set(_offer("data-intern"))[0]
    labels = list(question.evidence_needed)
    worksheet = build_worksheet(question, **FULL_STAR, evidence_checked=[labels[0]])
    checklist = evidence_checklist(question, checked=worksheet.evidence_checked)
    assessment = self_score(worksheet, question=question)
    assert checklist[0] == {"label": labels[0], "checked": True}
    assert [item["label"] for item in checklist if not item["checked"]] == assessment["evidence_missing"]
    assert assessment["evidence_coverage"] == round(1 / len(labels), 3)


def test_worksheet_requires_a_real_question_object() -> None:
    with pytest.raises(TypeError):
        build_worksheet("not-a-question")  # type: ignore[arg-type]


def test_worksheet_cleans_fields_and_deduplicates_evidence() -> None:
    question = build_question_set(_offer("finance-ma"))[0]
    worksheet = StarWorksheet(
        question_id=f"  {question.id}\x00  ",
        situation="  " + "Situation utile " * 400,
        evidence_checked=["Preuve A", "Preuve A", " ", None],  # type: ignore[list-item]
    )
    assert worksheet.question_id == question.id
    assert "\x00" not in worksheet.question_id
    assert len(worksheet.situation) <= 4_000
    assert worksheet.evidence_checked == ["Preuve A"]


def test_module_has_no_network_imports() -> None:
    tree = ast.parse(MODULE_PATH.read_text(encoding="utf-8"))
    imported: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.append(node.module)
    forbidden = ("requests", "httpx", "urllib", "socket", "http", "aiohttp", "openai", "google")
    assert not [name for name in imported if name.startswith(forbidden)]


# ---------------------------------------------------------------------------
# REST API (create_app)
# ---------------------------------------------------------------------------


def test_health_exposes_the_local_interview_simulator(tmp_path: Path) -> None:
    health = _client(tmp_path).get("/api/career/health")
    assert health.status_code == 200
    simulator = health.json()["interview_sim"]
    assert simulator["local_only"] is True
    assert simulator["provider_required"] is False
    assert simulator["recruitment_probability"] is False
    assert simulator["min_questions_per_offer"] == MIN_QUESTIONS


def test_api_lists_questions_for_a_saved_offer(tmp_path: Path) -> None:
    client = _client(tmp_path)
    offer = _import_offer(client, _offer("finance-ma"))
    response = client.get(f"/api/career/interview-sim/questions/{offer['id']}", params={"seed": 4})
    assert response.status_code == 200
    payload = response.json()
    assert payload["job_id"] == offer["id"]
    assert payload["kinds"] == list(KINDS)
    assert len(payload["questions"]) >= MIN_QUESTIONS
    assert all(set(question) == {"id", "kind", "question", "evidence_needed"} for question in payload["questions"])
    assert payload["disclaimer"]


def test_api_returns_a_worksheet_then_scores_it(tmp_path: Path) -> None:
    client = _client(tmp_path)
    offer = _import_offer(client, _offer("data-intern"))
    questions = client.get(f"/api/career/interview-sim/questions/{offer['id']}").json()["questions"]
    question = next(item for item in questions if item["kind"] == "behavior")

    template = client.get(f"/api/career/interview-sim/worksheet/{offer['id']}/{question['id']}")
    assert template.status_code == 200
    assert template.json()["worksheet"]["completeness"] == 0.0
    assert [item["label"] for item in template.json()["evidence_checklist"]] == question["evidence_needed"]

    response = client.post(
        "/api/career/interview-sim/worksheet",
        json={
            "job_id": offer["id"],
            "question_id": question["id"],
            "evidence_checked": [question["evidence_needed"][0]],
            **FULL_STAR,
        },
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["worksheet"]["completeness"] == 1.0
    assert payload["self_score"]["score"] == 100
    assert payload["self_score"]["evidence_coverage"] == round(1 / len(question["evidence_needed"]), 3)


def test_api_scores_a_worksheet_without_a_saved_offer(tmp_path: Path) -> None:
    response = _client(tmp_path).post(
        "/api/career/interview-sim/worksheet",
        json={"question_id": "behavior:deadline", **FULL_STAR},
    )
    assert response.status_code == 200
    assert response.json()["self_score"]["score"] == 100
    assert response.json()["self_score"]["evidence_missing"] == []


def test_api_rejects_unknown_offer_unknown_question_and_missing_question(tmp_path: Path) -> None:
    client = _client(tmp_path)
    unknown_job = client.get("/api/career/interview-sim/questions/does-not-exist")
    assert unknown_job.status_code == 400

    offer = _import_offer(client, _offer("consulting-intern"))
    unknown_question = client.get(
        f"/api/career/interview-sim/worksheet/{offer['id']}/behavior:does-not-exist"
    )
    assert unknown_question.status_code == 400

    no_question = client.post("/api/career/interview-sim/worksheet", json={**FULL_STAR})
    assert no_question.status_code == 400


def test_api_rejects_an_out_of_contract_question_limit(tmp_path: Path) -> None:
    client = _client(tmp_path)
    offer = _import_offer(client, _offer("finance-ma"))
    too_small = client.get(
        f"/api/career/interview-sim/questions/{offer['id']}", params={"limit": 3}
    )
    assert too_small.status_code == 422
    accepted = client.get(
        f"/api/career/interview-sim/questions/{offer['id']}", params={"limit": 12}
    )
    assert accepted.status_code == 200
    assert len(accepted.json()["questions"]) == 12


def test_question_ids_remain_stable_across_api_calls(tmp_path: Path) -> None:
    client = _client(tmp_path)
    offer = _import_offer(client, _offer("finance-ma"))
    first = client.get(f"/api/career/interview-sim/questions/{offer['id']}", params={"seed": 11}).json()
    second = client.get(f"/api/career/interview-sim/questions/{offer['id']}", params={"seed": 11}).json()
    assert first["questions"] == second["questions"]


def test_interview_question_contract_is_serializable() -> None:
    question = InterviewQuestion(id="x", kind="behavior", question="Q", evidence_needed=["E"])
    assert question.to_dict() == {
        "id": "x",
        "kind": "behavior",
        "question": "Q",
        "evidence_needed": ["E"],
    }


def test_compatibility_aliases_and_count_match_canonical_builder() -> None:
    offer = _offer("finance-ma")
    canonical = [q.to_dict() for q in build_question_set(offer, seed=7, limit=14)]
    for alias in (build_questions, generate_question_set, get_question_set):
        assert [q.to_dict() for q in alias(offer, seed=7, count=14)] == canonical


def test_bundled_fixtures_are_synthetic_and_loadable() -> None:
    offers = load_fixtures()
    assert len(offers) >= 3
    assert all(offer.get("id") for offer in offers)
    for offer in offers:
        assert len(build_question_set(offer, seed=0)) >= MIN_QUESTIONS
