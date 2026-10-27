"""Tests for SK-11 — dossier de candidature « 1 clic » et vérifiable.

The contract under test:

* every factual sentence cites an approved profile fact;
* every affirmation gets exactly one verdict — supported / unsupported / to_verify;
* an unsupported affirmation blocks the final export;
* nothing is invented — no degree, no skill, no figure, no language level;
* the offer announces the language, the person may change it;
* the dossier compares before / after and keeps a version history;
* nothing is ever submitted automatically and no network call is made.
"""

from __future__ import annotations

import json
import socket
from pathlib import Path

import pytest

from career.application_dossier import (
    AUTOMATIC_SUBMISSION,
    ApplicationDossier,
    DossierFact,
    build_application_dossier,
    detect_offer_language,
    export_dossier,
    facts_from_profile,
    normalize_dossier_language,
    reverify_dossier,
    verify_dossier_text,
)
from workspace_core import UserFacingError

FIXTURES = Path(__file__).parent / "fixtures" / "application_dossier"


def load_offer(name: str) -> dict:
    return json.loads((FIXTURES / f"{name}.json").read_text(encoding="utf-8"))


APPROVED_FACTS: list[dict] = [
    {
        "fact_id": "fact_skill_excel",
        "value": "Excel dashboards for sales reporting",
        "quote": "Excel dashboards for sales reporting",
        "category": "skill",
        "status": "approved",
    },
    {
        "fact_id": "fact_edu_finance",
        "value": "Master's degree in Finance",
        "quote": "Master's degree in Finance",
        "category": "education",
        "status": "approved",
    },
    {
        "fact_id": "fact_lang_en",
        "value": "English C1",
        "quote": "English C1",
        "category": "language",
        "status": "approved",
    },
    {
        "fact_id": "fact_exp_sql",
        "value": "SQL analysis at a retail company",
        "quote": "SQL analysis at a retail company",
        "category": "experience",
        "status": "approved",
    },
]


@pytest.fixture()
def offer_en() -> dict:
    return load_offer("offer_en")


@pytest.fixture()
def dossier(offer_en: dict) -> ApplicationDossier:
    return build_application_dossier(offer_en, APPROVED_FACTS)


# --------------------------------------------------------------------- language


class TestLanguage:
    def test_default_language_comes_from_the_offer(self, offer_en: dict) -> None:
        built = build_application_dossier(offer_en, APPROVED_FACTS)
        assert built.language == "en"
        assert built.language_source == "offer"

    @pytest.mark.parametrize(
        ("fixture", "expected"),
        [
            ("offer_fr", "fr"),
            ("offer_de", "de"),
            ("offer_it", "it"),
        ],
    )
    def test_detected_language_per_offer(self, fixture: str, expected: str) -> None:
        detected, source = detect_offer_language(load_offer(fixture))
        assert detected == expected
        assert source == "offer"

    def test_person_can_force_another_language(self, offer_en: dict) -> None:
        built = build_application_dossier(offer_en, APPROVED_FACTS, language="fr")
        assert built.language == "fr"
        assert built.language_source == "user"

    def test_language_aliases_are_accepted(self) -> None:
        assert normalize_dossier_language("Français") == "fr"
        assert normalize_dossier_language("english") == "en"
        assert normalize_dossier_language("it-IT") == "it"

    def test_unknown_language_is_refused(self) -> None:
        with pytest.raises(UserFacingError):
            normalize_dossier_language("klingon")

    def test_forced_language_changes_the_letter(self, offer_en: dict) -> None:
        built = build_application_dossier(offer_en, APPROVED_FACTS, language="de")
        letter = built.artifact("cover_letter")
        assert letter is not None
        assert "Guten Tag" in letter.body
        assert built.language == "de"


# ------------------------------------------------------------------ artifacts


class TestArtifacts:
    def test_six_deliverables_are_produced(self, dossier: ApplicationDossier) -> None:
        keys = [artifact.key for artifact in dossier.artifacts]
        assert keys == [
            "cv_recommendations",
            "adapted_cv",
            "cover_letter",
            "prep_sheet",
            "interview_questions",
            "checklist",
        ]

    def test_every_artifact_has_a_body_and_a_language(self, dossier: ApplicationDossier) -> None:
        for artifact in dossier.artifacts:
            assert artifact.body.strip()
            assert artifact.language == dossier.language

    def test_letter_repeats_the_facts_verbatim(self, dossier: ApplicationDossier) -> None:
        letter = dossier.artifact("cover_letter")
        assert letter is not None
        for fact in APPROVED_FACTS:
            assert fact["value"] in letter.body

    def test_adapted_cv_groups_the_facts_by_section(self, dossier: ApplicationDossier) -> None:
        cv = dossier.artifact("adapted_cv")
        assert cv is not None
        assert "## Education" in cv.body
        assert "## Skills" in cv.body
        assert "## Languages" in cv.body

    def test_recommendations_use_the_action_vocabulary(self, dossier: ApplicationDossier) -> None:
        assert dossier.recommendations
        codes = {item.code for item in dossier.recommendations}
        assert codes <= {
            "HIGHLIGHT",
            "REPHRASE",
            "DO_NOT_ADD",
            "QUANTIFY",
            "CONFIRM_LANGUAGE",
        }

    def test_prep_sheet_lists_the_offer_facts_to_verify(self, dossier: ApplicationDossier) -> None:
        prep = dossier.artifact("prep_sheet")
        assert prep is not None
        assert "Northwind Analytics" in prep.body
        assert "2026-11-30" in prep.body

    def test_interview_questions_reference_the_requirements(self, dossier: ApplicationDossier) -> None:
        questions = dossier.artifact("interview_questions")
        assert questions is not None
        assert "Excel" in questions.body

    def test_checklist_lists_the_pending_points(self, dossier: ApplicationDossier) -> None:
        checklist = dossier.artifact("checklist")
        assert checklist is not None
        assert "- [ ]" in checklist.body

    def test_no_automatic_submission_anywhere(self, dossier: ApplicationDossier) -> None:
        assert AUTOMATIC_SUBMISSION is False
        assert dossier.automatic_submission is False
        expected = "you send it yourself" if dossier.language == "en" else "tu envoies toi-même"
        for key in ("adapted_cv", "cover_letter", "prep_sheet", "checklist"):
            artifact = dossier.artifact(key)
            assert artifact is not None
            assert expected in artifact.body


# ------------------------------------------------------------------ verifier


class TestVerifier:
    def test_every_claim_has_a_known_verdict(self, dossier: ApplicationDossier) -> None:
        assert dossier.verification.claims
        for claim in dossier.verification.claims:
            assert claim.verdict in {"supported", "unsupported", "to_verify"}

    def test_supported_claims_cite_an_approved_fact(self, dossier: ApplicationDossier) -> None:
        approved = {fact["fact_id"] for fact in APPROVED_FACTS}
        for claim in dossier.verification.claims:
            if claim.verdict == "supported":
                assert claim.fact_id in approved
                assert claim.quote

    def test_generated_dossier_is_exportable(self, dossier: ApplicationDossier) -> None:
        assert dossier.verification.unsupported_count == 0
        assert dossier.export_allowed is True

    def test_counts_are_consistent(self, dossier: ApplicationDossier) -> None:
        verification = dossier.verification
        assert verification.supported_count == sum(
            1 for claim in verification.claims if claim.verdict == "supported"
        )
        assert verification.unsupported_count == sum(
            1 for claim in verification.claims if claim.verdict == "unsupported"
        )
        assert verification.to_verify_count == sum(
            1 for claim in verification.claims if claim.verdict == "to_verify"
        )

    def test_invented_figure_is_unsupported(self, dossier: ApplicationDossier) -> None:
        letter = dossier.artifact("cover_letter")
        assert letter is not None
        edited = letter.body + "\n\nI have 5 years of experience with Power BI.\n"
        verification = reverify_dossier(dossier, {"cover_letter": edited})
        assert verification.unsupported_count >= 1
        blocking = [claim for claim in verification.claims if claim.verdict == "unsupported"]
        assert any("5 years" in claim.text for claim in blocking)

    def test_invented_degree_is_unsupported(self, dossier: ApplicationDossier) -> None:
        letter = dossier.artifact("cover_letter")
        assert letter is not None
        edited = letter.body + "\n\nMy PhD in Quantitative Finance is complete.\n"
        verification = reverify_dossier(dossier, {"cover_letter": edited})
        assert verification.unsupported_count >= 1

    def test_invented_language_level_is_unsupported(self, dossier: ApplicationDossier) -> None:
        letter = dossier.artifact("cover_letter")
        assert letter is not None
        edited = letter.body + "\n\nMy German is at C2 level.\n"
        verification = reverify_dossier(dossier, {"cover_letter": edited})
        assert verification.unsupported_count >= 1

    def test_invented_skill_is_unsupported(self, dossier: ApplicationDossier) -> None:
        letter = dossier.artifact("cover_letter")
        assert letter is not None
        edited = letter.body + "\n\nI am a certified Kubernetes administrator.\n"
        verification = reverify_dossier(dossier, {"cover_letter": edited})
        assert verification.unsupported_count >= 1

    def test_sentence_backed_by_a_fact_is_supported(self, dossier: ApplicationDossier) -> None:
        letter = dossier.artifact("cover_letter")
        assert letter is not None
        edited = letter.body + "\n\nSQL analysis at a retail company is part of my background.\n"
        verification = reverify_dossier(dossier, {"cover_letter": edited})
        assert verification.unsupported_count == 0

    def test_offer_statement_is_not_a_candidate_claim(self, dossier: ApplicationDossier) -> None:
        letter = dossier.artifact("cover_letter")
        assert letter is not None
        edited = letter.body + "\n\nThe role is based in Berlin at Northwind Analytics.\n"
        verification = reverify_dossier(dossier, {"cover_letter": edited})
        assert verification.unsupported_count == 0
        assert verification.to_verify_count >= 1

    def test_to_verify_does_not_block_the_export(self, dossier: ApplicationDossier) -> None:
        letter = dossier.artifact("cover_letter")
        assert letter is not None
        edited = letter.body + "\n\nPlease confirm the start date with the team.\n"
        verification = reverify_dossier(dossier, {"cover_letter": edited})
        assert verification.unsupported_count == 0
        assert verification.export_allowed is True

    def test_verify_dossier_text_is_pure(self) -> None:
        facts = facts_from_profile(APPROVED_FACTS)
        claims = verify_dossier_text("cover_letter", "SQL analysis at a retail company", facts)
        assert len(claims) == 1
        assert claims[0].verdict == "supported"


# ----------------------------------------------------------------- zero invention


class TestZeroInvention:
    def test_uncovered_requirement_is_never_claimed(self, offer_en: dict) -> None:
        built = build_application_dossier(offer_en, APPROVED_FACTS)
        letter = built.artifact("cover_letter")
        assert letter is not None
        assert "Power BI" not in letter.body
        assert "3 years" not in letter.body

    def test_uncovered_requirement_becomes_do_not_add(self, offer_en: dict) -> None:
        built = build_application_dossier(offer_en, APPROVED_FACTS)
        power_bi = [
            item for item in built.recommendations if "Power BI" in item.requirement
        ]
        assert power_bi
        assert all(item.code == "DO_NOT_ADD" for item in power_bi)
        assert all(item.fact_id == "" for item in power_bi)

    def test_proposed_fact_never_proves_a_claim(self, offer_en: dict) -> None:
        facts = list(APPROVED_FACTS) + [
            {
                "fact_id": "fact_kafka",
                "value": "Kafka streams",
                "quote": "Kafka streams",
                "category": "skill",
                "status": "proposed",
            }
        ]
        built = build_application_dossier(offer_en, facts)
        supported_ids = {
            claim.fact_id
            for claim in built.verification.claims
            if claim.verdict == "supported"
        }
        assert "fact_kafka" not in supported_ids

    def test_rejected_fact_is_never_used(self, offer_en: dict) -> None:
        facts = list(APPROVED_FACTS) + [
            {
                "fact_id": "fact_rejected",
                "value": "Certified Kubernetes administrator",
                "quote": "Certified Kubernetes administrator",
                "category": "skill",
                "status": "rejected",
            }
        ]
        built = build_application_dossier(offer_en, facts)
        body = "\n".join(artifact.body for artifact in built.artifacts)
        assert "Kubernetes" not in body

    def test_negated_fact_does_not_prove(self) -> None:
        fact = DossierFact(
            fact_id="f1",
            value="Excel",
            quote="Excel",
            category="skill",
            status="approved",
            negated=True,
        )
        assert fact.usable is False


# ----------------------------------------------------------------- diff & history


class TestDiffAndHistory:
    def test_before_after_comparison_is_produced(self, offer_en: dict) -> None:
        base = "# CV\n- Excel dashboards for sales reporting\n- Legacy line to drop"
        built = build_application_dossier(offer_en, APPROVED_FACTS, base_cv=base)
        kinds = {item.kind for item in built.diff}
        assert "kept" in kinds
        assert "added" in kinds
        assert "removed" in kinds
        removed = [item for item in built.diff if item.kind == "removed"]
        assert any("Legacy line to drop" in item.text for item in removed)

    def test_diff_is_empty_without_a_base_cv(self, dossier: ApplicationDossier) -> None:
        assert all(item.kind == "added" for item in dossier.diff)

    def test_history_keeps_every_version(self, offer_en: dict) -> None:
        first = build_application_dossier(offer_en, APPROVED_FACTS, version=1)
        second = build_application_dossier(
            offer_en,
            APPROVED_FACTS,
            version=2,
            history=first.history,
            language="fr",
        )
        assert len(second.history) == 2
        assert [entry.version for entry in second.history] == [1, 2]
        assert second.history[1].language == "fr"
        assert second.history[1].language_source == "user"

    def test_version_entry_summarizes_the_verification(self, dossier: ApplicationDossier) -> None:
        latest = dossier.history[-1]
        assert latest.supported_count == dossier.verification.supported_count
        assert latest.unsupported_count == dossier.verification.unsupported_count


# --------------------------------------------------------------------- export


class TestExport:
    def test_export_writes_the_dossier(self, dossier: ApplicationDossier, tmp_path: Path) -> None:
        written = export_dossier(dossier, tmp_path / "dossier")
        assert (tmp_path / "dossier" / "cover_letter.md").exists()
        assert (tmp_path / "dossier" / "verification.json").exists()
        manifest = json.loads((tmp_path / "dossier" / "manifest.json").read_text(encoding="utf-8"))
        assert manifest["automatic_submission"] is False
        assert manifest["export_allowed"] is True
        assert set(written) >= {"adapted_cv", "cover_letter", "verification", "manifest"}

    def test_export_is_refused_when_an_claim_is_unproven(
        self, dossier: ApplicationDossier, tmp_path: Path
    ) -> None:
        letter = dossier.artifact("cover_letter")
        assert letter is not None
        edited = letter.body + "\n\nI mastered Kubernetes in five years.\n"
        from career.application_dossier import with_artifacts

        blocked = with_artifacts(dossier, {"cover_letter": edited})
        assert blocked.verification.unsupported_count >= 1
        assert blocked.export_allowed is False
        with pytest.raises(UserFacingError) as error:
            export_dossier(blocked, tmp_path / "blocked")
        assert "Export final bloqué" in str(error.value)
        assert not (tmp_path / "blocked").exists()

    def test_export_opens_no_socket(self, dossier: ApplicationDossier, tmp_path: Path) -> None:
        def refuse(*args: object, **kwargs: object) -> None:
            raise AssertionError("le dossier ne doit jamais ouvrir une connexion")

        original = socket.socket
        socket.socket = refuse  # type: ignore[assignment]
        try:
            export_dossier(dossier, tmp_path / "offline")
        finally:
            socket.socket = original  # type: ignore[assignment]


# ------------------------------------------------------------------- facts input


class TestFactsInput:
    def test_sk03_shape(self) -> None:
        facts = facts_from_profile(
            {
                "facts": [
                    {
                        "fact_id": "f1",
                        "category": "tech",
                        "value": "Excel",
                        "quote": "Excel",
                        "status": "approved",
                    }
                ],
                "profile_text": "Excel",
            }
        )
        assert len(facts) == 1
        assert facts[0].fact_id == "f1"
        assert facts[0].usable is True

    def test_sk10_shape_with_usable_facts(self) -> None:
        facts = facts_from_profile(
            {
                "usable_facts": [
                    {"id": "f2", "kind": "skill", "label": "SQL", "status": "approved"},
                    {"id": "f3", "kind": "skill", "label": "Kafka", "status": "proposed"},
                ]
            }
        )
        assert [fact.fact_id for fact in facts] == ["f2", "f3"]
        assert facts[0].usable is True
        assert facts[1].usable is False

    def test_local_profile_sections(self) -> None:
        facts = facts_from_profile(
            {
                "skills": ["Excel", "SQL"],
                "education": ["Master's degree in Finance"],
                "availability": ["Available from March"],
            }
        )
        values = {fact.value for fact in facts}
        assert "Excel" in values
        assert "Master's degree in Finance" in values

    def test_plain_strings_are_accepted(self) -> None:
        facts = facts_from_profile(["Excel", "SQL"])
        assert [fact.value for fact in facts] == ["Excel", "SQL"]
        assert all(fact.usable for fact in facts)

    def test_empty_profile_is_not_an_error(self) -> None:
        assert facts_from_profile(None) == ()
        assert facts_from_profile({}) == ()


# ------------------------------------------------------------- robustness


class TestRobustness:
    def test_offer_without_requirement_still_builds(self) -> None:
        built = build_application_dossier(load_offer("offer_minimal"), APPROVED_FACTS)
        assert built.artifacts
        assert built.verification.unsupported_count == 0

    def test_empty_profile_produces_no_fabrication(self, offer_en: dict) -> None:
        built = build_application_dossier(offer_en, [])
        letter = built.artifact("cover_letter")
        assert letter is not None
        assert "Excel dashboards" not in letter.body
        assert built.verification.unsupported_count == 0

    def test_offer_injection_is_not_turned_into_a_requirement(self) -> None:
        built = build_application_dossier(load_offer("offer_injection"), APPROVED_FACTS)
        texts = " ".join(item.text for item in built.coverage).lower()
        assert "ignore previous instructions" not in texts
        assert "ignore all previous instructions" not in texts

    def test_offer_text_never_executes_an_instruction(self) -> None:
        built = build_application_dossier(load_offer("offer_injection"), APPROVED_FACTS)
        assert built.verification.unsupported_count == 0
        assert built.export_allowed is True

    def test_build_is_deterministic(self, offer_en: dict) -> None:
        first = build_application_dossier(offer_en, APPROVED_FACTS)
        second = build_application_dossier(offer_en, APPROVED_FACTS)
        assert [artifact.body for artifact in first.artifacts] == [
            artifact.body for artifact in second.artifacts
        ]
        assert first.verification.to_dict() == second.verification.to_dict()

    def test_no_clock_is_used(self, offer_en: dict) -> None:
        built = build_application_dossier(offer_en, APPROVED_FACTS)
        assert built.history[-1].generated_at == ""

    def test_generated_at_is_supplied_by_the_caller(self, offer_en: dict) -> None:
        built = build_application_dossier(
            offer_en, APPROVED_FACTS, generated_at="2026-10-22T00:00:00Z"
        )
        assert built.history[-1].generated_at == "2026-10-22T00:00:00Z"
