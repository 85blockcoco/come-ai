"""Test C — gros volumes synthétiques, chemin DuckDB de bout en bout.

Construit une fois (portée module) un CSV de plusieurs centaines de milliers de
lignes, puis vérifie des agrégations exactes via la vue paresseuse, la
consolidation de deux copies et les contrôles qualité, sans charger la table en
mémoire Python.
"""

from __future__ import annotations

from pathlib import Path

import pytest

pytest.importorskip("duckdb")

from come_excel.catalog import SourceCatalog  # noqa: E402
from come_excel.consolidate import consolidate  # noqa: E402
from come_excel.quality import analyze_quality  # noqa: E402

ROWS = 200_000


@pytest.fixture(scope="module")
def big_csv(tmp_path_factory: pytest.TempPathFactory) -> Path:
    root = tmp_path_factory.mktemp("bigdata")
    data = root / "data"
    output = root / "output"
    data.mkdir()
    output.mkdir()
    path = data / "mouvements.csv"
    with path.open("w", encoding="utf-8") as handle:
        handle.write("id;groupe;montant\n")
        for index in range(ROWS):
            handle.write(f"{index};G{index % 5};{index}\n")
    return path


def _expected_sum(rows: int) -> int:
    return rows * (rows - 1) // 2


def test_big_csv_exact_aggregation_via_lazy_view(big_csv: Path) -> None:
    catalog = SourceCatalog(big_csv.parent, big_csv.parent.parent / "output")
    try:
        source = catalog.add(big_csv, count_rows=True)
        assert source.rows == ROWS
        total = catalog.query(
            f'SELECT count(*) AS n, sum(montant) AS total FROM "{source.registered_table}"'
        )[0]
        assert total["n"] == ROWS
        assert total["total"] == _expected_sum(ROWS)
        per_group = catalog.query(
            f'SELECT groupe, count(*) AS n FROM "{source.registered_table}" GROUP BY 1 ORDER BY 1'
        )
        assert len(per_group) == 5
        assert sum(row["n"] for row in per_group) == ROWS
    finally:
        catalog.close()


def test_big_consolidation_union_doubles_rows(big_csv: Path) -> None:
    # Deux copies distinctes pour forcer deux sources et un empilement réel.
    second = big_csv.parent / "mouvements_bis.csv"
    if not second.exists():
        second.write_bytes(big_csv.read_bytes())
    catalog = SourceCatalog(big_csv.parent, big_csv.parent.parent / "output")
    try:
        left = catalog.add(big_csv)
        right = catalog.add(second)
        result = consolidate(catalog, [left.source_id, right.source_id], output_table="union_big")
        assert result.rows == 2 * ROWS
        total = catalog.query('SELECT sum(montant) AS total FROM "union_big"')[0]["total"]
        assert total == 2 * _expected_sum(ROWS)
    finally:
        catalog.close()


def test_big_quality_counts_missing_without_full_load(big_csv: Path) -> None:
    catalog = SourceCatalog(big_csv.parent, big_csv.parent.parent / "output")
    try:
        source = catalog.add(big_csv, count_rows=True)
        report = analyze_quality(catalog.engine, source.registered_table)
        assert report.rows == ROWS
        assert report.duplicate_rows == 0
        montant = next(column for column in report.columns if column.column == "montant")
        assert montant.missing == 0
    finally:
        catalog.close()
