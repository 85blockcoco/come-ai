"""Tests automatisés du laboratoire d'évaluations.

Ces tests ne mesurent pas un modèle : ils vérifient que le runner détecte
correctement les défauts, produit des rapports et signale les régressions.
Exécution : python -m pytest evals/tests -q
"""

from __future__ import annotations

import json
import copy
from pathlib import Path
from types import SimpleNamespace

import pytest

from evals.checks import REGISTRY, run_checks
from evals.report import render_compare_report, render_run_report
from evals.runner import (
    FAULT_MODES,
    FaultInjectionTarget,
    SimulatedTarget,
    TargetResult,
    compare_runs,
    execute_case,
    run_suite,
)
from evals.schema import CaseError, _validate_case, load_cases, summarize_suite


# ----------------------------------------------------------- 1. chargement

def test_suite_charge_60_cas_repartis():
    cases = load_cases()
    assert len(cases) == 60
    summary = summarize_suite(cases)
    assert summary["by_category"] == {
        "conversation": 10, "documents": 15, "finance": 15, "memoire": 20,
    }
    assert summary["supported"] + summary["future"] == 60


def test_chaque_cas_a_les_champs_requis():
    for case in load_cases():
        assert case.id and case.title and case.objective
        assert case.acceptance and case.failure_conditions
        assert case.required_features


def test_suite_reproductible_deux_chargements_identiques():
    first = [c.raw for c in load_cases()]
    second = [c.raw for c in load_cases()]
    assert first == second


# ------------------------------------------ 2. détection d'un résultat faux

@pytest.mark.parametrize("mode,expected_min_failures", [
    ("wrong_answer", 1),
    ("invented_fact", 1),
    ("bad_citation", 1),
    ("lost_fact", 1),
    ("wrong_structure", 1),
    ("wrong_tool", 1),
    ("invalid_plan", 1),
    ("quota_overrun", 1),
    ("silent_failure", 1),
    ("fabricated_error", 1),
])
def test_chaque_famille_de_faute_est_detectee(mode, expected_min_failures):
    target = FaultInjectionTarget(mode)
    run = run_suite(target, persist=False)
    assert run["metrics"]["cases_failed"] >= expected_min_failures


def test_reponse_incorrecte_detectee_sur_cas_financier():
    cases = {c.id: c for c in load_cases()}
    result = execute_case(cases["FIN-001"], FaultInjectionTarget("wrong_answer"))
    assert result.status == "executed" and result.passed is False
    failed = [c["check"] for c in result.checks if not c["ok"]]
    assert "numeric_close" in failed


def test_citation_inventee_detectee():
    cases = {c.id: c for c in load_cases()}
    result = execute_case(cases["MEM-002"], FaultInjectionTarget("bad_citation"))
    assert result.passed is False
    details = " ".join(c["detail"] for c in result.checks if not c["ok"])
    assert "SOURCE_INCONNUE_404" in details


def test_cible_simulee_produit_zero_echec():
    # Auto-test du runner : la cible idéale doit passer tous les cas exécutables.
    run = run_suite(SimulatedTarget(), persist=False)
    assert run["metrics"]["cases_failed"] == 0
    assert run["metrics"]["cases_executed"] == 49


# ------------------------------------------------------- 3. détection de régression

def test_compare_detecte_les_regressions():
    baseline = run_suite(SimulatedTarget(), persist=False)
    candidate = run_suite(FaultInjectionTarget("wrong_answer"), persist=False)
    comparison = compare_runs(baseline, candidate)
    assert comparison["has_regressions"] is True
    assert len(comparison["regressions"]) >= 1
    ids = {r["case_id"] for r in comparison["regressions"]}
    assert "FIN-001" in ids


def test_compare_deux_runs_identiques_signale_zero_regression():
    baseline = run_suite(SimulatedTarget(), persist=False)
    candidate = run_suite(SimulatedTarget(), persist=False)
    comparison = compare_runs(baseline, candidate)
    assert comparison["has_regressions"] is False
    assert comparison["improvements"] == []


def test_compare_signale_une_amelioration():
    bad = run_suite(FaultInjectionTarget("wrong_answer"), persist=False)
    good = run_suite(SimulatedTarget(), persist=False)
    comparison = compare_runs(bad, good)
    assert comparison["has_regressions"] is False
    assert len(comparison["improvements"]) >= 1


# ---------------------------------------- 4. gestion d'un cas non pris en charge

def test_cas_futur_marque_non_supporte_et_non_echoue():
    cases = {c.id: c for c in load_cases()}
    result = execute_case(cases["MEM-016"], SimulatedTarget())
    assert result.status == "unsupported"
    assert result.passed is None
    assert "memory.semantic_search" in result.reason


def test_les_cas_futurs_ne_comptent_pas_dans_le_taux():
    run = run_suite(SimulatedTarget(), persist=False)
    m = run["metrics"]
    assert m["cases_unsupported"] == 11
    assert m["cases_executed"] + m["cases_unsupported"] == 60
    # Le taux ne porte que sur les exécutables.
    assert m["pass_rate_executable"] == 1.0


# ------------------------------------------------------- 5. production du rapport

def test_rapport_de_run_contient_les_metriques():
    run = run_suite(SimulatedTarget(), label="test", persist=False)
    report = render_run_report(run)
    assert "Cas exécutés" in report
    assert "Taux de réussite" in report
    assert "Exactitude des calculs" in report
    assert "Durée totale" in report
    assert "cible simulée" in report.lower()


def test_rapport_de_comparaison_signale_les_regressions():
    baseline = run_suite(SimulatedTarget(), persist=False)
    candidate = run_suite(FaultInjectionTarget("invalid_plan"), persist=False)
    report = render_compare_report(compare_runs(baseline, candidate))
    assert "Régressions" in report


def test_run_persiste_un_fichier_json(tmp_path):
    run = run_suite(SimulatedTarget(), persist=True, runs_dir=tmp_path)
    path = Path(run["_path"])
    assert path.exists()
    payload = json.loads(path.read_text(encoding="utf-8"))
    assert payload["schema"] == "come-evals-run/1"
    assert len(payload["results"]) == 60


# ------------------------------------------------------- 6. reproductibilité

def test_reproductibilite_metrics_stables():
    first = run_suite(SimulatedTarget(), persist=False)
    second = run_suite(SimulatedTarget(), persist=False)
    for key in ("cases_total", "cases_executed", "cases_passed", "cases_failed",
                "cases_unsupported", "pass_rate_executable"):
        assert first["metrics"][key] == second["metrics"][key]
    assert [r["case_id"] for r in first["results"]] == [r["case_id"] for r in second["results"]]
    assert [r["passed"] for r in first["results"]] == [r["passed"] for r in second["results"]]


def test_familles_de_fautes_couvertes():
    assert set(FAULT_MODES) == {
        "wrong_answer", "invented_fact", "bad_citation", "lost_fact",
        "wrong_structure", "wrong_tool", "invalid_plan", "quota_overrun",
        "silent_failure", "fabricated_error",
    }


# ------------------------------------------------- garde-fous d'intégrité

def test_validateur_inconnu_signale_comme_echec():
    case = {
        "input": {}, "expected": {},
        "acceptance": [{"check": "validateur_qui_n_existe_pas"}],
    }
    results = run_checks(case, {})
    assert results[0]["ok"] is False
    assert "inconnu" in results[0]["detail"]


def test_suite_invalide_rejetee(tmp_path):
    (tmp_path / "bad.json").write_text(json.dumps([
        {"id": "X-1", "category": "inconnue", "title": "t", "objective": "t",
         "status": "supported", "required_features": ["x"], "severity": "minor",
         "input": {}, "expected": {}, "acceptance": [{"check": "no_error"}],
         "failure_conditions": ["t"]}
    ]), encoding="utf-8")
    with pytest.raises(CaseError):
        load_cases(tmp_path)


def test_registry_des_validateurs_complet():
    attendus = {
        "exact_value", "numeric_close", "contains_all", "not_contains",
        "citations_valid", "no_hallucinated_facts", "facts_present",
        "structure_valid", "tools_called", "tools_not_called", "plan_valid",
        "budget_respected", "error_signaled", "no_error",
    }
    assert attendus <= set(REGISTRY)


# ------------------------------------------------- audit d'acceptation fermé

def _case(case_id="FIN-001"):
    return next(c for c in load_cases() if c.id == case_id)


class _RealTarget:
    name = "test-adapter"
    execution_kind = "real"

    def __init__(self, observation, *, supports=True):
        self.observation = observation
        self.supported_features = frozenset(_case().required_features)
        self.supports = supports
        self.called = False

    def supports_case(self, case):
        return self.supports

    def run(self, case):
        self.called = True
        return self.observation


@pytest.mark.parametrize("criterion", [
    {"check": "structure_valid", "schema": {}},
    {"check": "structure_valid", "schema": {"x": "anything"}},
    {"check": "structure_valid", "schema": {"x": []}},
    {"check": "budget_respected", "max": {}},
    {"check": "numeric_close", "path": "structured.x", "value": float("nan")},
    {"check": "numeric_close", "path": "structured.x", "value": 1, "tolerance": -1},
    {"check": "contains_all", "path": "answer", "values": []},
    {"check": "citations_valid", "min_citations": 0},
    {"check": "exact_value", "path": "structured..x", "value": None},
])
def test_critere_inefficace_ou_invalide_rejete(criterion):
    raw = copy.deepcopy(_case().raw)
    raw["acceptance"] = [criterion]
    with pytest.raises(CaseError):
        _validate_case(raw, "audit")
    assert run_checks(raw, {})[0]["ok"] is False


def test_aucun_critere_ne_peut_reussir_par_vacuite():
    assert run_checks({"acceptance": []}, {})[0]["ok"] is False


def test_citation_vide_rejetee():
    case = _case("MEM-002")
    observation = copy.deepcopy(case.expected)
    observation["citations"][0]["quote"] = ""
    assert execute_case(case, _ObservationTarget(observation)).passed is False


class _ObservationTarget:
    name = "observation-test"
    execution_kind = "simulated"

    def __init__(self, observation):
        self.observation = observation

    def run(self, case):
        return self.observation


@pytest.mark.parametrize("usage", [
    {"api_calls": -1}, {"api_calls": True}, {"api_calls": float("nan")},
    {"api_calls": float("inf")},
])
def test_budget_invalide_ne_passe_pas(usage):
    checks = run_checks({"input": {}, "expected": {}, "acceptance": [
        {"check": "budget_respected", "max": {"api_calls": 2}}
    ]}, {"usage": usage})
    assert checks[0]["ok"] is False


def test_erreur_cible_fait_echouer_meme_sans_no_error():
    case = _case()
    observation = copy.deepcopy(case.expected)
    observation["error"] = "Erreur explicite"
    result = execute_case(case, _ObservationTarget(observation))
    assert result.passed is False and result.outcome == "incorrect"
    assert any(c["check"] == "target_no_error" and not c["ok"] for c in result.checks)


@pytest.mark.parametrize("observation", [{}, None, {"error": None}])
def test_observation_incomplete_ne_passe_pas(observation):
    result = execute_case(_case("CONV-007"), _ObservationTarget(observation))
    assert result.passed is False and result.outcome == "execution_error"
    assert result.checks


def test_exception_cible_fail_closed_sans_message_ni_donnees():
    class CrashingTarget(SimulatedTarget):
        def run(self, case):
            raise ValueError("private-marker-sensitive-output")

    run = run_suite(CrashingTarget(), [_case()], persist=False)
    result = run["results"][0]
    assert result["outcome"] == "execution_error"
    assert "private-marker" not in json.dumps(run)
    assert run["metrics"]["calculation_accuracy"]["checks_total"] == 1
    assert run["metrics"]["calculation_accuracy"]["rate"] == 0.0


@pytest.mark.parametrize("supports,features", [
    (True, frozenset()), (False, frozenset({"local_arithmetic"})),
])
def test_capacite_absente_non_executee_et_non_notee(supports, features):
    target = _RealTarget(_case().expected, supports=supports)
    target.supported_features = features
    run = run_suite(target, [_case()], persist=False)
    assert target.called is False
    assert run["metrics"]["cases_unsupported"] == 1
    assert run["metrics"]["cases_failed"] == 0
    assert run["metrics"]["real_pass_rate"] is None


def test_resultat_simule_de_cible_reelle_rejete():
    target = _RealTarget(TargetResult(copy.deepcopy(_case().expected), status="simulated"))
    result = execute_case(_case(), target)
    assert result.passed is False and result.outcome == "execution_error"
    assert result.execution_kind == "real"


def test_targetresult_trace_et_statut_reel_conserves():
    trace = [{"tool": "synthetic-contract-test", "status": "done"}]
    target = _RealTarget(TargetResult(copy.deepcopy(_case().expected), trace=trace))
    result = execute_case(_case(), target)
    assert result.passed is True and result.outcome == "real"
    assert result.to_dict()["trace"] == trace


def test_nom_de_cible_ne_determine_pas_provenance():
    target = _RealTarget(copy.deepcopy(_case().expected))
    target.name = "simulated-looking-name"
    run = run_suite(target, [_case()], persist=False)
    assert run["execution_kind"] == "real"
    assert "cible simulée" not in render_run_report(run).lower()
    simulated = run_suite(SimulatedTarget(), [_case()], persist=False)
    assert simulated["metrics"]["real_pass_rate"] is None
    with pytest.raises(ValueError, match="provenance"):
        compare_runs(simulated, run)


def test_provenance_inconnue_non_comparee():
    target = SimpleNamespace(name="simulated", run=lambda case: copy.deepcopy(case.expected))
    run = run_suite(target, [_case()], persist=False)
    assert run["metrics"]["real_pass_rate"] is None
    assert "Provenance inconnue" in render_run_report(run)
    with pytest.raises(ValueError, match="provenance"):
        compare_runs(run, run)


def test_core_contractuel_ne_prouve_pas_verification_application():
    summary = summarize_suite(load_cases())
    assert summary["total"] == 60
    assert summary["supported"] == 49
    assert summary["application_verified"] == 0


def test_suite_independante_chargee_et_cli_cases_dir_respecte(tmp_path, capsys):
    from evals.__main__ import main
    path = tmp_path / "isolated.json"
    path.write_text(json.dumps([_case().raw]), encoding="utf-8")
    assert len(load_cases(path)) == 1
    assert main(["--cases-dir", str(path), "run", "--no-persist", "--strict"]) == 0
    assert "| Cas au total | 1 |" in capsys.readouterr().out


def test_exact_value_distingue_booleen_et_entier_meme_imbriques():
    raw = {"acceptance": [{"check": "exact_value", "path": "structured", "value": {"x": True}}]}
    assert run_checks(raw, {"structured": {"x": 1}})[0]["ok"] is False


def test_champ_absent_dans_liste_ne_devient_pas_null():
    raw = {"acceptance": [{"check": "exact_value", "path": "structured.items.x", "value": [None]}]}
    assert run_checks(raw, {"structured": {"items": [{}]}})[0]["ok"] is False


def test_plan_ids_et_dependances_obligatoires():
    raw = {"input": {"known_tools": ["inspect_file"]}, "acceptance": [{"check": "plan_valid"}]}
    for step in ({"tool": "inspect_file", "arguments": {}},
                 {"step_id": "s1", "tool": "inspect_file", "arguments": {}, "depends_on": "s1"}):
        assert run_checks(raw, {"plan": [step]})[0]["ok"] is False


def test_erreur_attendue_ne_peut_produire_structure_vide():
    raw = {"acceptance": [{"check": "error_signaled"}]}
    assert run_checks(raw, {"error": "Erreur", "answer": None, "structured": {}})[0]["ok"] is False


def test_consommation_declaree_ne_devient_pas_zero_mesure():
    run = run_suite(SimulatedTarget(), [_case("CONV-006")], persist=False)
    assert run["resources"]["declared_usage"]["api_calls"] == 2
    report = render_run_report(run)
    assert "| Appels API | 2 | déclaré" in report
    assert "aucun réseau" not in report


def test_comparaison_signale_perte_de_couverture():
    baseline = run_suite(SimulatedTarget(), [_case()], persist=False)
    candidate = copy.deepcopy(baseline)
    candidate["results"][0].update(status="unsupported", passed=None)
    comparison = compare_runs(baseline, candidate)
    assert comparison["has_coverage_loss"] is True
    assert comparison["coverage_losses"] == ["FIN-001"]
    assert "Perte de couverture" in render_compare_report(comparison)


def test_run_refuse_ids_dupliques():
    with pytest.raises(ValueError, match="dupliqués"):
        run_suite(SimulatedTarget(), [_case(), _case()], persist=False)


@pytest.mark.parametrize("case_id,key,value", [
    ("DOC-001", "sheets", []),
    ("DOC-003", "missing", {}),
    ("DOC-004", "data_types", {"quantite": "int64"}),
    ("DOC-008", "rows", 250000),
    ("MEM-013", "selected_fact", "4 avenue Verte"),
])
def test_detail_structurel_incomplet_ou_faux_detecte(case_id, key, value):
    case = _case(case_id)
    observation = copy.deepcopy(case.expected)
    observation["structured"][key] = value
    assert execute_case(case, _ObservationTarget(observation)).passed is False


def test_citations_dupliquees_ne_remplacent_pas_deux_sources():
    case = _case("MEM-004")
    observation = copy.deepcopy(case.expected)
    observation["citations"] = [observation["citations"][0]] * 2
    assert execute_case(case, _ObservationTarget(observation)).passed is False


def test_creation_plan_sans_confirmation_detectee():
    case = _case("CONV-005")
    observation = copy.deepcopy(case.expected)
    observation["plan"][-1]["requires_confirmation"] = False
    assert execute_case(case, _ObservationTarget(observation)).passed is False


def test_exception_controle_capacite_ne_devient_pas_unsupported():
    target = _RealTarget(_case().expected)

    def bad_support(case):
        raise RuntimeError("sensitive-capability-marker")

    target.supports_case = bad_support
    run = run_suite(target, [_case()], persist=False)
    assert run["metrics"]["cases_failed"] == 1
    assert run["metrics"]["cases_unsupported"] == 0
    assert run["results"][0]["outcome"] == "execution_error"
    assert "sensitive-capability-marker" not in json.dumps(run)


def test_cli_strict_sans_couverture_refuse_run(tmp_path, monkeypatch, capsys):
    import evals.__main__ as cli
    path = tmp_path / "case.json"
    path.write_text(json.dumps([_case().raw]), encoding="utf-8")
    target = _RealTarget(_case().expected, supports=False)
    monkeypatch.setattr(cli, "_build_target", lambda spec: target)
    assert cli.main(["--cases-dir", str(path), "run", "--no-persist", "--strict"]) == 2
    captured = capsys.readouterr()
    assert "aucun cas exécuté" in captured.err
    assert "| Taux de réussite réel | n/a |" in captured.out


def test_cli_list_ne_presente_pas_contrats_comme_capacites_application(capsys):
    from evals.__main__ import main
    assert main(["list"]) == 0
    output = capsys.readouterr().out
    assert "49 contrats supported" in output
    assert "0 déclarés vérifiés" in output


@pytest.mark.parametrize("section", ["input", "expected", "acceptance"])
def test_comparaison_refuse_contrat_modifie_sous_meme_id(section):
    raw = copy.deepcopy(_case().raw)
    if section == "input":
        raw["input"]["amounts"][0] += 1
    elif section == "expected":
        raw["expected"]["structured"]["total"] += 1
    else:
        raw["acceptance"][0]["value"] += 1
    modified = _validate_case(raw, "modified")
    baseline = run_suite(SimulatedTarget(), [_case()], persist=False)
    candidate = run_suite(SimulatedTarget(), [modified], persist=False)
    assert baseline["suite_hash"] != candidate["suite_hash"]
    with pytest.raises(ValueError, match="contrat modifié"):
        compare_runs(baseline, candidate)


def test_comparaison_cli_contrat_modifie_refuse_meme_en_strict(tmp_path, capsys):
    from evals.__main__ import main
    raw = copy.deepcopy(_case().raw)
    raw["acceptance"][0]["value"] += 1
    baseline = run_suite(SimulatedTarget(), [_case()], persist=False)
    candidate = run_suite(SimulatedTarget(), [_validate_case(raw, "modified")], persist=False)
    paths = [tmp_path / "baseline.json", tmp_path / "candidate.json"]
    for path, run in zip(paths, [baseline, candidate]):
        path.write_text(json.dumps(run), encoding="utf-8")
    assert main(["compare", str(paths[0]), str(paths[1]), "--strict"]) == 2
    assert "Aucune régression détectée" not in capsys.readouterr().out
