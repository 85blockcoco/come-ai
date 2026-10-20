"""Reports of the adversarial bench (CVBOOST-08): JSON and Markdown.

The report never mixes the three axes and never presents a synthetic run as
a measurement of the real product.  Every number it prints says where it
comes from: the synthetic suite, the real application code, or the network
(which is never used).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from . import contracts, thresholds
from .runner import BenchRun


def build_report(run: BenchRun, evaluation: thresholds.Evaluation | None = None) -> dict[str, Any]:
    """The full JSON payload of a bench run."""
    payload = run.to_dict()
    payload["thresholds"] = evaluation.to_dict() if evaluation else None
    payload["cross_axis_flags"] = cross_axis_flags(run)
    return payload


def cross_axis_flags(run: BenchRun) -> list[dict[str, Any]]:
    """Cases where two axes say different things about the same offer.

    The bench does not arbitrate: a case whose contract conforms while the
    advertised academic level is out of reach is *reported*, so that nobody
    reads the admissibility verdict as an admission.
    """
    flags: list[dict[str, Any]] = []
    for outcome in run.outcomes:
        eligibility = outcome.observation.get("eligibility") or {}
        education = outcome.observation.get("education") or {}
        verdict = contracts.ELIGIBILITY_BY_TARGET_STATUS.get(
            str(eligibility.get("target_status") or "to_verify"), "unknown"
        )
        level = str(education.get("status") or "unknown")
        if level == "outside_preference" and verdict == "eligible":
            flags.append(
                {
                    "case_id": outcome.case_id,
                    "family": outcome.family,
                    "admissibilite": verdict,
                    "niveau_academique": level,
                    "detail": (
                        "Le contrat est conforme mais le niveau académique annoncé dépasse la "
                        "préférence : le verdict d'admissibilité ne vaut pas admission."
                    ),
                }
            )
    return flags


def render_markdown(run: BenchRun, evaluation: thresholds.Evaluation | None = None) -> str:
    """The human-readable report."""
    metrics = run.metrics
    simulated = metrics["simulated"]
    verified = metrics["application_verified"]
    network = metrics["network_real"]
    hard = simulated["hard_checks"]
    semantic = simulated["semantic_checks"]

    lines: list[str] = []
    lines.append("# Banc adversarial de matching CV/offre — rapport (CVBOOST-08)")
    lines.append("")
    lines.append(f"- Suite : `{run.suite_version}` — schéma `{run.schema_version}`")
    lines.append(f"- Date de référence figée : `{run.as_of}`")
    lines.append(f"- Couples synthétiques exécutés : **{simulated['cases']}**")
    lines.append(f"- Réseau : **{network['status']}** — {network['reason']}")
    lines.append("")

    lines.append("## 1. Ce que ce banc mesure, et ce qu'il ne mesure pas")
    lines.append("")
    lines.append("| Provenance | Cas | Statut | Ce que cela signifie |")
    lines.append("|---|---|---|---|")
    lines.append(
        f"| Simulée (fixtures synthétiques) | {simulated['cases']} | mesuré | "
        "Métriques calculées sur des couples synthétiques, exécution locale déterministe. |"
    )
    lines.append(
        f"| Application vérifiée | {verified['cases']} | mesuré | "
        "Comportement produit par le code applicatif réel, pas par une reconstruction. |"
    )
    lines.append(
        f"| Réseau réel | {network['cases']} | {network['status']} | "
        "Aucune source officielle n'est contactée : ce chiffre ne vaut pas une mesure du réseau. |"
    )
    lines.append("")
    lines.append(
        "Les trois axes sont **mesurés séparément** et ne sont jamais additionnés : "
        "une forte couverture documentaire ne dit rien de l'admissibilité, et un score de "
        "pertinence ne dit rien de la couverture documentaire."
    )
    lines.append("")

    lines.append("## 2. Invariants durs (contrat du produit)")
    lines.append("")
    lines.append(f"- Contrôles exécutés : **{hard['total']}**")
    lines.append(f"- Respectés : **{hard['passed']}**")
    lines.append(f"- Violés : **{hard['failed']}**")
    if hard["failed_checks"]:
        lines.append(f"- Contrôles en défaut : {', '.join(f'`{name}`' for name in hard['failed_checks'])}")
    lines.append("")
    lines.append("| Invariant | Exigence |")
    lines.append("|---|---|")
    for name, description in contracts.HARD_CHECKS.items():
        state = "OK" if name not in hard["failed_checks"] else "**DÉFAUT**"
        lines.append(f"| `{name}` | {description} ({state}) |")
    lines.append("")

    lines.append("## 3. Contrôles sémantiques (comparaison à la vérité terrain)")
    lines.append("")
    lines.append(f"- Contrôles exécutés : **{semantic['total']}**")
    lines.append(f"- Respectés : **{semantic['passed']}**")
    lines.append(f"- Écarts : **{semantic['failed']}**")
    lines.append(f"- Couples sans aucun écart : **{simulated['cases_passed']} / {simulated['cases']}**")
    lines.append("")
    lines.append("| Contrôle | Exigence |")
    lines.append("|---|---|")
    for name, description in contracts.SEMANTIC_CHECKS.items():
        state = "OK" if name not in semantic["failed_checks"] else "**ÉCARTS**"
        lines.append(f"| `{name}` | {description} ({state}) |")
    lines.append("")

    lines.append("## 4. Résultats par famille adversariale")
    lines.append("")
    lines.append("| Famille | Cas | Défauts durs | Écarts | Couverture d'accord |")
    lines.append("|---|---|---|---|---|")
    for family, entry in sorted(simulated["by_family"].items()):
        lines.append(
            f"| {family} | {entry['cases']} | {entry['hard_failures']} | "
            f"{entry['semantic_failures']} | {round(entry['agreement_rate'] * 100)} % |"
        )
    lines.append("")

    lines.append("## 5. Axes (mesurés séparément)")
    lines.append("")
    axes = run.axes
    admissibility = axes["admissibilite"]["counts"]
    lines.append(
        f"- **Admissibilité** (contrat, durée, période) : admissible {admissibility.get('eligible', 0)}, "
        f"non admissible {admissibility.get('ineligible', 0)}, "
        f"indéterminé {admissibility.get('unknown', 0)}."
    )
    pertinence = axes["pertinence"]
    lines.append(
        f"- **Pertinence** (brief de recherche) : {pertinence['scores']} score(s), "
        f"moyenne {pertinence['score_mean']}, min {pertinence['score_min']}, max {pertinence['score_max']}."
    )
    couverture = axes["couverture"]
    lines.append(
        f"- **Couverture documentaire** : {couverture['requirements_detected']} exigence(s) détectée(s), "
        f"couverture moyenne {couverture['coverage_percent_mean']} %."
    )
    lines.append("")
    flags = cross_axis_flags(run)
    if flags:
        lines.append("### Divergences entre axes (signalées, jamais arbitrées)")
        lines.append("")
        for flag in flags:
            lines.append(f"- `{flag['case_id']}` — {flag['detail']}")
        lines.append("")

    lines.append("## 6. Défauts détectés")
    lines.append("")
    if not run.defects:
        lines.append("Aucun écart détecté.")
    else:
        hard_defects = [defect for defect in run.defects if defect["kind"] == "invariant_dur"]
        semantic_defects = [defect for defect in run.defects if defect["kind"] == "ecart_semantique"]
        lines.append(f"### 6.1 Invariants durs ({len(hard_defects)})")
        lines.append("")
        for defect in hard_defects:
            lines.append(f"- **`{defect['case_id']}`** · `{defect['check']}` : {defect['detail']}")
            for failure in defect["failures"]:
                lines.append(f"  - {failure}")
        lines.append("")
        lines.append(f"### 6.2 Écarts sémantiques ({len(semantic_defects)})")
        lines.append("")
        for defect in semantic_defects:
            lines.append(f"- **`{defect['case_id']}`** · `{defect['check']}` : {defect['detail']}")
            for failure in defect["failures"]:
                lines.append(f"  - {failure}")
    lines.append("")

    lines.append("## 7. Seuils de régression")
    lines.append("")
    if evaluation is None:
        lines.append("Aucun seuil évalué pour ce rapport.")
    else:
        measured = evaluation.measured
        lines.append(f"- Verdict : **{'CONFORME' if evaluation.ok else 'NON CONFORME'}**")
        lines.append("")
        lines.append("| Seuil | Mesuré | Autorisé |")
        lines.append("|---|---|---|")
        for key in thresholds.LIMIT_KEYS:
            lines.append(
                f"| {thresholds.LIMIT_LABELS[key]} | {measured.get(key.replace('_min', '').replace('_max', ''), '')} "
                f"| {evaluation.limits.get(key)} |"
            )
        for violation in evaluation.violations:
            lines.append(
                f"- **Violation** : {violation['label']} — mesuré {violation['measured']}, "
                f"autorisé {violation['allowed']}."
            )
    lines.append("")
    lines.append("## 8. Limites")
    lines.append("")
    lines.append("- Les offres et les profils sont synthétiques : aucune donnée réelle, aucun secret.")
    lines.append("- Les verdicts d'admissibilité sont des tests de chemin de décision sur données "
                 "synthétiques : ils ne prouvent aucune couverture de source réelle.")
    lines.append("- Les écarts détectés décrivent le comportement actuel ; ce lot ne modifie aucune "
                 "règle métier.")
    lines.append(f"- {contracts.NETWORK_POLICY}")
    lines.append("")
    return "\n".join(lines)


def write_reports(
    run: BenchRun,
    directory: Path | str,
    evaluation: thresholds.Evaluation | None = None,
    *,
    stem: str = "cvboost-08-bench",
) -> dict[str, Path]:
    """Write the JSON and Markdown reports next to each other."""
    target = Path(directory)
    target.mkdir(parents=True, exist_ok=True)
    json_path = target / f"{stem}.json"
    markdown_path = target / f"{stem}.md"
    payload = build_report(run, evaluation)
    json_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    markdown_path.write_text(render_markdown(run, evaluation), encoding="utf-8")
    return {"json": json_path, "markdown": markdown_path}
