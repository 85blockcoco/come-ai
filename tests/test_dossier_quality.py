"""Tests for SPEC-042 — transparent dossier quality score and kit integration."""

from __future__ import annotations

import json
from pathlib import Path


from career.dossier_quality import (
    FACTOR_WEIGHTS,
    audit_application_dossier,
    audit_dossier,
    build_dossier_quality_report,
    quality_report,
)

EVIDENCE = [
    {
        "fact_id": "excel",
        "category": "skills",
        "value": "Excel avancé",
        "level": "verified",
        "approved_at": "2026-01-10",
    },
    {
        "fact_id": "finance",
        "category": "experience",
        "value": "5 ans d'expérience en finance d'entreprise",
        "level": "quantified",
        "approved_at": "2026-01-15",
    },
    {
        "fact_id": "anglais",
        "category": "languages",
        "value": "Anglais C1",
        "level": "documented",
        "approved_at": "2026-01-20",
    },
]

READY_DOC = (
    "Je maîtrise Excel. "
    "J'ai 5 ans d'expérience en finance d'entreprise. "
    "Anglais C1."
)
REQUIREMENTS = ["Excel", "finance"]
ANSWERS = {"disponibilité": "mars 2027"}


def test_ready_dossier_is_high_score_and_exportable():
    report = audit_dossier(
        READY_DOC,
        evidence=EVIDENCE,
        requirements=REQUIREMENTS,
        recurring_answers=ANSWERS,
    )
    assert report.score >= 85
    assert report.verdict == "ready"
    assert report.export_allowed is True
    assert report.counts["invented"] == 0
    assert report.issues == ()


def test_three_published_factors_and_weights():
    report = audit_dossier(READY_DOC, evidence=EVIDENCE)
    keys = [factor.key for factor in report.factors]
    assert keys == ["factuality", "evidence", "argument"]
    assert [round(factor.weight, 2) for factor in report.factors] == [0.50, 0.30, 0.20]
    assert abs(sum(factor.weight for factor in report.factors) - 1.0) < 1e-9
    assert abs(sum(FACTOR_WEIGHTS.values()) - 1.0) < 1e-9


def test_every_factor_publishes_formula_and_inputs():
    report = audit_dossier(READY_DOC, evidence=EVIDENCE, requirements=REQUIREMENTS)
    for factor in report.factors:
        assert factor.formula
        assert factor.inputs
        assert 0 <= factor.score <= 100
        assert isinstance(factor.score, int)


def test_total_score_is_the_weighted_sum_of_factors():
    report = audit_dossier(READY_DOC, evidence=EVIDENCE, requirements=REQUIREMENTS)
    expected = round(
        sum(factor.weight * factor.score for factor in report.factors)
    )
    assert report.score == expected


def test_invented_fact_blocks_export_even_with_a_good_score():
    report = audit_dossier(
        READY_DOC + " J'ai géré un budget de 2 M€.",
        evidence=EVIDENCE,
        requirements=REQUIREMENTS,
        recurring_answers=ANSWERS,
    )
    assert report.counts["invented"] == 1
    assert report.export_allowed is False
    assert report.verdict == "blocked"
    assert any(issue["label"] == "invented" for issue in report.issues)


def test_moved_number_blocks_export_as_out_of_context():
    report = audit_dossier(
        "J'ai 5 ans d'expérience en Excel.",
        evidence=EVIDENCE,
        requirements=REQUIREMENTS,
    )
    assert report.counts["out_of_context"] == 1
    assert report.verdict == "blocked"
    assert report.export_allowed is False
    assert "contextes différents" in report.issues[0]["suggestion"]


def test_inflated_only_dossier_can_still_be_reviewed():
    report = audit_dossier(
        READY_DOC + " Je suis expert en Excel.",
        evidence=EVIDENCE,
        requirements=REQUIREMENTS,
        recurring_answers=ANSWERS,
    )
    assert report.counts["inflated"] == 1
    assert report.verdict == "review"
    assert report.export_allowed is True
    assert report.score >= 60


def test_empty_dossier_is_blocked():
    report = audit_dossier("", evidence=EVIDENCE)
    assert report.score == 0
    assert report.verdict == "blocked"
    assert report.export_allowed is False
    assert any("Aucun document" in warning for warning in report.warnings)


def test_offer_only_dossier_is_blocked():
    report = audit_dossier(
        "Votre offre mentionne notamment : Excel.",
        evidence=EVIDENCE,
        context={"terms": ["Votre offre mentionne notamment : Excel."]},
    )
    assert report.diagnostics["claim_count"] == 0
    assert report.verdict == "blocked"


def test_requirement_coverage_drives_the_argument_factor():
    covered = audit_dossier("Je maîtrise Excel.", evidence=EVIDENCE, requirements=["Excel"])
    missed = audit_dossier("Je maîtrise Excel.", evidence=EVIDENCE, requirements=["Python"])
    assert covered.factor_scores["argument"] > missed.factor_scores["argument"]
    assert covered.diagnostics["requirements_coverage"] == 1.0
    assert missed.diagnostics["requirements_coverage"] == 0.0


def test_recurring_answers_coverage_drives_the_argument_factor():
    answered = audit_dossier(
        "Je maîtrise Excel.",
        evidence=EVIDENCE,
        requirements=["Excel"],
        recurring_answers={"disponibilité": "mars 2027"},
    )
    unanswered = audit_dossier(
        "Je maîtrise Excel.",
        evidence=EVIDENCE,
        requirements=["Excel"],
        recurring_answers={"disponibilité": ""},
    )
    assert answered.factor_scores["argument"] > unanswered.factor_scores["argument"]
    assert answered.diagnostics["recurring_answers_coverage"] == 1.0
    assert unanswered.diagnostics["recurring_answers_coverage"] == 0.0


def test_missing_expectations_are_neutral_not_a_fake_pass():
    report = audit_dossier("Je maîtrise Excel.", evidence=EVIDENCE)
    assert report.factor_scores["argument"] == 50
    assert "neutre" in report.factors[2].formula


def test_generic_argument_lowers_the_argument_factor():
    with_generic = audit_dossier(
        "Je maîtrise Excel. Je suis motivé.",
        evidence=EVIDENCE,
        requirements=["Excel"],
    )
    without_generic = audit_dossier(
        "Je maîtrise Excel.",
        evidence=EVIDENCE,
        requirements=["Excel"],
    )
    assert with_generic.diagnostics["generic_arguments"] == 1
    assert with_generic.factor_scores["argument"] < without_generic.factor_scores["argument"]


def test_ats_stuffing_lowers_factuality():
    clean = audit_dossier("- Excel", evidence=EVIDENCE)
    stuffed = audit_dossier("- Excel\n- Excel\n- Excel\n- Excel", evidence=EVIDENCE)
    assert clean.diagnostics["ats_stuffing_blocks"] == 0
    assert stuffed.diagnostics["ats_stuffing_blocks"] == 4
    assert stuffed.factor_scores["factuality"] < clean.factor_scores["factuality"]


def test_evidence_factor_reports_levels_and_dates():
    report = audit_dossier(READY_DOC, evidence=EVIDENCE)
    diagnostics = report.diagnostics
    assert diagnostics["claims_with_evidence"] >= 1
    assert diagnostics["dated_evidence"] >= 1
    assert diagnostics["evidence_levels"]
    assert set(diagnostics["evidence_levels"]) <= {"declared", "documented", "verified", "quantified"}


def test_report_is_json_serializable_and_transparent():
    report = audit_dossier(READY_DOC, evidence=EVIDENCE, requirements=REQUIREMENTS)
    payload = json.loads(report.to_json())
    assert payload["score"] == report.score
    assert len(payload["factors"]) == 3
    assert payload["claim_report"]["claim_count"] == report.counts["supported"]
    assert "formula" in payload["factors"][0]
    assert payload["diagnostics"]["supported_rate"] == 100


def test_markdown_report_contains_score_formulas_and_claims():
    report = audit_dossier(READY_DOC, evidence=EVIDENCE, requirements=REQUIREMENTS)
    text = report.to_markdown()
    assert f"Score : {report.score}/100" in text
    assert "## Facteurs et formules" in text
    assert "100 ×" in text
    assert "Audit qualité des affirmations" in text
    assert "Je maîtrise Excel." in text


def test_report_verdict_label_is_french():
    assert audit_dossier("", evidence=EVIDENCE).verdict_label.startswith("export bloqué")
    ready = audit_dossier(READY_DOC, evidence=EVIDENCE, requirements=REQUIREMENTS)
    assert ready.verdict_label.startswith("prêt")


def test_rules_version_is_reported():
    report = audit_dossier(READY_DOC, evidence=EVIDENCE)
    assert report.rules_version == "1.0.0"


def test_custom_rules_path_is_honoured(tmp_path: Path):
    custom = tmp_path / "rules.json"
    custom.write_text(
        json.dumps(
            {
                "version": "2.0.0-test",
                "rules": [
                    {
                        "id": "buzzword",
                        "category": "inflated_anglicism",
                        "pattern": r"\bsynergie\b",
                        "severity": "medium",
                        "label": "mot creux",
                        "suggestion": "Retire ce mot.",
                    }
                ],
                "generic_phrases": [],
                "skill_terms": [],
                "credential_terms": [],
            }
        ),
        encoding="utf-8",
    )
    report = audit_dossier(
        "J'ai une synergie naturelle.",
        evidence=EVIDENCE,
        rules_path=str(custom),
    )
    assert report.rules_version == "2.0.0-test"
    assert report.counts["inflated"] == 1
    assert any(issue["label"] == "inflated" for issue in report.issues)


def test_cv_letter_and_answers_are_composed_as_sections():
    report = audit_dossier(
        cv="Je maîtrise Excel.",
        letter="J'ai 5 ans d'expérience en finance d'entreprise.",
        answers={"disponibilité": "mars 2027"},
        evidence=EVIDENCE,
    )
    sections = {claim["section"] for claim in report.claim_report["claims"]}
    assert "CV généré" in sections
    assert "Lettre générée" in sections
    assert "Réponses de formulaire" in sections


def test_reported_issues_are_bounded_and_prioritised():
    report = audit_dossier(
        "J'ai géré un budget de 2 M€. Je suis expert en Excel. Je maîtrise Excel.",
        evidence=EVIDENCE,
    )
    assert len(report.issues) <= 100
    assert report.issues
    assert all(issue["label"] != "supported" for issue in report.issues)


def test_report_is_deterministic():
    first = audit_dossier(READY_DOC, evidence=EVIDENCE, requirements=REQUIREMENTS)
    second = audit_dossier(READY_DOC, evidence=EVIDENCE, requirements=REQUIREMENTS)
    assert first.to_dict() == second.to_dict()


def test_aliases_are_stable():
    assert quality_report is audit_dossier
    assert audit_application_dossier is audit_dossier
    alias_report = build_dossier_quality_report("Je maîtrise Excel.", evidence=EVIDENCE)
    assert alias_report.score == audit_dossier("Je maîtrise Excel.", evidence=EVIDENCE).score


def test_scores_are_always_bounded():
    for document in ("", READY_DOC, "Je suis expert. J'ai 99 ans d'expérience.", "Excel Excel Excel Excel"):
        report = audit_dossier(document, evidence=EVIDENCE)
        assert 0 <= report.score <= 100
        assert all(0 <= factor.score <= 100 for factor in report.factors)


def test_apply_kit_exposes_quality_audit_before_export(tmp_path: Path):
    from career.service import CareerService

    service = CareerService(tmp_path)
    service.update_profile(
        {
            "display_name": "Personne Démo",
            "education": "Master Finance (démo)",
            "experience": "Projet étudiant de modélisation (démo)",
            "skills": "Excel, analyse financière",
            "languages": "Français, anglais C1",
            "eligibility": "compatible",
        }
    )
    job = service.import_job(
        {
            "company": "Banque de Démo",
            "title": "Stagiaire M&A",
            "source_name": "manual",
            "source_id": "REF-DEMO-2027-014",
            "official_url": "https://careers.example.test/jobs/demo-42",
            "job_family": "M&A / Investment Banking",
            "city": "Paris",
            "country": "France",
            "deadline_date": "2027-02-01",
            "start_date": "2027-02-01",
            "end_date": "2027-05-31",
            "duration_months": 4,
            "source_status": "open",
            "requirements": "Modélisation LBO avancée et valorisation.",
            "description_original": "Stage de démonstration, données synthétiques.",
        }
    )
    kit = service.build_apply_kit(job["id"])
    audit = kit["quality_audit"]
    assert isinstance(audit, dict)
    assert audit["score"] >= 60
    assert audit["export_allowed"] is True
    assert len(audit["factors"]) == 3
    assert audit["claim_report"]["claim_count"] >= 1

    ids = [item["id"] for item in kit["checklist"]]
    assert "quality_audit" in ids
    assert ids.index("quality_audit") < ids.index("official_url") or "official_url" not in ids
    step = next(item for item in kit["checklist"] if item["id"] == "quality_audit")
    assert step["done"] is True
    assert f"Score {audit['score']}/100" in step["note"]


def test_profile_fact_date_counts_as_dated_evidence():
    profile = {
        "facts": [
            {
                "fact_id": "finance",
                "category": "experience",
                "value": "5 ans d'expérience en finance d'entreprise",
                "quote": "5 ans d'expérience en finance d'entreprise (2021-2026)",
                "status": "approved",
                "level": "verified",
                "dated_at": "2026-10-12",
            }
        ]
    }
    report = audit_dossier("J'ai 5 ans d'expérience en finance d'entreprise.", profile=profile)
    diagnostics = report.diagnostics
    assert diagnostics["claims_with_evidence"] >= 1
    assert diagnostics["dated_evidence"] >= 1
    claim = report.claim_report["claims"][0]
    assert claim["best_evidence"]["dated_at"] == "2026-10-12"
