"""Source-published fields stay attributed and separate from qualification."""

from __future__ import annotations

import copy

from career.service import CareerService


def payload(*, contract: str = "Internship", quote: str = "Contract type: internship") -> dict:
    return {
        "company": "Synthetic Bank",
        "title": "Finance Intern",
        "source_name": "greenhouse",
        "source_id": "synthetic-source-material-1",
        "official_url": "https://boards.greenhouse.io/synthetic-bank/jobs/1",
        "description_original": quote,
        "source_fields": {"greenhouse": {"employmentType": contract, "first_published": "2026-10-20"}},
        "source_conflicts": [{
            "kind": "contract", "field": "employment_type", "source_field": "employmentType",
            "source_value": contract, "description_value": "internship", "quote": quote,
        }],
        "qualification": {
            "contract_type": "internship", "target_status": "to_verify",
            "source_conflicts": {"city": {"greenhouse": "London", "other": "Remote"}},
            "reasons": ["Qualification synthétique."],
        },
    }


def test_import_persists_source_material_without_mutating_qualification_or_payload(tmp_path) -> None:
    service = CareerService(tmp_path)
    offer = payload()
    original = copy.deepcopy(offer)

    imported = service.import_job(offer)
    material = imported["source_material"]

    assert offer == original
    assert material["version"] == 1
    assert material["material"]["source_fields"]["greenhouse"]["employmentType"] == "Internship"
    assert material["material"]["source_conflicts"][0]["source_field"] == "employmentType"
    assert imported["qualification_facts"]["source_conflicts"]["city"]["other"] == "Remote"


def test_identical_reimport_is_idempotent_and_changed_source_material_versions(tmp_path) -> None:
    service = CareerService(tmp_path)
    first = service.import_job(payload())
    repeated = service.import_job(payload())
    updated = service.import_job(payload(contract="Fixed term", quote="Contract type: fixed-term"))

    assert repeated["source_material"]["version"] == first["source_material"]["version"] == 1
    assert updated["source_material"]["version"] == 2
    assert updated["source_material"]["material"]["source_fields"]["greenhouse"]["employmentType"] == "Fixed term"
    assert updated["qualification_facts"]["source_conflicts"]["city"]["other"] == "Remote"


def test_source_material_survives_service_restart_and_import_without_material(tmp_path) -> None:
    first_service = CareerService(tmp_path)
    first = first_service.import_job(payload())
    refreshed = first_service.import_job({key: value for key, value in payload().items() if key not in {"source_fields", "source_conflicts"}})
    restarted = CareerService(tmp_path)

    persisted = restarted.get_job(first["id"])
    assert refreshed["source_material"]["version"] == 1
    assert persisted["source_material"]["material"]["source_fields"]["greenhouse"]["first_published"] == "2026-10-20"


def test_oversized_individual_field_is_bounded_before_it_is_stored(tmp_path) -> None:
    service = CareerService(tmp_path)
    offer = payload()
    offer["source_fields"]["greenhouse"]["oversized"] = "x" * 40_000

    imported = service.import_job(offer)
    value = imported["source_material"]["material"]["source_fields"]["greenhouse"]["oversized"]
    assert len(value) == 4_000


def test_aggregate_oversized_source_block_does_not_fail_offer_import(tmp_path) -> None:
    service = CareerService(tmp_path)
    offer = payload()
    offer["source_fields"] = {
        f"provider_{provider}": {f"field_{index}": "x" * 4_000 for index in range(10)}
        for provider in range(8)
    }

    imported = service.import_job(offer)

    assert imported["id"]
    assert imported["source_material"] is None
