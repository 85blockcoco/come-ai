"""Production d'un rapport Markdown lisible à partir d'un run ou d'une comparaison."""

from __future__ import annotations

from typing import Any


def _rate(value: Any) -> str:
    if value is None:
        return "n/a"
    return f"{value * 100:.1f} %"


def render_run_report(run: dict[str, Any]) -> str:
    m = run["metrics"]
    r = run["resources"]
    lines: list[str] = []
    lines.append(f"# Rapport d'évaluation Côme AI — run `{run['run_id']}`")
    lines.append("")
    if run.get("label"):
        lines.append(f"**Label :** {run['label']}")
        lines.append("")
    lines.append(f"- **Cible exécutée :** `{run['target']}`")
    execution_kind = run.get("execution_kind", "unknown")
    lines.append(f"- **Provenance :** `{execution_kind}`")
    lines.append(f"- **Horodatage (UTC) :** {run['timestamp_utc']}")
    lines.append(f"- **Environnement :** Python {run['environment']['python']} / {run['environment']['platform']}")
    lines.append("")
    if execution_kind == "simulated":
        lines.append("> ⚠️ **Cette exécution utilise une cible simulée.** Elle valide le "
                     "laboratoire (runner, détection, métriques) mais ne mesure **aucune** "
                     "qualité de modèle IA réel.")
        lines.append("")
    elif execution_kind != "real":
        lines.append("> ⚠️ Provenance inconnue : les résultats ne constituent pas une mesure de qualité de Côme AI.")
        lines.append("")
    lines.append("## Métriques")
    lines.append("")
    lines.append("| Indicateur | Valeur | Nature |")
    lines.append("|---|---|---|")
    lines.append(f"| Cas au total | {m['cases_total']} | mesuré |")
    lines.append(f"| Cas exécutés | {m['cases_executed']} | mesuré |")
    lines.append(f"| Cas réussis | {m['cases_passed']} | mesuré |")
    lines.append(f"| Cas en échec | {m['cases_failed']} | mesuré |")
    lines.append(f"| Cas non pris en charge | {m['cases_unsupported']} | mesuré |")
    lines.append(f"| Cas exécutés réellement | {m.get('cases_real', 0)} | mesuré |")
    lines.append(f"| Cas simulés | {m.get('cases_simulated', 0)} | auto-test du laboratoire |")
    lines.append(f"| Erreurs d'exécution | {m.get('cases_execution_error', 0)} | mesuré |")
    lines.append(f"| Taux de réussite réel | {_rate(m.get('real_pass_rate'))} | mesure de la cible réelle uniquement |")
    lines.append(f"| Taux de réussite (exécutables) | {_rate(m['pass_rate_executable'])} | mesuré |")
    lines.append(f"| Exactitude des calculs (numeric_close) | "
                 f"{_rate(m['calculation_accuracy']['rate'])} | mesuré |")
    lines.append(f"| Validité des structures (structure/plan) | "
                 f"{_rate(m['structure_validity']['rate'])} | mesuré |")
    lines.append(f"| Traçabilité des sources (citations) | "
                 f"{_rate(m['source_traceability']['rate'])} | mesuré |")
    lines.append(f"| Garde anti-hallucination (faits) | "
                 f"{_rate(m['hallucination_guard']['rate'])} | mesuré |")
    lines.append(f"| Erreurs critiques | {len(m['critical_failures'])} | mesuré |")
    lines.append(f"| Durée totale | {r['total_seconds']:.3f} s | mesuré |")
    lines.append(f"| Mémoire pic du processus | {r['peak_rss_kb'] / 1024:.1f} MiB | mesuré, pic de vie du processus |")
    usage = r.get("declared_usage", {})
    for key, label in (("api_calls", "Appels API"), ("tokens", "Tokens"), ("cost_usd", "Coût USD")):
        value = usage.get(key)
        lines.append(f"| {label} | {value if value is not None else 'n/a'} | déclaré par la cible, non mesuré par le runner |")
    lines.append("")
    if m["critical_failures"]:
        lines.append("## Erreurs critiques")
        lines.append("")
        for failure in m["critical_failures"]:
            lines.append(f"- **{failure['case_id']}** — contrôles en échec : "
                         f"{', '.join(failure['failed_checks'])}")
        lines.append("")
    if m["unsupported_ids"]:
        lines.append("## Cas non pris en charge par cette cible")
        lines.append("")
        reasons = {res["case_id"]: res.get("reason", "") for res in run["results"]}
        for case_id in m["unsupported_ids"]:
            lines.append(f"- {case_id} : {reasons.get(case_id, '')}")
        lines.append("")
    failed_results = [x for x in run["results"] if x["status"] == "executed" and not x["passed"]]
    if failed_results:
        lines.append("## Détail des échecs")
        lines.append("")
        for res in failed_results:
            lines.append(f"### {res['case_id']} ({res['category']}, sévérité {res['severity']})")
            if res["reason"]:
                lines.append(f"- {res['reason']}")
            for chk in res["checks"]:
                if not chk["ok"]:
                    lines.append(f"- ❌ `{chk['check']}` : {chk['detail']}")
            lines.append("")
    lines.append("---")
    lines.append("")
    lines.append(f"_Rapport généré par le laboratoire d'évaluations (`evals/`). "
                 f"Fichier JSON du run : `{run.get('_path', 'non persisté')}`_")
    lines.append("")
    return "\n".join(lines)


def render_compare_report(comparison: dict[str, Any]) -> str:
    lines: list[str] = []
    lines.append("# Rapport de comparaison de runs")
    lines.append("")
    lines.append(f"- **Baseline :** `{comparison['baseline_run_id']}` (cible `{comparison['baseline_target']}`)")
    lines.append(f"- **Candidat :** `{comparison['candidate_run_id']}` (cible `{comparison['candidate_target']}`)")
    lines.append(f"- **Provenance commune :** `{comparison.get('execution_kind', 'unknown')}`")
    lines.append("")
    if comparison["has_regressions"]:
        lines.append(f"## 🔴 Régressions : {len(comparison['regressions'])}")
        lines.append("")
        for reg in comparison["regressions"]:
            lines.append(f"- **{reg['case_id']}** — contrôles dégradés : "
                         f"{', '.join(reg['failed_checks'])}")
    else:
        lines.append("## 🟢 Aucune régression détectée")
    lines.append("")
    if comparison["improvements"]:
        lines.append(f"## Améliorations : {len(comparison['improvements'])}")
        lines.append("")
    if comparison.get("coverage_losses"):
        lines.append("## Perte de couverture")
        lines.append("")
        lines.append("Cas auparavant exécutés devenus non pris en charge ou retirés : " +
                     ", ".join(comparison["coverage_losses"]))
        lines.append("")
        for case_id in comparison["improvements"]:
            lines.append(f"- {case_id} repasse en succès")
        lines.append("")
    if comparison["status_changes"]:
        lines.append("## Changements de statut")
        lines.append("")
        for change in comparison["status_changes"]:
            lines.append(f"- {change['case_id']} : {change['change']}")
        lines.append("")
    if comparison["new_cases"] or comparison["removed_cases"]:
        lines.append("## Delta de suite")
        lines.append("")
        if comparison["new_cases"]:
            lines.append(f"- Cas ajoutés : {', '.join(comparison['new_cases'])}")
        if comparison["removed_cases"]:
            lines.append(f"- Cas retirés : {', '.join(comparison['removed_cases'])}")
        lines.append("")
    lines.append("---")
    lines.append("")
    lines.append("_Rapport généré par `python -m evals compare`._")
    lines.append("")
    return "\n".join(lines)
