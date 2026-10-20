"""Regression contract for the bounded, verified Career source expansion."""

from __future__ import annotations

from datetime import datetime
from urllib.parse import urlsplit

from career.connectors import default_exploration_connectors
from career.discovery import GreenhouseJobBoardConnector
from career.exploration import EXPLORATION_MAX_SOURCES
from career.source_registry import CURATED_SOURCES
from career.stage_search import STAGE_DOMAINS
from scripts.live_source_check import REPORT_SCHEMA, build_report, live_finance_brief


NEW_VERIFIED_SOURCES = {
    ("Man Group", "greenhouse", "mangroup"),
    ("AQR", "greenhouse", "aqr"),
    ("Robinhood", "greenhouse", "robinhood"),
    ("General Atlantic", "greenhouse", "generalatlantic"),
    ("Qonto", "lever", "qonto"),
}

SECOND_WAVE_VERIFIED_SOURCES = {
    ("Doctolib", "greenhouse", "doctolib"),
    ("Pigment", "lever", "pigment"),
    ("OakNorth", "ashby", "oaknorth"),
    ("Monzo", "greenhouse", "monzo"),
    ("Thought Machine", "ashby", "thought-machine"),
    ("Alan", "ashby", "alan"),
    ("Contentsquare", "lever", "contentsquare"),
    ("Dataiku", "greenhouse", "dataiku"),
}

WAVE3_VERIFIED_SOURCES = {
    # Connecteur Recruitee (neuf) et première source SmartRecruiters démontrée.
    ("bunq", "recruitee", "bunq"),
    ("Experian", "smartrecruiters", "Experian"),
}


def _token(source: dict[str, str]) -> str:
    return source.get("board_token") or source.get("company_identifier") or ""


def test_registry_contains_only_the_reviewed_source_expansion() -> None:
    observed = {(source["company"], source["provider"], _token(source)) for source in CURATED_SOURCES}
    assert NEW_VERIFIED_SOURCES <= observed
    assert SECOND_WAVE_VERIFIED_SOURCES <= observed
    assert WAVE3_VERIFIED_SOURCES <= observed


def test_registry_identifiers_are_unique_and_have_auditable_provenance() -> None:
    identities: set[tuple[str, str]] = set()
    ids: set[str] = set()
    for source in CURATED_SOURCES:
        identity = (source["provider"], _token(source))
        assert identity[1]
        assert identity not in identities
        assert source["id"] not in ids
        identities.add(identity)
        ids.add(source["id"])
        for field in ("public_url", "provenance_url"):
            parsed = urlsplit(source[field])
            assert parsed.scheme == "https" and parsed.hostname
        assert datetime.fromisoformat(source["verified_at"].replace("Z", "+00:00")).tzinfo is not None


def test_explicit_explorer_enables_registered_public_ats_connectors() -> None:
    connectors = default_exploration_connectors(GreenhouseJobBoardConnector())
    assert connectors["lever"].enabled is True
    assert connectors["ashby"].enabled is True
    assert connectors["smartrecruiters"].enabled is True


def test_one_explicit_refresh_can_consult_the_whole_curated_registry() -> None:
    assert EXPLORATION_MAX_SOURCES >= len(CURATED_SOURCES)


def test_every_connector_declares_known_conditions_and_official_documentation() -> None:
    from career.connectors import CONNECTOR_SPECS

    providers = {source["provider"] for source in CURATED_SOURCES}
    documented = set(CONNECTOR_SPECS) | {"greenhouse"}
    assert providers <= documented
    for spec in CONNECTOR_SPECS.values():
        assert spec.doc_verified is True
        assert spec.known_conditions.strip()
        assert spec.documentation_url.startswith("https://")


def test_live_report_keeps_only_bounded_public_job_facts() -> None:
    payload = {
        "brief": {"contract_types": ["stage"], "start_months": [1]},
        "summary": {"sources_succeeded": 1, "retained_count": 1},
        "outcomes": [{"source_id": "source:one", "provider": "greenhouse", "company": "Example",
                      "status": "success", "attempted": True, "raw_count": 2, "retained_count": 1,
                      "message": "internal detail not exported"}],
        "matches": [{"job": {"company": "Example", "title": "Finance Intern", "location": "Paris",
                               "official_url": "https://careers.example.test/job/1", "source_name": "greenhouse",
                               "source_id": "public-1", "description_original": "large remote body"},
                     "qualification": {"contract_type": "internship", "target_status": "to_verify",
                                       "missing_fields": ["durée"]}}],
    }
    report = build_report(payload, source_count=1)
    assert report["schema"] == REPORT_SCHEMA
    assert report["registered_sources_checked"] == 1
    assert report["matches"][0]["target_status"] == "to_verify"
    encoded = str(report)
    assert "large remote body" not in encoded
    assert "internal detail not exported" not in encoded


def test_live_check_explicitly_selects_every_finance_domain() -> None:
    brief = live_finance_brief()
    assert set(brief["domains"]) == set(STAGE_DOMAINS)
    assert brief["contract_types"] == ["stage", "cdd", "cdi", "vie"]
    assert brief["start_months"] == [1, 2, 3]
    assert brief["minimum_stage_duration_months"] == 6
