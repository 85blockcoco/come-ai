"""Tests for the versioned offer-intelligence snapshot (SPEC SK-07 / CVBOOST-28).

Every offer used here is synthetic: no real company, no real posting, no
personal data.  The suite checks the contract of the bridge:

- one snapshot per offer, one identifier per requirement, everywhere;
- every confirmed fact carries its verbatim passage and its offsets;
- a missing information stays "à vérifier" and is never silently dropped;
- a repeated import with an unchanged source keeps the same version and the
  same identifiers, a changed source creates a new version;
- notes, shortlist and application state survive a re-import;
- the whole feature works offline, without any model call.
"""

from __future__ import annotations

import json
from pathlib import Path
import socket

import pytest

from career.offer_intelligence import (
    OfferIntelligenceSnapshot,
    align_display_requirements,
    build_snapshot,
    compute_source_hash,
    requirement_index,
    snapshot_summary,
)
from career.offer_intelligence_store import (
    delete_snapshots,
    ensure_schema,
    load_current,
    load_history,
    store_snapshot,
)
from career.offer_qualification import qualify_offer
from career.service import CareerService

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "offer_intelligence" / "offers.json"
ADVERSARIAL_FIXTURES = (
    Path(__file__).resolve().parent / "fixtures" / "offer_intelligence" / "adversarial.json"
)


def _cases() -> list[dict]:
    return json.loads(FIXTURES.read_text(encoding="utf-8"))["cases"]


def _adversarial_cases() -> list[dict]:
    return json.loads(ADVERSARIAL_FIXTURES.read_text(encoding="utf-8"))["cases"]


def _case(case_id: str) -> dict:
    return next(case for case in _cases() if case["id"] == case_id)


def _offer(case_id: str) -> dict:
    return dict(_case(case_id)["offer"])


def _snapshot(case_id: str) -> OfferIntelligenceSnapshot:
    offer = _offer(case_id)
    return build_snapshot(offer, qualify_offer(offer).to_dict())


def _synthetic_payload(**changes: object) -> dict:
    payload: dict[str, object] = {
        "company": "Synthetic Bank",
        "title": "M&A Intern",
        "official_url": "https://careers.example.test/jobs/77",
        "job_family": "M&A / Investment Banking",
        "city": "Berlin",
        "country": "Germany",
        "posted_date": "2026-10-01",
        "requirements": "Advanced Excel\nSQL for data analysis",
        "languages_required": "English (C1)",
        "description_original": (
            "Apply by 15 November 2026.\n"
            "The programme starts in January 2027 and lasts six months.\n"
            "Fluent English is required."
        ),
        "source_status": "open",
    }
    payload.update(changes)
    return payload


# --------------------------------------------------------------- the contract


def test_snapshot_exposes_every_section_of_the_contract() -> None:
    snapshot = _snapshot("fr_stage_complet")

    assert snapshot.schema_version >= 1
    assert snapshot.source_hash and len(snapshot.source_hash) == 64
    assert snapshot.temporal_facts and snapshot.requirements
    assert snapshot.provenance_map
    assert snapshot.qualifications["contract_type"] == "internship"
    assert snapshot.trust["status"] in {"verified", "unverified", "contradictory", "missing"}
    assert snapshot.geo["city"] == "Berlin"
    assert snapshot.lang["status"] == "known"
    assert snapshot.contradictions == ()
    assert snapshot.missing == ()


def test_snapshot_is_pure_and_never_modifies_the_offer() -> None:
    offer = _offer("fr_stage_complet")
    reference = json.dumps(offer, ensure_ascii=False, sort_keys=True)

    _snapshot("fr_stage_complet")

    assert json.dumps(offer, ensure_ascii=False, sort_keys=True) == reference


def test_snapshot_is_deterministic_for_the_same_source() -> None:
    first = _snapshot("fr_stage_complet")
    second = _snapshot("fr_stage_complet")

    assert first.source_hash == second.source_hash
    assert first.requirement_ids() == second.requirement_ids()
    assert [fact.id for fact in first.temporal_facts] == [fact.id for fact in second.temporal_facts]


def test_source_hash_ignores_the_user_state_of_the_offer() -> None:
    offer = _offer("fr_stage_complet")
    with_note = {**offer, "personal_note": "À suivre", "shortlisted": 1, "status": "shortlisted"}

    assert compute_source_hash(offer) == compute_source_hash(with_note)


def test_requirement_identifiers_are_the_canonical_ones() -> None:
    snapshot = _snapshot("fr_stage_complet")

    assert all(record.id.startswith("req_") for record in snapshot.requirements)
    assert len(set(snapshot.requirement_ids())) == len(snapshot.requirements)


@pytest.mark.parametrize("case_id", [case["id"] for case in _cases()])
def test_frozen_corpus_classifies_every_fact_and_requirement(case_id: str) -> None:
    expected = _case(case_id)["expected"]
    snapshot = _snapshot(case_id)

    facts = [
        {
            "kind": fact.kind,
            "value": fact.value,
            "lower_bound": fact.lower_bound,
            "upper_bound": fact.upper_bound,
            "precision": fact.precision,
        }
        for fact in snapshot.temporal_facts
    ]
    assert facts == expected["temporal_facts"]

    requirements = [
        {"text": record.text, "modality": record.modality, "category": record.category}
        for record in snapshot.requirements
    ]
    assert requirements == expected["requirements"]

    assert {item.field for item in snapshot.missing} == set(expected["missing_fields"])
    assert len(snapshot.contradictions) == expected["contradictions"]


def test_a_deadline_is_never_reused_as_a_start_date() -> None:
    snapshot = _snapshot("en_deadline_is_not_a_start")

    deadline = [fact for fact in snapshot.temporal_facts if fact.kind == "deadline"]
    start = [fact for fact in snapshot.temporal_facts if fact.kind == "start"]

    assert [fact.value for fact in deadline] == ["2026-11-15"]
    assert [fact.value for fact in start] == ["2027-01"]
    assert deadline[0].id != start[0].id


def test_a_month_only_statement_never_becomes_an_exact_day() -> None:
    snapshot = _snapshot("it_scadenza")

    start = next(fact for fact in snapshot.temporal_facts if fact.kind == "start")

    assert start.precision == "month"
    assert start.value == "2027-01"
    assert len(start.value or "") == len("YYYY-MM")
    assert start.evidence.quote == "Inizio attività: gennaio 2027"


def test_an_upper_bound_never_proves_a_minimum() -> None:
    snapshot = _snapshot("en_deadline_is_not_a_start")

    duration = next(fact for fact in snapshot.temporal_facts if fact.kind == "duration")

    assert duration.upper_bound == "6"
    assert duration.lower_bound is None
    assert duration.value is None


def test_every_confirmed_fact_carries_its_quote_and_its_offsets() -> None:
    snapshot = _snapshot("fr_stage_complet")

    for fact in snapshot.temporal_facts:
        evidence = fact.evidence
        assert evidence.quote
        source_text = _offer("fr_stage_complet").get(evidence.source_field) or ""
        if evidence.start_offset is not None:
            assert source_text[evidence.start_offset:evidence.end_offset] == evidence.quote
        assert snapshot.provenance_map[fact.id].quote == evidence.quote

    for record in snapshot.requirements:
        evidence = record.evidence
        assert evidence.quote
        assert evidence.locator
        source_text = _offer("fr_stage_complet").get(evidence.source_field) or ""
        if evidence.start_offset is not None:
            assert source_text[evidence.start_offset:evidence.end_offset] == evidence.quote
        assert snapshot.provenance_map[record.id].quote == evidence.quote


def test_a_missing_information_stays_to_verify_and_is_never_dropped() -> None:
    snapshot = _snapshot("it_scadenza")

    missing = {item.field: item for item in snapshot.missing}

    assert "duration_months" in missing
    for item in missing.values():
        assert item.status == "to_verify"
        assert "vérifier" in item.reason
        assert "absente" not in item.reason


def test_a_contradiction_keeps_both_sides_without_choosing_one() -> None:
    snapshot = _snapshot("structured_field_contradicts_text")

    assert snapshot.contradictions
    for contradiction in snapshot.contradictions:
        assert contradiction.left and contradiction.right
        assert contradiction.left != contradiction.right


def test_an_injection_attempt_stays_inert_data() -> None:
    snapshot = _snapshot("injection_and_truncation")

    suspects = [record for record in snapshot.requirements if record.injection_suspect]

    assert len(suspects) == 1
    assert suspects[0].modality == "unknown"
    assert any("instruction" in warning for warning in snapshot.warnings)


def test_an_expired_deadline_stays_visible() -> None:
    snapshot = _snapshot("expired_deadline")

    deadlines = [fact for fact in snapshot.temporal_facts if fact.kind == "deadline"]

    assert deadlines
    assert all(fact.value == "2026-01-15" for fact in deadlines)


def test_the_snapshot_never_carries_candidate_profile_data() -> None:
    offer = {**_offer("fr_stage_complet"), "skills": "un fait du candidat", "profile": "secret"}
    snapshot = build_snapshot(offer)

    assert "skills" not in snapshot.qualifications
    assert "profile" not in snapshot.qualifications
    assert "secret" not in json.dumps(snapshot.to_dict(), ensure_ascii=False)


def test_the_snapshot_works_offline_without_any_model_call(monkeypatch: pytest.MonkeyPatch) -> None:
    def _forbidden(*args: object, **kwargs: object) -> None:
        raise AssertionError("aucun appel réseau n'est autorisé pendant l'analyse")

    monkeypatch.setattr(socket, "socket", _forbidden)
    monkeypatch.setattr(socket, "create_connection", _forbidden)

    snapshot = _snapshot("fr_stage_complet")

    assert snapshot.requirements


def test_the_summary_points_at_the_same_identifiers() -> None:
    snapshot = _snapshot("fr_stage_complet")
    summary = snapshot_summary(snapshot)

    assert summary["requirement_ids"] == list(snapshot.requirement_ids())
    assert summary["source_hash"] == snapshot.source_hash
    assert summary["requirements_total"] == len(snapshot.requirements)


def test_the_requirement_index_resolves_every_identifier() -> None:
    snapshot = _snapshot("fr_stage_complet")
    index = requirement_index(snapshot)

    assert set(index) == set(snapshot.requirement_ids())
    for identifier, record in index.items():
        assert record["id"] == identifier
        assert record["text"]


def test_the_snapshot_round_trips_through_its_json_document() -> None:
    snapshot = _snapshot("fr_stage_complet")
    restored = OfferIntelligenceSnapshot.from_dict(snapshot.to_dict())

    assert restored.source_hash == snapshot.source_hash
    assert restored.requirement_ids() == snapshot.requirement_ids()
    assert len(restored.temporal_facts) == len(snapshot.temporal_facts)


def test_the_alignment_never_invents_an_identifier() -> None:
    snapshot = _snapshot("fr_stage_complet")
    aligned = align_display_requirements(
        [{"text": "Maîtrise d'Excel"}, {"text": "Une exigence absente du contrat"}],
        snapshot,
    )

    assert aligned[0]["requirement_id"] in snapshot.requirement_ids()
    assert aligned[1]["requirement_id"] is None


# ------------------------------------------------------------- the versioning


def test_an_unchanged_source_keeps_the_version_and_the_identifiers(tmp_path: Path) -> None:
    service = CareerService(tmp_path)
    job = service.import_job(_synthetic_payload())

    again = service.import_job(_synthetic_payload())

    assert again["id"] == job["id"]
    assert again["offer_intelligence_version"] == job["offer_intelligence_version"]
    detail = service.get_job(job["id"])
    assert detail["offer_intelligence_summary"]["requirement_ids"] == job["offer_intelligence_summary"]["requirement_ids"]


def test_a_changed_source_creates_a_new_version_and_retires_the_previous_one(tmp_path: Path) -> None:
    service = CareerService(tmp_path)
    job = service.import_job(_synthetic_payload())
    first_ids = list(job["offer_intelligence_summary"]["requirement_ids"])

    updated = service.import_job(
        _synthetic_payload(description_original="Apply by 20 November 2026.\nSQL is required.")
    )

    assert updated["offer_intelligence_version"] == job["offer_intelligence_version"] + 1
    detail = service.get_job(job["id"])
    assert detail["offer_intelligence"]["source_hash"] != job["offer_intelligence_summary"]["source_hash"]
    assert list(detail["offer_intelligence_summary"]["requirement_ids"]) != first_ids

    history = service.get_offer_intelligence(job["id"])["history"]
    assert [entry["version"] for entry in history] == [2, 1]
    assert [entry["is_current"] for entry in history] == [True, False]


def test_a_stale_evidence_is_never_presented_as_current(tmp_path: Path) -> None:
    service = CareerService(tmp_path)
    job = service.import_job(_synthetic_payload())
    stale_quote = "Apply by 15 November 2026."

    service.import_job(_synthetic_payload(description_original="Apply by 20 November 2026.\nSQL is required."))

    detail = service.get_job(job["id"])
    quotes = [fact["evidence"]["quote"] for fact in detail["offer_intelligence"]["temporal_facts"]]
    assert stale_quote not in quotes
    history = service.get_offer_intelligence(job["id"])["history"]
    assert len(history) == 2
    assert history[1]["is_current"] is False


def test_the_notes_shortlist_and_application_survive_a_reimport(tmp_path: Path) -> None:
    service = CareerService(tmp_path)
    job = service.import_job(_synthetic_payload())
    service.set_shortlist(job["id"], True, "À relancer")
    service.update_job_note(job["id"], "Relancer l'offre.")
    application = service.create_application(job["id"])
    service.update_application_stage(application["id"], "to_prepare")

    service.import_job(_synthetic_payload())

    refreshed = service.get_job(job["id"])
    assert refreshed["personal_note"] == "Relancer l'offre."
    assert refreshed["shortlisted"] is True
    assert refreshed["application"]["id"] == application["id"]
    assert refreshed["application"]["stage"] == "to_prepare"


def test_the_store_keeps_one_current_version_per_offer(tmp_path: Path) -> None:
    import sqlite3

    connection = sqlite3.connect(tmp_path / "store.sqlite3")
    connection.row_factory = sqlite3.Row
    ensure_schema(connection)
    snapshot = build_snapshot(_offer("fr_stage_complet"))
    snapshot = OfferIntelligenceSnapshot(
        job_id="job_store", schema_version=snapshot.schema_version,
        source_hash=snapshot.source_hash, temporal_facts=snapshot.temporal_facts,
        requirements=snapshot.requirements, contradictions=snapshot.contradictions,
        missing=snapshot.missing, qualifications=snapshot.qualifications,
        trust=snapshot.trust, geo=snapshot.geo, lang=snapshot.lang,
        provenance_map=snapshot.provenance_map, warnings=snapshot.warnings,
    )

    first = store_snapshot(connection, snapshot, now="2026-10-21T00:00:00+00:00")
    second = store_snapshot(connection, snapshot, now="2026-10-21T00:01:00+00:00")

    assert first["version"] == 1 and first["created"] is True
    assert second["version"] == 1 and second["created"] is False
    assert second["changed"] is False
    current = load_current(connection, "job_store")
    assert current is not None and current["version"] == 1
    assert len(load_history(connection, "job_store")) == 1
    assert delete_snapshots(connection, "job_store") == 1
    assert load_current(connection, "job_store") is None
    connection.close()


# -------------------------------------------------------- the shared screens


def test_every_screen_shares_the_same_requirement_identifiers(tmp_path: Path) -> None:
    service = CareerService(tmp_path)
    service.update_stage_search({"domains": ["M&A"], "cities": ["Berlin"], "countries": ["Germany"]})
    job = service.import_job(_synthetic_payload())

    explorer = service.list_jobs()[0]
    detail = service.get_job(job["id"])
    prep = service.get_job_prep(job["id"])
    matches = service.list_stage_matches()["matches"]
    match = next(item for item in matches if item["job"]["id"] == job["id"])

    explorer_ids = list(explorer["offer_intelligence_summary"]["requirement_ids"])
    detail_ids = [record["id"] for record in detail["offer_intelligence"]["requirements"]]
    prep_ids = list(prep["offer_intelligence"]["requirement_ids"])
    match_ids = list(match["requirement_ids"])

    assert explorer_ids == detail_ids == prep_ids == match_ids
    assert prep_ids
    assert [item["requirement_id"] for item in prep["requirements"]] == prep_ids


def test_the_dashboard_checklist_reads_the_same_snapshot(tmp_path: Path) -> None:
    import re

    service = CareerService(tmp_path)
    service.update_profile({"skills": "Excel and SQL", "languages": "English C1"})
    job = service.import_job(_synthetic_payload())
    application = service.create_application(job["id"])

    dashboard = service.application_dashboard()
    entry = next(item for item in dashboard["entries"] if item["application_id"] == application["id"])

    detail = service.get_job(job["id"])
    total = len(detail["offer_intelligence"]["requirements"])
    found = re.search(
        r"(\d+)/(\d+) exigences détectées",
        entry["prep"]["factors"]["couverture"]["detail"],
    )

    assert found is not None
    assert int(found.group(2)) == total


def test_the_snapshot_survives_a_restart(tmp_path: Path) -> None:
    service = CareerService(tmp_path)
    job = service.import_job(_synthetic_payload())
    before = service.get_job(job["id"])["offer_intelligence_summary"]["requirement_ids"]

    restarted = CareerService(tmp_path)

    after = restarted.get_job(job["id"])["offer_intelligence_summary"]["requirement_ids"]
    assert after == before


def test_the_cover_letter_quotes_the_canonical_requirements(tmp_path: Path) -> None:
    service = CareerService(tmp_path)
    service.update_profile({"skills": "Excel and SQL", "languages": "English C1"})
    job = service.import_job(_synthetic_payload())

    draft = service.create_application_draft(job["id"], "fr")
    prep = service.get_job_prep(job["id"])

    canonical = [
        record["text"] for record in prep["offer_intelligence"]["requirements_by_id"].values()
    ]

    assert canonical
    assert any(
        text in draft["cv_markdown"] or text in draft["letter_markdown"] for text in canonical
    )


def test_the_route_exposes_the_same_snapshot_as_the_service(tmp_path: Path) -> None:
    from fastapi.testclient import TestClient

    from come_ai_web import create_app

    service = CareerService(tmp_path)
    job = service.import_job(_synthetic_payload())

    with TestClient(create_app(base_dir=tmp_path, career_override=service)) as client:
        detail = client.get(f"/api/career/jobs/{job['id']}").json()
        alias = client.get(f"/api/career/offer-intelligence/{job['id']}").json()
        nested = client.get(f"/api/career/jobs/{job['id']}/offer-intelligence").json()

    assert alias["snapshot"]["source_hash"] == detail["offer_intelligence"]["source_hash"]
    assert nested["snapshot"]["source_hash"] == detail["offer_intelligence"]["source_hash"]
    assert alias["summary"]["requirement_ids"] == nested["summary"]["requirement_ids"]


# ------------------------------------------------------- the adversarial pass
#
# Two statements that agree must never be shown as a contradiction, and two
# statements that cannot both be true must always be shown.  A user who is
# told that a correct offer is contradictory stops trusting the screen.


@pytest.mark.parametrize("case", _adversarial_cases(), ids=lambda case: case["id"])
def test_the_adversarial_corpus_separates_compatibility_from_contradiction(case: dict) -> None:
    offer = dict(case["offer"])
    snapshot = build_snapshot(offer, qualify_offer(offer).to_dict())

    assert len(snapshot.contradictions) == case["expected"]["contradictions"]
    assert sorted(item.kind for item in snapshot.contradictions) == sorted(
        case["expected"]["kinds"]
    )


def test_a_month_statement_never_contradicts_the_day_it_contains() -> None:
    offer = {
        "id": "job_month_contains_day",
        "title": "Data Analyst Intern",
        "company": "Synthetic Analytics",
        "city": "Berlin",
        "country": "Germany",
        "start_date": "2027-01-15",
        "requirements": "SQL for data analysis",
        "description_original": "The programme starts in January 2027.",
    }

    snapshot = build_snapshot(offer)

    starts = [fact for fact in snapshot.temporal_facts if fact.kind == "start"]
    assert {fact.precision for fact in starts} == {"month", "exact_date"}
    assert snapshot.contradictions == ()


def test_an_upper_bound_never_contradicts_the_duration_it_allows() -> None:
    offer = {
        "id": "job_bound_allows_exact",
        "title": "Data Analyst Intern",
        "company": "Synthetic Analytics",
        "city": "London",
        "country": "United Kingdom",
        "requirements": "Advanced Excel",
        "description_original": (
            "The placement lasts up to six months.\nThe placement lasts six months."
        ),
    }

    snapshot = build_snapshot(offer)

    durations = [fact for fact in snapshot.temporal_facts if fact.kind == "duration"]
    assert durations
    assert snapshot.contradictions == ()


def test_a_real_conflict_is_never_hidden() -> None:
    offer = {
        "id": "job_real_conflict",
        "title": "Data Analyst Intern",
        "company": "Synthetic Analytics",
        "city": "Berlin",
        "country": "Germany",
        "requirements": "SQL for data analysis",
        "description_original": (
            "The programme starts 5 January 2027.\nThe programme starts 12 January 2027."
        ),
    }

    snapshot = build_snapshot(offer)

    assert len(snapshot.contradictions) == 1
    contradiction = snapshot.contradictions[0]
    assert contradiction.kind == "temporal_conflict"
    assert contradiction.left["value"] == "2027-01-05"
    assert contradiction.right["value"] == "2027-01-12"


def test_a_disjoint_duration_is_never_hidden() -> None:
    offer = {
        "id": "job_disjoint_duration",
        "title": "Data Analyst Intern",
        "company": "Synthetic Analytics",
        "city": "Berlin",
        "country": "Germany",
        "requirements": "SQL for data analysis",
        "description_original": (
            "The placement lasts at least eight months.\nThe placement lasts up to four months."
        ),
    }

    snapshot = build_snapshot(offer)

    assert len(snapshot.contradictions) == 1
    assert snapshot.contradictions[0].topic == "duration"


def test_the_qualification_facts_keep_their_evidence() -> None:
    offer = _offer("fr_stage_complet")
    snapshot = build_snapshot(offer, qualify_offer(offer).to_dict())

    provenance = snapshot.qualifications.get("provenance")
    assert isinstance(provenance, dict) and provenance
    for field, evidence in provenance.items():
        assert isinstance(evidence, dict), field
        assert evidence.get("source"), field
        assert "value" in evidence, field


def test_the_source_hash_covers_the_whole_source_text() -> None:
    before = {
        "id": "job_long_text",
        "title": "Data Intern",
        "company": "Synthetic Co",
        "description_original": ("A" * 40_000) + "Apply by 15 November 2026.",
    }
    after = {
        "id": "job_long_text",
        "title": "Data Intern",
        "company": "Synthetic Co",
        "description_original": ("A" * 40_000) + "Apply by 20 November 2026.",
    }

    assert compute_source_hash(before) != compute_source_hash(after)


def test_an_unchanged_requirement_keeps_its_identifier_after_a_refresh(tmp_path: Path) -> None:
    service = CareerService(tmp_path)
    job = service.import_job(_synthetic_payload())
    before = set(job["offer_intelligence_summary"]["requirement_ids"])

    refreshed = service.import_job(
        _synthetic_payload(description_original="Apply by 15 November 2026.\nSQL is required.")
    )

    after = set(refreshed["offer_intelligence_summary"]["requirement_ids"])
    assert before & after
    assert refreshed["offer_intelligence_version"] == job["offer_intelligence_version"] + 1


def test_the_cv_gaps_carry_the_canonical_requirement_id(tmp_path: Path) -> None:
    service = CareerService(tmp_path)
    service.update_profile({"skills": "Communication and teamwork"})
    service.import_profile_text(
        source_kind="cv",
        text=(
            "EXPERIENCE\nSynthetic Corp — Analyst (2024-2026)\n"
            "Reduced the reporting time by 30%.\n"
            "FORMATION\nMaster 2 Finance — Synthetic University (2023)\n"
            "SKILLS\nCommunication and teamwork\n"
            "LANGUAGES\nEnglish C1\n"
            "PROJECTS\nExcel model for a retail dashboard\n"
            "CERTIFICATIONS\nExcel certification\n"
        ),
    )
    job = service.import_job(
        _synthetic_payload(language="English", start_date="2027-01-15", end_date="2027-07-15")
    )

    prep = service.get_job_prep(job["id"])
    detail = service.get_job(job["id"])
    canonical = {record["id"] for record in detail["offer_intelligence"]["requirements"]}

    gaps = [gap for gap in prep["gaps"] if gap.get("requirement_id")]
    assert gaps
    for gap in gaps:
        assert gap["requirement_id"] in canonical


def test_the_snapshot_stays_readable_without_any_candidate_data(tmp_path: Path) -> None:
    service = CareerService(tmp_path)
    job = service.import_job(_synthetic_payload())
    service.update_job_note(job["id"], "Relancer avant la date limite.")

    detail = service.get_job(job["id"])

    assert "Relancer avant la date limite." not in json.dumps(
        detail["offer_intelligence"], ensure_ascii=False
    )
