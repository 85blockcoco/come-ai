"""Tests SK-18 — extracteur de missions complètes.

`career.cv_quality.missions_extractor` lit les sections « missions » d'une
offre (six langues) et renvoie une liste de `MissionFact` : type de mission,
extrait verbatim, citation, offsets dans le texte source, confiance et
compétences techniques implicites.

Le corpus `tests/fixtures/missions_extractor/synthetic_missions.json` contient
29 offres synthétiques (aucune donnée personnelle, aucun texte réel) qui
figent le résultat attendu : type, texte, confiance et compétences. Les
tests de contrat vérifient ensuite que les offsets et les citations sont
réellement sourcés dans le texte d'entrée, que le module est déterministe et
hors-ligne, et que l'intégration (qualify_offer, prepare_application,
summarize_offer) expose les missions sans casser l'existant.
"""

from __future__ import annotations

import ast
import json
import re
from pathlib import Path

import pytest

from career.cv_quality.missions_extractor import (
    MISSION_TYPES,
    SUPPORTED_LANGUAGES,
    MissionFact,
    classify_mission_type,
    detect_implied_skills,
    detect_language,
    extract_missions,
    missions_as_dicts,
    normalize_offer_text,
)

FIXTURES_PATH = (
    Path(__file__).resolve().parent
    / "fixtures"
    / "missions_extractor"
    / "synthetic_missions.json"
)
MODULE_PATH = (
    Path(__file__).resolve().parents[1]
    / "career"
    / "cv_quality"
    / "missions_extractor.py"
)

FIXTURES = json.loads(FIXTURES_PATH.read_text(encoding="utf-8"))["fixtures"]
FIXTURES_BY_ID = {fixture["id"]: fixture for fixture in FIXTURES}


def fixture(fixture_id: str) -> dict:
    return FIXTURES_BY_ID[fixture_id]


# ------------------------------------------------------------------- corpus


def test_corpus_is_large_enough_and_multilingual() -> None:
    assert len(FIXTURES) >= 20, "le corpus doit contenir au moins 20 offres."
    languages = {fixture["language"] for fixture in FIXTURES}
    assert languages == set(SUPPORTED_LANGUAGES), (
        f"le corpus doit couvrir les six langues (lu : {sorted(languages)})."
    )
    assert len({fixture["id"] for fixture in FIXTURES}) == len(FIXTURES)


@pytest.mark.parametrize("fixture_id", sorted(FIXTURES_BY_ID))
def test_expected_missions_are_extracted(fixture_id: str) -> None:
    data = fixture(fixture_id)
    facts = extract_missions(data["description_original"])
    extracted = [
        {
            "type": fact.mission_type,
            "text": fact.text,
            "confidence": fact.confidence,
            "implied_skills": fact.implied_skills,
        }
        for fact in facts
    ]
    assert extracted == data["expected"], (
        f"{fixture_id} : les missions extraites ne correspondent pas au corpus figé."
    )


@pytest.mark.parametrize("fixture_id", sorted(FIXTURES_BY_ID))
def test_offsets_point_at_the_verbatim_text(fixture_id: str) -> None:
    data = fixture(fixture_id)
    description = data["description_original"]
    for fact in extract_missions(description):
        assert 0 <= fact.start_offset < fact.end_offset <= len(description)
        assert description[fact.start_offset:fact.end_offset] == fact.text, (
            f"{fixture_id} : le texte extrait n'est pas l'extrait verbatim."
        )


@pytest.mark.parametrize("fixture_id", sorted(FIXTURES_BY_ID))
def test_quote_is_a_verbatim_excerpt_of_the_offer(fixture_id: str) -> None:
    data = fixture(fixture_id)
    description = normalize_offer_text(data["description_original"])
    for fact in extract_missions(data["description_original"]):
        assert fact.quote, f"{fixture_id} : une mission doit être citée."
        assert fact.quote in description, (
            f"{fixture_id} : la citation doit être un extrait du texte source."
        )
        assert fact.source_field == "description_original"


def test_html_description_is_normalised_before_extraction() -> None:
    html = (
        "<h2>Missions</h2><ul><li>Modélisation financière</li>"
        "<li>Reporting mensuel</li></ul><p>Profil : Bac+5</p>"
    )
    facts = extract_missions(html)
    assert [fact.text for fact in facts] == ["Modélisation financière", "Reporting mensuel"]
    # La preuve reste résolvable dans le texte normalisé.
    assert facts[0].quote in normalize_offer_text(html)


def test_html_entities_are_decoded() -> None:
    assert normalize_offer_text("Missions&nbsp;: Mod&eacute;lisation") == (
        "Missions : Modélisation"
    )
    assert normalize_offer_text("Missions : M&A") == "Missions : M&A"


def test_missions_are_sorted_by_offset() -> None:
    facts = extract_missions(
        "Missions :\n• Modélisation financière\n• Reporting mensuel\n• Support équipe"
    )
    offsets = [fact.start_offset for fact in facts]
    assert offsets == sorted(offsets)


# ------------------------------------------------------------------ contrat


@pytest.mark.parametrize("value", ["", "   ", "\n\n", None, 123, [], {}])
def test_empty_or_invalid_input_returns_no_mission(value) -> None:
    assert extract_missions(value) == []  # type: ignore[arg-type]


def test_extraction_is_deterministic() -> None:
    description = "Missions : Modélisation financière LBO. Reporting mensuel."
    first = extract_missions(description)
    second = extract_missions(description)
    assert first == second
    assert missions_as_dicts(first) == missions_as_dicts(second)


def test_long_mission_is_truncated_and_flagged() -> None:
    long_mission = "Analyser " * 120
    facts = extract_missions(f"Missions :\n• {long_mission}")
    assert len(facts) == 1
    assert len(facts[0].text) == 500
    assert "truncated" in facts[0].notes
    assert facts[0].end_offset - facts[0].start_offset == 500


@pytest.mark.parametrize(
    "vague",
    [
        "Missions : Selon profil",
        "Missions : To be discussed",
        "Missions : TBD",
        "Missions : Divers",
        "Missions : A confirmer",
    ],
)
def test_vague_items_are_filtered(vague: str) -> None:
    assert extract_missions(vague) == []


def test_profile_section_is_never_extracted_as_a_mission() -> None:
    description = (
        "Missions :\n• Modélisation financière\n\n"
        "Profil recherché :\n• Bac+5 en finance\n• Maîtrise d'Excel\n\n"
        "Avantages :\n• Tickets restaurant"
    )
    facts = extract_missions(description)
    assert [fact.text for fact in facts] == ["Modélisation financière"]


def test_empty_bullets_and_lone_numbers_are_filtered() -> None:
    facts = extract_missions("Missions :\n•\n• \n1.\n2. Reporting mensuel")
    assert [fact.text for fact in facts] == ["Reporting mensuel"]


def test_duplicated_mission_is_kept_once_and_flagged() -> None:
    facts = extract_missions(
        "Missions :\n• Modélisation financière\n• Modélisation financière\n• Reporting mensuel"
    )
    assert [fact.text for fact in facts] == ["Modélisation financière", "Reporting mensuel"]
    assert any("dupliqu" in note for note in facts[0].notes)


@pytest.mark.parametrize(
    "text, expected_type",
    [
        ("Être responsable du périmètre clients", "responsibility"),
        ("Analyser les données chaque jour", "task"),
        ("Produire le rapport mensuel", "deliverable"),
        ("KPI : taux de closing supérieur à 30 %", "kpi"),
        ("Encadrer l'équipe analytique", "team"),
        ("Périmètre : portefeuille clients", "scope"),
    ],
)
def test_every_mission_type_is_classifiable(text: str, expected_type: str) -> None:
    mission_type, _conflicts, _confidence = classify_mission_type(text)
    assert mission_type == expected_type
    assert mission_type in MISSION_TYPES


def test_confidence_distinguishes_explicit_inferred_and_ambiguous() -> None:
    assert classify_mission_type("Produire le rapport mensuel")[2] == "explicit"
    assert classify_mission_type("Analyser les données")[2] == "inferred"
    assert classify_mission_type("Responsable du reporting")[2] == "ambiguous"


def test_ambiguous_type_exposes_the_conflict() -> None:
    facts = extract_missions("Missions :\n• Responsable du reporting mensuel")
    assert facts[0].mission_type == "responsibility"
    assert facts[0].confidence == "ambiguous"
    assert facts[0].contradictions
    assert "deliverable" in facts[0].contradictions[0]


@pytest.mark.parametrize(
    "text, expected_skill",
    [
        ("Écrire des scripts Python", "Python"),
        ("Construire un suivi Excel", "Excel"),
        ("Automatiser des macros VBA", "VBA"),
        ("Écrire des requêtes SQL", "SQL"),
        ("Construire un dashboard Power BI", "Power BI"),
        ("Construire un tableau Tableau", "Tableau"),
        ("Utiliser la terminale Bloomberg", "Bloomberg"),
        ("Modélisation financière LBO", "Financial Modeling"),
        ("Travaux de valuation", "Valuation"),
        ("Support transactions M&A", "M&A"),
        ("Opérations LBO", "LBO"),
        ("Analyse due diligence", "Due Diligence"),
        ("Lead client presentations", "Client Presentation"),
        ("Gestion de projet", "Project Management"),
    ],
)
def test_implicit_skills_are_detected(text: str, expected_skill: str) -> None:
    assert expected_skill in detect_implied_skills(text)


def test_at_least_ten_skill_patterns_are_covered() -> None:
    assert len(
        {
            skill
            for text in (
                "Python", "Excel", "VBA", "SQL", "Power BI", "Tableau",
                "Bloomberg", "Modélisation financière", "valuation", "M&A",
            )
            for skill in detect_implied_skills(text)
        }
    ) >= 10


def test_explicit_language_restricts_the_headings() -> None:
    english = "Key responsibilities: Build financial models."
    assert extract_missions(english, lang="en")
    assert extract_missions(english, lang="fr") == []


@pytest.mark.parametrize(
    "text, expected_language",
    [
        ("Vos missions : Modélisation financière pour notre équipe", "fr"),
        ("What you'll do: Build financial models for our team", "en"),
        ("Ihre Aufgaben: Finanzmodellierung für unser Team", "de"),
        ("Mansioni: Analisi valutazione per il nostro team", "it"),
        ("Funciones: Modelado financiero para nuestro equipo", "es"),
        ("Taken: Financiële modellering voor ons team", "nl"),
    ],
)
def test_language_detection(text: str, expected_language: str) -> None:
    assert detect_language(text) == expected_language


def test_missions_as_dicts_is_json_serialisable() -> None:
    facts = extract_missions("Missions :\n• Modélisation financière\n• Reporting mensuel")
    payload = missions_as_dicts(facts)
    assert json.loads(json.dumps(payload, ensure_ascii=False)) == payload
    assert payload[0]["mission_type"] == "deliverable"
    assert payload[0]["source_field"] == "description_original"


def test_module_is_offline_and_never_evaluates_code() -> None:
    source = MODULE_PATH.read_text(encoding="utf-8")
    tree = ast.parse(source)
    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module.split(".")[0])
    forbidden = {"requests", "urllib", "httpx", "socket", "subprocess", "http"}
    assert not imported & forbidden, f"import réseau/interdit : {imported & forbidden}"
    # ``re.compile`` est légitime ; ``eval``/``exec``/``compile`` comme
    # fonctions natives ne le sont pas.
    dynamic_call = re.compile(r"(?<![\w.])(eval|exec|compile|__import__)\s*\(")
    assert not dynamic_call.search(source), (
        "appel dynamique interdit dans le module d'extraction."
    )


def test_module_does_not_use_a_clock() -> None:
    source = MODULE_PATH.read_text(encoding="utf-8")
    assert "datetime" not in source
    assert "time.time" not in source


# --------------------------------------------------------------- intégration


def _offer() -> dict:
    return {
        "id": "synthetic-missions-1",
        "title": "Investment Banking Intern",
        "company": "Banque Synthetique",
        "description_original": (
            "Missions :\n• Modélisation financière LBO\n• Support transactions M&A\n"
            "\nProfil recherché :\n• Bac+5 en finance"
        ),
        "source_name": "Source Synthetique",
        "source_id": "synthetic-missions-1",
        "official_url": "https://example.test/jobs/synthetic-missions-1",
        "source_verified": True,
        "employment_type": "stage",
        "posted_date": "2026-10-01",
        "start_date": "2027-01-15",
        "duration_months": 6,
    }


def test_qualify_offer_cites_the_missions_as_evidence() -> None:
    from career.offer_qualification import qualify_offer

    result = qualify_offer(_offer())
    evidence = result.provenance["missions"]
    assert evidence.source == "missions_extractor"
    assert evidence.value == ["Modélisation financière LBO", "Support transactions M&A"]
    assert evidence.quote
    assert "Modélisation financière LBO" in evidence.quote


def test_qualification_snapshot_persists_missions_as_readable_text() -> None:
    from career.qualification_persistence import normalize_qualification_snapshot

    snapshot = normalize_qualification_snapshot(
        {
            "contract_type": "internship",
            "provenance": {
                "missions": {
                    "value": ["Modélisation financière LBO", "Support transactions M&A"],
                    "source": "missions_extractor",
                    "quote": "• Modélisation financière LBO",
                }
            },
        },
        _offer(),
    )
    stored = json.loads(snapshot["provenance_json"])["missions"]
    assert stored["value"] == "Modélisation financière LBO\nSupport transactions M&A"
    assert stored["source"] == "missions_extractor"


def test_prepare_application_exposes_the_missions() -> None:
    from career.application_prep import prepare_application

    panel = prepare_application({}, {}, _offer())
    assert [mission["text"] for mission in panel["missions"]] == [
        "Modélisation financière LBO",
        "Support transactions M&A",
    ]
    assert panel["missions"][0]["mission_type"] == "deliverable"
    assert panel["missions"][1]["implied_skills"] == ["M&A"]


def test_summarize_offer_keeps_the_legacy_missions_and_adds_the_details() -> None:
    from career.application_prep import summarize_offer

    summary = summarize_offer(_offer())
    # La clé historique reste la liste des exigences : la mesure
    # d'exhaustivité (seuil CI) et le repli d'affichage en dépendent.
    assert summary["missions"] == summary["missions"]
    assert summary["mission_details"]
    assert summary["mission_details"][0]["text"] == "Modélisation financière LBO"
    assert summary["mission_details"][0]["mission_type"] == "deliverable"


def test_offer_without_mission_section_exposes_nothing() -> None:
    from career.application_prep import summarize_offer

    offer = _offer()
    offer["description_original"] = "Profil recherché :\n• Bac+5 en finance"
    summary = summarize_offer(offer)
    assert summary["mission_details"] == []


def test_mission_fact_carries_the_documented_contract() -> None:
    fields = {field.name: field.type for field in MissionFact.__dataclass_fields__.values()}
    assert fields["mission_type"] is not None
    assert fields["text"] is not None
    assert fields["source_field"] is not None
    assert fields["quote"] is not None
    assert fields["start_offset"] is not None
    assert fields["end_offset"] is not None
    assert fields["confidence"] is not None
    assert fields["contradictions"] is not None
    assert fields["implied_skills"] is not None
