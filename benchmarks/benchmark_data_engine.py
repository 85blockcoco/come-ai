#!/usr/bin/env python
"""Benchmark reproductible : Pandas (avant) contre DuckDB (après).

Mesure, sur des données **synthétiques** uniquement, le temps d'exécution et le
pic de mémoire résidente (RSS) de charges équivalentes, chacune dans un
**sous-processus** isolé (pour un pic RSS propre au processus) :

* ``aggregate`` : un seul balayage d'agrégation (compte, somme, moyenne).
  C'est le cas où DuckDB lit le CSV en flux sans le charger en mémoire.
* ``analyze``   : analyse descriptive complète (statistiques de toutes les
  colonnes numériques) puis performance d'une série temporelle.

Aucune donnée personnelle n'est lue ou écrite.

Exemples :

    .venv/bin/python -m benchmarks.benchmark_data_engine --rows 1000000
    .venv/bin/python -m benchmarks.benchmark_data_engine --rows 200000 --repeat 3 --json benchmarks/results/run.json
"""

from __future__ import annotations

import argparse
import json
import resource
import subprocess
import sys
import tempfile
import time
from pathlib import Path

BENCH_DIR = Path(__file__).resolve().parent


def peak_rss_bytes() -> int:
    """Pic RSS du processus courant, normalisé en octets (macOS vs Linux)."""
    usage = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    if sys.platform == "darwin":
        return int(usage)
    return int(usage) * 1024


def generate_csv(path: Path, rows: int) -> None:
    with path.open("w", encoding="utf-8") as handle:
        handle.write("id,date,symbole,quantite,prix,variation\n")
        symbols = ("AAA", "BBB", "CCC", "DDD")
        for index in range(rows):
            day = (index % 28) + 1
            month = ((index // 28) % 12) + 1
            handle.write(
                f"{index},2024-{month:02d}-{day:02d},{symbols[index % 4]},"
                f"{1 + index % 50},{1000 + index % 1000}.5,{(index % 21) - 10}.25\n"
            )


# --------------------------------------------------------------------------- #
# Charges « avant » : Pandas
# --------------------------------------------------------------------------- #
def pandas_aggregate(path: str) -> dict:
    import pandas as pd

    started = time.perf_counter()
    frame = pd.read_csv(path)
    result = {
        "rows": int(len(frame)),
        "sum": round(float(frame["prix"].sum()), 3),
        "mean": round(float(frame["quantite"].mean()), 6),
    }
    elapsed = time.perf_counter() - started
    return {"engine": "pandas", "scenario": "aggregate", "seconds": round(elapsed, 4), "result": result}


def pandas_analyze(path: str) -> dict:
    import pandas as pd

    started = time.perf_counter()
    frame = pd.read_csv(path)
    numeric = frame.select_dtypes(include=["number"])
    stats = {}
    for column in numeric.columns[:30]:
        series = pd.to_numeric(numeric[column], errors="coerce").dropna()
        stats[column] = {
            "sum": round(float(series.sum()), 3),
            "mean": round(float(series.mean()), 6),
        }
    ordered = frame.sort_values("date")
    prices = ordered["prix"].astype(float).tolist()
    trend = round(prices[-1] / prices[0] - 1, 6) if prices and prices[0] else None
    elapsed = time.perf_counter() - started
    return {
        "engine": "pandas",
        "scenario": "analyze",
        "seconds": round(elapsed, 4),
        "result": {"rows": int(len(frame)), "trend": trend, "stats": stats},
    }


# --------------------------------------------------------------------------- #
# Charges « après » : DuckDB
# --------------------------------------------------------------------------- #
def duckdb_aggregate(path: str) -> dict:
    sys.path.insert(0, str(BENCH_DIR.parent))
    from come_data import ComeDataEngine
    from come_data.safety import quote_identifier

    started = time.perf_counter()
    root = Path(path).parent
    (root / "output").mkdir(exist_ok=True)
    with ComeDataEngine(root, root / "output") as engine:
        info = engine.register(path, name="bench")  # vue paresseuse, un seul balayage
        table = quote_identifier(info.name)
        row = engine.engine._con.execute(
            f"SELECT count(*), sum(prix), avg(quantite) FROM {table}"
        ).fetchone()
    elapsed = time.perf_counter() - started
    result = {"rows": int(row[0]), "sum": round(float(row[1]), 3), "mean": round(float(row[2]), 6)}
    return {"engine": "duckdb", "scenario": "aggregate", "seconds": round(elapsed, 4), "result": result}


def duckdb_analyze(path: str) -> dict:
    sys.path.insert(0, str(BENCH_DIR.parent))
    from come_data import ComeDataEngine

    started = time.perf_counter()
    root = Path(path).parent
    (root / "output").mkdir(exist_ok=True)
    with ComeDataEngine(root, root / "output") as engine:
        summary = engine.analyze(path).as_dict()
        performance = engine.performance(path, "prix", time_column="date")
    elapsed = time.perf_counter() - started
    stats = {column: {"sum": value["sum"], "mean": value["mean"]}
             for column, value in summary["numeric_statistics"].items()}
    result = {"rows": summary["rows"], "trend": performance["total_return"], "stats": stats}
    return {"engine": "duckdb", "scenario": "analyze", "seconds": round(elapsed, 4), "result": result}


WORKERS = {
    ("pandas", "aggregate"): pandas_aggregate,
    ("pandas", "analyze"): pandas_analyze,
    ("duckdb", "aggregate"): duckdb_aggregate,
    ("duckdb", "analyze"): duckdb_analyze,
}


def run_worker(engine: str, scenario: str, path: Path) -> dict:
    completed = subprocess.run(
        [sys.executable, str(Path(__file__).resolve()), "--worker", engine, "--scenario", scenario, "--path", str(path)],
        capture_output=True,
        text=True,
        check=True,
    )
    return json.loads(completed.stdout.strip().splitlines()[-1])


def summarise(runs: list[dict]) -> dict:
    seconds = sorted(run["seconds"] for run in runs)
    memory = sorted(run.get("peak_rss_bytes", 0) for run in runs)
    return {
        "engine": runs[0]["engine"],
        "scenario": runs[0]["scenario"],
        "seconds_median": round(seconds[len(seconds) // 2], 4),
        "seconds_min": round(seconds[0], 4),
        "peak_rss_mb_median": round(memory[len(memory) // 2] / (1024 * 1024), 1),
        "peak_rss_mb_max": round(max(memory) / (1024 * 1024), 1),
        "result": runs[0]["result"],
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Benchmark Pandas vs DuckDB (données synthétiques).")
    parser.add_argument("--rows", type=int, default=1_000_000)
    parser.add_argument("--repeat", type=int, default=3)
    parser.add_argument("--json", type=str, default="")
    parser.add_argument("--worker", choices=["pandas", "duckdb"], help=argparse.SUPPRESS)
    parser.add_argument("--scenario", choices=["aggregate", "analyze"], help=argparse.SUPPRESS)
    parser.add_argument("--path", type=str, help=argparse.SUPPRESS)
    args = parser.parse_args(argv)

    if args.worker and args.scenario:
        payload = WORKERS[(args.worker, args.scenario)](args.path)
        payload["peak_rss_bytes"] = peak_rss_bytes()
        print(json.dumps(payload))
        return 0

    with tempfile.TemporaryDirectory(prefix="come_data_bench_") as tmp:
        root = Path(tmp)
        csv_path = root / "synthetic.csv"
        generate_csv(csv_path, args.rows)
        size_mb = round(csv_path.stat().st_size / (1024 * 1024), 1)

        print(f"Benchmark sur {args.rows:,} lignes synthétiques ({size_mb} Mo), {args.repeat} répétitions.")
        report: dict[str, dict] = {}
        for scenario in ("aggregate", "analyze"):
            scenarios: dict[str, dict] = {}
            for engine in ("pandas", "duckdb"):
                runs = [run_worker(engine, scenario, csv_path) for _ in range(args.repeat)]
                scenarios[engine] = summarise(runs)
            report[scenario] = scenarios

    for scenario, scenarios in report.items():
        pandas_summary = scenarios["pandas"]
        duckdb_summary = scenarios["duckdb"]
        speedup = pandas_summary["seconds_median"] / duckdb_summary["seconds_median"] if duckdb_summary["seconds_median"] else float("nan")
        memory_ratio = duckdb_summary["peak_rss_mb_median"] / pandas_summary["peak_rss_mb_median"] if pandas_summary["peak_rss_mb_median"] else float("nan")
        print()
        print(f"Scénario « {scenario} » — {pandas_summary['result'].get('rows', 0):,} lignes")
        print(f"  {'moteur':<8} {'temps médian (s)':>18} {'pic RSS médian (Mo)':>22}")
        for summary in (pandas_summary, duckdb_summary):
            print(f"  {summary['engine']:<8} {summary['seconds_median']:>18.4f} {summary['peak_rss_mb_median']:>22.1f}")
        print(f"  → DuckDB : x{speedup:.2f} en vitesse, {memory_ratio * 100:.0f} % de la RAM de Pandas")

    if args.json:
        target = Path(args.json)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(report, indent=2), encoding="utf-8")
        print(f"\nRapport JSON : {target}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
