"""Command line of the adversarial bench (CVBOOST-08).

    PYTHONPATH=. python -m career.matching_bench list
    PYTHONPATH=. python -m career.matching_bench run --out .devkit/bench
    PYTHONPATH=. python -m career.matching_bench compare base.json candidat.json
    PYTHONPATH=. python -m career.matching_bench thresholds --write

``run`` exits with code 1 when a threshold is violated: the bench is usable
as a gate, not only as a report.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from . import contracts, thresholds
from .fixtures import load_cases, summarize_cases
from .report import render_markdown, write_reports
from .runner import run_bench


def _list(arguments: argparse.Namespace) -> int:
    cases = load_cases()
    summary = summarize_cases(cases)
    if arguments.json:
        print(json.dumps(summary, ensure_ascii=False, indent=2))
        return 0
    print(f"Suite {contracts.SUITE_VERSION} — {summary['cases']} couples synthétiques")
    print(f"Exigences de référence : {summary['requirements']}")
    for family, count in sorted(summary["by_family"].items()):
        print(f"  {family:<28} {count:>3} cas   {contracts.FAMILIES[family]}")
    for axis, count in sorted(summary["by_axis"].items()):
        print(f"  axe {axis:<24} {count:>3} cas")
    return 0


def _run(arguments: argparse.Namespace) -> int:
    cases = load_cases()
    run = run_bench(cases)
    limits = None
    try:
        stored = thresholds.load_thresholds()
        if stored.get("suite_version") == contracts.SUITE_VERSION:
            limits = stored.get("limits")
    except (FileNotFoundError, ValueError):
        limits = None
    evaluation = thresholds.evaluate(run, limits)
    if arguments.out:
        written = write_reports(run, arguments.out, evaluation)
        print(f"Rapport JSON     : {written['json']}")
        print(f"Rapport Markdown : {written['markdown']}")
    if arguments.print_markdown:
        print(render_markdown(run, evaluation))
    simulated = run.metrics["simulated"]
    print(
        f"{simulated['cases']} cas — défauts durs : {evaluation.measured['hard_failures']} "
        f"(max {evaluation.limits['hard_failures_max']}) — écarts sémantiques : "
        f"{evaluation.measured['semantic_failures']} (max {evaluation.limits['semantic_failures_max']})"
    )
    if not evaluation.ok:
        for violation in evaluation.violations:
            print(
                f"VIOLATION {violation['limit']} : mesuré {violation['measured']}, "
                f"autorisé {violation['allowed']}",
                file=sys.stderr,
            )
        return 1
    print("Seuils respectés.")
    return 0


def _compare(arguments: argparse.Namespace) -> int:
    baseline = json.loads(Path(arguments.baseline).read_text(encoding="utf-8"))
    candidate = json.loads(Path(arguments.candidate).read_text(encoding="utf-8"))
    comparison = thresholds.compare_runs(baseline, candidate)
    print(json.dumps(comparison, ensure_ascii=False, indent=2))
    return 0 if comparison["ok"] else 1


def _thresholds(arguments: argparse.Namespace) -> int:
    run = run_bench()
    payload = thresholds.build_thresholds(run)
    if arguments.write:
        path = thresholds.save_thresholds(payload)
        print(f"{path} écrit.")
        print(json.dumps(payload["limits"], ensure_ascii=False, indent=2))
        return 0
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Banc adversarial de matching CV/offre (CVBOOST-08).")
    subparsers = parser.add_subparsers(dest="command", required=True)

    listing = subparsers.add_parser("list", help="inventaire des couples synthétiques")
    listing.add_argument("--json", action="store_true", help="sortie JSON")
    listing.set_defaults(handler=_list)

    runner = subparsers.add_parser("run", help="exécute le banc et écrit les rapports")
    runner.add_argument("--out", default=None, help="dossier des rapports")
    runner.add_argument("--print-markdown", action="store_true", help="affiche le rapport Markdown")
    runner.set_defaults(handler=_run)

    comparison = subparsers.add_parser("compare", help="compare deux exécutions")
    comparison.add_argument("baseline")
    comparison.add_argument("candidate")
    comparison.set_defaults(handler=_compare)

    gates = subparsers.add_parser("thresholds", help="seuils de régression")
    gates.add_argument("--write", action="store_true", help="écrit le fichier de seuils versionné")
    gates.set_defaults(handler=_thresholds)

    arguments = parser.parse_args(argv)
    return int(arguments.handler(arguments))


if __name__ == "__main__":
    raise SystemExit(main())
