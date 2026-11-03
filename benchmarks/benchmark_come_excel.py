#!/usr/bin/env python
"""Benchmark reproductible de ``come_excel`` sur données **synthétiques**.

Mesure, dans un processus isolé (pic RSS propre), les phases réelles de
l'Objectif 1 : génération, inspection légère, enregistrement (catalogue),
consolidation, contrôle qualité et export CSV. Aucune donnée personnelle.

Exemples :

    .venv/bin/python -m benchmarks.benchmark_come_excel --files 12 --rows 100000
    .venv/bin/python -m benchmarks.benchmark_come_excel --files 4 --rows 25000 --json benchmarks/results/come_excel_smoke.json
"""

from __future__ import annotations

import argparse
import json
import resource
import sys
import tempfile
import time
from pathlib import Path

BENCH_DIR = Path(__file__).resolve().parent


def peak_rss_bytes() -> int:
    usage = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    return int(usage) if sys.platform == "darwin" else int(usage) * 1024


def generate_monthly(data_dir: Path, files: int, rows: int) -> list[Path]:
    paths: list[Path] = []
    for month in range(1, files + 1):
        path = data_dir / f"mois_{month:02d}.csv"
        with path.open("w", encoding="utf-8") as handle:
            handle.write("date;poste;montant;quantite\n")
            for index in range(rows):
                handle.write(f"2024-{month:02d}-{(index % 28) + 1:02d};P{index % 50};{index}.5;{1 + index % 7}\n")
        paths.append(path)
    return paths


def run(files: int, rows: int) -> dict:
    from come_excel.catalog import SourceCatalog
    from come_excel.consolidate import consolidate
    from come_excel.inspect import inspect_file
    from come_excel.quality import analyze_quality

    report: dict = {"files": files, "rows_per_file": rows, "total_rows": files * rows}
    with tempfile.TemporaryDirectory(prefix="come_excel_bench_") as tmp:
        root = Path(tmp)
        data = root / "data"
        output = root / "output"
        data.mkdir()
        output.mkdir()

        started = time.perf_counter()
        paths = generate_monthly(data, files, rows)
        report["generate_seconds"] = round(time.perf_counter() - started, 4)
        report["disk_mb"] = round(sum(path.stat().st_size for path in paths) / (1024 * 1024), 1)

        started = time.perf_counter()
        for path in paths:
            inspect_file(path)
        report["inspect_seconds"] = round(time.perf_counter() - started, 4)

        with SourceCatalog(data, output) as catalog:
            started = time.perf_counter()
            sources = [catalog.add(path) for path in paths]
            report["register_seconds"] = round(time.perf_counter() - started, 4)

            started = time.perf_counter()
            result = consolidate(catalog, [source.source_id for source in sources], output_table="consolide")
            report["consolidate_seconds"] = round(time.perf_counter() - started, 4)
            report["consolidated_rows"] = result.rows

            started = time.perf_counter()
            quality = analyze_quality(catalog.engine, result.table)
            report["quality_seconds"] = round(time.perf_counter() - started, 4)
            report["anomalies"] = len(quality.anomalies())

            started = time.perf_counter()
            catalog.engine.export_query_to_csv(
                f'SELECT * FROM "{result.table}"', output / "export.csv"
            )
            report["export_seconds"] = round(time.perf_counter() - started, 4)

        report["peak_rss_mb"] = round(peak_rss_bytes() / (1024 * 1024), 1)
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Benchmark come_excel (données synthétiques).")
    parser.add_argument("--files", type=int, default=12)
    parser.add_argument("--rows", type=int, default=100_000)
    parser.add_argument("--json", type=str, default="")
    args = parser.parse_args(argv)

    report = run(args.files, args.rows)
    print(json.dumps(report, indent=2))
    if args.json:
        target = Path(args.json)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(report, indent=2), encoding="utf-8")
        print(f"\nRapport JSON : {target}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
