#!/usr/bin/env python3
"""NAGE — petit CLI local pour les devoirs et le quotidien.

Aucun réseau, aucune clé, aucune donnée personnelle dans le dépôt : le livre
de comptes par défaut vit sous ``~/.nage/ledger.jsonl``.

Exemples :
    .venv/bin/python nage.py finance future_value pv=100 rate=0.1 periods=2
    .venv/bin/python nage.py math mean values=1,2,3
    .venv/bin/python nage.py budget report --month 2026-11
    .venv/bin/python nage.py budget add expense 12.5 "Cantine" --category repas
    .venv/bin/python nage.py plan --minutes 120 --task "NPV|2026-11-03|45|1"
    .venv/bin/python nage.py research --topic "Finance durable" \
        --section "Introduction" --section "Données" --fact "La BCE publie..."
    .venv/bin/python nage.py homework --type npv --level master
    .venv/bin/python nage.py vc review --minutes 10
    .venv/bin/python nage.py vc drill run VC04-D001 --answer "10 M€"
    .venv/bin/python nage.py vc case grade VC03-CASE01 --answers answers.json
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict
from datetime import date
from pathlib import Path
from typing import Any, Sequence

from academics.daily_toolkit import Ledger, Task, budget_report, category_totals, daily_brief, daily_plan
from academics.research_kit import build_outline, homework_steps
from academics.router import FINANCE_OPERATIONS, MATH_OPERATIONS

DEFAULT_LEDGER = Path.home() / ".nage" / "ledger.jsonl"


def _parse_value(raw: str) -> Any:
    """Interprète ``1,2,3`` comme une liste et ``0.1`` comme un nombre."""
    text = raw.strip()
    if "," in text:
        return [_parse_value(part) for part in text.split(",") if part.strip()]
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return text


def _parse_arguments(pairs: list[str]) -> dict[str, Any]:
    arguments: dict[str, Any] = {}
    for pair in pairs:
        if "=" not in pair:
            raise ValueError(f"argument attendu au format clé=valeur : {pair!r}")
        key, raw = pair.split("=", 1)
        key = key.strip()
        if not key:
            raise ValueError(f"clé vide dans l'argument : {pair!r}")
        arguments[key] = _parse_value(raw)
    return arguments


def _parse_tasks(values: list[str]) -> list[Task]:
    tasks: list[Task] = []
    for value in values:
        parts = [part.strip() for part in value.split("|")]
        if len(parts) < 3:
            raise ValueError(f"tâche attendue au format Titre|AAAA-MM-JJ|minutes[|priorité] : {value!r}")
        title, due, estimate = parts[0], parts[1], int(parts[2])
        priority = int(parts[3]) if len(parts) > 3 and parts[3] else 2
        tasks.append(Task(title=title, due=due, estimate_minutes=estimate, priority=priority))
    return tasks


def _emit(payload: Any, as_json: bool) -> None:
    if as_json:
        print(json.dumps(payload, ensure_ascii=False, indent=2, default=str))
        return
    if isinstance(payload, dict):
        for key, value in payload.items():
            if isinstance(value, (dict, list)):
                print(f"{key}:")
                print(json.dumps(value, ensure_ascii=False, indent=2, default=str))
            else:
                print(f"{key}: {value}")
    else:
        print(payload)


def _operation_result(operations: dict[str, Any], operation: str, arguments: dict[str, Any]) -> dict[str, Any]:
    function = operations.get(operation)
    if function is None:
        allowed = ", ".join(sorted(operations))
        raise ValueError(f"opération inconnue {operation!r}. Autorisées : {allowed}")
    result = function(**arguments)
    return {
        "operation": operation,
        "result": asdict(result) if hasattr(result, "__dataclass_fields__") else result,
    }


def _budget_parser(subparsers: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    budget = subparsers.add_parser("budget", help="Livre de comptes et rapport mensuel")
    budget.add_argument("--ledger", type=Path, default=DEFAULT_LEDGER, help="Fichier JSONL local")
    actions = budget.add_subparsers(dest="action", required=True)

    report = actions.add_parser("report", help="Rapport du mois")
    report.add_argument("--month", default=date.today().strftime("%Y-%m"), help="AAAA-MM")

    add = actions.add_parser("add", help="Ajouter un revenu ou une dépense")
    add.add_argument("kind", choices=("income", "expense"))
    add.add_argument("amount", type=float)
    add.add_argument("label")
    add.add_argument("--category", default="divers")
    add.add_argument("--date", dest="date_str", default=None)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="nage",
        description="NAGE — devoirs finance/maths, budget, plan du jour. 100 % local.",
    )
    parser.add_argument("--json", action="store_true", help="Sortie JSON lisible par machine")
    subparsers = parser.add_subparsers(dest="command", required=True)

    for name, operations, help_text in (
        ("finance", FINANCE_OPERATIONS, "Calcul de finance (opérations autorisées)"),
        ("math", MATH_OPERATIONS, "Calcul de maths/statistiques (opérations autorisées)"),
    ):
        command = subparsers.add_parser(name, help=help_text)
        command.add_argument("operation", help="Nom de l'opération")
        command.add_argument(
            "arguments",
            nargs="*",
            help="Paramètres clé=valeur, listes séparées par des virgules",
        )

    plan = subparsers.add_parser("plan", help="Plan du jour borné en minutes")
    plan.add_argument("--minutes", type=int, default=120)
    plan.add_argument("--today", default=None)
    plan.add_argument("--task", action="append", default=[], help="Titre|AAAA-MM-JJ|minutes[|priorité]")

    brief = subparsers.add_parser("brief", help="Brief quotidien (tâches urgentes, budget, révisions)")
    brief.add_argument("--minutes", type=int, default=120)
    brief.add_argument("--today", default=None)
    brief.add_argument("--task", action="append", default=[])
    brief.add_argument("--ledger", type=Path, default=DEFAULT_LEDGER)
    brief.add_argument("--month", default=date.today().strftime("%Y-%m"))
    brief.add_argument("--cards-due", type=int, default=0)

    research = subparsers.add_parser("research", help="Plan de recherche sans invention")
    research.add_argument("--topic", required=True)
    research.add_argument("--section", action="append", default=[])
    research.add_argument("--fact", action="append", default=[])

    homework = subparsers.add_parser("homework", help="Méthode pas-à-pas (jamais la réponse)")
    homework.add_argument(
        "--type",
        dest="problem_type",
        required=True,
        choices=("derivative", "integral", "annuity", "npv", "statistics", "equation"),
    )
    homework.add_argument("--level", default="")

    _budget_parser(subparsers)

    from academics.vc.cli import build_vc_parser

    vc = subparsers.add_parser("vc", help="Révision Venture Capital (local, hors-ligne)")
    build_vc_parser(vc)
    return parser


def run(args: argparse.Namespace) -> Any:
    if args.command in {"finance", "math"}:
        operations = FINANCE_OPERATIONS if args.command == "finance" else MATH_OPERATIONS
        return _operation_result(operations, args.operation, _parse_arguments(args.arguments))

    if args.command == "plan":
        plan = daily_plan(_parse_tasks(args.task), minutes_per_day=args.minutes, today=args.today)
        selected = [asdict(task) for task in plan["tasks"]]
        return {
            "day_date": plan["day_date"],
            "tasks": selected,
            "total_minutes": sum(task["estimate_minutes"] for task in selected),
        }

    if args.command == "brief":
        ledger = Ledger(args.ledger)
        return daily_brief(
            _parse_tasks(args.task),
            (ledger, args.month),
            args.cards_due,
            args.today or date.today().isoformat(),
        )

    if args.command == "research":
        outline = build_outline(args.topic, args.section, args.fact)
        return asdict(outline)

    if args.command == "homework":
        return homework_steps(args.problem_type, args.level)

    if args.command == "budget":
        ledger = Ledger(args.ledger)
        if args.action == "add":
            return ledger.add(args.kind, args.amount, args.label, args.category, args.date_str)
        return {
            "report": budget_report(ledger, args.month),
            "categories": category_totals(ledger, args.month),
        }

    raise ValueError(f"commande inconnue : {args.command}")


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.command == "vc":
        from academics.vc.cli import run_vc

        return run_vc(args)
    try:
        payload = run(args)
    except (TypeError, ValueError, ZeroDivisionError) as error:
        print(f"erreur : {error}", file=sys.stderr)
        return 2
    _emit(payload, args.json)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
