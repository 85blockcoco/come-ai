"""Tests for the work-condition extractor (SK-17).

All fixtures are synthetic — no real offer, no personal data, no network.
The extractor must stay pure: same text in, same facts out.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from career.cv_quality import (
    CONDITION_GROUPS,
    ConditionFact,
    detect_language,
    extract_conditions,
    extract_conditions_from_offer,
    summarize_conditions,
)
from career.cv_quality.conditions_extractor import SUPPORTED_LANGUAGES
from career.offer_qualification import qualify_offer

FIXTURES_PATH = Path(__file__).resolve().parent / "fixtures" / "conditions_extractor" / "conditions_cases.json"


def _load_cases() -> list[dict[str, Any]]:
    """Charge les fixtures synthétiques multilingues du module."""
    with FIXTURES_PATH.open("r", encoding="utf-8") as handle:
        payload = json.load(handle)
    return payload["cases"]


CASES = _load_cases()
CASE_IDS = [case["id"] for case in CASES]


# ──────────────────────────────────────────────────────────────────────
# Corpus de fixtures
# ──────────────────────────────────────────────────────────────────────


def test_fixture_corpus_is_large_enough() -> None:
    """Le corpus couvre au moins 25 cas synthétiques (contrat SK-17)."""
    assert len(CASES) >= 25


def test_fixture_corpus_covers_six_languages() -> None:
    """Les six langues du contrat sont représentées."""
    languages = {case["lang"] for case in CASES}
    assert languages == set(SUPPORTED_LANGUAGES)


def test_fixture_ids_are_unique() -> None:
    """Chaque fixture a un identifiant unique."""
    assert len(set(CASE_IDS)) == len(CASE_IDS)


@pytest.mark.parametrize("case", CASES, ids=CASE_IDS)
def test_fixture_case(case: dict[str, Any]) -> None:
    """Chaque fixture produit exactement les conditions attendues."""
    facts = extract_conditions(case["text"], case["lang"])
    observed = [(fact.condition_type, fact.value, fact.confidence) for fact in facts]
    expected = [
        (item["condition_type"], item["value"], item["confidence"])
        for item in case["expect"]
    ]
    assert observed == expected


@pytest.mark.parametrize("case", CASES, ids=CASE_IDS)
def test_fixture_quotes_are_verbatim(case: dict[str, Any]) -> None:
    """Chaque citation est un extrait exact du texte analysé."""
    for fact in extract_conditions(case["text"], case["lang"]):
        assert fact.quote
        assert fact.quote in case["text"]
        assert case["text"][fact.start_offset:fact.end_offset] == fact.quote


# ──────────────────────────────────────────────────────────────────────
# Contrat de l'API
# ──────────────────────────────────────────────────────────────────────


def test_empty_text_yields_no_fact() -> None:
    """Un texte vide ne produit aucun fait — jamais une valeur par défaut."""
    assert extract_conditions("") == []
    assert extract_conditions("   \n\t ") == []


def test_text_without_condition_yields_no_fact() -> None:
    """Une offre qui ne parle pas de conditions ne renvoie rien."""
    facts = extract_conditions("Nous recherchons un analyste de données pour notre équipe.")
    assert facts == []


def test_extraction_is_deterministic() -> None:
    """Le même texte produit toujours la même liste de faits."""
    text = "Full remote. Horaires flexibles. Budget formation 2000 EUR. Hybrid 3 days per week remote."
    first = extract_conditions(text)
    second = extract_conditions(text)
    assert [fact.to_dict() for fact in first] == [fact.to_dict() for fact in second]


def test_facts_are_sorted_by_position() -> None:
    """Les faits sont rendus dans l'ordre de lecture du texte."""
    facts = extract_conditions("Full remote. Horaires flexibles. Tickets resto. Mutuelle.")
    assert [fact.start_offset for fact in facts] == sorted(fact.start_offset for fact in facts)


def test_source_field_is_reported() -> None:
    """Le champ d'origine est reporté dans chaque fait."""
    facts = extract_conditions("Full remote", source_field="title")
    assert facts
    assert facts[0].source_field == "title"


def test_fact_to_dict_is_json_safe() -> None:
    """La version sérialisable d'un fait ne contient que des types simples."""
    fact = extract_conditions("Full remote")[0]
    payload = fact.to_dict()
    assert payload["condition_type"] == "remote"
    assert payload["group"] == "work_location"
    assert json.dumps(payload)


def test_condition_groups_cover_every_type() -> None:
    """Chaque type de condition est rattaché à un groupe du contrat."""
    for condition_type in CONDITION_GROUPS:
        assert condition_type in {
            "remote", "hybrid", "onsite", "flexible_hours", "part_time",
            "meal_vouchers", "health_insurance", "transport", "equipment",
            "training_budget", "certification_support", "language_training",
            "relocation", "visa_sponsorship", "mobility_budget",
        }


def test_all_condition_types_are_reachable() -> None:
    """Les 15 types de conditions sont extraits au moins une fois."""
    corpus = " ".join(case["text"] for case in CASES)
    corpus += (
        " Full remote. Présentiel. Hybrid 3 days per week remote. Horaires flexibles. "
        "Temps partiel 20 heures par semaine. Tickets resto. Mutuelle. Jobticket. "
        "Matériel fourni. Budget formation 2000 EUR. Certification support. "
        "Language classes. Relocation package. Visa sponsorship. Budget mobilité 500 EUR."
    )
    found = {fact.condition_type for fact in extract_conditions(corpus)}
    assert found == set(CONDITION_GROUPS)


# ──────────────────────────────────────────────────────────────────────
# Langues
# ──────────────────────────────────────────────────────────────────────


def test_detect_language_on_native_texts() -> None:
    """La détection de langue reconnaît les six langues du contrat."""
    samples = {
        "fr": "Nous recherchons un profil avec des horaires flexibles et une mutuelle",
        "en": "We are looking for a profile with flexible hours and health insurance",
        "de": "Wir suchen ein Profil mit Gleitzeit und Krankenversicherung",
        "it": "Cerchiamo una figura con orari flessibili e assicurazione salute",
        "es": "Buscamos un perfil con horario flexible y seguro médico",
        "nl": "Wij zoeken een profiel met flexibele werkuren en ziekteverzekering",
    }
    for language, text in samples.items():
        assert detect_language(text) == language, text


def test_explicit_language_is_accepted() -> None:
    """Une langue explicite est acceptée et normalisée."""
    assert extract_conditions("Full remote", "en")
    assert extract_conditions("Full remote", "EN")


def test_unsupported_language_is_rejected() -> None:
    """Une langue inconnue est refusée explicitement."""
    with pytest.raises(ValueError):
        extract_conditions("Full remote", "pt")


def test_language_never_removes_facts() -> None:
    """La langue fixe une priorité, elle ne filtre jamais les faits."""
    facts = extract_conditions("Full remote", lang="fr")
    assert [fact.condition_type for fact in facts] == ["remote"]


# ──────────────────────────────────────────────────────────────────────
# Localisation du travail
# ──────────────────────────────────────────────────────────────────────


def test_hybrid_extracts_days_per_week() -> None:
    """Le rythme hybridé est chiffré dans les six langues."""
    samples = {
        "fr": ("Télétravail 2 jours par semaine", "2 days/week"),
        "en": ("Hybrid: 3 days from home", "3 days/week"),
        "de": ("Hybrid: 2 Tage Homeoffice", "2 days/week"),
        "it": ("Smart working 3 giorni", "3 days/week"),
        "es": ("Híbrido 4 días por semana", "4 days/week"),
        "nl": ("Thuiswerken 1 dag", "1 days/week"),
    }
    for language, (text, expected) in samples.items():
        facts = extract_conditions(text)
        hybrid = [fact for fact in facts if fact.condition_type == "hybrid"]
        assert hybrid, text
        assert hybrid[0].value == expected, text


def test_hybrid_without_precision_is_boolean() -> None:
    """« Hybride » sans précision donne une valeur booléenne."""
    facts = extract_conditions("Organisation hybride")
    hybrid = [fact for fact in facts if fact.condition_type == "hybrid"]
    assert hybrid
    assert hybrid[0].value is True


def test_onsite_is_detected() -> None:
    """Le présentiel est détecté dans les six langues."""
    samples = (
        "Présentiel obligatoire",
        "Onsite required for workshops",
        "Arbeit vor Ort im Büro",
        "Lavoro in sede",
        "Trabajo presencial en oficina",
        "Op locatie werken",
    )
    for text in samples:
        facts = extract_conditions(text)
        assert "onsite" in {fact.condition_type for fact in facts}, text


def test_remote_is_detected() -> None:
    """Le télétravail est détecté dans les six langues."""
    samples = (
        "Télétravail uniquement",
        "Fully remote position",
        "Vollständig remote möglich",
        "Lavoro da casa completo",
        "Trabajo remoto",
        "Volledig remote werken",
    )
    for text in samples:
        facts = extract_conditions(text)
        assert "remote" in {fact.condition_type for fact in facts}, text


def test_quantified_remote_is_reported_as_hybrid() -> None:
    """« Télétravail 2 jours par semaine » est un rythme hybride, pas un/full remote."""
    facts = extract_conditions("Télétravail 2 jours par semaine")
    assert {fact.condition_type for fact in facts} == {"hybrid"}


def test_remote_negation_is_explicit() -> None:
    """« Pas de télétravail » est un fait négatif explicite, pas une absence."""
    samples = (
        ("Pas de télétravail", "fr"),
        ("No remote work", "en"),
        ("Kein Homeoffice", "de"),
        ("Nessun lavoro da casa", "it"),
        ("Sin teletrabajo", "es"),
        ("Geen thuiswerken", "nl"),
    )
    for text, language in samples:
        facts = extract_conditions(text, language)
        remote = [fact for fact in facts if fact.condition_type == "remote"]
        assert remote, text
        assert remote[0].value is False, text
        assert remote[0].confidence == "explicit", text


def test_negation_does_not_cross_a_field_boundary() -> None:
    """La négation ne franchit pas une virgule : « sur site » reste positif."""
    facts = extract_conditions("Pas de télétravail, sur site 5j/7")
    onsite = [fact for fact in facts if fact.condition_type == "onsite"]
    assert onsite
    assert onsite[0].value is True


# ──────────────────────────────────────────────────────────────────────
# Avantages, formation, mobilité
# ──────────────────────────────────────────────────────────────────────


def test_benefits_are_typed() -> None:
    """Les avantages sont typés : repas, santé, transport, équipement."""
    text = "Tickets resto, mutuelle, jobticket, matériel fourni"
    found = {fact.condition_type for fact in extract_conditions(text)}
    assert {"meal_vouchers", "health_insurance", "transport", "equipment"} <= found


def test_training_budget_carries_the_amount() -> None:
    """Le budget de formation porte le montant écrit."""
    facts = extract_conditions("Fortbildungsbudget 2000€")
    budget = [fact for fact in facts if fact.condition_type == "training_budget"]
    assert budget
    assert budget[0].value == 2000


def test_training_without_amount_is_boolean() -> None:
    """Une formation financée sans montant donne une valeur booléenne."""
    facts = extract_conditions("Formation prise en charge")
    training = [fact for fact in facts if fact.condition_type == "training_budget"]
    assert training
    assert training[0].value is True


def test_certification_and_language_training_are_separate() -> None:
    """Certification et cours de langues sont deux types distincts."""
    facts = extract_conditions("Certification support and language training")
    found = {fact.condition_type for fact in facts}
    assert "certification_support" in found
    assert "language_training" in found


def test_mobility_conditions_are_typed() -> None:
    """Relocation, visa et budget mobilité sont trois types distincts."""
    facts = extract_conditions("Relocation package, visa sponsorship, mobility budget")
    found = {fact.condition_type for fact in facts}
    assert {"relocation", "visa_sponsorship", "mobility_budget"} <= found


def test_part_time_hours_are_capped() -> None:
    """Un volume temps plein n'est jamais signalé comme temps partiel."""
    facts = extract_conditions("40 heures par semaine")
    part_time = [fact for fact in facts if fact.condition_type == "part_time"]
    assert part_time
    assert part_time[0].value is False


def test_part_time_volume_is_reported() -> None:
    """Un volume horaire partiel est chiffré."""
    facts = extract_conditions("20 heures par semaine")
    part_time = [fact for fact in facts if fact.condition_type == "part_time"]
    assert part_time
    assert part_time[0].value == "20 h/week"


def test_flexible_without_precision_is_inferred() -> None:
    """« Flexible » seul est une inférence, pas une déclaration."""
    facts = extract_conditions("Flexible")
    flexible = [fact for fact in facts if fact.condition_type == "flexible_hours"]
    assert flexible
    assert flexible[0].confidence == "inferred"


def test_flexible_hours_is_explicit_when_named() -> None:
    """« Horaires flexibles » est une déclaration explicite."""
    facts = extract_conditions("Horaires flexibles")
    flexible = [fact for fact in facts if fact.condition_type == "flexible_hours"]
    assert flexible
    assert flexible[0].confidence == "explicit"


# ──────────────────────────────────────────────────────────────────────
# Contradictions
# ──────────────────────────────────────────────────────────────────────


def test_full_remote_and_onsite_days_are_contradictory() -> None:
    """« Full remote » + « 2 days onsite » : deux faits, contradiction mutuelle."""
    facts = extract_conditions("Full remote position. 2 days onsite.")
    remote = [fact for fact in facts if fact.condition_type == "remote"]
    hybrid = [fact for fact in facts if fact.condition_type == "hybrid"]
    assert len(facts) == 2
    assert remote and hybrid
    assert remote[0].value is True
    assert hybrid[0].value == "2 days/week"
    assert "remote_vs_hybrid" in remote[0].contradictions
    assert "remote_vs_hybrid" in hybrid[0].contradictions


def test_hybrid_and_onsite_are_contradictory() -> None:
    """« Hybrid 3 days » + « Onsite required » : contradiction tracée."""
    facts = extract_conditions("Hybrid 3 days per week. Onsite required for workshops.")
    hybrid = [fact for fact in facts if fact.condition_type == "hybrid"]
    onsite = [fact for fact in facts if fact.condition_type == "onsite"]
    assert hybrid and onsite
    assert hybrid[0].value == "3 days/week"
    assert onsite[0].value is True
    assert "onsite_vs_hybrid" in hybrid[0].contradictions
    assert "onsite_vs_hybrid" in onsite[0].contradictions


def test_conflicting_hybrid_values_are_ambiguous() -> None:
    """Deux rythmes hybrided contradictoires marquent l'ambiguïté."""
    facts = extract_conditions("Hybrid 2 days per week remote and hybrid 4 days per week remote")
    assert len(facts) == 2
    assert all(fact.confidence == "ambiguous" for fact in facts)
    assert all("hybrid_conflict" in fact.contradictions for fact in facts)


def test_remote_and_its_negation_are_ambiguous() -> None:
    """« Remote » et « pas de télétravail » se contredisent."""
    facts = extract_conditions("Remote position. Pas de télétravail.")
    remote = [fact for fact in facts if fact.condition_type == "remote"]
    assert len(remote) == 2
    assert all(fact.confidence == "ambiguous" for fact in remote)
    assert all("remote_conflict" in fact.contradictions for fact in remote)


# ──────────────────────────────────────────────────────────────────────
# Offre complète (plusieurs champs)
# ──────────────────────────────────────────────────────────────────────


def test_offer_extraction_reads_several_fields() -> None:
    """Les champs de l'offre sont analysés séparément et concaténés."""
    offer = {
        "description_original": "Full remote possible",
        "title": "Data Analyst",
        "benefits": "Tickets resto",
    }
    facts = extract_conditions_from_offer(offer)
    assert {fact.condition_type for fact in facts} == {"remote", "meal_vouchers"}
    assert {fact.source_field for fact in facts} == {"description_original", "benefits"}


def test_offer_extraction_detects_cross_field_contradiction() -> None:
    """« Remote » en description et « Onsite » en métadonnées se contredisent."""
    offer = {"description_original": "Remote", "title": "Onsite"}
    facts = extract_conditions_from_offer(offer)
    assert len(facts) == 2
    assert all("remote_vs_onsite" in fact.contradictions for fact in facts)


def test_offer_extraction_rejects_non_objects() -> None:
    """Une offre qui n'est pas un objet est refusée."""
    with pytest.raises(TypeError):
        extract_conditions_from_offer(["not", "an", "offer"])  # type: ignore[arg-type]


def test_offer_extraction_handles_list_fields() -> None:
    """Un champ structuré en liste est lu comme du texte."""
    offer = {"requirements": ["Full remote", "Hybrid 2 days per week remote"]}
    facts = extract_conditions_from_offer(offer)
    assert facts
    assert all(fact.source_field == "requirements" for fact in facts)


# ──────────────────────────────────────────────────────────────────────
# Intégration dans qualify_offer()
# ──────────────────────────────────────────────────────────────────────


def _offer(description: str) -> dict[str, Any]:
    return {
        "title": "Data Analyst",
        "description_original": description,
        "employment_type": "CDI",
        "source_name": "synthetic",
        "source_id": "synthetic-sk17",
        "official_url": "https://example.invalid/offers/sk17",
        "source_verified": True,
        "posted_date": "2026-10-01",
        "start_date": "2027-03-01",
        "duration_min_months": 12,
        "duration_max_months": 12,
        "country": "France",
        "city": "Paris",
        "language": "fr",
    }


def test_qualify_offer_exposes_conditions_as_evidence() -> None:
    """qualify_offer() recopie les conditions dans sa provenance."""
    result = qualify_offer(_offer("Full remote possible. Horaires flexibles. Tickets resto."))
    assert "conditions" in result.provenance
    evidence = result.provenance["conditions"]
    assert evidence.source.startswith("source_field:")
    types = {item["condition_type"] for item in evidence.value}
    assert {"remote", "flexible_hours", "meal_vouchers"} <= types
    for item in evidence.value:
        assert item["quote"]
        assert item["group"] in CONDITION_GROUPS.values()


def test_qualify_offer_without_condition_has_no_evidence() -> None:
    """Une offre sans condition n'ajoute pas de provenance vide."""
    result = qualify_offer(_offer("Nous recherchons un analyste de données."))
    assert "conditions" not in result.provenance


def test_qualify_offer_conditions_do_not_decide_conformity() -> None:
    """Les conditions sont informatives : elles ne changent pas la décision."""
    without = qualify_offer(_offer("Nous recherchons un analyste de données."))
    with_conditions = qualify_offer(_offer("Full remote possible. Horaires flexibles."))
    assert without.target_status == with_conditions.target_status


# ──────────────────────────────────────────────────────────────────────
# Résumé
# ──────────────────────────────────────────────────────────────────────


def test_summarize_conditions_is_serializable() -> None:
    """Le résumé des conditions est sérialisable et sans doublon."""
    facts = extract_conditions("Full remote. Horaires flexibles. Tickets resto.")
    summary = summarize_conditions(facts)
    assert summary["types"] == ["remote", "flexible_hours", "meal_vouchers"]
    assert summary["by_type"]["remote"] == [True]
    assert summary["contradictions"] == []
    assert json.dumps(summary)


def test_summarize_conditions_lists_contradictions() -> None:
    """Le résumé remonte les jetons de contradiction."""
    facts = extract_conditions("Full remote position. 2 days onsite.")
    summary = summarize_conditions(facts)
    assert summary["contradictions"] == ["remote_vs_hybrid"]


def test_condition_fact_defaults_contradictions() -> None:
    """Un fait construit à la main a une liste de contradictions vide."""
    fact = ConditionFact(
        condition_type="remote",
        value=True,
        source_field="description_original",
        quote="Full remote",
        start_offset=0,
        end_offset=10,
        confidence="explicit",
    )
    assert fact.contradictions == []
    assert fact.group == "work_location"
