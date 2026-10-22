"""Constitution exécutable (SPEC-014) : DSL, moteur, gouvernance, API, UI.

Toutes les fixtures sont synthétiques : aucune offre réelle, aucune donnée
personnelle, aucun appel réseau. Ce qui est vérifié : le moteur n'exécute
jamais de code arbitraire, une donnée absente n'est jamais transformée en
violation, la gouvernance (brouillon → approbation → dépréciation → archive)
est réellement appliquée, le rollback restaure une version antérieure, les
signatures détectent une altération, la dérive est signalée, l'API HTTP
refuse ce qui doit l'être, les tests générés depuis les règles passent, et
l'interface ne parle qu'à la Constitution locale.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
import sys
import time
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.responses import JSONResponse
from fastapi.testclient import TestClient

from career.constitution import (
    DEFAULT_RULES,
    DEFAULT_RULESETS,
    ENTITY_ID_KEY,
    ENTITY_TYPE_KEY,
    ConstitutionEngine,
    EvaluationError,
    ExpressionError,
    MissingFieldError,
    Rule,
    RuleSet,
    build_entity_context,
    check_expression,
    evaluate_expression,
    expression_identifiers,
    expression_summary,
    generate_rule_tests,
    validate_rule_payload,
)
from career.constitution_audit import build_audit_report, detect_drift, render_report_markdown
from career.constitution_store import ConstitutionStore, canonical_json
from career.router import create_career_router
from career.service import CareerService
from workspace_core import UserFacingError


ROOT = Path(__file__).resolve().parents[1]
CONSTITUTION_SOURCE = ROOT / "career" / "constitution.py"
UI_SCRIPT = ROOT / "career_static" / "js" / "constitution.js"
UI_HTML = ROOT / "career_static" / "index.html"


# --- Fixtures ----------------------------------------------------------------


def make_rule(**changes: object) -> Rule:
    """Règle synthétique minimale."""
    payload: dict[str, object] = {
        "rule_id": "matching.demo.threshold",
        "name": "Seuil de démonstration",
        "domain": "matching",
        "version": 1,
        "status": "active",
        "description": "Règle synthétique de test.",
        "rationale": "Fixture de test.",
        "expression": "matching.score >= 45",
        "dsl_type": "cel",
        "parameters": {},
        "scope": ["offer"],
        "tags": ["test"],
        "created_at": "2026-10-01T00:00:00+00:00",
        "updated_at": "2026-10-01T00:00:00+00:00",
        "created_by": "test",
        "approved_by": "reviewer",
        "approved_at": "2026-10-01T00:00:00+00:00",
        "severity": "error",
    }
    payload.update(changes)
    return Rule.from_dict(payload)


def make_ruleset(rule_ids: list[str]) -> RuleSet:
    return RuleSet(
        ruleset_id="test.core",
        name="Jeu de test",
        version=1,
        rules=rule_ids,
        description="Jeu de règles synthétique.",
        effective_from="2026-10-01T00:00:00+00:00",
    )


@pytest.fixture()
def store(tmp_path: Path) -> ConstitutionStore:
    return ConstitutionStore(tmp_path)


def constitution_client(tmp_path: Path) -> TestClient:
    """Application minimale avec le même contrat d'erreur que l'application réelle."""
    service = CareerService(tmp_path)
    app = FastAPI()
    app.include_router(create_career_router(service))

    @app.exception_handler(UserFacingError)
    async def known_error(_: object, error: UserFacingError) -> JSONResponse:
        return JSONResponse(status_code=400, content={"detail": str(error)})

    return TestClient(app)


# --- 1. DSL : un langage interprété, jamais exécuté ----------------------------


def test_expression_evaluate_une_comparaison() -> None:
    assert evaluate_expression("matching.score >= 45", {"matching": {"score": 72}}) is True
    assert evaluate_expression("matching.score >= 45", {"matching": {"score": 12}}) is False


def test_expression_chemin_absent_leve_une_erreur_nommee() -> None:
    with pytest.raises(MissingFieldError):
        evaluate_expression("matching.score >= 45", {"matching": {}})


def test_expression_erreurs_de_syntaxe_sont_explicites() -> None:
    with pytest.raises(ExpressionError):
        evaluate_expression("matching.score >=", {})
    with pytest.raises(ExpressionError):
        evaluate_expression("matching.score 45", {})
    with pytest.raises(ExpressionError):
        evaluate_expression("", {})


def test_expression_fonction_inconnue_refusee() -> None:
    with pytest.raises(ExpressionError):
        evaluate_expression("mystery(1)", {})


def test_expression_macros_all_exists_et_filter() -> None:
    context = {
        "privacy": {"pii_fields": [{"field": "email", "encrypted": True}, {"field": "phone", "encrypted": True}]},
        "matching": {"critical_requirements": [{"covered": True}, {"covered": False}]},
    }
    assert evaluate_expression("privacy.pii_fields.all(field, field.encrypted == true)", context) is True
    assert evaluate_expression("matching.critical_requirements.all(req, req.covered == true)", context) is False
    assert evaluate_expression("matching.critical_requirements.exists(req, req.covered == false)", context) is True
    filtered = evaluate_expression("matching.critical_requirements.filter(req, req.covered == true)", context)
    assert filtered == [{"covered": True}]


def test_expression_operateurs_logiques_et_priorites() -> None:
    context = {"a": {"value": True}, "b": {"value": False}}
    assert evaluate_expression("a.value && !b.value", context) is True
    assert evaluate_expression("b.value || a.value", context) is True
    assert evaluate_expression("b.value && a.value", context) is False


def test_expression_arithmetique_entiere_et_modulo() -> None:
    assert evaluate_expression("7 / 2", {}) == 3
    assert evaluate_expression("-7 / 2", {}) == -3
    assert evaluate_expression("7 % 3", {}) == 1
    assert evaluate_expression("2 * 3 + 1", {}) == 7


def test_expression_egalite_entre_types_differents() -> None:
    assert evaluate_expression("1 == true", {}) is False
    assert evaluate_expression("1 == 1.0", {}) is True
    assert evaluate_expression("'a' == 'a'", {}) is True


def test_expression_has_detecte_un_champ_absent() -> None:
    assert evaluate_expression("has(matching.score)", {"matching": {"score": 1}}) is True
    assert evaluate_expression("has(matching.score)", {"matching": {}}) is False


def test_expression_division_par_zero_refusee() -> None:
    with pytest.raises(EvaluationError):
        evaluate_expression("1 / 0", {})


def test_expression_non_booleane_est_signalee() -> None:
    result = ConstitutionEngine().evaluate(make_rule(expression="matching.score"), {"matching": {"score": 10}})
    assert result.status == "error"
    assert result.passed is False
    assert "booléen" in result.message


def test_identifiants_extraits_ignorent_les_variables_de_macro() -> None:
    identifiers = expression_identifiers("privacy.pii_fields.all(field, field.encrypted == true)")
    assert identifiers == ["privacy.pii_fields"]


def test_resume_d_expression_expose_macros_et_constantes() -> None:
    summary = expression_summary("freshness.certification.max_age_days <= 365")
    assert summary["identifiers"] == ["freshness.certification.max_age_days"]
    assert summary["constants"] == [365]


def test_verification_syntaxique_sans_erreur_est_positive() -> None:
    assert check_expression("matching.score >= 45")["valid"] is True
    assert check_expression("matching.score >=")["valid"] is False


def test_le_moteur_n_utilise_jamais_eval_ni_exec() -> None:
    """Garde-fou : le DSL est interprété, aucun code Python n'est exécuté."""
    source = CONSTITUTION_SOURCE.read_text(encoding="utf-8")
    assert re.search(r"\beval\s*\(", source) is None
    assert re.search(r"\bexec\s*\(", source) is None
    assert re.search(r"\b__import__\s*\(", source) is None


def test_une_expression_ne_peut_pas_lire_le_disque() -> None:
    with pytest.raises((ExpressionError, EvaluationError)):
        evaluate_expression("open('/etc/passwd')", {})


def test_evaluation_reste_rapide_sous_la_milliseconde_par_regle() -> None:
    engine = ConstitutionEngine()
    rule = make_rule()
    context = {"matching": {"score": 72}}
    engine.evaluate(rule, context)  # amorçage du cache de compilation
    started = time.perf_counter()
    for _ in range(200):
        engine.evaluate(rule, context)
    elapsed = time.perf_counter() - started
    assert elapsed / 200 < 0.001, f"évaluation trop lente : {elapsed / 200 * 1000:.3f} ms par règle"


# --- 2. Moteur : conformité, violations, absence de données -------------------


def test_regle_non_respectee_produit_une_violation() -> None:
    engine = ConstitutionEngine()
    result = engine.evaluate(make_rule(), {"matching": {"score": 10}}, entity_id="offre-1", entity_type="offer")
    assert result.passed is False
    assert result.status == "failed"
    assert result.severity == "error"
    assert result.entity_id == "offre-1"


def test_donnee_absente_ne_viole_pas_la_regle() -> None:
    """Une donnée manquante est « non évaluable », jamais une violation."""
    engine = ConstitutionEngine()
    result = engine.evaluate(make_rule(), {"matching": {}}, entity_id="offre-2", entity_type="offer")
    assert result.status == "not_evaluable"
    assert result.passed is False
    assert result.severity == "warning"
    assert result.remediation


def test_evaluate_all_utilise_les_regles_du_ruleset() -> None:
    engine = ConstitutionEngine()
    engine.register(make_rule(rule_id="matching.demo.one", expression="matching.score >= 10"))
    engine.register(make_rule(rule_id="matching.demo.two", expression="matching.score >= 90"))
    ruleset = make_ruleset(["matching.demo.one", "matching.demo.two"])
    results = engine.evaluate_all(ruleset, {"matching": {"score": 50}})
    assert [result.rule_id for result in results] == ["matching.demo.one", "matching.demo.two"]
    assert [result.passed for result in results] == [True, False]


def seed_active_rule(store: ConstitutionStore, rule_id: str, expression: str, *, severity: str = "error") -> None:
    """Crée puis approuve une règle (une règle non approuvée n'est pas effective)."""
    store.create_rule(
        {
            "rule_id": rule_id,
            "name": f"Règle {rule_id}",
            "domain": "matching",
            "expression": expression,
            "scope": ["offer"],
            "severity": severity,
        },
        actor="alice",
    )
    store.approve_rule(rule_id, approver="bob")


def test_check_conformance_calcule_un_score_honnete(tmp_path: Path) -> None:
    store = ConstitutionStore(tmp_path)
    seed_active_rule(store, "matching.demo.one", "matching.score >= 10")
    seed_active_rule(store, "matching.demo.two", "matching.score >= 90")
    seed_active_rule(store, "matching.demo.three", "matching.absent >= 1")
    store.create_ruleset(
        {
            "ruleset_id": "test.conformance",
            "name": "Jeu de conformité",
            "rules": ["matching.demo.one", "matching.demo.two", "matching.demo.three"],
        },
        actor="alice",
    )
    engine = ConstitutionEngine(store=store)
    report = engine.check_conformance(
        {"matching": {"score": 50}, ENTITY_ID_KEY: "e1", ENTITY_TYPE_KEY: "offer"},
        "test.conformance",
    )
    assert report.total_rules == 3
    assert report.passed == 1
    assert report.not_evaluable == 1
    assert report.compliance_score == 0.5
    assert [violation.rule_id for violation in report.violations] == ["matching.demo.two"]
    assert report.entity_id == "e1"
    assert report.entity_type == "offer"


def test_une_regle_non_approuvee_n_est_pas_effectivee(tmp_path: Path) -> None:
    """Gouvernance : un brouillon ne s'applique jamais aux entités."""
    store = ConstitutionStore(tmp_path)
    store.create_rule(
        {
            "rule_id": "matching.demo.brouillon",
            "name": "Règle en brouillon",
            "domain": "matching",
            "expression": "matching.score >= 10",
            "scope": ["offer"],
        },
        actor="alice",
    )
    store.create_ruleset(
        {"ruleset_id": "test.brouillon", "name": "Jeu brouillon", "rules": ["matching.demo.brouillon"]},
        actor="alice",
    )
    engine = ConstitutionEngine(store=store)
    report = engine.check_conformance({"matching": {"score": 50}}, "test.brouillon")
    assert report.total_rules == 0
    assert report.compliance_score == 1.0


def test_get_violations_filtre_par_severite_minimale() -> None:
    engine = ConstitutionEngine()
    engine.register(make_rule(rule_id="matching.demo.info", severity="info", expression="matching.score >= 90"))
    engine.register(make_rule(rule_id="matching.demo.critical", severity="critical", expression="matching.score >= 90"))
    context = {"matching": {"score": 50}}
    assert [violation.rule_id for violation in engine.get_violations(context, "warning")] == ["matching.demo.critical"]
    assert len(engine.get_violations(context, "info")) == 2


def test_contexte_construit_a_partir_d_une_offre_reelle() -> None:
    context = build_entity_context(
        "offer",
        {
            "id": "offre-1",
            "duration_months": 6,
            "start_date": "2027-02-01",
            "employment_type": "Stage",
            "scoring": {"score": 72, "weights": {"metier": 25, "competences": 20}},
        },
    )
    assert context["matching"]["score"] == 72
    assert context["matching"]["duration_months"] == 6
    assert context["matching"]["start_month"] == 2
    assert context["matching"]["contract_type"] == "stage"
    assert context[ENTITY_ID_KEY] == "offre-1"
    assert context[ENTITY_TYPE_KEY] == "offer"


def test_contexte_ne_fabrique_pas_de_donnee_absente() -> None:
    context = build_entity_context("offer", {"id": "offre-2"})
    assert "duration_months" not in context.get("matching", {})
    assert "freshness" not in context
    assert "privacy" not in context


# --- 3. Gouvernance : versions, approbation, rollback, signatures ------------


def test_creation_regle_exige_un_brouillon(store: ConstitutionStore) -> None:
    rule = store.create_rule(
        {
            "rule_id": "matching.demo.created",
            "name": "Règle créée",
            "domain": "matching",
            "expression": "matching.score >= 45",
            "scope": ["offer"],
        },
        actor="alice",
    )
    assert rule["status"] == "draft"
    assert rule["version"] == 1
    assert rule["approved_by"] is None


def test_creation_regle_invalide_refusee(store: ConstitutionStore) -> None:
    with pytest.raises(UserFacingError):
        store.create_rule(
            {
                "rule_id": "Matching.Inválide",
                "name": "",
                "domain": "inconnu",
                "expression": "matching.score >=",
                "scope": ["offre"],
            }
        )


def test_modification_cree_une_version_et_conserve_l_historique(store: ConstitutionStore) -> None:
    store.create_rule(
        {
            "rule_id": "matching.demo.version",
            "name": "Version 1",
            "domain": "matching",
            "expression": "matching.score >= 45",
            "scope": ["offer"],
        },
        actor="alice",
    )
    store.approve_rule("matching.demo.version", approver="bob")
    updated = store.update_rule(
        "matching.demo.version",
        {"expression": "matching.score >= 60"},
        actor="alice",
        change_note="Seuil durci",
    )
    assert updated["version"] == 2
    assert updated["status"] == "draft"
    versions = store.list_rule_versions("matching.demo.version")
    assert [version["version"] for version in versions] == [2, 1]
    assert versions[1]["status"] == "active"
    # La version approuvée reste effective tant que la nouvelle n'est pas approuvée.
    effective = store.effective_rule("matching.demo.version")
    assert effective["expression"] == "matching.score >= 45"


def test_approbation_exige_un_tiers_different_de_l_auteur(store: ConstitutionStore) -> None:
    store.create_rule(
        {
            "rule_id": "matching.demo.separation",
            "name": "Règle relue",
            "domain": "matching",
            "expression": "matching.score >= 45",
            "scope": ["offer"],
        },
        actor="alice",
    )
    with pytest.raises(UserFacingError):
        store.approve_rule("matching.demo.separation", approver="alice")
    approved = store.approve_rule("matching.demo.separation", approver="bob")
    assert approved["status"] == "active"
    assert approved["approved_by"] == "bob"


def test_approbation_deprecie_la_version_precedente(store: ConstitutionStore) -> None:
    store.create_rule(
        {
            "rule_id": "matching.demo.transition",
            "name": "Règle transition",
            "domain": "matching",
            "expression": "matching.score >= 45",
            "scope": ["offer"],
        },
        actor="alice",
    )
    store.approve_rule("matching.demo.transition", approver="bob")
    store.update_rule("matching.demo.transition", {"expression": "matching.score >= 60"}, actor="alice")
    store.approve_rule("matching.demo.transition", approver="bob")
    versions = {version["version"]: version for version in store.list_rule_versions("matching.demo.transition")}
    assert versions[1]["status"] == "deprecated"
    assert versions[2]["status"] == "active"


def test_deprecation_puis_archivage(store: ConstitutionStore) -> None:
    store.create_rule(
        {
            "rule_id": "matching.demo.retirement",
            "name": "Règie retirée",
            "domain": "matching",
            "expression": "matching.score >= 45",
            "scope": ["offer"],
        },
        actor="alice",
    )
    store.approve_rule("matching.demo.retirement", approver="bob")
    deprecated = store.deprecate_rule("matching.demo.retirement", actor="bob", reason="Seuil obsolète")
    assert deprecated["status"] == "deprecated"
    archived = store.archive_rule("matching.demo.retirement", actor="bob", reason="Période de transition terminée")
    assert archived["status"] == "archived"
    assert store.effective_rule("matching.demo.retirement") is None


def test_rollback_restaure_instantanement_une_version_anterieure(store: ConstitutionStore) -> None:
    store.create_rule(
        {
            "rule_id": "matching.demo.rollback",
            "name": "Version initiale",
            "domain": "matching",
            "expression": "matching.score >= 45",
            "scope": ["offer"],
        },
        actor="alice",
    )
    store.approve_rule("matching.demo.rollback", approver="bob")
    store.update_rule("matching.demo.rollback", {"expression": "matching.score >= 95"}, actor="alice")
    store.approve_rule("matching.demo.rollback", approver="bob")
    restored = store.rollback_rule("matching.demo.rollback", target_version=1, actor="carol", reason="Régression")
    assert restored["expression"] == "matching.score >= 45"
    assert restored["status"] == "active"
    assert restored["version"] == 3
    assert store.effective_rule("matching.demo.rollback")["expression"] == "matching.score >= 45"


def test_signature_detecte_une_alteration_de_contenu(store: ConstitutionStore) -> None:
    rule = store.create_rule(
        {
            "rule_id": "matching.demo.signature",
            "name": "Règle signée",
            "domain": "matching",
            "expression": "matching.score >= 45",
            "scope": ["offer"],
        },
        actor="alice",
    )
    assert store.verify_rule(rule) is True
    altered = {**rule, "expression": "matching.score >= 1"}
    assert store.verify_rule(altered) is False


def test_journal_audit_trace_les_actions(store: ConstitutionStore) -> None:
    store.create_rule(
        {
            "rule_id": "matching.demo.audit",
            "name": "Règle auditée",
            "domain": "matching",
            "expression": "matching.score >= 45",
            "scope": ["offer"],
        },
        actor="alice",
    )
    store.approve_rule("matching.demo.audit", approver="bob")
    actions = [entry["action"] for entry in store.list_audit(subject_id="matching.demo.audit")]
    assert "rule.created" in actions
    assert "rule.approved" in actions


def test_amorcage_du_referentiel_est_idempotent(tmp_path: Path) -> None:
    first = ConstitutionStore(tmp_path)
    count = len(first.list_rules())
    second = ConstitutionStore(tmp_path)
    assert len(second.list_rules()) == count
    assert len(second.list_rulesets()) == len(DEFAULT_RULESETS)


def test_regle_inconnue_leve_une_erreur_claire(store: ConstitutionStore) -> None:
    with pytest.raises(UserFacingError):
        store.update_rule("matching.demo.absente", {"expression": "matching.score >= 1"})


def test_jeu_de_regles_refuse_une_regle_inconnue(store: ConstitutionStore) -> None:
    with pytest.raises(UserFacingError):
        store.create_ruleset(
            {
                "ruleset_id": "test.inconnu",
                "name": "Jeu invalide",
                "rules": ["matching.demo.absente"],
            }
        )


def test_rollback_jeu_de_regles_restaure_la_version_precedente(store: ConstitutionStore) -> None:
    store.create_ruleset(
        {"ruleset_id": "test.rollback", "name": "Version 1", "rules": ["matching.score.minimum_match"]},
        actor="alice",
    )
    store.update_ruleset(
        "test.rollback",
        {"rules": ["matching.score.strong_match"], "name": "Version 2"},
        actor="alice",
    )
    restored = store.rollback_ruleset("test.rollback", target_version=1, actor="bob", reason="Retour arrière")
    assert restored["version"] == 3
    assert restored["rules"] == ["matching.score.minimum_match"]


# --- 4. Référentiel : les règles reprennent les seuils réels du code ---------


def test_le_referentiel_pose_les_regles_mirrant_le_code_existant() -> None:
    service_source = (ROOT / "career" / "service.py").read_text(encoding="utf-8")
    qualification_source = (ROOT / "career" / "offer_qualification.py").read_text(encoding="utf-8")
    scoring_source = (ROOT / "career" / "scoring.py").read_text(encoding="utf-8")
    assert "score >= 45" in service_source
    assert "minimum_duration_months: int = 6" in qualification_source
    assert "SCORING_WEIGHTS" in scoring_source


def test_chaque_reference_de_source_pointe_vers_un_code_reel() -> None:
    """Une règle « active » doit pointer une ligne de code qui existe vraiment."""
    for payload in DEFAULT_RULES:
        reference = payload.get("source_reference")
        if not reference:
            continue
        path, _, span = str(reference).partition(":")
        target = ROOT / path
        assert target.is_file(), f"{payload['rule_id']} : fichier inconnu {path}"
        lines = target.read_text(encoding="utf-8").splitlines()
        start, _, end = span.partition("-")
        first = int(start)
        last = int(end) if end else first
        assert 1 <= first <= last <= len(lines), f"{payload['rule_id']} : lignes hors fichier {span}"
        assert any(lines[index - 1].strip() for index in range(first, last + 1))


def test_les_seuils_mirres_existent_dans_le_code_source() -> None:
    """Chaque seuil repris dans la Constitution est bien celui du code."""
    from career.scoring import SCORING_WEIGHTS

    service_lines = (ROOT / "career" / "service.py").read_text(encoding="utf-8").splitlines()
    qualification_lines = (ROOT / "career" / "offer_qualification.py").read_text(encoding="utf-8").splitlines()
    assert "score >= 70" in service_lines[146]
    assert "score >= 45" in service_lines[148]
    assert "minimum_duration_months: int = 6" in qualification_lines[134]
    assert "1 <= minimum_duration_months <= 24" in qualification_lines[151]
    assert "allowed_start_months = [required_start_month] if required_start_month is not None else [1, 2, 3]" in qualification_lines[158]
    assert 'allowed_contract_types = ["stage", "cdd", "cdi", "vie"]' in qualification_lines[162]
    assert sum(SCORING_WEIGHTS.values()) == 100


def test_une_regle_sans_code_equivalent_reste_un_brouillon() -> None:
    """Aucune règle ne prétend décrire un code qui n'existe pas."""
    for payload in DEFAULT_RULES:
        if not payload.get("source_reference"):
            assert payload.get("status") == "draft", (
                f"{payload['rule_id']} : une règle sans référence de code doit rester une proposition."
            )


def test_chaque_regle_du_referentiel_est_valide() -> None:
    for payload in DEFAULT_RULES:
        problems = validate_rule_payload(payload)
        assert problems == [], f"{payload['rule_id']} : {problems}"


def test_les_regles_proposees_restent_en_brouillon() -> None:
    statuts = {payload["rule_id"]: payload.get("status") for payload in DEFAULT_RULES}
    assert statuts["freshness.certification.max_age_days"] == "draft"
    assert statuts["matching.score.minimum_match"] == "active"


def test_les_jeux_de_regles_par_defaut_pointent_des_regles_existantes() -> None:
    rule_ids = {payload["rule_id"] for payload in DEFAULT_RULES}
    for ruleset in DEFAULT_RULESETS:
        assert ruleset["rules"], "un jeu de règles vide ne sert à rien"
        for rule_id in ruleset["rules"]:
            assert rule_id in rule_ids


# --- 5. Audit et dérive --------------------------------------------------------


def test_audit_signale_les_signatures_valides(store: ConstitutionStore) -> None:
    report = build_audit_report(store)
    assert report["conformity"]["integrity"]["unsigned_rules"] == []
    assert report["conformity"]["rules"]["total"] >= len(DEFAULT_RULES)


def test_drift_signale_une_modification_sans_relecture(store: ConstitutionStore) -> None:
    store.create_rule(
        {
            "rule_id": "matching.demo.drift",
            "name": "Règle modifiée",
            "domain": "matching",
            "expression": "matching.score >= 45",
            "scope": ["offer"],
        },
        actor="alice",
    )
    store.approve_rule("matching.demo.drift", approver="bob")
    store.update_rule("matching.demo.drift", {"expression": "matching.score >= 50"}, actor="alice")
    drift = detect_drift(store)
    assert "matching.demo.drift" in drift["metrics"]["unreviewed_rules"]
    assert drift["metrics"]["unreviewed_modification_rate"] > 0
    assert drift["drifting"] is True


def test_drift_signale_une_couverture_de_tests_insuffisante(store: ConstitutionStore) -> None:
    drift = detect_drift(store)
    alert = next(item for item in drift["alerts"] if item["metric"] == "test_coverage")
    assert alert["value"] < 0.9
    assert alert["status"] == "alert"


def test_drift_signale_les_violations_critiques(store: ConstitutionStore) -> None:
    store.record_conformance(
        {
            "entity_id": "offre-1",
            "entity_type": "offer",
            "ruleset_id": "career.core",
            "ruleset_version": 1,
            "checked_at": "2026-10-22T00:00:00+00:00",
            "compliance_score": 0.5,
            "passed": 1,
            "warnings": 0,
            "errors": 0,
            "critical": 1,
            "violations": [
                {
                    "rule_id": "privacy.pii_fields.encrypted",
                    "entity_id": "offre-1",
                    "entity_type": "offer",
                    "severity": "critical",
                    "message": "Champ non chiffré",
                    "details": {},
                    "remediation": None,
                }
            ],
        }
    )
    drift = detect_drift(store)
    assert drift["metrics"]["critical_violations"] == 1
    alert = next(item for item in drift["alerts"] if item["metric"] == "critical_violations")
    assert alert["status"] == "alert"


def test_drift_signale_une_regle_non_revue_depuis_plus_d_un_an(store: ConstitutionStore) -> None:
    store.create_rule(
        {
            "rule_id": "matching.demo.old",
            "name": "Règle ancienne",
            "domain": "matching",
            "expression": "matching.score >= 45",
            "scope": ["offer"],
        },
        actor="alice",
    )
    ancient = (date.today() - timedelta(days=800)).isoformat()
    with store._connection() as connection:  # noqa: SLF001 - simulation d'une règle ancienne
        row = connection.execute(
            "SELECT payload_json FROM constitution_rules WHERE rule_id = ?", ("matching.demo.old",)
        ).fetchone()
        payload = json.loads(row["payload_json"])
        payload["created_at"] = ancient
        payload["updated_at"] = ancient
        payload["approved_at"] = ancient
        connection.execute(
            "UPDATE constitution_rules SET payload_json = ?, signature = ?, created_at = ?, updated_at = ? WHERE rule_id = ?",
            (canonical_json(payload), store.sign(payload), ancient, ancient, "matching.demo.old"),
        )
    drift = detect_drift(store)
    assert any(item.startswith("matching.demo.old") for item in drift["metrics"]["stale_reviews"])
    alert = next(item for item in drift["alerts"] if item["metric"] == "stale_review")
    assert alert["status"] == "alert"


def test_rapport_markdown_reste_lisible(store: ConstitutionStore) -> None:
    markdown = render_report_markdown(build_audit_report(store))
    assert "# Rapport de conformité" in markdown
    assert "## Dérive" in markdown
    assert "| Métrique |" in markdown


# --- 6. API HTTP ---------------------------------------------------------------


def test_api_creation_regle_demande_le_draft(tmp_path: Path) -> None:
    client = constitution_client(tmp_path)
    response = client.post(
        "/api/constitution/rules",
        json={
            "rule_id": "matching.demo.http",
            "name": "Règle HTTP",
            "domain": "matching",
            "expression": "matching.score >= 45",
            "scope": ["offer"],
            "created_by": "alice",
        },
    )
    assert response.status_code == 201
    assert response.json()["status"] == "draft"


def test_api_refuse_un_approbateur_identique_a_l_auteur(tmp_path: Path) -> None:
    client = constitution_client(tmp_path)
    client.post(
        "/api/constitution/rules",
        json={
            "rule_id": "matching.demo.http2",
            "name": "Règle HTTP 2",
            "domain": "matching",
            "expression": "matching.score >= 45",
            "scope": ["offer"],
            "created_by": "alice",
        },
    )
    refused = client.post("/api/constitution/rules/matching.demo.http2/approve", json={"approved_by": "alice"})
    assert refused.status_code == 400
    accepted = client.post("/api/constitution/rules/matching.demo.http2/approve", json={"approved_by": "bob"})
    assert accepted.status_code == 200
    assert accepted.json()["status"] == "active"


def test_api_liste_filtre_par_domaine_et_par_statut(tmp_path: Path) -> None:
    client = constitution_client(tmp_path)
    matching = client.get("/api/constitution/rules", params={"domain": "matching"}).json()
    assert matching["count"] >= 1
    assert all(rule["domain"] == "matching" for rule in matching["rules"])
    drafts = client.get("/api/constitution/rules", params={"status": "draft"}).json()
    assert all(rule["status"] == "draft" for rule in drafts["rules"])


def test_api_detail_regle_expose_historique_et_signature(tmp_path: Path) -> None:
    client = constitution_client(tmp_path)
    client.post(
        "/api/constitution/rules",
        json={
            "rule_id": "matching.demo.detail",
            "name": "Règle détaillée",
            "domain": "matching",
            "expression": "matching.score >= 45",
            "scope": ["offer"],
        },
    )
    detail = client.get("/api/constitution/rules/matching.demo.detail").json()
    assert detail["rule"]["rule_id"] == "matching.demo.detail"
    assert detail["signature_valid"] is True
    assert len(detail["versions"]) == 1


def test_api_regle_inconnue_renvoie_une_erreur_claire(tmp_path: Path) -> None:
    client = constitution_client(tmp_path)
    response = client.get("/api/constitution/rules/matching.demo.absente")
    assert response.status_code == 400
    assert "introuvable" in response.json()["detail"]


def test_api_modification_cree_une_nouvelle_version(tmp_path: Path) -> None:
    client = constitution_client(tmp_path)
    client.post(
        "/api/constitution/rules",
        json={
            "rule_id": "matching.demo.patch",
            "name": "Règle patchée",
            "domain": "matching",
            "expression": "matching.score >= 45",
            "scope": ["offer"],
        },
    )
    response = client.patch(
        "/api/constitution/rules/matching.demo.patch",
        json={"expression": "matching.score >= 60", "change_note": "Seuil durci", "actor": "alice"},
    )
    assert response.status_code == 200
    assert response.json()["version"] == 2
    assert response.json()["status"] == "draft"


def test_api_validation_donne_un_rapport_de_conformite(tmp_path: Path) -> None:
    client = constitution_client(tmp_path)
    response = client.post(
        "/api/constitution/validate",
        json={
            "entity_id": "offre-http",
            "entity_type": "offer",
            "entity": {"duration_months": 6, "scoring": {"score": 80, "weights": {"metier": 100}}},
        },
    )
    assert response.status_code == 200
    report = response.json()["report"]
    assert report["entity_id"] == "offre-http"
    assert 0.0 <= report["compliance_score"] <= 1.0
    assert response.json()["results"]


def test_api_rapport_entite_sans_historique_renvoie_une_erreur(tmp_path: Path) -> None:
    client = constitution_client(tmp_path)
    response = client.get("/api/constitution/report/offre-inconnue")
    assert response.status_code == 400
    assert "Aucune conformité" in response.json()["detail"]


def test_api_audit_et_drift_sont_disponibles(tmp_path: Path) -> None:
    client = constitution_client(tmp_path)
    audit = client.get("/api/constitution/audit")
    assert audit.status_code == 200
    assert "# Rapport de conformité" in audit.json()["markdown"]
    drift = client.get("/api/constitution/drift")
    assert drift.status_code == 200
    assert "alerts" in drift.json()


def test_api_generation_de_tests_ecrit_le_contenu(tmp_path: Path) -> None:
    client = constitution_client(tmp_path)
    response = client.post("/api/constitution/test/generate", json={"write": False})
    assert response.status_code == 200
    assert response.json()["rules"] >= 1
    assert "test_rule_expression_is_evaluable" in response.json()["content"]


def test_api_expression_check_et_preview(tmp_path: Path) -> None:
    client = constitution_client(tmp_path)
    check = client.post("/api/constitution/expression/check", json={"expression": "matching.score >= 45"})
    assert check.json()["valid"] is True
    invalid = client.post("/api/constitution/expression/check", json={"expression": "matching.score >="})
    assert invalid.json()["valid"] is False
    preview = client.post(
        "/api/constitution/expression/preview",
        json={"expression": "matching.score >= 45", "context": {"matching": {"score": 80}}},
    )
    assert preview.json()["value"] is True


def test_api_creation_jeu_de_regles_et_rollback(tmp_path: Path) -> None:
    client = constitution_client(tmp_path)
    created = client.post(
        "/api/constitution/rulesets",
        json={"ruleset_id": "test.http", "name": "Jeu HTTP", "rules": ["matching.score.minimum_match"]},
    )
    assert created.status_code == 201
    rollback = client.post("/api/constitution/rollback/test.http", json={"target_version": 1})
    assert rollback.status_code == 200
    assert rollback.json()["version"] == 2


def test_api_validation_une_offre_stockee_par_son_identifiant(tmp_path: Path) -> None:
    """Intégration : la Constitution contrôle une offre réellement importée."""
    service = CareerService(tmp_path)
    service.update_profile({"display_name": "Personne Démo", "skills": "Excel", "languages": "Français"})
    service.import_job(
        {
            "company": "Banque de Démo",
            "title": "Stagiaire M&A",
            "source_name": "manual",
            "source_id": "REF-DEMO-2027-014",
            "official_url": "https://careers.example.test/jobs/demo-42",
            "duration_months": 6,
            "start_date": "2027-02-01",
            "employment_type": "Stage",
            "requirements": "Modélisation LBO avancée.",
        }
    )
    job = service.list_jobs()[0]
    app = FastAPI()
    app.include_router(create_career_router(service))
    client = TestClient(app)
    response = client.post(
        "/api/constitution/validate",
        json={"entity_id": job["id"], "entity_type": "offer", "job_id": job["id"]},
    )
    assert response.status_code == 200
    report = response.json()["report"]
    assert report["entity_id"] == job["id"]
    evaluated = {result["rule_id"] for result in response.json()["results"]}
    assert "matching.duration_months.minimum" in evaluated


# --- 7. Tests générés depuis les règles ----------------------------------------


def test_tests_generes_sont_executables(tmp_path: Path) -> None:
    store = ConstitutionStore(tmp_path)
    content = generate_rule_tests([Rule.from_dict(payload) for payload in store.list_rules(status="active")])
    target = tmp_path / "test_constitution_generated.py"
    target.write_text(content, encoding="utf-8")
    completed = subprocess.run(
        [sys.executable, "-m", "pytest", "-q", str(target)],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert completed.returncode == 0, completed.stdout + completed.stderr


def test_tests_generes_couvrent_chaque_regle_active(tmp_path: Path) -> None:
    store = ConstitutionStore(tmp_path)
    active = store.list_rules(status="active")
    content = generate_rule_tests([Rule.from_dict(payload) for payload in active])
    for payload in active:
        assert payload["rule_id"] in content


# --- 8. Ligne de commande -------------------------------------------------------


def test_cli_valide_le_referentiel(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    from career import constitution as constitution_module

    code = constitution_module.main(["--base-dir", str(tmp_path), "validate", "--all"])
    assert code == 0
    assert "Constitution valide" in capsys.readouterr().out


def test_cli_signale_une_regle_creee_localement(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    from career import constitution as constitution_module

    store = ConstitutionStore(tmp_path)
    store.create_rule(
        {
            "rule_id": "matching.demo.cli",
            "name": "Règle CLI",
            "domain": "matching",
            "expression": "matching.score >= 45",
            "scope": ["offer"],
        },
        actor="alice",
    )
    code = constitution_module.main(["--base-dir", str(tmp_path), "validate", "--all"])
    output = capsys.readouterr().out
    assert code == 0
    assert "Constitution valide" in output


def test_cli_genere_les_tests_depuis_les_regles(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    from career import constitution as constitution_module

    code = constitution_module.main(["--base-dir", str(tmp_path), "test", "--generate-tests"])
    assert code == 0
    assert "test_rule_expression_is_evaluable" in capsys.readouterr().out


def test_cli_controle_une_entite_fournie(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    from career import constitution as constitution_module

    entity = tmp_path / "entite.json"
    entity.write_text(
        json.dumps(
            {
                "id": "offre-cli",
                "entity_type": "offer",
                "duration_months": 6,
                "scoring": {"score": 80, "weights": {"metier": 100}},
            }
        ),
        encoding="utf-8",
    )
    code = constitution_module.main(["--base-dir", str(tmp_path), "check", "--all-entities", "--entity", str(entity)])
    output = capsys.readouterr().out
    assert code == 0
    assert "offre-cli" in output


# --- 9. Interface locale --------------------------------------------------------


def test_interface_constitution_est_integree_au_html() -> None:
    html = UI_HTML.read_text(encoding="utf-8")
    assert 'id="view-constitution"' in html
    assert 'data-view="constitution"' in html
    assert "/career-static/js/constitution.js" in html
    assert 'id="constitution-editor"' in html
    assert 'id="constitution-graph"' in html
    assert 'id="constitution-dashboard"' in html
    assert 'id="constitution-history"' in html
    assert 'id="constitution-audit"' in html


def test_interface_constitution_ne_contacte_aucun_service_distant() -> None:
    source = UI_SCRIPT.read_text(encoding="utf-8")
    urls = [url for url in re.findall(r"https?://[^\s\"']+", source) if "www.w3.org/2000/svg" not in url]
    assert urls == [], f"l'interface ne doit contacter que l'origine locale : {urls}"
    assert "fetch(" in source


def _node() -> str:
    executable = shutil.which("node")
    if executable:
        return executable
    for candidate in ("/usr/local/bin/node", "/opt/homebrew/bin/node"):
        if Path(candidate).is_file():
            return candidate
    pytest.skip("Node absent : impossible d'exécuter les gardes JavaScript")


@pytest.mark.js
def test_fonctions_pures_de_l_interface_sont_verifiables_hors_navigateur() -> None:
    script = f"""
const assert = require("assert");
const constitution = require({json.dumps(str(UI_SCRIPT))});
assert.deepStrictEqual(constitution.collectIdentifiers("matching.score >= 45"), ["matching.score"]);
assert.deepStrictEqual(constitution.checkSyntax("matching.score >= 45"), {{ valid: true, error: null }});
assert.strictEqual(constitution.checkSyntax("matching.score >=").valid, false);
assert.strictEqual(constitution.checkSyntax("(a").valid, false);
assert.strictEqual(constitution.formatScore(0.75), "75,0 %");
assert.strictEqual(constitution.severityLabel("critical"), "Critique");
assert.strictEqual(constitution.statusLabel("draft"), "Brouillon");
assert.strictEqual(constitution.describeAction("rule.approved"), "Règle approuvée");
const changes = constitution.diffVersions(
  {{ name: "A", domain: "matching", expression: "x >= 1", severity: "error", status: "draft", scope: ["offer"] }},
  {{ name: "B", domain: "matching", expression: "x >= 2", severity: "error", status: "draft", scope: ["offer", "profile"] }}
);
assert.strictEqual(changes.length, 3);
const graph = constitution.buildGraphModel(
  [{{ rule_id: "matching.demo", domain: "matching", scope: ["offer"], status: "active", severity: "error" }}],
  [{{ rule_id: "matching.demo", passed: true, status: "passed", severity: "info" }}]
);
assert.strictEqual(graph.nodes.length, 4);
assert.strictEqual(graph.edges.length, 3);
const suggestions = constitution.suggestCompletions("matching.sc", 10, constitution.CONSTITUTION_IDENTIFIER_CATALOG);
assert.ok(suggestions.some((item) => item.path === "matching.score"));
"""
    completed = subprocess.run([_node(), "-e", script], capture_output=True, text=True, timeout=20)
    assert completed.returncode == 0, completed.stderr


# --- 10. Contrat public ---------------------------------------------------------


def test_le_moteur_expose_le_contrat_attendu() -> None:
    engine = ConstitutionEngine()
    for method in ("evaluate", "evaluate_all", "check_conformance", "get_violations"):
        assert callable(getattr(engine, method))


def test_le_store_expose_le_contrat_attendu(tmp_path: Path) -> None:
    store = ConstitutionStore(tmp_path)
    for method in (
        "create_rule",
        "get_rule",
        "list_rules",
        "update_rule",
        "approve_rule",
        "deprecate_rule",
        "create_ruleset",
        "get_ruleset",
        "update_ruleset",
        "rollback_ruleset",
        "record_conformance",
        "list_audit",
    ):
        assert callable(getattr(store, method))


def test_horodatage_utc_utilise_dans_les_traces(tmp_path: Path) -> None:
    store = ConstitutionStore(tmp_path)
    entries = store.list_audit(limit=1)
    assert entries
    assert entries[0]["occurred_at"].endswith("+00:00")
    assert datetime.fromisoformat(entries[0]["occurred_at"]).tzinfo == timezone.utc
