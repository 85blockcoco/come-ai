"""Tests for SPEC-042 — deterministic claim-by-claim dossier audit."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from career.claim_check import (
    ApprovedEvidence,
    audit_claims,
    build_evidence_ledger,
    check_claims,
    load_rules,
    readable_report,
)

EVIDENCE = [
    {
        "fact_id": "excel",
        "category": "skills",
        "value": "Excel avancé (TCD, Power Query)",
        "level": "documented",
        "approved_at": "2026-01-10",
    },
    {
        "fact_id": "python",
        "category": "skills",
        "value": "Python (pandas, numpy)",
        "level": "documented",
        "approved_at": "2026-02-02",
    },
    {
        "fact_id": "finance",
        "category": "experience",
        "value": "5 ans d'expérience en finance d'entreprise",
        "level": "verified",
        "approved_at": "2026-01-15",
    },
    {
        "fact_id": "master",
        "category": "education",
        "value": "Master Finance, 2021",
        "level": "verified",
        "approved_at": "2026-01-01",
    },
    {
        "fact_id": "anglais",
        "category": "languages",
        "value": "Anglais C1",
        "level": "documented",
        "approved_at": "2026-01-20",
    },
    {
        "fact_id": "equipe",
        "category": "experience",
        "value": "Management d'une équipe de 8 personnes",
        "level": "verified",
        "approved_at": "2026-03-01",
    },
    {
        "fact_id": "stage",
        "category": "experience",
        "value": "Stage de 6 mois en contrôle de gestion chez Alpha Conseil",
        "level": "verified",
        "approved_at": "2026-04-01",
    },
    {
        "fact_id": "cfa",
        "category": "education",
        "value": "Certification CFA niveau 1",
        "level": "verified",
        "approved_at": "2026-02-10",
    },
    {
        "fact_id": "ventes",
        "category": "experience",
        "value": "12 projets livrés en 2023",
        "level": "verified",
        "approved_at": "2026-05-01",
    },
    {
        "fact_id": "lbo",
        "category": "skills",
        "value": "Modélisation LBO sur 3 dossiers",
        "level": "verified",
        "approved_at": "2026-02-20",
    },
]


def label_of(sentence: str, evidence=None) -> str:
    report = check_claims(sentence, evidence=EVIDENCE if evidence is None else evidence)
    claims = report.audited_claims
    assert claims, f"aucune affirmation auditée pour {sentence!r} ({report.skipped})"
    return claims[0].label


SUPPORTED_CASES = [
    "J'ai 5 ans d'expérience en finance d'entreprise.",
    "Je maîtrise Excel.",
    "J'utilise Python.",
    "Anglais C1.",
    "J'ai un Master Finance (2021).",
    "J'ai managé une équipe de 8 personnes.",
    "J'ai réalisé un stage de 6 mois en contrôle de gestion chez Alpha Conseil.",
    "12 projets livrés en 2023.",
    "J'ai obtenu la certification CFA niveau 1.",
    "Je maîtrise la modélisation LBO.",
    "Je suis diplômé d'un Master Finance.",
]

INVENTED_CASES = [
    "J'ai 10 ans d'expérience en finance.",
    "J'ai livré 40 projets.",
    "J'ai obtenu un Master Finance en 2024.",
    "J'ai géré un budget de 2 M€.",
    "J'ai travaillé chez Google.",
    "Je maîtrise TensorFlow.",
    "J'ai 5 ans d'expérience en marketing.",
    "J'ai encadré 20 personnes.",
    "Je suis certifié en Excel.",
    "Je suis certifié en marketing.",
]

INFLATED_CASES = [
    "Je suis expert en Excel.",
    "Je suis expert en Python.",
    "Je suis senior en Excel.",
    "Mon travail est parfaitement fiable.",
    "Je garantis des résultats.",
    "Je promets une amélioration immédiate.",
    "Je suis passionné par la finance.",
    "Je suis un ninja de l'Excel.",
    "J'ai toujours réussi mes projets.",
    "Je suis le meilleur candidat.",
    "Mon approche est à la pointe.",
    "Je suis un gourou de la finance.",
    "Je certifie que mes résultats sont garantis.",
]

OUT_OF_CONTEXT_CASES = [
    "J'ai 5 ans d'expérience en Excel.",
    "J'ai 12 projets en finance.",
    "J'ai 6 mois d'expérience en Python.",
    "J'ai 8 personnes en modélisation LBO.",
    "Master Finance avec 12 projets livrés.",
    "Anglais C1 avec 5 ans d'expérience en Excel.",
    "Certification CFA avec 6 mois de stage.",
    "J'ai 3 dossiers LBO en contrôle de gestion.",
]

UNVERIFIABLE_CASES = [
    "Je suis motivé.",
    "Je suis dynamique et rigoureux.",
    "J'ai un excellent relationnel.",
    "Je suis autonome.",
    "Mon objectif est de progresser.",
    "Je suis curieux.",
    "J'ai une bonne capacité d'adaptation.",
    "Je suis polyvalent.",
]


@pytest.mark.parametrize("sentence", SUPPORTED_CASES, ids=lambda value: value[:34])
def test_supported_claim(sentence: str):
    assert label_of(sentence) == "supported"


@pytest.mark.parametrize("sentence", INVENTED_CASES, ids=lambda value: value[:34])
def test_invented_claim(sentence: str):
    assert label_of(sentence) == "invented"


@pytest.mark.parametrize("sentence", INFLATED_CASES, ids=lambda value: value[:34])
def test_inflated_claim(sentence: str):
    assert label_of(sentence) == "inflated"


@pytest.mark.parametrize("sentence", OUT_OF_CONTEXT_CASES, ids=lambda value: value[:34])
def test_out_of_context_claim(sentence: str):
    assert label_of(sentence) == "out_of_context"


@pytest.mark.parametrize("sentence", UNVERIFIABLE_CASES, ids=lambda value: value[:34])
def test_unverifiable_claim(sentence: str):
    assert label_of(sentence) == "unverifiable"


@pytest.mark.parametrize("sentence", OUT_OF_CONTEXT_CASES, ids=lambda value: f"not-invented-{value[:20]}")
def test_out_of_context_is_not_invented(sentence: str):
    verdict = check_claims(sentence, evidence=EVIDENCE).audited_claims[0]
    assert verdict.label == "out_of_context"
    assert verdict.missing_evidence == ()


@pytest.mark.parametrize("sentence", INVENTED_CASES, ids=lambda value: f"missing-{value[:24]}")
def test_invented_claim_names_the_missing_fact(sentence: str):
    verdict = check_claims(sentence, evidence=EVIDENCE).audited_claims[0]
    assert verdict.label == "invented"
    assert verdict.missing_evidence
    assert verdict.suggestion


def test_claim_report_is_json_serializable():
    report = check_claims("Je suis expert en Excel.", evidence=EVIDENCE)
    payload = json.loads(report.to_json())
    assert payload["rules_version"] == "1.0.0"
    assert payload["claim_count"] == 1
    assert payload["claims"][0]["label"] == "inflated"
    assert payload["claims"][0]["label_label"] == "exagéré"


def test_readable_report_quotes_claim_and_proof():
    report = check_claims("Je suis expert en Excel.", evidence=EVIDENCE)
    text = readable_report(report)
    assert "Je suis expert en Excel." in text
    assert "Excel avancé (TCD, Power Query)" in text
    assert "documented" in text
    assert "2026-01-10" in text
    assert "Reformulation sûre" in text


def test_suggestion_never_invents_a_fact():
    report = check_claims("J'ai géré un budget de 2 M€.", evidence=EVIDENCE)
    verdict = report.audited_claims[0]
    assert verdict.label == "invented"
    assert "2 M€" in verdict.suggestion
    assert "l'auditeur ne fabrique aucune valeur" in verdict.suggestion


def test_mapping_sections_and_offsets():
    report = check_claims(
        {"CV": "Je maîtrise Excel.\nJ'ai 5 ans d'expérience.", "Lettre": "Je suis expert en Excel."},
        evidence=EVIDENCE,
    )
    assert {claim.section for claim in report.audited_claims} == {"CV", "Lettre"}
    first = report.audited_claims[0]
    assert first.text == "Je maîtrise Excel."
    assert first.offset == 0
    assert any(claim.label == "inflated" and claim.section == "Lettre" for claim in report.audited_claims)


def test_contact_offer_and_boilerplate_are_skipped():
    report = check_claims(
        {
            "CV": "demo@example.test\nBanque de Démo\nMadame, Monsieur,\nJe maîtrise Excel.",
        },
        evidence=EVIDENCE,
        context={"entities": ["Banque de Démo"]},
    )
    assert report.skipped.get("contact") == 1
    assert report.skipped.get("offer_reference") == 1
    assert report.skipped.get("boilerplate") == 1
    assert len(report.audited_claims) == 1
    assert report.audited_claims[0].label == "supported"


def test_offer_reference_sentence_is_not_audited():
    report = check_claims(
        "Votre offre mentionne notamment : Modélisation LBO avancée.",
        evidence=EVIDENCE,
        context={"terms": ["Modélisation LBO avancée"]},
    )
    assert report.audited_claims == ()
    assert report.skipped.get("offer_reference") == 1


def test_empty_document_warns_and_has_zero_counts():
    report = check_claims("", evidence=EVIDENCE)
    assert report.audited_claims == ()
    assert set(report.counts.values()) == {0}
    assert any("Document vide" in warning for warning in report.warnings)


def test_no_evidence_never_claims_support():
    report = check_claims("Je maîtrise Excel.", evidence=[])
    verdict = report.audited_claims[0]
    assert verdict.label in {"invented", "unverifiable"}
    assert any("Aucune preuve approuvée" in warning for warning in report.warnings)


def test_ats_keyword_stuffing_above_threshold():
    report = check_claims(
        "- Excel\n- Excel\n- Excel\n- Excel\n",
        evidence=EVIDENCE,
    )
    assert report.counts["inflated"] == 4
    assert all(
        any(issue.code == "ats_keyword_stuffing" for issue in claim.issues)
        for claim in report.audited_claims
    )


def test_ats_keyword_stuffing_at_threshold_is_allowed():
    report = check_claims("- Excel\n- Excel\n- Excel\n", evidence=EVIDENCE)
    assert report.counts["supported"] == 3
    assert report.counts["inflated"] == 0


def test_custom_ats_threshold(tmp_path: Path):
    rules_path = tmp_path / "rules.json"
    payload = json.loads((Path("career") / "dossier_quality_rules.json").read_text(encoding="utf-8"))
    payload["ats_repetition_threshold"] = 1
    rules_path.write_text(json.dumps(payload), encoding="utf-8")
    rules = load_rules(rules_path)
    report = check_claims("- Excel\n- Excel\n", evidence=EVIDENCE, rules=rules)
    assert report.counts["inflated"] == 2


def test_rules_file_is_versioned_and_editable():
    rules = load_rules()
    assert rules.version == "1.0.0"
    assert rules.source_path.endswith("dossier_quality_rules.json")
    assert len(rules.rules) >= 10
    assert rules.ats_repetition_threshold == 3
    assert rules.expert_min_years == 5
    assert "expert_without_years" in rules.patterns
    assert "excel" in rules.skill_terms
    assert "master" in rules.credential_terms


def test_custom_rule_file_changes_the_verdict(tmp_path: Path):
    rules_path = tmp_path / "custom_rules.json"
    rules_path.write_text(
        json.dumps(
            {
                "version": "9.9.9-test",
                "ats_repetition_threshold": 3,
                "rules": [
                    {
                        "id": "synergy_buzzword",
                        "category": "inflated_anglicism",
                        "pattern": r"\bsynergie\b",
                        "severity": "medium",
                        "label": "mot creux",
                        "suggestion": "Retire ce mot creux.",
                    }
                ],
                "generic_phrases": [],
                "skill_terms": [],
                "credential_terms": [],
            }
        ),
        encoding="utf-8",
    )
    rules = load_rules(rules_path)
    report = check_claims("J'ai une synergie naturelle.", evidence=EVIDENCE, rules=rules)
    verdict = report.audited_claims[0]
    assert verdict.label == "inflated"
    assert verdict.issues[0].code == "synergy_buzzword"
    assert report.rules_version == "9.9.9-test"


def test_invalid_rules_file_falls_back_with_warning(tmp_path: Path):
    rules = load_rules(tmp_path / "missing.json")
    assert rules.version == "fallback"
    assert rules.warnings
    report = check_claims("Je suis expert en Excel.", evidence=EVIDENCE, rules=rules)
    assert report.counts["inflated"] == 1


def test_profile_mapping_becomes_an_evidence_ledger():
    ledger = build_evidence_ledger(
        {
            "skills": "Excel\nPython",
            "experience": "Stage de 6 mois en contrôle de gestion",
            "education": "Master Finance",
            "updated_at": "2026-01-01",
        }
    )
    assert len(ledger) == 4
    assert all(item.dated_at == "2026-01-01" for item in ledger)
    assert all(isinstance(item, ApprovedEvidence) for item in ledger)


def test_unapproved_facts_are_never_evidence():
    ledger = build_evidence_ledger(
        [
            {"value": "Excel", "status": "approved"},
            {"value": "Python", "status": "proposed"},
            {"value": "SQL", "status": "rejected"},
            {"value": "SAS", "status": "modified"},
        ]
    )
    quotes = {item.quote for item in ledger}
    assert quotes == {"Excel", "SAS"}


def test_evidence_service_adapter_and_levels():
    class Service:
        def approved_facts(self):
            return [
                {
                    "fact_id": "f1",
                    "category": "skills",
                    "quote": "Excel avancé",
                    "level": "strong",
                    "verified_at": "2026-03-03",
                    "status": "approved",
                },
                {
                    "fact_id": "f2",
                    "category": "skills",
                    "quote": "Python",
                    "status": "rejected",
                },
            ]

    ledger = build_evidence_ledger(Service())
    assert len(ledger) == 1
    assert ledger[0].level == "verified"
    assert ledger[0].dated_at == "2026-03-03"
    report = check_claims("Je maîtrise Excel.", evidence_service=Service())
    assert report.audited_claims[0].label == "supported"
    assert report.evidence_count == 1


def test_audit_claims_alias_is_stable():
    assert audit_claims is check_claims


def test_report_is_deterministic():
    first = check_claims({"CV": "Je maîtrise Excel.", "Lettre": "Je suis expert."}, evidence=EVIDENCE)
    second = check_claims({"CV": "Je maîtrise Excel.", "Lettre": "Je suis expert."}, evidence=EVIDENCE)
    assert first.to_dict() == second.to_dict()


def test_dated_at_and_proof_date_are_recognised_as_proof_dates():
    """The canonical output key ``dated_at`` (and ``proof_date``) must survive
    the ledger: SPEC-042 promises a proof *level plus its date*."""
    facts = [
        {
            "fact_id": "d1",
            "category": "experience",
            "quote": "5 ans d'expérience en finance d'entreprise",
            "level": "verified",
            "dated_at": "2026-10-12",
            "status": "approved",
        },
        {
            "fact_id": "d2",
            "category": "skills",
            "quote": "Modélisation LBO sous Excel",
            "proof_date": "2026-09-01",
            "status": "approved",
        },
    ]
    ledger = build_evidence_ledger(facts)
    by_id = {item.fact_id: item for item in ledger}
    assert by_id["d1"].dated_at == "2026-10-12"
    assert by_id["d2"].dated_at == "2026-09-01"


def test_best_evidence_round_trip_keeps_the_date():
    dated = [
        {
            "fact_id": "finance",
            "category": "experience",
            "value": "5 ans d'expérience en finance d'entreprise",
            "level": "verified",
            "dated_at": "2026-10-12",
        }
    ]
    report = check_claims("J'ai 5 ans d'expérience en finance d'entreprise.", evidence=dated)
    claim = report.audited_claims[0]
    assert claim.label == "supported"
    assert claim.best_evidence is not None
    assert claim.best_evidence["dated_at"] == "2026-10-12"
    # Re-feeding the report's own evidence into a ledger never loses the date.
    ledger = build_evidence_ledger([claim.best_evidence])
    assert ledger and ledger[0].dated_at == "2026-10-12"
