"""Interface en ligne de commande du laboratoire d'évaluations.

Exemples :
    python -m evals list
    python -m evals run --target simulated
    python -m evals run --target fault:wrong_answer --label "démo faute"
    python -m evals compare runs/A.json runs/B.json
    python -m evals suite

Les validateurs sont déterministes. La cible choisie déclare séparément la
provenance et la consommation de son exécution.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .report import render_compare_report, render_run_report
from .runner import (
    FAULT_MODES,
    FaultInjectionTarget,
    SimulatedTarget,
    compare_runs,
    run_suite,
)
from .schema import CaseError, load_cases, summarize_suite


def _build_target(spec: str):
    if spec == "come-ai":
        from .come_ai_target import ComeAITarget
        return ComeAITarget()
    if spec == "simulated":
        return SimulatedTarget()
    if spec.startswith("fault:"):
        return FaultInjectionTarget(spec.split(":", 1)[1])
    raise SystemExit(
        f"Cible inconnue : {spec!r}. Choix : come-ai, simulated, fault:<mode> avec mode dans {FAULT_MODES}"
    )


def cmd_list(args: argparse.Namespace) -> int:
    cases = load_cases(args.cases_dir)
    summary = summarize_suite(cases)
    print(f"Suite : {summary['total']} cas "
          f"({summary['supported']} contrats supported, {summary['future']} futurs ; "
          f"{summary['application_verified']} déclarés vérifiés sur l'application)")
    print("Le statut supported décrit le contrat ; l'exécution dépend des capacités de la cible.")
    print(f"Répartition : {summary['by_category']} | critiques : {summary['critical']}")
    print()
    for case in cases:
        flag = "✓" if case.status == "supported" else "→ futur"
        print(f"{case.id:<9} [{flag:^7}] {case.category:<12} {case.title}")
    return 0


def cmd_suite(args: argparse.Namespace) -> int:
    cases = load_cases(args.cases_dir)
    print(json.dumps(summarize_suite(cases), ensure_ascii=False, indent=2))
    return 0


def cmd_run(args: argparse.Namespace) -> int:
    target = _build_target(args.target)
    case_path = args.cases_dir
    if case_path is None and args.target == "come-ai":
        case_path = Path(__file__).parent / "cases" / "come_ai_real.json"
    cases = load_cases(case_path)
    run = run_suite(target, cases, label=args.label, persist=not args.no_persist)
    report = render_run_report(run)
    if args.out:
        Path(args.out).write_text(report, encoding="utf-8")
        print(f"Rapport écrit : {args.out}")
    else:
        print(report)
    print(f"Run JSON : {run.get('_path', '(non persisté)')}", file=sys.stderr)
    # Code de sortie : 1 si échec parmi les cas exécutables (pas pour « futur »).
    failed = run["metrics"]["cases_failed"]
    if args.strict and run["metrics"]["cases_executed"] == 0:
        print("Exécution stricte refusée : aucun cas exécuté par cette cible.", file=sys.stderr)
        return 2
    return 1 if failed and args.strict else 0


def cmd_compare(args: argparse.Namespace) -> int:
    baseline = json.loads(Path(args.baseline).read_text(encoding="utf-8"))
    candidate = json.loads(Path(args.candidate).read_text(encoding="utf-8"))
    comparison = compare_runs(baseline, candidate)
    report = render_compare_report(comparison)
    if args.out:
        Path(args.out).write_text(report, encoding="utf-8")
        print(f"Rapport écrit : {args.out}")
    else:
        print(report)
    if args.json:
        Path(args.json).write_text(
            json.dumps(comparison, ensure_ascii=False, indent=2), encoding="utf-8"
        )
    return 1 if args.strict and (comparison["has_regressions"] or comparison.get("has_coverage_loss")) else 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="evals", description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--cases-dir", default=None,
                        help="dossier ou fichier JSON des cas (défaut : suite de la cible)")
    sub = parser.add_subparsers(dest="command", required=True)

    p_list = sub.add_parser("list", help="lister la suite de cas")
    p_list.set_defaults(func=cmd_list)

    p_suite = sub.add_parser("suite", help="résumé JSON de la suite")
    p_suite.set_defaults(func=cmd_suite)

    p_run = sub.add_parser("run", help="exécuter la suite")
    p_run.add_argument("--target", default="simulated",
                       help="come-ai | simulated | fault:<mode>")
    p_run.add_argument("--label", default="", help="label du run")
    p_run.add_argument("--out", default=None, help="écrire le rapport Markdown dans un fichier")
    p_run.add_argument("--no-persist", action="store_true", help="ne pas écrire runs/*.json")
    p_run.add_argument("--strict", action="store_true",
                       help="code de sortie 1 si échec")
    p_run.set_defaults(func=cmd_run)

    p_cmp = sub.add_parser("compare", help="comparer deux runs JSON")
    p_cmp.add_argument("baseline")
    p_cmp.add_argument("candidate")
    p_cmp.add_argument("--out", default=None)
    p_cmp.add_argument("--json", default=None, help="écrire aussi la comparaison JSON")
    p_cmp.add_argument("--strict", action="store_true")
    p_cmp.set_defaults(func=cmd_compare)

    args = parser.parse_args(argv)
    try:
        return args.func(args)
    except CaseError as exc:
        print(f"Erreur de suite de cas : {exc}", file=sys.stderr)
        return 2
    except (ValueError, OSError, KeyError) as exc:
        print(f"Erreur d'évaluation : {type(exc).__name__}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
