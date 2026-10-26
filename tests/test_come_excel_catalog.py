"""Tests du catalogue de sources (enregistrement, provenance, isolation)."""

from __future__ import annotations

from pathlib import Path

import pytest

pytest.importorskip("duckdb")
pytest.importorskip("openpyxl")

from come_excel.catalog import SourceCatalog  # noqa: E402
from come_excel.errors import UnsupportedSpreadsheetError  # noqa: E402
from tests.come_excel_helpers import write_budget_workbook, write_csv, write_workbook  # noqa: E402


def make_catalog(tmp_path: Path) -> SourceCatalog:
    data = tmp_path / "data"
    output = tmp_path / "output"
    data.mkdir(exist_ok=True)
    output.mkdir(exist_ok=True)
    return SourceCatalog(data, output)


def test_catalog_registers_csv_with_provenance(tmp_path: Path) -> None:
    catalog = make_catalog(tmp_path)
    try:
        source_file = write_csv(catalog.data_dir / "ventes.csv", "poste;montant\nA;10\nB;20\n")
        source = catalog.add(source_file, count_rows=True)

        assert source.kind == "csv"
        assert source.rows == 2
        assert source.columns == 2
        assert len(source.fingerprint) == 64
        assert source.registered_table
        rows = catalog.query(f'SELECT sum(montant) AS total FROM "{source.registered_table}"')
        assert rows[0]["total"] == 30
        assert len(catalog.sources()) == 1
        assert catalog.audit.entries()[0].operation == "register"
    finally:
        catalog.close()


def test_catalog_is_idempotent_per_file_and_sheet(tmp_path: Path) -> None:
    catalog = make_catalog(tmp_path)
    try:
        path = write_csv(catalog.data_dir / "v.csv", "a\n1\n")
        first = catalog.add(path)
        second = catalog.add(path)
        assert first.source_id == second.source_id
        assert len(catalog.sources()) == 1
    finally:
        catalog.close()


def test_catalog_add_all_sheets_registers_each_tab(tmp_path: Path) -> None:
    catalog = make_catalog(tmp_path)
    try:
        path = write_workbook(
            catalog.data_dir / "classeur.xlsx",
            {"Janvier": [["poste", "montant"], ["A", 1]], "Fevrier": [["poste", "montant"], ["B", 2]]},
        )
        sources = catalog.add_all_sheets(path)
        assert [source.sheet for source in sources] == ["Janvier", "Fevrier"]
        assert all(source.kind == "xlsx" for source in sources)
        assert len({source.source_id for source in sources}) == 2
    finally:
        catalog.close()


def test_catalog_rejects_file_outside_allowed_dirs(tmp_path: Path) -> None:
    catalog = make_catalog(tmp_path)
    try:
        outside = tmp_path / "ailleurs.csv"
        outside.write_text("a\n1\n", encoding="utf-8")
        with pytest.raises(UnsupportedSpreadsheetError):
            catalog.add(outside)
    finally:
        catalog.close()


def test_source_dict_hides_path_by_default(tmp_path: Path) -> None:
    catalog = make_catalog(tmp_path)
    try:
        path = write_csv(catalog.data_dir / "v.csv", "a\n1\n")
        source = catalog.add(path)
        assert "path" not in source.as_dict()
        assert "path" in source.as_dict(include_path=True)
    finally:
        catalog.close()


def test_catalog_rejects_unknown_sheet(tmp_path: Path) -> None:
    catalog = make_catalog(tmp_path)
    try:
        path = write_budget_workbook(catalog.data_dir / "b.xlsx")
        with pytest.raises(UnsupportedSpreadsheetError):
            catalog.add(path, sheet="Inexistante")
    finally:
        catalog.close()
