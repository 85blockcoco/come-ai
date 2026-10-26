"""Tests des contrôles qualité (manquants, doublons, types mixtes, anomalies)."""

from __future__ import annotations

from pathlib import Path

import pytest

pytest.importorskip("duckdb")

from come_excel.catalog import SourceCatalog  # noqa: E402
from come_excel.quality import analyze_quality  # noqa: E402
from tests.come_excel_helpers import write_csv  # noqa: E402


def make_catalog(tmp_path: Path) -> SourceCatalog:
    data = tmp_path / "data"
    output = tmp_path / "output"
    data.mkdir(exist_ok=True)
    output.mkdir(exist_ok=True)
    return SourceCatalog(data, output)


def test_quality_counts_missing_values(tmp_path: Path) -> None:
    catalog = make_catalog(tmp_path)
    try:
        path = write_csv(catalog.data_dir / "trous.csv", "a;b\n1;x\n;y\n3;\n")
        source = catalog.add(path, count_rows=True)
        report = analyze_quality(catalog.engine, source.registered_table)
        by_name = {column.column: column for column in report.columns}
        assert report.rows == 3
        assert by_name["a"].missing == 1
        assert by_name["b"].missing == 1
    finally:
        catalog.close()


def test_quality_detects_exact_duplicate_rows(tmp_path: Path) -> None:
    catalog = make_catalog(tmp_path)
    try:
        path = write_csv(catalog.data_dir / "dupes.csv", "a;b\n1;x\n1;x\n2;y\n")
        source = catalog.add(path, count_rows=True)
        report = analyze_quality(catalog.engine, source.registered_table)
        assert report.duplicate_rows == 1
        assert any(item["kind"] == "duplicate_rows" for item in report.anomalies())
    finally:
        catalog.close()


def test_quality_flags_numeric_outlier(tmp_path: Path) -> None:
    catalog = make_catalog(tmp_path)
    try:
        values = [10, 20, 30, 40, 50, 60, 70, 80, 90, 1000]
        text = "montant\n" + "\n".join(str(value) for value in values) + "\n"
        path = write_csv(catalog.data_dir / "extreme.csv", text)
        source = catalog.add(path, count_rows=True)
        report = analyze_quality(catalog.engine, source.registered_table)
        montant = next(column for column in report.columns if column.column == "montant")
        assert montant.outliers >= 1
        assert montant.upper_bound is not None
    finally:
        catalog.close()


def test_quality_flags_mixed_types_in_text_column(tmp_path: Path) -> None:
    catalog = make_catalog(tmp_path)
    try:
        # 'erreur' n'est pas un marqueur de valeur manquante : la colonne devient
        # VARCHAR tout en contenant majoritairement des nombres.
        path = write_csv(catalog.data_dir / "mixte.csv", "montant\n10\n20\nerreur\n40\n")
        source = catalog.add(path, count_rows=True)
        report = analyze_quality(catalog.engine, source.registered_table)
        montant = next(column for column in report.columns if column.column == "montant")
        assert montant.non_numeric == 1
        assert any(item["kind"] == "mixed_types" for item in report.anomalies())
    finally:
        catalog.close()


def test_quality_report_is_json_serializable(tmp_path: Path) -> None:
    import json

    catalog = make_catalog(tmp_path)
    try:
        path = write_csv(catalog.data_dir / "ok.csv", "a\n1\n2\n")
        source = catalog.add(path, count_rows=True)
        report = analyze_quality(catalog.engine, source.registered_table)
        payload = json.dumps(report.as_dict())
        assert "columns" in json.loads(payload)
    finally:
        catalog.close()
