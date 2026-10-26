"""Verdicts d'éligibilité par offre (SPEC-043, CVBOOST-78).

Offres synthétiques, tickets de profil explicites, zéro réseau, zéro IA
décisionnelle : chaque cas illustre une clause du moteur et la règle
« à défaut de preuve, À VÉRIFIER — jamais de verdict positif implicite ».
"""

from __future__ import annotations

import copy
import socket
from dataclasses import dataclass, field as dc_field
from typing import Any

import pytest

from career.eligibility import (
    CLAUSE_NOT_OK,
    CLAUSE_OK,
    CLAUSE_TO_VERIFY,
    RulesError,
    STATE_BY_VERDICT,
    VERDICT_ELIGIBLE,
    VERDICT_NOT_ELIGIBLE,
    VERDICT_TO_VERIFY,
    apply_eligibility_to_offers,
    check_eligibility,
    eligibility_ranking_key,
    load_rules,
    validate_rules,
)
from career.exploration import ranking_key


@pytest.fixture(autouse=True)
def block_network(monkeypatch):
    def blocked(*args, **kwargs):
        raise AssertionError("Network is forbidden in eligibility tests")
    monkeypatch.setattr(socket, "socket", blocked)
    monkeypatch.setattr(socket, "create_connection", blocked)


# ───────────────────────────────────────────────────────────────────────
# Jeux de données synthétiques
# ───────────────────────────────────────────────────────────────────────

def base_rules() -> dict[str, Any]:
    """Profil approuvé typique d'un étudiant en recherche d'alternance."""
    return {
        "schema": "eligibility_rules",
        "version": 1,
        "profile_approved": True,
        "rules": {
            "contract": {"accepted": ["internship", "apprenticeship"]},
            "duration": {"minimum_months": 3},
            "education": {"profile_level": "bac+3", "profile_fields": ["finance"]},
            "work_authorization": {
                "status": "student",
                "work_permits": ["FR", "DE", "EU"],
                "visa_sponsorship_needed": False,
            },
            "location": {
                "countries": ["FR", "DE"],
                "excluded_countries": ["US"],
                "excluded_cities": [],
                "work_modes": ["onsite", "hybrid", "remote"],
            },
            "languages": {"profile_levels": {"anglais": "c1", "français": "native"}},
        },
    }


def qualification(
    contract_type: str | None = "internship",
    duration: tuple[int, int] | None = (6, 6),
    country: str | None = "France",
    city: str | None = "Paris",
    **extra: Any,
) -> dict[str, Any]:
    """Un ``qualification`` réaliste, sortie de ``qualify_offer``."""
    provenance: dict[str, Any] = {}
    if contract_type is not None:
        provenance["contract_type"] = {
            "value": contract_type, "source": "description", "quote": "stage de 6 mois",
        }
    payload: dict[str, Any] = {
        "contract_type": contract_type,
        "duration_min_months": duration[0] if duration else None,
        "duration_max_months": duration[1] if duration else None,
        "country": country,
        "city": city,
        "provenance": provenance,
    }
    payload.update(extra)
    return payload


def offer(**overrides: Any) -> dict[str, Any]:
    """Offre éligible de référence : alternance 6 mois à Paris, sans visa."""
    payload: dict[str, Any] = {"qualification": qualification()}
    payload.update(overrides)
    return payload


@dataclass
class Fact:
    """Mini-fait SK-17 (même surface que ``ConditionFact.to_dict``)."""

    condition_type: str
    value: Any
    quote: str = ""
    source_field: str = "description"

    def to_dict(self) -> dict[str, Any]:
        return {
            "condition_type": self.condition_type,
            "value": self.value,
            "quote": self.quote,
            "source_field": self.source_field,
        }


def requirement(text: str, category: str, modality: str = "required", **extra: Any) -> dict[str, Any]:
    return {"text": text, "category": category, "modality": modality, **extra}


def clause(result: dict[str, Any], rule: str) -> dict[str, Any]:
    return next(item for item in result["clauses"] if item["rule"] == rule)


def assert_no_false_eligible(result: dict[str, Any]) -> None:
    """Un verdict ÉLIGIBLE doit citer une preuve pour chaque clause ok."""
    if result["verdict"] != VERDICT_ELIGIBLE:
        return
    assert result["clauses"], "verdict ÉLIGIBLE sans clause examinée"
    for item in result["clauses"]:
        assert item["statut_ok"] == CLAUSE_OK
        assert item["exigence_offre"], "clause sans exigence citée"
        assert item["fait_profil"], "clause sans fait de profil cité"


# ───────────────────────────────────────────────────────────────────────
# Fichier de règles : chargement, validation, tickets
# ───────────────────────────────────────────────────────────────────────

def test_rules_of_the_package_load_and_validate():
    rules = load_rules()
    assert rules["schema"] == "eligibility_rules"
    assert validate_rules(rules) == []


def test_package_tickets_are_unfilled_by_default():
    """Un fichier livré sans tickets remplis ne peut jamais rendre éligible."""
    rules = load_rules()
    assert rules["profile_approved"] is False
    assert rules["rules"]["work_authorization"]["work_permits"] == []
    assert rules["rules"]["work_authorization"]["visa_sponsorship_needed"] is None
    result = check_eligibility(offer(qualification=qualification(country="Germany")), rules)
    assert result["verdict"] == VERDICT_TO_VERIFY
    assert "Profil non approuvé" in result["points_a_verifier"][0]


def test_missing_rules_file_is_an_error(tmp_path):
    with pytest.raises(RulesError, match="introuvable"):
        load_rules(tmp_path / "absent.json")


def test_unreadable_rules_file_is_an_error(tmp_path):
    path = tmp_path / "rules.json"
    path.write_text("{ not json", encoding="utf-8")
    with pytest.raises(RulesError, match="illisible"):
        load_rules(path)


def test_unknown_rule_section_is_rejected():
    rules = base_rules()
    rules["rules"]["magic_filter"] = {}
    assert any("inconnues" in problem for problem in validate_rules(rules))


def test_unknown_work_status_is_rejected():
    rules = base_rules()
    rules["rules"]["work_authorization"]["status"] = "astronaute"
    assert any("statut inconnu" in problem for problem in validate_rules(rules))


def test_unknown_work_permit_is_rejected():
    rules = base_rules()
    rules["rules"]["work_authorization"]["work_permits"] = ["XX"]
    assert any("work_permits inconnus" in problem for problem in validate_rules(rules))


def test_unknown_language_level_is_rejected():
    rules = base_rules()
    rules["rules"]["languages"]["profile_levels"] = {"anglais": "b9"}
    assert any("inconnu" in problem for problem in validate_rules(rules))


def test_unknown_work_mode_is_rejected():
    rules = base_rules()
    rules["rules"]["location"]["work_modes"] = ["metaverse"]
    assert any("modes de travail inconnus" in problem for problem in validate_rules(rules))


def test_invalid_rules_are_refused_by_the_engine():
    rules = base_rules()
    rules["profile_approved"] = "oui"
    with pytest.raises(RulesError):
        check_eligibility(offer(), rules)


# ───────────────────────────────────────────────────────────────────────
# Sortie du moteur : forme du contrat
# ───────────────────────────────────────────────────────────────────────

def test_output_shape_matches_the_mission_contract():
    result = check_eligibility(offer(), base_rules())
    assert set(result) == {
        "verdict", "clauses", "etat_suivant", "points_a_verifier",
        "motifs_non_eligibilite", "rules_version", "profile_approved",
    }
    for item in result["clauses"]:
        assert set(item) >= {"rule", "exigence_offre", "fait_profil", "statut_ok", "preuve"}


def test_clause_cites_evidence_from_the_offer():
    result = check_eligibility(offer(), base_rules())
    contract = clause(result, "contract")
    assert contract["statut_ok"] == CLAUSE_OK
    assert contract["preuve"]["offre"]["quote"] == "stage de 6 mois"


def test_states_follow_the_verdict():
    assert STATE_BY_VERDICT[VERDICT_ELIGIBLE] == "classable"
    assert STATE_BY_VERDICT[VERDICT_TO_VERIFY] == "a_verifier"
    assert STATE_BY_VERDICT[VERDICT_NOT_ELIGIBLE] == "exclue_du_classement"


def eligible_offer() -> tuple[dict[str, Any], dict[str, Any], list[dict[str, Any]], list[dict[str, Any]]]:
    """Offre prouvée clause par clause : rien ne reste « à vérifier »."""
    conditions = [Fact("hybrid", True, "Hybrid: two days onsite, three remote.")]
    requirements: list[dict[str, Any]] = []
    return offer(), base_rules(), conditions, requirements


def test_full_alternance_offer_is_eligible():
    offer_payload, rules, conditions, requirements = eligible_offer()
    result = check_eligibility(offer_payload, rules, conditions=conditions, requirements=requirements)
    assert result["verdict"] == VERDICT_ELIGIBLE
    assert result["etat_suivant"] == "classable"
    assert result["points_a_verifier"] == []
    assert_no_false_eligible(result)


def test_dataclass_conditions_are_accepted():
    conditions = [Fact("visa_sponsorship", False, "No sponsorship provided.")]
    result = check_eligibility(offer(), base_rules(), conditions=conditions)
    visa = clause(result, "visa_sponsorship")
    assert visa["statut_ok"] == CLAUSE_OK
    assert visa["preuve"]["offre"]["quote"] == "No sponsorship provided."


# ───────────────────────────────────────────────────────────────────────
# Jamais de verdict positif implicite
# ───────────────────────────────────────────────────────────────────────

def test_empty_offer_is_to_verify_and_lists_the_points():
    result = check_eligibility({}, base_rules())
    assert result["verdict"] == VERDICT_TO_VERIFY
    assert result["points_a_verifier"], "un verdict prudent doit motiver ses points"
    assert result["etat_suivant"] == "a_verifier"


def test_unapproved_profile_blocks_eligible():
    rules = base_rules()
    rules["profile_approved"] = False
    result = check_eligibility(offer(), rules)
    assert result["verdict"] == VERDICT_TO_VERIFY
    assert result["profile_approved"] is False
    assert any("profile_approved" in point for point in result["points_a_verifier"])


def test_absent_extraction_is_not_proven_absence():
    """``conditions=None``/``requirements=None`` : extraction non exécutée."""
    result = check_eligibility(offer(), base_rules(), conditions=None, requirements=None)
    assert result["verdict"] != VERDICT_ELIGIBLE
    languages = clause(result, "languages")
    assert languages["statut_ok"] == CLAUSE_TO_VERIFY


# ───────────────────────────────────────────────────────────────────────
# Clause contrat (stage / alternance / CDI)
# ───────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("contract,accepted", [
    ("internship", ["internship", "apprenticeship"]),
    ("stage", ["internship"]),
    ("apprenticeship", ["apprenticeship"]),
    ("alternance", ["apprenticeship"]),
    ("fixed_term", ["fixed_term"]),
])
def test_accepted_contract_is_ok(contract, accepted):
    rules = base_rules()
    rules["rules"]["contract"]["accepted"] = accepted
    rules["rules"]["work_authorization"]["status"] = "employee"
    result = check_eligibility(offer(qualification=qualification(contract_type=contract)), rules)
    assert clause(result, "contract")["statut_ok"] == CLAUSE_OK


def test_closed_contract_is_not_eligible():
    rules = base_rules()
    rules["rules"]["contract"]["accepted"] = ["apprenticeship"]
    result = check_eligibility(offer(qualification=qualification(contract_type="fixed_term")), rules)
    assert result["verdict"] == VERDICT_NOT_ELIGIBLE
    assert result["motifs_non_eligibilite"]
    assert clause(result, "contract")["statut_ok"] == CLAUSE_NOT_OK


def test_unknown_contract_is_to_verify():
    result = check_eligibility(offer(qualification=qualification(contract_type="unknown")), base_rules())
    assert clause(result, "contract")["statut_ok"] == CLAUSE_TO_VERIFY
    assert result["verdict"] == VERDICT_TO_VERIFY


def test_missing_contract_is_to_verify():
    result = check_eligibility(offer(qualification=qualification(contract_type=None)), base_rules())
    assert clause(result, "contract")["statut_ok"] == CLAUSE_TO_VERIFY


def test_cdi_is_blocked_for_a_student_ticket():
    """Un statut étudiant n'ouvre pas un CDI : blocage explicite, cité."""
    result = check_eligibility(offer(qualification=qualification(contract_type="permanent")), base_rules())
    assert result["verdict"] == VERDICT_NOT_ELIGIBLE
    contract = clause(result, "contract")
    assert contract["statut_ok"] == CLAUSE_NOT_OK
    assert "étudiant" in contract["fait_profil"]


def test_cdi_is_fine_for_an_employee_ticket():
    rules = base_rules()
    rules["rules"]["contract"]["accepted"] = ["permanent"]
    rules["rules"]["work_authorization"]["status"] = "employee"
    result = check_eligibility(offer(qualification=qualification(contract_type="permanent")), rules)
    assert clause(result, "contract")["statut_ok"] == CLAUSE_OK


# ───────────────────────────────────────────────────────────────────────
# Clause durée (sk02 / qualification)
# ───────────────────────────────────────────────────────────────────────

def test_duration_below_minimum_is_not_eligible():
    result = check_eligibility(offer(qualification=qualification(duration=(2, 2))), base_rules())
    assert result["verdict"] == VERDICT_NOT_ELIGIBLE
    assert clause(result, "duration")["statut_ok"] == CLAUSE_NOT_OK


def test_duration_at_the_minimum_is_ok():
    result = check_eligibility(offer(qualification=qualification(duration=(3, 6))), base_rules())
    assert clause(result, "duration")["statut_ok"] == CLAUSE_OK


def test_duration_just_under_minimum_is_not_eligible():
    result = check_eligibility(offer(qualification=qualification(duration=(1, 2))), base_rules())
    assert clause(result, "duration")["statut_ok"] == CLAUSE_NOT_OK


def test_unknown_duration_is_to_verify():
    result = check_eligibility(offer(qualification=qualification(duration=None)), base_rules())
    assert clause(result, "duration")["statut_ok"] == CLAUSE_TO_VERIFY
    assert result["verdict"] == VERDICT_TO_VERIFY


def test_duration_minimum_below_rules_without_maximum_stays_to_verify():
    """Un minimum connu trop bas ne prouve rien sans maximum connu."""
    result = check_eligibility(offer(qualification=qualification(duration=(2, None))), base_rules())
    assert clause(result, "duration")["statut_ok"] == CLAUSE_TO_VERIFY


# ───────────────────────────────────────────────────────────────────────
# Clauses école : niveau et filière
# ───────────────────────────────────────────────────────────────────────

def _with_requirements(offer_payload: dict[str, Any], requirements: Any) -> dict[str, Any]:
    payload = dict(offer_payload)
    payload["requirements"] = requirements
    return payload


def test_higher_required_level_is_not_eligible():
    rules = base_rules()
    rules["rules"]["education"]["profile_level"] = "bac+3"
    requirements = [requirement("Master 2 (Bac+5) in finance required.", "education", level="master")]
    result = check_eligibility(_with_requirements(offer(), requirements), rules)
    assert result["verdict"] == VERDICT_NOT_ELIGIBLE
    assert clause(result, "education_level")["statut_ok"] == CLAUSE_NOT_OK


def test_equal_required_level_is_ok():
    rules = base_rules()
    rules["rules"]["education"]["profile_level"] = "bac+5"
    requirements = [requirement("Master 2 (Bac+5) in finance required.", "education", level="master")]
    result = check_eligibility(_with_requirements(offer(), requirements), rules)
    assert clause(result, "education_level")["statut_ok"] == CLAUSE_OK


def test_unreadable_level_is_to_verify():
    """Une exigence académique existe mais son niveau n'est pas lisible."""
    rules = base_rules()
    requirements = [requirement("Pursuing studies in a business school.", "education")]
    result = check_eligibility(_with_requirements(offer(), requirements), rules)
    assert clause(result, "education_level")["statut_ok"] == CLAUSE_TO_VERIFY
    assert result["verdict"] != VERDICT_ELIGIBLE


def test_missing_requirements_extraction_is_to_verify():
    result = check_eligibility(offer(), base_rules(), requirements=None)
    level = clause(result, "education_level")
    assert level["statut_ok"] == CLAUSE_TO_VERIFY
    assert "extraction" in level["exigence_offre"]


def test_no_education_requirement_found_is_ok():
    requirements = [requirement("Python and SQL required.", "technical_skill")]
    result = check_eligibility(_with_requirements(offer(), requirements), base_rules())
    assert clause(result, "education_level")["statut_ok"] == CLAUSE_OK


def test_unfilled_profile_level_is_to_verify():
    rules = base_rules()
    rules["rules"]["education"]["profile_level"] = ""
    requirements = [requirement("Master 2 (Bac+5) required.", "education", level="master")]
    result = check_eligibility(_with_requirements(offer(), requirements), rules)
    assert clause(result, "education_level")["statut_ok"] == CLAUSE_TO_VERIFY


def test_matching_field_is_ok_and_unknown_field_is_to_verify():
    rules = base_rules()
    matched = [requirement("Master in finance required.", "education", field="finance")]
    result = check_eligibility(_with_requirements(offer(), matched), rules)
    assert clause(result, "education_field")["statut_ok"] == CLAUSE_OK
    mismatched = [requirement("Master in biology required.", "education", field="biology")]
    result = check_eligibility(_with_requirements(offer(), mismatched), rules)
    # Un écart de filière n'est jamais un blocage prouvé (« ou équivalent »).
    assert clause(result, "education_field")["statut_ok"] == CLAUSE_TO_VERIFY


def test_unfilled_profile_fields_with_field_requirement_is_to_verify():
    rules = base_rules()
    rules["rules"]["education"]["profile_fields"] = []
    requirements = [requirement("Master in finance required.", "education", field="finance")]
    result = check_eligibility(_with_requirements(offer(), requirements), rules)
    assert clause(result, "education_field")["statut_ok"] == CLAUSE_TO_VERIFY


def test_education_access_fallback_reads_doctorate_only():
    """Repli ``education_access`` : exigence doctorale explicite."""
    rules = base_rules()
    rules["rules"]["education"]["profile_level"] = "bac+5"
    offer_payload = offer(education_access={"status": "outside_preference", "labels": ["Doctorat"]})
    result = check_eligibility(offer_payload, rules)
    assert clause(result, "education_level")["statut_ok"] == CLAUSE_NOT_OK


def test_education_access_fallback_reads_master2():
    rules = base_rules()
    rules["rules"]["education"]["profile_level"] = "bac+5"
    offer_payload = offer(education_access={"status": "consider", "labels": ["Master 2 / Bac+5"]})
    result = check_eligibility(offer_payload, rules)
    assert clause(result, "education_level")["statut_ok"] == CLAUSE_OK


# ───────────────────────────────────────────────────────────────────────
# Clause autorisation de travail : tickets pays (WORK AUTH)
# ───────────────────────────────────────────────────────────────────────

def test_permit_covers_the_offer_country():
    result = check_eligibility(offer(qualification=qualification(country="Germany")), base_rules())
    assert clause(result, "work_authorization")["statut_ok"] == CLAUSE_OK


def test_region_permit_covers_its_countries():
    rules = base_rules()
    rules["rules"]["work_authorization"]["work_permits"] = ["EU"]
    result = check_eligibility(offer(qualification=qualification(country="Netherlands")), rules)
    assert clause(result, "work_authorization")["statut_ok"] == CLAUSE_OK


def test_region_permit_does_not_cover_outside_countries():
    rules = base_rules()
    rules["rules"]["work_authorization"]["work_permits"] = ["EU"]
    result = check_eligibility(offer(qualification=qualification(country="Switzerland")), rules)
    assert result["verdict"] == VERDICT_NOT_ELIGIBLE
    assert clause(result, "work_authorization")["statut_ok"] == CLAUSE_NOT_OK


def test_unfilled_permit_ticket_is_to_verify():
    rules = base_rules()
    rules["rules"]["work_authorization"]["work_permits"] = []
    result = check_eligibility(offer(), rules)
    assert clause(result, "work_authorization")["statut_ok"] == CLAUSE_TO_VERIFY
    assert "n'est pas rempli" in clause(result, "work_authorization")["fait_profil"]


def test_unidentified_country_is_to_verify():
    result = check_eligibility(offer(qualification=qualification(country="Atlantide")), base_rules())
    assert clause(result, "work_authorization")["statut_ok"] == CLAUSE_TO_VERIFY


def test_missing_country_is_to_verify():
    result = check_eligibility(offer(qualification=qualification(country=None)), base_rules())
    assert clause(result, "work_authorization")["statut_ok"] == CLAUSE_TO_VERIFY


# ───────────────────────────────────────────────────────────────────────
# Clause visa : tickets explicites, jamais devinés
# ───────────────────────────────────────────────────────────────────────

def test_visa_needed_and_refused_by_offer_is_not_eligible():
    rules = base_rules()
    rules["rules"]["work_authorization"]["visa_sponsorship_needed"] = True
    conditions = [Fact("visa_sponsorship", False, "We do not sponsor visas.")]
    result = check_eligibility(offer(), rules, conditions=conditions)
    assert result["verdict"] == VERDICT_NOT_ELIGIBLE
    visa = clause(result, "visa_sponsorship")
    assert visa["statut_ok"] == CLAUSE_NOT_OK
    assert visa["preuve"]["offre"]["quote"] == "We do not sponsor visas."


def test_visa_needed_and_offered_is_ok():
    rules = base_rules()
    rules["rules"]["work_authorization"]["visa_sponsorship_needed"] = True
    conditions = [Fact("visa_sponsorship", True, "Visa sponsorship available.")]
    result = check_eligibility(offer(), rules, conditions=conditions)
    assert clause(result, "visa_sponsorship")["statut_ok"] == CLAUSE_OK


def test_unknown_visa_ticket_is_to_verify_even_when_offer_refuses():
    """Ticket visa non rempli : aucune conclusion, même face à un refus."""
    rules = base_rules()
    rules["rules"]["work_authorization"]["visa_sponsorship_needed"] = None
    conditions = [Fact("visa_sponsorship", False, "We do not sponsor visas.")]
    result = check_eligibility(offer(), rules, conditions=conditions)
    assert clause(result, "visa_sponsorship")["statut_ok"] == CLAUSE_TO_VERIFY


def test_unknown_visa_sponsorship_in_offer_is_to_verify():
    rules = base_rules()
    rules["rules"]["work_authorization"]["visa_sponsorship_needed"] = True
    conditions = [Fact("visa_sponsorship", None, "Visa mentioned.")]
    result = check_eligibility(offer(), rules, conditions=conditions)
    assert clause(result, "visa_sponsorship")["statut_ok"] == CLAUSE_TO_VERIFY


def test_visa_not_needed_and_offer_silent_is_ok():
    rules = base_rules()
    rules["rules"]["work_authorization"]["visa_sponsorship_needed"] = False
    result = check_eligibility(offer(), rules, conditions=[])
    assert clause(result, "visa_sponsorship")["statut_ok"] == CLAUSE_OK


def test_visa_needed_and_offer_silent_is_to_verify():
    rules = base_rules()
    rules["rules"]["work_authorization"]["visa_sponsorship_needed"] = True
    result = check_eligibility(offer(), rules, conditions=[])
    assert clause(result, "visa_sponsorship")["statut_ok"] == CLAUSE_TO_VERIFY


# ───────────────────────────────────────────────────────────────────────
# Clause localisation / mode de travail
# ───────────────────────────────────────────────────────────────────────

def test_excluded_country_is_not_eligible():
    result = check_eligibility(offer(qualification=qualification(country="United States")), base_rules())
    assert result["verdict"] == VERDICT_NOT_ELIGIBLE
    assert clause(result, "location")["statut_ok"] == CLAUSE_NOT_OK


def test_whitelisted_country_is_ok_and_outside_is_not():
    result = check_eligibility(offer(qualification=qualification(country="Germany")), base_rules())
    assert clause(result, "location")["statut_ok"] == CLAUSE_OK
    result = check_eligibility(offer(qualification=qualification(country="Spain")), base_rules())
    assert clause(result, "location")["statut_ok"] == CLAUSE_NOT_OK


def test_no_whitelist_means_no_country_block():
    """Sans pays ciblés, un pays non exclu ne bloque pas."""
    rules = base_rules()
    rules["rules"]["location"]["countries"] = []
    result = check_eligibility(offer(qualification=qualification(country="Spain")), rules)
    assert clause(result, "location")["statut_ok"] == CLAUSE_OK


def test_excluded_city_is_not_eligible():
    rules = base_rules()
    rules["rules"]["location"]["excluded_cities"] = ["Londres"]
    result = check_eligibility(offer(qualification=qualification(country="United Kingdom", city="Londres")), rules)
    assert result["verdict"] == VERDICT_NOT_ELIGIBLE
    location = clause(result, "location")
    assert location["statut_ok"] == CLAUSE_NOT_OK
    assert "Londres" in location["exigence_offre"]


def test_unknown_country_with_whitelist_is_to_verify():
    result = check_eligibility(offer(qualification=qualification(country=None)), base_rules())
    assert clause(result, "location")["statut_ok"] == CLAUSE_TO_VERIFY


@pytest.mark.parametrize("mode,value,profile,expected", [
    ("remote", True, ["remote"], CLAUSE_OK),
    ("onsite", True, ["onsite"], CLAUSE_OK),
    ("onsite", True, ["remote"], CLAUSE_NOT_OK),
    ("hybrid", True, ["remote"], CLAUSE_TO_VERIFY),
    ("hybrid", True, ["hybrid"], CLAUSE_OK),
    ("remote", False, ["onsite"], CLAUSE_OK),
])
def test_work_modes_against_the_ticket(mode, value, profile, expected):
    rules = base_rules()
    rules["rules"]["location"]["work_modes"] = profile
    conditions = [Fact(mode, value, f"Work is {mode}.")]
    result = check_eligibility(offer(), rules, conditions=conditions)
    assert clause(result, "work_mode")["statut_ok"] == expected


def test_contradictory_work_modes_are_to_verify():
    conditions = [
        Fact("remote", True, "Fully remote."),
        Fact("onsite", True, "Onsite in Paris."),
    ]
    result = check_eligibility(offer(), base_rules(), conditions=conditions)
    assert clause(result, "work_mode")["statut_ok"] == CLAUSE_TO_VERIFY


def test_unfilled_work_mode_ticket_is_to_verify():
    rules = base_rules()
    rules["rules"]["location"]["work_modes"] = []
    conditions = [Fact("remote", True, "Fully remote.")]
    result = check_eligibility(offer(), rules, conditions=conditions)
    assert clause(result, "work_mode")["statut_ok"] == CLAUSE_TO_VERIFY


def test_missing_mode_conditions_are_to_verify():
    result = check_eligibility(offer(), base_rules(), conditions=[])
    assert clause(result, "work_mode")["statut_ok"] == CLAUSE_TO_VERIFY


# ───────────────────────────────────────────────────────────────────────
# Clause langues
# ───────────────────────────────────────────────────────────────────────

def test_structured_language_field_meets_profile():
    offer_payload = offer(languages_required="Anglais C1")
    result = check_eligibility(offer_payload, base_rules())
    languages = [item for item in result["clauses"] if item["rule"] == "languages"]
    assert languages[0]["statut_ok"] == CLAUSE_OK


def test_structured_language_field_below_profile_is_not_eligible():
    rules = base_rules()
    rules["rules"]["languages"]["profile_levels"] = {"anglais": "b1"}
    offer_payload = offer(languages_required="Anglais C1")
    result = check_eligibility(offer_payload, rules)
    assert result["verdict"] == VERDICT_NOT_ELIGIBLE
    languages = [item for item in result["clauses"] if item["rule"] == "languages"]
    assert languages[0]["statut_ok"] == CLAUSE_NOT_OK


def test_language_requirement_without_level_is_to_verify():
    requirements = [requirement("Fluent English required.", "language", language="en")]
    result = check_eligibility(_with_requirements(offer(), requirements), base_rules())
    languages = [item for item in result["clauses"] if item["rule"] == "languages"]
    assert languages[0]["statut_ok"] == CLAUSE_TO_VERIFY


def test_unfilled_profile_language_level_is_to_verify():
    rules = base_rules()
    rules["rules"]["languages"]["profile_levels"] = {}
    offer_payload = offer(languages_required="Anglais C1")
    result = check_eligibility(offer_payload, rules)
    languages = [item for item in result["clauses"] if item["rule"] == "languages"]
    assert languages[0]["statut_ok"] == CLAUSE_TO_VERIFY


def test_native_requirement_is_never_proven_by_c2():
    """« Langue maternelle » face à un C2 : un diplôme ne le prouve pas."""
    rules = base_rules()
    rules["rules"]["languages"]["profile_levels"] = {"anglais": "c2"}
    requirements = [requirement("Native English speaker.", "language", language="en", level="native")]
    result = check_eligibility(_with_requirements(offer(), requirements), rules)
    languages = [item for item in result["clauses"] if item["rule"] == "languages"]
    assert languages[0]["statut_ok"] == CLAUSE_TO_VERIFY


def test_no_language_required_is_ok_but_absent_extraction_is_to_verify():
    requirements: list[dict[str, Any]] = []
    result = check_eligibility(_with_requirements(offer(), requirements), base_rules())
    languages = [item for item in result["clauses"] if item["rule"] == "languages"]
    assert languages[0]["statut_ok"] == CLAUSE_OK
    result = check_eligibility(offer(), base_rules(), requirements=None)
    languages = [item for item in result["clauses"] if item["rule"] == "languages"]
    assert languages[0]["statut_ok"] == CLAUSE_TO_VERIFY


def test_unknown_language_is_its_own_clause_to_verify():
    requirements = [requirement("Fluent Korean required.", "language", language="ko")]
    result = check_eligibility(_with_requirements(offer(), requirements), base_rules())
    languages = [item for item in result["clauses"] if item["rule"] == "languages"]
    assert len(languages) == 1
    assert languages[0]["statut_ok"] == CLAUSE_TO_VERIFY


# ───────────────────────────────────────────────────────────────────────
# Agrégation des verdicts
# ───────────────────────────────────────────────────────────────────────

def test_one_blocked_clause_makes_the_whole_offer_not_eligible():
    result = check_eligibility(offer(qualification=qualification(duration=(2, 2))), base_rules())
    assert result["verdict"] == VERDICT_NOT_ELIGIBLE
    assert len(result["motifs_non_eligibilite"]) == 1
    assert "Durée" in result["motifs_non_eligibilite"][0]


def test_all_ok_clauses_without_approval_stay_to_verify():
    offer_payload, rules, conditions, requirements = eligible_offer()
    rules["profile_approved"] = False
    result = check_eligibility(offer_payload, rules, conditions=conditions, requirements=requirements)
    assert all(item["statut_ok"] == CLAUSE_OK for item in result["clauses"])
    assert result["verdict"] == VERDICT_TO_VERIFY


def test_to_verify_point_quotes_the_offers_requirement():
    result = check_eligibility(offer(qualification=qualification(duration=None)), base_rules())
    assert any("Durée" in point for point in result["points_a_verifier"])


def test_qualified_offer_object_with_to_dict_is_accepted():
    @dataclass
    class Qualified:
        qualification: dict[str, Any] = dc_field(default_factory=lambda: qualification())
        def to_dict(self) -> dict[str, Any]:
            return {"qualification": self.qualification}

    _payload, rules, conditions, requirements = eligible_offer()
    result = check_eligibility(Qualified(), rules, conditions=conditions, requirements=requirements)
    assert result["verdict"] == VERDICT_ELIGIBLE


def test_requirements_embedded_in_the_offer_are_used():
    """Relevés déjà portés par l'offre : utilisés quand l'argument est absent."""
    requirements = [requirement("Master 2 (Bac+5) required.", "education", level="master")]
    offer_payload = dict(offer())
    offer_payload["requirements"] = requirements
    result = check_eligibility(offer_payload, base_rules())
    assert clause(result, "education_level")["statut_ok"] == CLAUSE_NOT_OK


def test_non_mapping_offer_is_a_type_error():
    with pytest.raises(TypeError):
        check_eligibility("stage de six mois", base_rules())  # type: ignore[arg-type]


# ───────────────────────────────────────────────────────────────────────
# Radar / dailies : marquage et classement
# ───────────────────────────────────────────────────────────────────────

def test_batch_annotation_marks_each_offer():
    offers = [
        {"id": "a", "qualification": qualification()},
        {"id": "b", "qualification": qualification(duration=(2, 2))},
        {"id": "c", "qualification": qualification(country="Spain")},
    ]
    _payload, rules, conditions, requirements = eligible_offer()
    annotated = apply_eligibility_to_offers(
        offers, rules,
        conditions_by_offer={"a": conditions},
        requirements_by_offer={"a": requirements},
    )
    verdicts = {item["id"]: item["eligibility"]["verdict"] for item in annotated}
    assert verdicts == {
        "a": VERDICT_ELIGIBLE, "b": VERDICT_NOT_ELIGIBLE, "c": VERDICT_NOT_ELIGIBLE,
    }
    states = {item["id"]: item["eligibility"]["etat_suivant"] for item in annotated}
    assert states["a"] == "classable"
    assert states["b"] == "exclue_du_classement"


def test_non_eligible_offers_sink_but_stay_visible():
    offers = [
        {"id": "good", "match_score": 50, "qualification": qualification()},
        {"id": "blocked", "match_score": 99, "qualification": qualification(country="United States")},
    ]
    annotated = apply_eligibility_to_offers(offers, base_rules())
    assert [item["id"] for item in annotated] == ["good", "blocked"]
    # Toujours visible, avec ses motifs, pour apprendre pourquoi.
    assert annotated[1]["eligibility"]["motifs_non_eligibilite"]


def test_batch_annotation_does_not_mutate_the_input():
    offers = [{"id": "a", "qualification": qualification()}]
    snapshot = copy.deepcopy(offers)
    apply_eligibility_to_offers(offers, base_rules())
    assert offers == snapshot


def test_ranking_key_sinks_annotated_non_eligible_offers():
    match = {"score": 10}
    good = {"id": "good", "qualification": {"target_status": "conforming"}}
    blocked = {"id": "blocked", "qualification": {"target_status": "conforming"},
               "eligibility": {"verdict": VERDICT_NOT_ELIGIBLE}}
    to_verify = {"id": "mid", "qualification": {"target_status": "conforming"},
                 "eligibility": {"verdict": VERDICT_TO_VERIFY}}
    ranked = sorted([blocked, good, to_verify], key=lambda job: ranking_key(job, match))
    assert [job["id"] for job in ranked] == ["good", "mid", "blocked"]


def test_ranking_key_is_unchanged_without_annotation():
    match = {"score": 10}
    first = {"id": "a", "qualification": {"target_status": "conforming"}}
    second = {"id": "b", "qualification": {"target_status": "to_verify"}}
    ranked = sorted([second, first], key=lambda job: ranking_key(job, match))
    assert [job["id"] for job in ranked] == ["a", "b"]


def test_standalone_ranking_key_keeps_score_order_within_a_verdict():
    good_high = {"id": "high", "match_score": 80, "qualification": qualification()}
    good_low = {"id": "low", "match_score": 20, "qualification": qualification()}
    ranked = sorted([good_low, good_high], key=eligibility_ranking_key)
    assert [item["id"] for item in ranked] == ["high", "low"]
