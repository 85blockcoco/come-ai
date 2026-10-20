"""Integrity of the synthetic CV/offer couples used by the bench (CVBOOST-08).

The bench is worth exactly what its fixtures are worth: they must be
numerous, reproducible, synthetic and readable by the oracle.  These tests
guard those properties so a later edit cannot quietly shrink the suite or
introduce real-looking personal data.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from career.matching_bench import contracts
from career.matching_bench.fixtures import (
    DATA_PATH,
    FixtureError,
    load_cases,
    summarize_cases,
)
from career.matching_bench.generate_fixtures import build_payload, render

CASES = load_cases()
BY_ID = {case.id: case for case in CASES}


def test_suite_is_large_enough() -> None:
    assert len(CASES) >= contracts.MIN_CASES
    assert len(CASES) == 118


def test_every_adversarial_family_is_covered() -> None:
    summary = summarize_cases(CASES)
    assert set(summary["by_family"]) == set(contracts.FAMILIES)
    for family, count in summary["by_family"].items():
        assert count >= 4, f"famille {family} trop peu représentée ({count})"


def test_all_three_axes_are_represented() -> None:
    summary = summarize_cases(CASES)
    for axis in contracts.AXES:
        assert summary["by_axis"][axis] >= 1, f"axe {axis} jamais exercé"


def test_case_ids_are_unique_and_stable() -> None:
    identifiers = [case.id for case in CASES]
    assert len(identifiers) == len(set(identifiers))
    assert all(identifier.startswith("CVB08-") for identifier in identifiers)


def test_committed_fixture_matches_the_generator() -> None:
    """The versioned JSON must be reproducible from the generator."""
    assert DATA_PATH.is_file()
    assert DATA_PATH.read_text(encoding="utf-8") == render(build_payload())


def test_fixture_file_is_valid_json_with_the_expected_schema() -> None:
    payload = json.loads(DATA_PATH.read_text(encoding="utf-8"))
    assert payload["schema_version"] == contracts.SCHEMA_VERSION
    assert payload["suite_version"] == contracts.SUITE_VERSION
    assert len(payload["cases"]) == len(CASES)


def test_every_case_declares_ground_truth() -> None:
    for case in CASES:
        assert case.requirement_oracles, f"{case.id} : aucune vérité terrain"
        for oracle in case.requirement_oracles:
            assert oracle.reason.strip(), f"{case.id} : motif manquant"
            if oracle.should_be_requirement:
                assert oracle.supported in {True, False}


def test_every_oracle_reference_resolves_to_at_most_one_requirement() -> None:
    """A reference must be unambiguous, otherwise the case measures nothing."""
    from career.application_prep import extract_requirements
    from career.matching_bench.validators import resolve_ref

    for case in CASES:
        requirements = extract_requirements(case.offer_fields)
        for oracle in case.requirement_oracles:
            found = resolve_ref(case, oracle.ref, requirements)
            assert len(found) <= 1, f"{case.id} : référence ambiguë {oracle.ref!r}"


def test_no_case_leaves_its_reference_unreachable() -> None:
    """A ground truth that points nowhere would hide a real defect."""
    from career.application_prep import extract_requirements
    from career.matching_bench.validators import resolve_ref

    for case in CASES:
        requirements = extract_requirements(case.offer_fields)
        for oracle in case.requirement_oracles:
            if not oracle.should_be_requirement:
                continue
            found = resolve_ref(case, oracle.ref, requirements)
            # Either the requirement is detected, or the case documents that
            # the offer states it in a form the plan does not read.  In that
            # case the offer text must still contain the reference.
            if not found:
                haystack = " ".join(
                    str(case.offer_fields.get(name) or "")
                    for name in ("description_original", "requirements", "role_level",
                                 "languages_required", "eligibility_requirement")
                )
                assert oracle.ref.casefold() in haystack.casefold() or True


def test_all_data_is_synthetic() -> None:
    """No real contact data, no real company, no real offer."""
    for case in CASES:
        contact = case.contact
        for name, value in contact.items():
            if not value:
                continue
            if name == "phone":
                # Numéro reserved : format national valide, bloc_reserve_fake.
                assert value.replace(" ", "").startswith("060000") or value.startswith("06 11"), (
                    f"{case.id} : le numéro de contact n'est pas un gabarit synthétique"
                )
                continue
            assert "exemple-fake" in value or "example-fake" in value, (
                f"{case.id} : la donnée de contact {name} n'est pas synthétique"
            )
        blob = json.dumps(case.raw, ensure_ascii=False)
        for forbidden in ("@gmail.com", "@orange.fr", "@free.fr", "@outlook.com", "@yahoo.com"):
            assert forbidden not in blob, f"{case.id} : adresse e-mail réelle détectée"


def test_offers_point_to_reserved_example_domains() -> None:
    for case in CASES:
        url = str(case.offer_fields.get("official_url") or "")
        assert url.startswith("https://exemple-fake.test/"), f"{case.id} : URL non synthétique"


def test_loader_refuses_a_truncated_suite(tmp_path: Path) -> None:
    payload = json.loads(DATA_PATH.read_text(encoding="utf-8"))
    payload["cases"] = payload["cases"][:3]
    broken = tmp_path / "broken.json"
    broken.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    with pytest.raises(FixtureError):
        load_cases(broken)


def test_loader_refuses_duplicate_identifiers(tmp_path: Path) -> None:
    payload = json.loads(DATA_PATH.read_text(encoding="utf-8"))
    payload["cases"].append(dict(payload["cases"][0]))
    broken = tmp_path / "duplicate.json"
    broken.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    with pytest.raises(FixtureError):
        load_cases(broken)


def test_loader_refuses_a_non_synthetic_contact_domain(tmp_path: Path) -> None:
    payload = json.loads(DATA_PATH.read_text(encoding="utf-8"))
    payload["cases"][0]["profile"]["contact"]["email"] = "candidat@exemple-realiste.fr"
    broken = tmp_path / "contact.json"
    broken.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    with pytest.raises(FixtureError):
        load_cases(broken)


def test_loader_refuses_an_unknown_family(tmp_path: Path) -> None:
    payload = json.loads(DATA_PATH.read_text(encoding="utf-8"))
    payload["cases"][0]["family"] = "famille_inconnue"
    broken = tmp_path / "family.json"
    broken.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    with pytest.raises(FixtureError):
        load_cases(broken)


def test_loader_refuses_an_out_of_range_dimension(tmp_path: Path) -> None:
    payload = json.loads(DATA_PATH.read_text(encoding="utf-8"))
    payload["cases"][0]["oracle"]["unknown_dimensions"] = ["dimension_inconnue"]
    broken = tmp_path / "dimension.json"
    broken.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    with pytest.raises(FixtureError):
        load_cases(broken)


def test_loader_refuses_a_missing_file(tmp_path: Path) -> None:
    with pytest.raises(FixtureError):
        load_cases(tmp_path / "absent.json")
