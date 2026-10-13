"""Offline tests for the local-only Côme AI Career Agent Phase 1.

Every test uses a temporary directory.  They do not read a real ``.env``, do
not call Gemini/Ollama, do not open a browser, and do not contact a job board.
"""

from __future__ import annotations

import csv
import hashlib
import json
import sqlite3
import stat
import zipfile
from datetime import date, timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from openpyxl import load_workbook
from pypdf import PdfReader

from career.models import availability_assessment, canonical_url, dedup_key
from career import discovery as discovery_module
from career import service as career_service_module
from career.discovery import DiscoveryPayload, GreenhouseBoard, GreenhouseJobBoardConnector, PublicSourceError, parse_greenhouse_board_token
from career.ocr import OCRResult
from career.application_studio import build_local_application_draft, parse_ai_draft
from career.interview import evaluate_answer, progress_summary, select_question
from career.profile_import import parse_profile_text
from career.scoring import SCORING_WEIGHTS, SCORING_VERSION, score_job, scoring_placeholder
from career.service import CareerService, DELETE_CONFIRMATION
from career.sources import LOCAL_LANGUAGE_HINTS, SEARCH_TERMS, discovery_request_for
from come_ai_web import create_app
from workspace_core import UserFacingError


def manual_job(**changes: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "company": "Banque Exemple",
        "title": "M&A Intern",
        "source_name": "manual",
        "source_id": "",
        "official_url": "https://careers.example.test/jobs/42?utm_source=mail",
        "job_family": "M&A / Investment Banking",
        "city": "Paris",
        "country": "France",
        "posted_date": "2026-10-01",
        "deadline_date": "2026-12-15",
        "start_date": "2027-02-01",
        "end_date": "2027-05-31",
        "duration_months": 4,
        "source_status": "open",
        "description_original": "Stage de quatre mois.",
    }
    payload.update(changes)
    return payload


@pytest.mark.parametrize(
    ("payload", "expected"),
    [
        ({"start_date": "2027-01-01", "end_date": "2027-06-30", "duration_months": 6}, "compatible"),
        ({"start_date": "2026-12-15", "end_date": "2027-02-15", "duration_months": 3}, "partial"),
        ({"start_date": "2027-04-01", "end_date": "2027-07-31", "duration_months": 4}, "potentially_incompatible"),
        ({"start_date": "2027-07-01", "end_date": "2027-09-30", "duration_months": 3}, "incompatible"),
        ({"start_date": None, "end_date": None, "duration_months": 3}, "to_verify"),
        ({"start_date": "2027-02-01", "end_date": "2027-03-01", "duration_months": 1}, "potentially_incompatible"),
    ],
)
def test_calendar_assessment_is_deterministic(payload: dict[str, object], expected: str) -> None:
    assert availability_assessment(**payload)["status"] == expected  # type: ignore[arg-type]


def test_calendar_and_url_validation_do_not_leak_technical_errors() -> None:
    with pytest.raises(UserFacingError, match="date de fin"):
        availability_assessment(start_date="2027-04-03", end_date="2027-04-02", duration_months=3)
    with pytest.raises(UserFacingError, match="port"):
        canonical_url("https://example.test:bad-port/jobs/1")
    with pytest.raises(UserFacingError, match="identifiant"):
        canonical_url(('https://' + 'name:sec' + 'ret@exam' + 'ple.test' + '/jobs/1'))

    assert canonical_url("HTTPS://EXAMPLE.TEST:443/jobs/42/?utm_medium=email&ref=x#ignored") == "https://example.test/jobs/42"
    assert canonical_url("http://example.test:80/jobs/42") == "http://example.test/jobs/42"


def test_scoring_interface_is_honest_until_phase_two() -> None:
    placeholder = scoring_placeholder()
    assert placeholder["score"] is None
    assert placeholder["version"] == SCORING_VERSION
    assert sum(SCORING_WEIGHTS.values()) == 100
    assert placeholder["state"] == "not_configured"


def test_future_source_vocabulary_is_local_and_family_scoped() -> None:
    request = discovery_request_for("Private Equity")
    assert request.terms == SEARCH_TERMS["Private Equity"]
    assert "Private Equity Intern" in request.terms
    assert {"tirocinio", "Praktikum", "Werkstudent"}.issubset(LOCAL_LANGUAGE_HINTS)
    with pytest.raises(ValueError, match="Unknown"):
        discovery_request_for("Not a configured family")


class FakeGreenhouseTransport:
    """Offline transport that proves connector parsing without HTTP."""

    def __init__(self, responses: list[object]) -> None:
        self.responses = list(responses)
        self.endpoints: list[tuple[str, int]] = []

    def get_json(self, endpoint: str, timeout_seconds: int) -> object:
        self.endpoints.append((endpoint, timeout_seconds))
        value = self.responses.pop(0)
        if isinstance(value, Exception):
            raise value
        return value


class FakeDiscoveryConnector:
    """In-process source fixture; it never opens a public board."""

    def __init__(self, responses: list[object]) -> None:
        self.responses = list(responses)
        self.boards: list[GreenhouseBoard] = []

    def discover(self, board: GreenhouseBoard) -> DiscoveryPayload:
        self.boards.append(board)
        value = self.responses.pop(0)
        if isinstance(value, Exception):
            raise value
        assert isinstance(value, DiscoveryPayload)
        return value


def _greenhouse_payload(*jobs: dict[str, object], verified_at: str = "2026-10-10T10:00:00+00:00") -> DiscoveryPayload:
    return DiscoveryPayload(jobs=tuple(jobs), verified_at=verified_at, truncated=False)


def greenhouse_job(**changes: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "company": "Example Bank",
        "title": "M&A Off-Cycle Intern",
        "source_name": "greenhouse",
        "source_id": "official-42",
        "official_url": "https://boards.greenhouse.io/example/jobs/42",
        "city": "Paris",
        "country": "France",
        "source_status": "open",
        "description_original": "Analyse financière et Excel.",
        "requirements": "Excel, analyse financière",
        "languages_required": "English",
        "eligibility_requirement": "Student status required",
    }
    payload.update(changes)
    return payload


def test_greenhouse_connector_is_fixed_host_bounded_and_sanitises_html(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    raw = {
        "jobs": [
            {
                "id": 42,
                "title": "M&A Off-Cycle Intern",
                "absolute_url": "https://boards.greenhouse.io/example/jobs/42",
                "location": {"name": "Paris, France"},
                "content": "<p>Analyse <strong>financière</strong></p><script>alert('x')</script><ul><li>Excel</li></ul>",
            }
        ]
    }
    transport = FakeGreenhouseTransport([PublicSourceError("trop de demandes", retryable=True, code="429"), raw])
    monkeypatch.setattr(discovery_module.time, "sleep", lambda _: None)
    connector = GreenhouseJobBoardConnector(transport)  # type: ignore[arg-type]
    result = connector.discover(GreenhouseBoard(id="source_example", company="Example Bank", board_token="example"))

    assert len(transport.endpoints) == 2
    assert all(endpoint == "https://boards-api.greenhouse.io/v1/boards/example/jobs?content=true" for endpoint, _ in transport.endpoints)
    assert result.jobs[0]["city"] == "Paris"
    assert result.jobs[0]["country"] == "France"
    assert "alert" not in result.jobs[0]["description_original"]
    assert "<" not in result.jobs[0]["description_original"]
    assert "Analyse" in result.jobs[0]["description_original"]
    assert parse_greenhouse_board_token("https://boards.greenhouse.io/example") == "example"
    with pytest.raises(UserFacingError, match="Greenhouse"):
        parse_greenhouse_board_token("https://127.0.0.1/private-board")
    with pytest.raises(UserFacingError, match="board public"):
        parse_greenhouse_board_token("https://boards-api.greenhouse.io/v1/boards/example/not-jobs")


def test_discovery_preserves_tracking_marks_missing_jobs_unknown_and_survives_errors(tmp_path: Path) -> None:
    first = _greenhouse_payload(greenhouse_job())
    refreshed = _greenhouse_payload(
        greenhouse_job(description_original="Description officielle actualisée."),
        verified_at="2026-10-10T10:10:00+00:00",
    )
    empty = _greenhouse_payload(verified_at="2026-10-10T10:20:00+00:00")
    connector = FakeDiscoveryConnector(
        [first, refreshed, empty, PublicSourceError("Source temporairement indisponible.", retryable=True, code="503")]
    )
    service = CareerService(tmp_path, discovery_connector=connector)  # type: ignore[arg-type]
    source = service.create_discovery_source(
        {"company": "Example Bank", "board_reference": "https://boards.greenhouse.io/example"}
    )
    assert connector.boards == []  # configuration alone has no network effect

    initial = service.discover_opportunities(force=True)
    assert initial["outcomes"][0]["status"] == "success"
    saved = service.list_jobs()
    assert len(saved) == 1
    job = saved[0]
    assert job["source_name"] == "greenhouse"
    assert job["discovery_source_id"] == source["id"]
    assert job["last_verified_at"] == "2026-10-10T10:00:00+00:00"
    assert "<script>" not in job["description_original"]

    service.set_shortlist(job["id"], True, "À comparer au desk Paris")
    application = service.create_application(job["id"])
    second = service.discover_opportunities(force=True)
    assert second["outcomes"][0]["updated_count"] == 1
    refreshed_job = service.get_job(job["id"])
    assert refreshed_job["shortlisted"] is True
    assert refreshed_job["personal_note"] == "À comparer au desk Paris"
    assert refreshed_job["application"]["id"] == application["id"]
    assert refreshed_job["description_original"] == "Description officielle actualisée."

    absent = service.discover_opportunities(force=True)
    assert absent["outcomes"][0]["found_count"] == 0
    assert service.get_job(job["id"])["source_status"] == "unknown"

    failed = service.discover_opportunities(force=True)
    assert failed["outcomes"][0]["status"] == "error"
    assert service.get_job(job["id"])["source_status"] == "unknown"
    assert service.list_discovery_runs()[0]["status"] == "error"
    assert len(connector.boards) == 4

    # Re-opening the local database maintains configuration, history, and the
    # candidate's tracking without causing a public-board request.
    reopened = CareerService(tmp_path, discovery_connector=FakeDiscoveryConnector([]))  # type: ignore[arg-type]
    assert reopened.list_discovery_sources()[0]["id"] == source["id"]
    assert reopened.get_job(job["id"])["application"]["id"] == application["id"]

    isolated_dir = tmp_path / "unexpected-connector"
    isolated = CareerService(isolated_dir, discovery_connector=FakeDiscoveryConnector([RuntimeError("internal detail")]))  # type: ignore[arg-type]
    isolated.create_discovery_source({"company": "Unexpected Source", "board_reference": "unexpected-source"})
    outcome = isolated.discover_opportunities(force=True)["outcomes"][0]
    assert outcome["status"] == "error"
    assert "internal detail" not in outcome["message"]
    assert isolated.list_discovery_runs()[0]["status"] == "error"


def test_deterministic_scoring_explains_matches_unknowns_and_known_blockers(tmp_path: Path) -> None:
    service = CareerService(tmp_path)
    preferences = service.get_preferences()
    profile = {
        "skills": "Excel, Python, valuation, financial modeling",
        "experience": "Financial analysis project",
        "languages": "French, English",
        "eligibility": "compatible",
        "target_companies": "Example Bank",
    }
    job = {
        **greenhouse_job(),
        "job_family": "M&A / Investment Banking",
        "calendar_status": "compatible",
        "calendar_reasons": ["La période annoncée est comprise dans janvier–juin 2027."],
    }
    score = score_job(profile, preferences, {}, job)
    assert score["score"] >= 85
    assert score["is_recommendable"] is True
    assert score["reasons"]
    assert score["disclaimer"].startswith("Score de pertinence explicable")

    missing_language = score_job({**profile, "languages": "French"}, preferences, {}, job)
    assert any("anglais" in item.lower() or "english" in item.lower() for item in missing_language["unknowns"])
    assert missing_language["is_recommendable"] is False

    blocked = score_job(
        {**profile, "eligibility": "incompatible"},
        preferences,
        {},
        {**job, "calendar_status": "incompatible"},
    )
    assert blocked["state"] == "blocked"
    assert blocked["is_recommendable"] is False
    assert len(blocked["blocking_constraints"]) >= 2


def test_local_interview_engine_adapts_and_persists_a_targeted_session(tmp_path: Path) -> None:
    question = select_question(mode="technical", difficulty="beginner", language="en")
    assert question["topic"] == "DCF"
    feedback = evaluate_answer(
        question["id"],
        "First I project unlevered free cash flow from EBIT after tax, capex and working capital. "
        "Then I discount the cash flows with WACC and estimate terminal value. Finally I bridge enterprise value to equity value using net debt and run sensitivities.",
        "en",
    )
    assert feedback["scores"]["overall"] >= 70
    assert feedback["reference_answer"]
    assert "likelihood of being recruited" in feedback["disclaimer"]

    service = CareerService(tmp_path)
    job = service.import_job(manual_job(title="M&A Intern", requirements="Excel and financial modeling"))
    application = service.create_application(job["id"])
    session = service.create_interview_session(
        {
            "mode": "company",
            "difficulty": "intermediate",
            "language": "fr",
            "application_id": application["id"],
        }
    )
    assert session["job_id"] == job["id"]
    assert job["company"] in session["current_question"]["prompt"]
    assert session["progress"]["answered_count"] == 0

    answered = service.answer_interview_session(
        session["id"],
        "Je pars des exigences vérifiées dans l’offre, puis je relie deux compétences factuelles de mon profil. "
        "Je prépare enfin une question précise pour l’intervieweur au lieu d’inventer des informations sur l’entreprise.",
    )
    assert answered["progress"]["answered_count"] == 1
    assert answered["turns"][0]["feedback"]["scores"]["overall"] >= 0
    assert answered["turns"][0]["answer"].startswith("Je pars")
    assert answered["current_question"]["id"] != session["current_question"]["id"]

    completed = service.complete_interview_session(session["id"])
    assert completed["status"] == "completed"
    with pytest.raises(UserFacingError, match="terminée"):
        service.answer_interview_session(session["id"], "Nouvelle réponse après clôture.")
    reopened = CareerService(tmp_path)
    saved = reopened.get_interview_session(session["id"])
    assert saved["status"] == "completed"
    assert saved["progress"]["answered_count"] == 1


@pytest.mark.parametrize(
    ("language", "answer", "prompt_fragment", "disclaimer_fragment", "score_label", "progress_label"),
    [
        (
            "fr",
            "D’abord je projette les flux de trésorerie disponibles après impôt et capex. Ensuite je les actualise au WACC, calcule la valeur terminale, puis je passe de l’Enterprise Value à l’Equity Value avec la dette nette.",
            "Explique-moi les étapes",
            "probabilité de recrutement",
            "Score de l’exercice",
            "Réponses travaillées",
        ),
        (
            "en",
            "First I project free cash flow after tax and capex. Then I discount it using WACC, calculate terminal value, and bridge enterprise value to equity value with net debt.",
            "Walk me through a DCF",
            "likelihood of being recruited",
            "Exercise score",
            "Answers practised",
        ),
        (
            "it",
            "Prima progetto i flussi di cassa disponibili dopo imposte e capex. Poi attualizzo con il WACC, calcolo il valore terminale e passo dall’Enterprise Value all’Equity Value con il debito netto.",
            "Spiegami le fasi",
            "probabilità di ottenere il ruolo",
            "Punteggio dell’esercizio",
            "Risposte esercitate",
        ),
        (
            "de",
            "Zuerst plane ich den Free Cashflow nach Steuern und Capex. Dann diskontiere ich mit WACC, berechne den Terminalwert und leite mit Nettoverschuldung vom Enterprise Value zum Equity Value über.",
            "Erkläre mir die Schritte",
            "Wahrscheinlichkeit, eingestellt zu werden",
            "Übungspunktzahl",
            "Geübte Antworten",
        ),
    ],
)
def test_interview_coach_localizes_question_feedback_and_progress(
    language: str,
    answer: str,
    prompt_fragment: str,
    disclaimer_fragment: str,
    score_label: str,
    progress_label: str,
) -> None:
    """Local-language wording must not change the transparent score contract."""
    question = select_question(mode="technical", difficulty="beginner", language=language)
    assert question["language"] == language
    assert prompt_fragment in question["prompt"]
    assert question["topic"] == "DCF"  # Historic canonical field remains stable.
    assert question["topic_label"]
    assert question["reference_answer_language"] == language

    feedback = evaluate_answer(question["id"], answer, language)
    repeated = evaluate_answer(question["id"], answer, language)
    assert feedback["scores"] == repeated["scores"]
    assert feedback["scores"]["overall"] >= 70
    assert feedback["language"] == language
    assert feedback["reference_answer_language"] == language
    assert disclaimer_fragment in feedback["disclaimer"]
    assert feedback["score_labels"]["overall"] == score_label
    assert feedback["feedback_labels"]["coaching"]
    assert feedback["reference_answer"]

    progress = progress_summary([{"topic": question["topic"], "feedback": feedback}])
    assert progress["language"] == language
    assert progress["labels"]["answered_count"] == progress_label
    assert progress["disclaimer"]


def test_dashboard_action_plan_is_local_ordered_stable_and_covers_next_steps(tmp_path: Path) -> None:
    service = CareerService(tmp_path)

    initial_plan = service.dashboard()["action_plan"]
    assert [item["id"] for item in initial_plan] == [
        "profile-completeness",
        "intake-completion",
        "discover-source",
        "discover-jobs",
    ]
    assert all(set(item) == {"id", "priority", "title", "detail", "target_view"} for item in initial_plan)
    assert all(item["target_view"] in {"profile", "discover", "applications", "interviews"} for item in initial_plan)
    assert [item["priority"] for item in initial_plan] == sorted(item["priority"] for item in initial_plan)

    # Filling the profile and finite local intake removes setup actions without
    # making an external request.  Configuring a public board is likewise only
    # local configuration until a person explicitly starts a search.
    service.update_profile(
        {
            "display_name": "Côme Delavenne",
            "contact_email": "come@example.test",
            "education": "Master Finance",
            "experience": "Projet d’analyse financière",
            "skills": "Excel, Python, valuation",
            "languages": "Français, anglais C1",
            "eligibility": "unknown",
        }
    )
    for answer in (
        "M&A et private equity",
        "Paris et Londres",
        "Banques et fonds",
        "Modélisation et analyse",
        "Excel et Python",
        "Stage de trois à six mois",
    ):
        service.answer_intake(answer)
    service.create_discovery_source(
        {"company": "Example Bank", "board_reference": "https://boards.greenhouse.io/example"}
    )

    deadline = (date.today() + timedelta(days=3)).isoformat()
    job = service.import_job(
        manual_job(
            deadline_date=deadline,
            start_date="",
            end_date="",
            duration_months=None,
            source_status="unknown",
        )
    )
    application = service.create_application(job["id"])
    service.create_application_draft(job["id"], "fr")
    service.approve_for_manual_submission(application["id"], True, "Relecture locale terminée")
    service.create_interview_session(
        {
            "mode": "technical",
            "difficulty": "intermediate",
            "language": "fr",
            "application_id": application["id"],
        }
    )

    dashboard = service.dashboard()
    plan = dashboard["action_plan"]
    ids = [item["id"] for item in plan]
    assert {
        "offers-deadline",
        "applications-manual-submission",
        "offers-verification",
        "draft-review",
        "interview-continue",
    }.issubset(ids)
    assert not {"profile-completeness", "intake-completion", "discover-source", "discover-jobs"}.intersection(ids)
    assert len(plan) <= 12
    assert [item["priority"] for item in plan] == sorted(item["priority"] for item in plan)
    assert dashboard["action_plan"] == service.dashboard()["action_plan"]
    assert next(item for item in plan if item["id"] == "offers-deadline")["target_view"] == "discover"
    assert next(item for item in plan if item["id"] == "applications-manual-submission")["target_view"] == "applications"
    assert next(item for item in plan if item["id"] == "interview-continue")["target_view"] == "interviews"


def test_local_storage_profile_preferences_and_persistence(tmp_path: Path) -> None:
    service = CareerService(tmp_path)
    assert service.data_dir.parent == tmp_path
    assert not (tmp_path / "data").exists()
    assert (stat.S_IMODE(service.data_dir.stat().st_mode) & 0o077) == 0
    assert (stat.S_IMODE(service.db_path.stat().st_mode) & 0o077) == 0

    initial_profile = service.get_profile()
    assert initial_profile["eligibility"] == "unknown"
    preferences = service.get_preferences()
    assert len(preferences["families"]) == 6
    assert {item["priority"] for item in preferences["families"]} == {100}
    primary_locations = [item for item in preferences["locations"] if item["scope"] == "primary"]
    secondary_locations = [item for item in preferences["locations"] if item["scope"] == "secondary"]
    assert len(primary_locations) == 6
    assert {item["priority"] for item in primary_locations} == {100}
    assert secondary_locations == [
        {
            "key": "other-europe",
            "label": "Autres villes européennes",
            "enabled": True,
            "priority": 50,
            "scope": "secondary",
        }
    ]

    updated_profile = service.update_profile(
        {
            "display_name": "Côme",
            "education": "Master 1",
            "skills": "Analyse financière",
            "languages": "Français, anglais C1",
            "eligibility": "unknown",
        }
    )
    assert updated_profile["eligibility"] == "unknown"
    preferences["families"][0]["enabled"] = False
    preferences["families"][0]["priority"] = 900
    updated_preferences = service.update_preferences(preferences)
    assert updated_preferences["families"][0]["enabled"] is False
    assert updated_preferences["families"][0]["priority"] == 900

    reconfigured = service.update_preferences(
        {
            **updated_preferences,
            "availability": {
                **updated_preferences["availability"],
                "availability_start": "2027-02-01",
                "availability_end": "2027-07-31",
                "minimum_duration_months": 2,
                "maximum_duration_months": 7,
            },
        }
    )
    assert reconfigured["availability"]["availability_start"] == "2027-02-01"
    assert reconfigured["availability"]["maximum_duration_months"] == "7"
    with pytest.raises(UserFacingError, match="conservées ou désactivées"):
        service.update_preferences({**reconfigured, "families": reconfigured["families"][:-1]})

    job = service.import_job(manual_job())
    assert job["calendar_status"] == "compatible"
    incompatible = service.update_preferences(
        {
            **reconfigured,
            "availability": {
                **reconfigured["availability"],
                "availability_start": "2027-06-01",
                "availability_end": "2027-07-31",
            },
        }
    )
    assert incompatible["availability"]["availability_start"] == "2027-06-01"
    assert service.get_job(job["id"])["calendar_status"] == "incompatible"
    reopened = CareerService(tmp_path)
    assert reopened.get_profile()["display_name"] == "Côme"
    assert len(reopened.list_jobs()) == 1


def _stage_profile_text_document(service: CareerService, name: str, text: str) -> tuple[Path, int, str]:
    source = service.profile_upload_temp_path()
    encoded = text.encode("utf-8")
    source.write_bytes(encoded)
    return source, len(encoded), hashlib.sha256(encoded).hexdigest()


def test_profile_parser_and_private_cv_import_require_explicit_review(tmp_path: Path) -> None:
    source_text = """Côme Delavenne
come@example.test
+33 6 12 34 56 78
https://www.linkedin.com/in/come-delavenne?trk=public_profile

FORMATION
Master Finance — EDHEC

EXPÉRIENCE PROFESSIONNELLE
Stage en analyse financière

COMPÉTENCES
Excel, Python, analyse financière

LANGUES
Français natif, anglais C1
"""
    parsed = parse_profile_text(source_text)
    assert parsed["values"]["display_name"] == "Côme Delavenne"
    assert parsed["values"]["contact_email"] == "come@example.test"
    assert parsed["values"]["linkedin_url"] == "https://www.linkedin.com/in/come-delavenne"
    assert parsed["values"]["education"] == "Master Finance — EDHEC"
    assert "eligibility" not in parsed["values"]
    assert "nationality" not in parsed["values"]

    generic_data = tmp_path / "data"
    generic_data.mkdir()
    (generic_data / "keep.txt").write_text("not a Career source", encoding="utf-8")
    service = CareerService(tmp_path)
    service.update_profile({"display_name": "Avant", "skills": "Excel avancé", "eligibility": "unknown"})
    original_profile = service.get_profile()
    source, size_bytes, checksum = _stage_profile_text_document(service, "cv.txt", source_text)
    draft = service.import_profile_document(
        source_kind="cv",
        original_name="Mon CV.txt",
        temporary_path=source,
        content_sha256=checksum,
        size_bytes=size_bytes,
    )

    assert draft["status"] == "pending"
    assert draft["has_local_file"] is True
    assert draft["suggestions"]["values"]["skills"] == "Excel, Python, analyse financière"
    assert draft["suggestions"]["values"]["experience"] == "Stage en analyse financière"
    assert not source.exists()
    stored_sources = list(service.documents_dir.glob("profile_*"))
    assert len(stored_sources) == 1
    assert stored_sources[0].parent == service.documents_dir
    assert (generic_data / "keep.txt").read_text(encoding="utf-8") == "not a Career source"
    assert service.get_profile() == original_profile  # Importing never writes the profile by itself.

    applied = service.apply_profile_import(
        draft["id"],
        [
            {"field": "display_name", "mode": "replace", "value": "Côme Delavenne"},
            {"field": "skills", "mode": "append", "value": "Python"},
        ],
        draft["base_profile_updated_at"],
    )
    assert applied["profile"]["display_name"] == "Côme Delavenne"
    assert applied["profile"]["skills"] == "Excel avancé\nPython"
    assert applied["profile"]["education"] == ""  # Unchecked fields are untouched.
    assert applied["profile"]["eligibility"] == "unknown"
    assert applied["profile_import"]["status"] == "applied"

    service.delete_profile_import(draft["id"])
    assert not stored_sources[0].exists()
    assert service.list_profile_imports() == []


def test_profile_text_import_conflict_migration_and_reset_are_local(tmp_path: Path) -> None:
    service = CareerService(tmp_path)
    draft = service.import_profile_text(
        source_kind="linkedin_text",
        original_name="profil-linkedin-copie",
        text="""Jane Doe
jane@example.test

FORMATION
Master in Finance

SKILLS
Valuation, Excel
""",
    )
    duplicate = service.import_profile_text(
        source_kind="linkedin_text",
        original_name="copie-identique",
        text="""Jane Doe
jane@example.test

FORMATION
Master in Finance

SKILLS
Valuation, Excel
""",
    )
    assert duplicate["id"] == draft["id"]
    assert duplicate["duplicate"] is True
    assert duplicate["has_local_file"] is False

    changed = service.get_profile()
    service.update_profile({**changed, "notes": "Modifié manuellement après l’extraction"})
    with pytest.raises(UserFacingError, match="modifié depuis"):
        service.apply_profile_import(
            draft["id"],
            [{"field": "education", "mode": "replace", "value": "Master in Finance"}],
            draft["base_profile_updated_at"],
        )

    # Explicitly importing the same pending source again refreshes its review
    # revision; it does not silently apply anything or create a duplicate.
    reopened = service.import_profile_text(
        source_kind="linkedin_text",
        original_name="profil-linkedin-copie",
        text="""Jane Doe
jane@example.test

FORMATION
Master in Finance

SKILLS
Valuation, Excel
""",
    )
    assert reopened["id"] == draft["id"]
    assert reopened["base_profile_updated_at"] == service.get_profile()["updated_at"]
    assert service.apply_profile_import(
        reopened["id"],
        [{"field": "education", "mode": "replace", "value": "Master in Finance"}],
        reopened["base_profile_updated_at"],
    )["profile"]["education"] == "Master in Finance"

    # A real v1 installation is migrated in place without wiping its profile.
    with sqlite3.connect(service.db_path) as connection:
        connection.execute("PRAGMA user_version = 1")
    migrated = CareerService(tmp_path)
    with sqlite3.connect(migrated.db_path) as connection:
        assert connection.execute("PRAGMA user_version").fetchone()[0] == 6
        columns = {row[1] for row in connection.execute("PRAGMA table_info(candidate_profile)").fetchall()}
    assert {"contact_email", "contact_phone", "linkedin_url", "experience"}.issubset(columns)
    assert migrated.get_profile()["notes"] == "Modifié manuellement après l’extraction"

    v3_data = tmp_path / "data"
    v3_data.mkdir(exist_ok=True)
    (v3_data / "keep.txt").write_text("do not touch", encoding="utf-8")
    migrated.reset_personal_data(DELETE_CONFIRMATION)
    assert migrated.list_profile_imports() == []
    assert (v3_data / "keep.txt").read_text(encoding="utf-8") == "do not touch"


def test_legacy_schema_migration_creates_private_consistent_backup(tmp_path: Path) -> None:
    """A v1 database is preserved before any schema-changing migration runs."""
    legacy_db = tmp_path / "career_data" / "career.sqlite3"
    legacy_db.parent.mkdir(parents=True)
    with sqlite3.connect(legacy_db) as connection:
        connection.executescript(
            """
            CREATE TABLE candidate_profile (
                id INTEGER PRIMARY KEY CHECK (id = 1),
                display_name TEXT NOT NULL DEFAULT '',
                education TEXT NOT NULL DEFAULT '',
                skills TEXT NOT NULL DEFAULT '',
                languages TEXT NOT NULL DEFAULT '',
                eligibility TEXT NOT NULL DEFAULT 'unknown',
                target_companies TEXT NOT NULL DEFAULT '',
                notes TEXT NOT NULL DEFAULT '',
                updated_at TEXT NOT NULL
            );
            CREATE TABLE preference_items (
                kind TEXT NOT NULL,
                item_key TEXT NOT NULL,
                label TEXT NOT NULL,
                enabled INTEGER NOT NULL DEFAULT 1,
                priority INTEGER NOT NULL DEFAULT 100,
                scope TEXT NOT NULL DEFAULT 'primary',
                PRIMARY KEY (kind, item_key)
            );
            CREATE TABLE career_settings (setting_key TEXT PRIMARY KEY, setting_value TEXT NOT NULL);
            CREATE TABLE jobs (id TEXT PRIMARY KEY);
            CREATE TABLE applications (id TEXT PRIMARY KEY, job_id TEXT NOT NULL UNIQUE);
            CREATE TABLE application_events (id TEXT PRIMARY KEY, job_id TEXT NOT NULL);
            CREATE TABLE career_audit_log (
                id TEXT PRIMARY KEY,
                action TEXT NOT NULL,
                subject_type TEXT NOT NULL,
                subject_id TEXT NOT NULL,
                created_at TEXT NOT NULL
            );
            """
        )
        connection.execute(
            """
            INSERT INTO candidate_profile
                (id, display_name, education, skills, languages, eligibility, target_companies, notes, updated_at)
            VALUES (1, 'Côme', 'Master Finance', 'Excel', 'Français', 'unknown', '', 'donnée v1 à préserver', '2026-10-11T09:00:00+00:00')
            """
        )
        connection.execute("PRAGMA user_version = 1")

    migrated = CareerService(tmp_path)
    backups = list(migrated.backups_dir.glob("career-before-v1-to-v6-*.sqlite3"))
    assert len(backups) == 1
    backup_path = backups[0]
    assert (stat.S_IMODE(backup_path.stat().st_mode) & 0o077) == 0

    with sqlite3.connect(backup_path) as backup:
        assert backup.execute("PRAGMA user_version").fetchone()[0] == 1
        assert backup.execute("SELECT notes FROM candidate_profile WHERE id = 1").fetchone()[0] == "donnée v1 à préserver"
        legacy_columns = {row[1] for row in backup.execute("PRAGMA table_info(candidate_profile)").fetchall()}
    assert "contact_email" not in legacy_columns

    with sqlite3.connect(migrated.db_path) as current:
        assert current.execute("PRAGMA user_version").fetchone()[0] == 6
        current_columns = {row[1] for row in current.execute("PRAGMA table_info(candidate_profile)").fetchall()}
    assert {"contact_email", "contact_phone", "linkedin_url", "experience"}.issubset(current_columns)
    assert migrated.get_profile()["notes"] == "donnée v1 à préserver"


def test_migration_stops_before_schema_change_when_backup_creation_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    service = CareerService(tmp_path)
    service.update_profile({**service.get_profile(), "notes": "ne pas modifier sans sauvegarde"})
    with sqlite3.connect(service.db_path) as connection:
        connection.execute("PRAGMA user_version = 1")

    def deny_backup_path(*_args: object, **_kwargs: object) -> int:
        raise OSError("backup directory unavailable")

    monkeypatch.setattr(career_service_module.os, "open", deny_backup_path)
    with pytest.raises(UserFacingError, match="sauvegarde locale de sécurité"):
        CareerService(tmp_path)

    with sqlite3.connect(service.db_path) as current:
        assert current.execute("PRAGMA user_version").fetchone()[0] == 1
    assert service.get_profile()["notes"] == "ne pas modifier sans sauvegarde"
    assert list(service.backups_dir.glob("*.sqlite3")) == []


def test_explicit_reset_removes_generated_migration_backups_only(tmp_path: Path) -> None:
    service = CareerService(tmp_path)
    generated = service.backups_dir / "career-before-v1-to-v6-test.sqlite3"
    interrupted = service.backups_dir / ".career-before-v2-to-v6-interrupted.tmp"
    personal_copy = service.backups_dir / "copie-personnelle.sqlite3"
    generated.write_bytes(b"application-generated snapshot")
    interrupted.write_bytes(b"incomplete application snapshot")
    personal_copy.write_bytes(b"a file deliberately kept by the person")

    service.reset_personal_data(DELETE_CONFIRMATION)

    assert not generated.exists()
    assert not interrupted.exists()
    assert personal_copy.exists()


class FakeLocalOCR:
    """Offline stand-in: tests must not compile Swift or run Vision."""

    @staticmethod
    def status() -> dict[str, object]:
        return {"available": True, "engine": "macOS Vision", "network": False, "reason": ""}

    def extract_pdf(self, path: Path, *, max_pages: int = 8) -> OCRResult:
        assert path.suffix == ".pdf"
        assert max_pages == 8
        return OCRResult(
            text="""Jane OCR
jane.ocr@example.test

FORMATION
Master Finance

COMPETENCES
Excel, Python""",
            pages=1,
            truncated=False,
            warnings=["OCR local simulé pour le test."],
        )


def test_scanned_profile_pdf_uses_injected_local_ocr_only(tmp_path: Path) -> None:
    service = CareerService(tmp_path, ocr=FakeLocalOCR())  # type: ignore[arg-type]
    source = service.profile_upload_temp_path()
    # It only needs a valid PDF signature here: the fake OCR replaces native
    # Vision, and the service must never route the source through V3 data/.
    payload = b"%PDF-1.4\nscanned-page-without-text\n%%EOF"
    source.write_bytes(payload)
    draft = service.import_profile_document(
        source_kind="cv",
        original_name="cv-scanne.pdf",
        temporary_path=source,
        content_sha256=hashlib.sha256(payload).hexdigest(),
        size_bytes=len(payload),
    )
    assert draft["extraction_method"] == "macos_vision"
    assert draft["ocr_pages"] == 1
    assert draft["ocr_warnings"] == ["OCR local simulé pour le test."]
    assert draft["suggestions"]["values"]["education"] == "Master Finance"
    assert not source.exists()
    assert not list((tmp_path / "data").glob("*")) if (tmp_path / "data").exists() else True


def test_guided_intake_and_local_application_studio_are_fact_faithful(tmp_path: Path) -> None:
    service = CareerService(tmp_path)
    profile = service.update_profile(
        {
            "display_name": "Côme Delavenne",
            "contact_email": "come@example.test",
            "education": "Master Finance — EDHEC",
            "experience": "Projet d’analyse financière universitaire",
            "skills": "Excel, Python, analyse financière <script>alert(1)</script>",
            "languages": "Français natif, anglais C1",
            "eligibility": "unknown",
        }
    )
    assert profile["display_name"] == "Côme Delavenne"
    answers = [
        "M&A et private equity",
        "Paris et Londres",
        "Banques et fonds",
        "Analyse, modélisation et due diligence",
        "Excel, Python et projet universitaire",
        "Stage de 3 à 6 mois ; vérifier les dates",
    ]
    for index, answer in enumerate(answers, start=1):
        intake = service.answer_intake(answer)
        assert intake["step_index"] == index
    assert intake["completed"] is True
    assert intake["answers"]["target_roles"] == "M&A et private equity"
    with pytest.raises(UserFacingError, match="déjà terminé"):
        service.answer_intake("une septième réponse")

    job = service.import_job(
        manual_job(
            company="Banque Exemple",
            title="M&A Intern",
            requirements="Analyse de transactions, Excel et communication écrite.",
            description_original="Mission d’analyse sur des transactions cross-border.",
        )
    )
    draft = service.create_application_draft(job["id"], "en")
    assert draft["generation_mode"] == "local"
    assert draft["provider"].startswith("Local")
    assert "M&A Intern" in draft["cv_markdown"]
    assert "Banque Exemple" in draft["letter_markdown"]
    assert "Master Finance — EDHEC" in draft["letter_markdown"]
    assert "without overstating" in draft["letter_markdown"].lower()
    assert len(service.list_application_drafts()) == 1

    markdown_path = service.export_application_draft(draft["id"], "cv", "md")
    html_path = service.export_application_draft(draft["id"], "cv", "html")
    assert markdown_path.suffix == ".md"
    html_content = html_path.read_text(encoding="utf-8")
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in html_content
    assert "<script>alert(1)</script>" not in html_content
    assert html_path.parent == service.studio_dir

    docx_path = service.export_application_draft(draft["id"], "cv", "docx")
    pdf_path = service.export_application_draft(draft["id"], "cv", "pdf")
    assert docx_path.suffix == ".docx"
    assert pdf_path.read_bytes().startswith(b"%PDF")
    assert stat.S_IMODE(docx_path.stat().st_mode) & 0o077 == 0
    assert stat.S_IMODE(pdf_path.stat().st_mode) & 0o077 == 0
    with zipfile.ZipFile(docx_path) as archive:
        document_xml = archive.read("word/document.xml")
        relation_files = [name for name in archive.namelist() if name.endswith(".rels")]
        relation_xml = b"".join(archive.read(name) for name in relation_files)
        archive_names = archive.namelist()
    assert all("vbaProject" not in name for name in archive_names)
    assert b"TargetMode=\"External\"" not in relation_xml
    assert b"&lt;script&gt;alert(1)&lt;/script&gt;" in document_xml
    assert b"<script>alert(1)</script>" not in document_xml
    # Career documents target European applications, so both editable and PDF
    # variants use A4 rather than the stock US Letter document template.
    assert b'w:w="11906"' in document_xml
    assert b'w:h="16838"' in document_xml
    reader = PdfReader(str(pdf_path))
    assert reader.pages
    assert "Côme" in (reader.pages[0].extract_text() or "")
    assert abs(float(reader.pages[0].mediabox.width) - 595.28) < 1
    assert abs(float(reader.pages[0].mediabox.height) - 841.89) < 1
    assert b"/JavaScript" not in pdf_path.read_bytes()

    reset = service.reset_intake()
    assert reset["step_index"] == 0
    assert reset["answers"] == {}


def test_ai_draft_parser_never_accepts_non_json_or_missing_checks() -> None:
    parsed = parse_ai_draft(
        json.dumps({"cv_markdown": "# CV\nFact only", "letter_markdown": "# Letter\nFact only"}),
        "en",
    )
    assert parsed.language == "en"
    assert parsed.checks
    with pytest.raises(UserFacingError, match="modèle"):
        parse_ai_draft("This is not JSON", "fr")


def test_local_draft_translates_missing_fact_placeholders() -> None:
    job = {"company": "Example Co", "title": "Intern"}
    assert "[Education to complete]" in build_local_application_draft({}, {}, job, "en").cv_markdown
    assert "[Formazione da completare]" in build_local_application_draft({}, {}, job, "it").cv_markdown
    assert "[Ausbildung ergänzen]" in build_local_application_draft({}, {}, job, "de").cv_markdown


def test_manual_import_deduplicates_urls_and_preserves_user_tracking(tmp_path: Path) -> None:
    service = CareerService(tmp_path)
    first = service.import_job(manual_job())
    assert first["created"] is True
    job_id = first["id"]
    service.set_shortlist(job_id, True, "À approfondir")
    tracking = service.create_application(job_id)

    refreshed = service.import_job(
        manual_job(
            official_url="https://careers.example.test/jobs/42?utm_campaign=autumn&gclid=ignored",
            description_original="Description actualisée.",
        )
    )
    assert refreshed["created"] is False
    assert refreshed["duplicate"] is True
    assert refreshed["id"] == job_id
    assert refreshed["shortlisted"] is True
    assert refreshed["personal_note"] == "À approfondir"
    assert refreshed["application"]["id"] == tracking["id"]
    assert refreshed["description_original"] == "Description actualisée."

    # An unqualified ATS identifier pasted during a manual import cannot be
    # trusted as globally unique across companies.
    unrelated = service.import_job(
        manual_job(
            company="Autre banque",
            title="Private Equity Intern",
            city="Milan",
            official_url="",
            source_id="42",
            job_family="Private Equity",
        )
    )
    assert unrelated["created"] is True
    assert unrelated["id"] != job_id
    assert dedup_key(
        source_name="greenhouse",
        source_id="42",
        official_url="",
        company="x",
        title="x",
        city="x",
    ) == "source:greenhouse:42"


def test_application_tracking_cannot_claim_or_retry_a_submission(tmp_path: Path) -> None:
    service = CareerService(tmp_path)
    job = service.import_job(manual_job())
    application = service.create_application(job["id"])
    repeated = service.create_application(job["id"])
    assert repeated["id"] == application["id"]
    assert repeated["created"] is False

    with pytest.raises(UserFacingError, match="ne peut pas être défini"):
        service.update_application_stage(application["id"], "submitted_confirmed")
    with pytest.raises(UserFacingError, match="Approuve d’abord"):
        service.confirm_receipt(application["id"], "E-mail de confirmation")
    with pytest.raises(UserFacingError, match="approbation explicite"):
        service.approve_for_manual_submission(application["id"], False)

    approved = service.approve_for_manual_submission(application["id"], True, "Validation par Côme")
    assert approved["stage"] == "approved_for_manual_submission"
    confirmed = service.confirm_receipt(application["id"], "Dossier #2027-001")
    assert confirmed["stage"] == "submitted_confirmed"
    assert confirmed["receipt_status"] == "confirmed"
    with pytest.raises(UserFacingError, match="déjà une confirmation"):
        service.confirm_receipt(application["id"], "Dossier #2027-002")
    with pytest.raises(UserFacingError, match="ne peut pas revenir"):
        service.update_application_stage(application["id"], "to_prepare")
    with pytest.raises(UserFacingError, match="déjà confirmée"):
        service.mark_receipt_unknown(application["id"], "Timeout supposé")

    # A later recruiter response is a valid follow-up, but it does not erase
    # the confirmed receipt state.
    response = service.update_application_stage(application["id"], "response_received", "Réponse RH")
    assert response["stage"] == "response_received"
    assert response["receipt_status"] == "confirmed"


def test_exports_privacy_and_reset_are_isolated(tmp_path: Path) -> None:
    v3_data = tmp_path / "data"
    v3_output = tmp_path / "output"
    v3_data.mkdir()
    v3_output.mkdir()
    (v3_data / "keep.txt").write_text("do not touch", encoding="utf-8")
    (v3_output / "keep.txt").write_text("do not touch", encoding="utf-8")

    service = CareerService(tmp_path)
    service.update_profile({"display_name": "Côme", "eligibility": "unknown"})
    job = service.import_job(manual_job(company="=Formula Company"))
    application = service.create_application(job["id"])

    csv_path = service.export_applications("csv")
    with csv_path.open(encoding="utf-8-sig", newline="") as stream:
        exported_rows = list(csv.DictReader(stream, delimiter=";"))
    assert exported_rows[0]["Entreprise"] == "'=Formula Company"

    xlsx_path = service.export_applications("xlsx")
    workbook = load_workbook(xlsx_path, data_only=False)
    sheet = workbook["Candidatures"]
    assert sheet.freeze_panes == "A2"
    assert sheet.auto_filter.ref == sheet.dimensions
    assert sheet["A2"].value == "'=Formula Company"
    assert service.safe_export_path(xlsx_path.name) == xlsx_path
    with pytest.raises(UserFacingError):
        service.safe_export_path("../not-an-export.xlsx")

    privacy_path = service.export_personal_data()
    exported = json.loads(privacy_path.read_text(encoding="utf-8"))
    assert exported["profile"]["display_name"] == "Côme"
    assert exported["jobs"][0]["id"] == job["id"]
    assert exported["applications"][0]["id"] == application["id"]
    assert exported["application_events"]
    assert exported["audit_log"]

    with pytest.raises(UserFacingError, match="confirmation"):
        service.reset_personal_data("wrong phrase")
    assert service.list_jobs()
    service.reset_personal_data(DELETE_CONFIRMATION)
    assert service.list_jobs() == []
    assert service.get_profile()["display_name"] == ""
    assert (v3_data / "keep.txt").read_text(encoding="utf-8") == "do not touch"
    assert (v3_output / "keep.txt").read_text(encoding="utf-8") == "do not touch"
    assert not csv_path.exists()
    assert not xlsx_path.exists()


class FakeAgent:
    def provider_status(self) -> dict[str, object]:
        return {
            "gemini": {"configured": False, "primary_model": "fake", "fallback_models": []},
            "ollama": {"configured": False, "model": None},
            "request_timeout_seconds": 30,
            "retry_attempts": 1,
        }

    def ask(self, message: str, *, allow_writes: bool) -> dict[str, object]:
        return {"answer": "sans appel fournisseur", "tool_events": [], "provider": "Faux modèle"}


class FakeCareerDraftAgent(FakeAgent):
    def generate_career_application(self, prompt: str) -> dict[str, object]:
        assert "untrusted applicant and job data" in prompt
        return {
            "text": json.dumps(
                {
                    "cv_markdown": "# CV\nOnly supplied facts.",
                    "letter_markdown": "# Letter\nOnly supplied facts.",
                    "checks": ["Review supplied facts."],
                }
            ),
            "provider": "Faux fournisseur contrôlé",
        }


def test_career_routes_are_local_and_do_not_break_v3(tmp_path: Path) -> None:
    client = TestClient(create_app(tmp_path, agent_override=FakeAgent()))
    homepage = client.get("/")
    assert homepage.status_code == 200
    assert "Career Agent" in homepage.text
    assert homepage.headers["content-security-policy"]

    career_page = client.get("/career")
    assert career_page.status_code == 200
    for text in ("Découvrir", "Ma shortlist", "Application Studio", "Candidatures", "Coach d’entretien"):
        assert text in career_page.text

    health = client.get("/api/career/health")
    assert health.status_code == 200
    assert health.json()["network_connectors"] is True
    assert health.json()["automated_submission"] is False
    assert health.json()["calendar_export"] == {
        "enabled": True,
        "format": "ics",
        "local_only": True,
        "automatic_sync": False,
    }
    assert client.get("/api/health").json()["career_agent"]["enabled"] is True

    dashboard = client.get("/api/career/dashboard")
    assert dashboard.status_code == 200
    assert dashboard.json()["action_plan"][0]["id"] == "profile-completeness"
    assert all(
        set(item) == {"id", "priority", "title", "detail", "target_view"}
        for item in dashboard.json()["action_plan"]
    )

    profile = client.put("/api/career/profile", json={"display_name": "Côme", "eligibility": "unknown"})
    assert profile.status_code == 200
    assert profile.json()["eligibility"] == "unknown"
    malformed = client.post(
        "/api/career/jobs/import",
        json=manual_job(official_url="https://example.test:bad-port/jobs/1"),
    )
    assert malformed.status_code == 400

    imported = client.post("/api/career/jobs/import", json=manual_job())
    assert imported.status_code == 201
    job = imported.json()
    shortlisted = client.post(f"/api/career/jobs/{job['id']}/shortlist", json={"shortlisted": True, "note": "À lire"})
    assert shortlisted.status_code == 200
    application = client.post("/api/career/applications", json={"job_id": job["id"]})
    assert application.status_code == 201
    application_id = application.json()["id"]
    assert client.post(
        f"/api/career/applications/{application_id}/confirm-receipt",
        json={"confirmation_reference": "Mail reçu"},
    ).status_code == 400
    assert client.post(
        f"/api/career/applications/{application_id}/approve",
        json={"approved": True, "note": "Validation locale"},
    ).status_code == 200
    assert client.post(
        f"/api/career/applications/{application_id}/confirm-receipt",
        json={"confirmation_reference": "Mail reçu"},
    ).json()["receipt_status"] == "confirmed"

    csv_export = client.get("/api/career/export/csv")
    assert csv_export.status_code == 200
    assert csv_export.headers["content-type"].startswith("text/csv")
    calendar_export = client.get("/api/career/deadlines.ics")
    assert calendar_export.status_code == 200
    assert calendar_export.headers["content-type"].startswith("text/calendar")
    assert calendar_export.headers["cache-control"] == "no-store"
    assert calendar_export.content.startswith(b"BEGIN:VCALENDAR\r\n")
    assert client.request("DELETE", "/api/career/data", json={"confirmation": "not enough"}).status_code == 400
    assert client.request("DELETE", "/api/career/data", json={"confirmation": DELETE_CONFIRMATION}).json() == {"deleted": True}


def test_discovery_routes_use_an_injected_offline_connector_and_keep_exports_private(tmp_path: Path) -> None:
    connector = FakeDiscoveryConnector([_greenhouse_payload(greenhouse_job())])
    career = CareerService(tmp_path, discovery_connector=connector)  # type: ignore[arg-type]
    client = TestClient(create_app(tmp_path, agent_override=FakeAgent(), career_override=career))

    source = client.post(
        "/api/career/discovery-sources",
        json={"company": "Example Bank", "board_reference": "https://boards.greenhouse.io/example"},
    )
    assert source.status_code == 201
    assert connector.boards == []

    search = client.post("/api/career/discovery/search", json={"force": True})
    assert search.status_code == 200
    assert search.json()["outcomes"][0]["status"] == "success"
    assert len(connector.boards) == 1
    job = client.get("/api/career/jobs").json()["jobs"][0]
    assert job["company"] == "Example Bank"
    assert job["scoring"]["disclaimer"]

    draft = client.post(
        "/api/career/application-drafts",
        json={"job_id": job["id"], "language": "fr", "mode": "local", "consent_external": False},
    )
    assert draft.status_code == 201
    for export_format, media_type in (
        ("docx", "application/vnd.openxmlformats-officedocument.wordprocessingml.document"),
        ("pdf", "application/pdf"),
    ):
        response = client.get(
            f"/api/career/application-drafts/{draft.json()['id']}/download/cv/{export_format}"
        )
        assert response.status_code == 200
        assert response.headers["content-type"].startswith(media_type)
        assert response.headers["cache-control"] == "no-store"

    disabled = client.patch(f"/api/career/discovery-sources/{source.json()['id']}", json={"enabled": False})
    assert disabled.status_code == 200
    no_source = client.post("/api/career/discovery/search", json={"force": True})
    assert no_source.status_code == 400
    assert len(connector.boards) == 1


def test_interview_coach_routes_are_local_persistent_and_provider_free(tmp_path: Path) -> None:
    client = TestClient(create_app(tmp_path, agent_override=FakeAgent()))
    health = client.get("/api/career/health")
    assert health.status_code == 200
    assert health.json()["interview_coach"]["local_text_only"] is True

    job = client.post("/api/career/jobs/import", json=manual_job()).json()
    application = client.post("/api/career/applications", json={"job_id": job["id"]}).json()
    started = client.post(
        "/api/career/interview-sessions",
        json={
            "mode": "company",
            "difficulty": "intermediate",
            "language": "en",
            "application_id": application["id"],
        },
    )
    assert started.status_code == 201
    session = started.json()
    assert session["current_question"]["id"]
    assert session["job_id"] == job["id"]

    answered = client.post(
        f"/api/career/interview-sessions/{session['id']}/answers",
        json={
            "answer": "I will use the official job requirements, connect them to verified profile evidence, and prepare a question for the interviewer."
        },
    )
    assert answered.status_code == 200
    assert answered.json()["turns"][0]["feedback"]["disclaimer"]
    completed = client.post(f"/api/career/interview-sessions/{session['id']}/complete")
    assert completed.status_code == 200
    assert completed.json()["status"] == "completed"
    history = client.get("/api/career/interview-sessions")
    assert history.status_code == 200
    assert history.json()["interview_sessions"][0]["progress"]["answered_count"] == 1


def test_profile_import_routes_are_private_and_require_apply(tmp_path: Path) -> None:
    client = TestClient(create_app(tmp_path, agent_override=FakeAgent()))
    payload = b"""Jane Doe
jane@example.test
https://www.linkedin.com/in/jane-doe

FORMATION
Master Finance

COMPETENCES
Excel, Python
"""
    imported = client.post(
        "/api/career/profile-imports",
        data={"source_kind": "linkedin_export"},
        files={"document": ("profil-linkedin.txt", payload, "text/plain")},
    )
    assert imported.status_code == 201
    draft = imported.json()
    assert draft["source_kind"] == "linkedin_export"
    assert draft["has_local_file"] is True
    assert draft["suggestions"]["values"]["education"] == "Master Finance"
    assert client.get("/api/career/profile").json()["education"] == ""
    # The normal V3 file registry never sees a private Career profile source.
    assert client.get("/api/files").json()["count"] == 0

    applied = client.post(
        f"/api/career/profile-imports/{draft['id']}/apply",
        json={
            "base_profile_updated_at": draft["base_profile_updated_at"],
            "updates": [
                {"field": "education", "mode": "replace", "value": "Master Finance"},
                {"field": "skills", "mode": "replace", "value": "Excel, Python"},
            ],
        },
    )
    assert applied.status_code == 200
    assert applied.json()["profile"]["education"] == "Master Finance"
    assert applied.json()["profile_import"]["status"] == "applied"
    assert client.delete(f"/api/career/profile-imports/{draft['id']}").json() == {"deleted": True}
    assert client.get("/api/career/profile-imports").json()["profile_imports"] == []

    pasted = client.post(
        "/api/career/profile-imports/text",
        json={
            "source_kind": "linkedin_text",
            "original_name": "profil-copié",
            "text": "John Doe\n\nLANGUES\nFrançais, anglais C1",
        },
    )
    assert pasted.status_code == 201
    assert pasted.json()["has_local_file"] is False


def test_career_studio_routes_default_to_local_and_gate_ai_consent(tmp_path: Path) -> None:
    client = TestClient(create_app(tmp_path, agent_override=FakeAgent()))
    profile = client.put(
        "/api/career/profile",
        json={
            "display_name": "Côme",
            "education": "Master Finance",
            "experience": "Projet étudiant",
            "skills": "Excel",
            "languages": "Français, anglais C1",
            "eligibility": "unknown",
        },
    )
    assert profile.status_code == 200
    first_question = client.get("/api/career/intake")
    assert first_question.status_code == 200
    assert first_question.json()["current_question"]["key"] == "target_roles"
    assert client.post("/api/career/intake/answers", json={"answer": "M&A"}).status_code == 200

    job = client.post(
        "/api/career/jobs/import",
        json=manual_job(requirements="Excel et analyse financière"),
    ).json()
    local_draft = client.post(
        "/api/career/application-drafts",
        json={"job_id": job["id"], "language": "fr", "mode": "local", "consent_external": False},
    )
    assert local_draft.status_code == 201
    draft = local_draft.json()
    assert draft["generation_mode"] == "local"
    assert client.get(f"/api/career/application-drafts/{draft['id']}").json()["cv_markdown"]
    html_download = client.get(f"/api/career/application-drafts/{draft['id']}/download/cv/html")
    assert html_download.status_code == 200
    assert html_download.headers["content-type"].startswith("text/html")

    no_consent = client.post(
        "/api/career/application-drafts",
        json={"job_id": job["id"], "language": "fr", "mode": "ai", "consent_external": False},
    )
    assert no_consent.status_code == 400
    assert client.delete(f"/api/career/application-drafts/{draft['id']}").json() == {"deleted": True}


def test_career_studio_ai_route_requires_consent_and_uses_injected_provider(tmp_path: Path) -> None:
    client = TestClient(create_app(tmp_path, agent_override=FakeCareerDraftAgent()))
    job = client.post("/api/career/jobs/import", json=manual_job()).json()
    blocked = client.post(
        "/api/career/application-drafts",
        json={"job_id": job["id"], "language": "en", "mode": "ai", "consent_external": False},
    )
    assert blocked.status_code == 400
    created = client.post(
        "/api/career/application-drafts",
        json={"job_id": job["id"], "language": "en", "mode": "ai", "consent_external": True},
    )
    assert created.status_code == 201
    assert created.json()["generation_mode"] == "ai"
    assert created.json()["provider"] == "Faux fournisseur contrôlé"
