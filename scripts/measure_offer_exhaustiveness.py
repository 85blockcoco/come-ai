#!/usr/bin/env python3
"""Mesure du score d'exhaustivité par offre (SK-20) sur le corpus local.

Contrairement à `scripts/measure_exhaustiveness.py` (garde-fou sur le taux de
champs du *résumé*), ce script mesure le score d'exhaustivité SK-20 — missions,
salaire, conditions, éducation, dates — calculé par
`career.offer_exhaustiveness.compute_exhaustiveness` sur les offres effectivement
qualifiées dans la base locale (job_qualification_snapshots + jobs).

Aucune donnée n'est inventée : une offre sans snapshot de qualification est
ignorée (comptée comme non mesurable), et si aucune offre n'est mesurable le
script échoue explicitement au lieu de retourner un score de complaisance.

Usage :
    python3 scripts/measure_offer_exhaustiveness.py [--db PATH] [--check N]
    python3 scripts/measure_offer_exhaustiveness.py --fixtures

`--check N` échoue (exit 1) si la moyenne mesurée est sous N %. Objectif cible
de la mission : > 60 % une fois les extracteurs SK-16/SK-17/SK-18/SK-19
connectés ; tant que ce n'est pas le cas, la mesure sert de baseline honnête.
"""
from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from career.offer_exhaustiveness import compute_exhaustiveness  # noqa: E402

DEFAULT_DB = PROJECT_ROOT / "career_data" / "career.sqlite3"
FIXTURES = PROJECT_ROOT / "tests" / "fixtures" / "offer_exhaustiveness"


class NoMeasurableOffer(ValueError):
    """Le corpus local ne contient aucune offre qualifiée mesurable."""


def load_qualified_jobs(db_path: Path) -> list[dict[str, Any]]:
    """Reconstruit les dicts job mesurables depuis le snapshot de qualification.

    Chaque entrée suit la forme attendue par compute_exhaustiveness :
    {"qualification": {"provenance": <serde de FactEvidence>,
                       "duration_min_months": int|None},
     "start_date": str|None, "deadline_date": str|None}
    """
    if not db_path.is_file():
        raise FileNotFoundError(
            f"Base introuvable : {db_path}. Aucune mesure inventée ; pointe --db vers une base locale.")
    with sqlite3.connect(f"file:{db_path}?mode=ro", uri=True) as connection:
        connection.row_factory = sqlite3.Row
        rows = connection.execute(
            """
            SELECT j.start_date, j.deadline_date,
                   s.provenance_json, s.facts_json
            FROM jobs j
            JOIN job_qualification_snapshots s ON s.job_id = j.id
            """
        ).fetchall()
    if not rows:
        raise NoMeasurableOffer(
            "Aucune offre n'est qualifiée en base (job_qualification_snapshots vide).")
    jobs: list[dict[str, Any]] = []
    for row in rows:
        provenance = json.loads(row["provenance_json"] or "{}")
        facts = json.loads(row["facts_json"] or "{}")
        if not isinstance(provenance, dict):
            provenance = {}
        jobs.append({
            "start_date": row["start_date"] or None,
            "deadline_date": row["deadline_date"] or None,
            "qualification": {
                "provenance": provenance,
                "duration_min_months": (
                    facts.get("duration_min_months")
                    if isinstance(facts, dict) and type(facts.get("duration_min_months")) is int
                    else None
                ),
            },
        })
    return jobs


def load_fixture_jobs() -> list[dict[str, Any]]:
    """Les 17 fixtures synthétiques du dépôt, données de mesure pures."""
    if not FIXTURES.is_dir():
        raise FileNotFoundError(f"Fixtures absentes : {FIXTURES}")
    return [json.loads(path.read_text(encoding="utf-8")) for path in sorted(FIXTURES.glob("*.json"))]


def measure(jobs: list[dict[str, Any]]) -> dict[str, Any]:
    """Score moyen + distribution + contribution par composante."""
    if not jobs:
        raise NoMeasurableOffer("Corpus vide : aucune offre à mesurer.")
    scores = [compute_exhaustiveness(job) for job in jobs]
    total = sum(score.overall_score for score in scores)
    distribution: dict[str, int] = {"green": 0, "orange": 0, "red": 0, "gray": 0}
    per_component = {"missions": 0, "salary": 0, "conditions": 0, "education": 0, "dates": 0}
    salary_mentions = 0
    for score in scores:
        distribution[score.badge_color] += 1
        for component, weight in score.breakdown.items():
            per_component[component] += weight
        if score.breakdown["salary"]:
            salary_mentions += 1
    return {
        "jobs": len(jobs),
        "average": round(total / len(scores), 2),
        "distribution": distribution,
        "per_component_hits": per_component,
        "salary_mention_rate": round(100 * salary_mentions / len(scores), 2),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Mesure SK-20 du score d'exhaustivité par offre.")
    parser.add_argument("--db", type=Path, default=DEFAULT_DB,
                        help=f"Base locale career (défaut : {DEFAULT_DB.name}).")
    parser.add_argument("--check", type=float, default=None, metavar="N",
                        help="Échoue si la moyenne est sous N %.")
    parser.add_argument("--fixtures", action="store_true",
                        help="Mesure le corpus de fixtures natif plutôt que la base locale.")
    args = parser.parse_args(argv)

    if args.fixtures:
        jobs = load_fixture_jobs()
    else:
        try:
            jobs = load_qualified_jobs(args.db)
        except FileNotFoundError as error:
            print(json.dumps({"error": str(error)}, ensure_ascii=False))
            return 1
    try:
        report = measure(jobs)
    except NoMeasurableOffer as error:
        print(json.dumps({"error": str(error)}, ensure_ascii=False))
        return 1
    report["source"] = "fixtures" if args.fixtures else str(args.db)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    if args.check is not None and report["average"] < args.check:
        print(f"ÉCHEC : moyenne {report['average']}% sous le seuil de {args.check}%.", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
