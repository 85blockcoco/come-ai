"""Tests de l'inspection légère (Objectif 1, phase préalable au chargement)."""

from __future__ import annotations

from pathlib import Path

import pytest

openpyxl = pytest.importorskip("openpyxl")

from come_excel.errors import InspectionError, UnsupportedSpreadsheetError  # noqa: E402
from come_excel.inspect import inspect_file  # noqa: E402
from tests.come_excel_helpers import write_budget_workbook, write_csv, write_workbook  # noqa: E402


def test_inspect_xlsx_discovers_sheets_headers_and_types(tmp_path: Path) -> None:
    path = write_budget_workbook(tmp_path / "budget.xlsx")
    inspection = inspect_file(path)

    assert inspection.kind == "xlsx"
    assert inspection.file_name == "budget.xlsx"
    assert [sheet.name for sheet in inspection.sheets] == ["Budget", "Notes"]

    budget = inspection.sheets[0]
    assert budget.headers == ("poste", "2023", "2024")
    assert budget.max_row == 6
    types = {column.name: column.apparent_type for column in budget.columns}
    assert types["poste"] == "string"
    assert types["2023"] == "integer"


def test_inspect_xlsx_detects_formulas_and_merges_and_names(tmp_path: Path) -> None:
    path = write_budget_workbook(tmp_path / "budget.xlsx")
    inspection = inspect_file(path)

    budget = inspection.sheets[0]
    assert budget.formula_count >= 3  # C3, B4, C4
    assert "A6:B6" in budget.merged_ranges
    assert ("Taux_Croissance", "Budget!$C$2") in inspection.defined_names


def test_inspect_does_not_modify_source(tmp_path: Path) -> None:
    path = write_budget_workbook(tmp_path / "budget.xlsx")
    before = path.read_bytes()
    inspect_file(path)
    assert path.read_bytes() == before


def test_inspect_csv_sniffs_semicolon_and_types(tmp_path: Path) -> None:
    path = write_csv(tmp_path / "ventes.csv", "poste;montant\nA;10\nB;20.5\n")
    inspection = inspect_file(path)

    assert inspection.kind == "csv"
    sheet = inspection.sheets[0]
    assert sheet.headers == ("poste", "montant")
    types = {column.name: column.apparent_type for column in sheet.columns}
    assert types["poste"] == "string"
    assert types["montant"] == "float"


def test_inspect_csv_treats_na_as_empty(tmp_path: Path) -> None:
    path = write_csv(tmp_path / "trous.csv", "date;prix\n2024-01-01;100\n2024-01-02;NA\n2024-01-03;\n")
    sheet = inspect_file(path).sheets[0]
    prix = next(column for column in sheet.columns if column.name == "prix")
    # 'NA' et vide ne comptent pas comme valeurs non vides.
    assert prix.non_empty == 1


def test_inspect_unsupported_suffix_is_rejected(tmp_path: Path) -> None:
    path = tmp_path / "notes.txt"
    path.write_text("hello", encoding="utf-8")
    with pytest.raises(UnsupportedSpreadsheetError):
        inspect_file(path)


def test_inspect_missing_file_raises(tmp_path: Path) -> None:
    with pytest.raises(InspectionError):
        inspect_file(tmp_path / "absent.xlsx")


def test_inspect_multiple_sheets_shapes(tmp_path: Path) -> None:
    path = write_workbook(
        tmp_path / "multi.xlsx",
        {
            "Alpha": [["k", "v"], ["a", 1], ["b", 2]],
            "Beta": [["x"], [True]],
        },
    )
    inspection = inspect_file(path)
    assert [sheet.name for sheet in inspection.sheets] == ["Alpha", "Beta"]
    beta = inspection.sheets[1]
    assert beta.headers == ("x",)
    assert beta.columns[0].apparent_type == "boolean"
