"""Inspection légère d'un classeur/fichier tabulaire avant tout chargement.

Objectif : découvrir feuilles, entêtes, colonnes, formules, plages fusionnées,
noms définis, dimensions et types apparents **sans** matérialiser le fichier
entier. Pour un ``.xlsx``/``.xlsm`` on ouvre en ``read_only`` et on ne lit que
les premières lignes ; les plages fusionnées sont extraites directement du XML
interne (moins coûteux qu'une seconde ouverture complète).

Seules les données synthétiques servent aux tests ; l'inspection ne modifie
jamais le fichier source.
"""

from __future__ import annotations

import csv
import datetime as _dt
import re
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from xml.etree import ElementTree

from .errors import InspectionError, UnsupportedSpreadsheetError
from .provenance import fingerprint_file

CSV_SUFFIXES = {".csv", ".tsv"}
EXCEL_SUFFIXES = {".xlsx", ".xlsm"}
LEGACY_EXCEL_SUFFIXES = {".xls"}
PARQUET_SUFFIXES = {".parquet"}
SUPPORTED_SUFFIXES = CSV_SUFFIXES | EXCEL_SUFFIXES | LEGACY_EXCEL_SUFFIXES | PARQUET_SUFFIXES

_DEFAULT_SAMPLE_ROWS = 30
_MAX_RESAMPLE_ROWS = 400

#: Marqueurs de valeur manquante, alignés sur le ``nullstr`` du moteur DuckDB,
#: afin que l'inspection voie la même chose que l'exécution SQL.
_MISSING_MARKERS = {"", "na", "nan", "null", "#n/a", "<na>"}

_XML_NS = {
    "main": "http://schemas.openxmlformats.org/spreadsheetml/2006/main",
    "rel": "http://schemas.openxmlformats.org/officeDocument/2006/relationships",
    "pkgrel": "http://schemas.openxmlformats.org/package/2006/relationships",
}


@dataclass(frozen=True)
class ColumnProfile:
    """Profil d'une colonne déduit d'un échantillon de cellules."""

    name: str
    apparent_type: str
    sampled: int
    non_empty: int
    formula_count: int

    def as_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "apparent_type": self.apparent_type,
            "sampled": self.sampled,
            "non_empty": self.non_empty,
            "formula_count": self.formula_count,
        }


@dataclass(frozen=True)
class SheetInspection:
    """Description légère d'une feuille ou d'une source plate."""

    name: str
    max_row: int | None
    max_column: int | None
    headers: tuple[str, ...]
    sample: tuple[tuple[Any, ...], ...]
    columns: tuple[ColumnProfile, ...]
    formula_count: int
    merged_ranges: tuple[str, ...]
    is_empty: bool
    cell_range: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "max_row": self.max_row,
            "max_column": self.max_column,
            "cell_range": self.cell_range,
            "headers": list(self.headers),
            "sample": [list(row) for row in self.sample],
            "columns": [column.as_dict() for column in self.columns],
            "formula_count": self.formula_count,
            "merged_ranges": list(self.merged_ranges),
            "is_empty": self.is_empty,
        }


@dataclass(frozen=True)
class WorkbookInspection:
    """Résultat complet d'une inspection légère."""

    path: str
    file_name: str
    kind: str
    fingerprint: str
    size_bytes: int
    sheets: tuple[SheetInspection, ...]
    defined_names: tuple[tuple[str, str], ...] = ()

    def as_dict(self, *, include_path: bool = True) -> dict[str, Any]:
        data: dict[str, Any] = {
            "file_name": self.file_name,
            "kind": self.kind,
            "fingerprint": self.fingerprint,
            "size_bytes": self.size_bytes,
            "sheet_count": len(self.sheets),
            "sheets": [sheet.as_dict() for sheet in self.sheets],
            "defined_names": [list(item) for item in self.defined_names],
        }
        if include_path:
            data["path"] = self.path
        return data


# --------------------------------------------------------------------------- #
# API principale
# --------------------------------------------------------------------------- #
def inspect_file(
    path: str | Path,
    *,
    sample_rows: int = _DEFAULT_SAMPLE_ROWS,
    include_merged: bool = True,
) -> WorkbookInspection:
    """Inspecte un fichier tabulaire sans le charger entièrement."""
    resolved = Path(path).expanduser()
    if not resolved.is_file():
        raise InspectionError("Ce fichier est introuvable pour l'inspection.")
    suffix = resolved.suffix.lower()
    if suffix not in SUPPORTED_SUFFIXES:
        raise UnsupportedSpreadsheetError(
            "L'inspection lit les CSV, TSV, XLSX, XLSM, XLS et Parquet."
        )
    size = resolved.stat().st_size
    digest = fingerprint_file(resolved)

    if suffix in EXCEL_SUFFIXES:
        sheets, defined = _inspect_excel(resolved, sample_rows, include_merged)
    elif suffix in CSV_SUFFIXES:
        sheets, defined = [_inspect_csv(resolved, sample_rows)], ()
    elif suffix in LEGACY_EXCEL_SUFFIXES:
        sheets, defined = [_inspect_legacy_excel(resolved, sample_rows)], ()
    else:  # parquet
        sheets, defined = [_inspect_parquet(resolved, sample_rows)], ()

    return WorkbookInspection(
        path=str(resolved),
        file_name=resolved.name,
        kind=suffix.lstrip("."),
        fingerprint=digest,
        size_bytes=size,
        sheets=tuple(sheets),
        defined_names=tuple(defined),
    )


# --------------------------------------------------------------------------- #
# Excel moderne (.xlsx / .xlsm)
# --------------------------------------------------------------------------- #
def _inspect_excel(
    path: Path, sample_rows: int, include_merged: bool
) -> tuple[list[SheetInspection], list[tuple[str, str]]]:
    try:
        from openpyxl import load_workbook  # noqa: PLC0415
    except ImportError as error:  # pragma: no cover - dépend de l'environnement
        raise UnsupportedSpreadsheetError(
            "openpyxl est requis pour inspecter un classeur Excel."
        ) from error

    merges: dict[str, list[str]] = _merged_ranges_from_xml(path) if include_merged else {}
    try:
        workbook = load_workbook(path, read_only=True, data_only=False, keep_links=False)
    except Exception as error:  # noqa: BLE001 - message générique
        raise UnsupportedSpreadsheetError("Ce classeur Excel n'a pas pu être inspecté.") from error

    try:
        defined = [
            (name, str(definition.attr_text or ""))
            for name, definition in workbook.defined_names.items()
        ]
        sheets = [
            _sheet_from_openpyxl(worksheet, sample_rows, merges.get(worksheet.title, []))
            for worksheet in workbook.worksheets
        ]
    finally:
        workbook.close()
    return sheets, defined


def _sheet_from_openpyxl(
    worksheet: Any, sample_rows: int, merged: list[str]
) -> SheetInspection:
    max_row = worksheet.max_row
    max_column = worksheet.max_column
    # ``max_row``/``max_column`` peuvent être None si la dimension manque dans
    # le XML : on lit alors un nombre borné de lignes pour rester léger.
    limit = sample_rows if not max_row else min(sample_rows, max(1, max_row))
    sample: list[tuple[Any, ...]] = []
    for index, row in enumerate(worksheet.iter_rows(min_row=1, max_row=limit, values_only=True)):
        sample.append(tuple(_normalize_cell(value) for value in row))
        if index + 1 >= limit:
            break
    headers, data_rows = _split_headers(sample)
    columns = _profile_columns(headers, data_rows)
    formula_count = sum(column.formula_count for column in columns)
    is_empty = not headers and not data_rows
    dimension = worksheet.calculate_dimension() if max_row or max_column else None
    return SheetInspection(
        name=worksheet.title,
        max_row=max_row,
        max_column=max_column,
        headers=tuple(headers),
        sample=tuple(data_rows[:sample_rows]),
        columns=tuple(columns),
        formula_count=formula_count,
        merged_ranges=tuple(merged),
        is_empty=is_empty,
        cell_range=dimension,
    )


# --------------------------------------------------------------------------- #
# CSV / TSV
# --------------------------------------------------------------------------- #
def _inspect_csv(path: Path, sample_rows: int) -> SheetInspection:
    delimiter = "\t" if path.suffix.lower() == ".tsv" else _sniff_delimiter(path)
    sample: list[tuple[Any, ...]] = []
    header: list[str] = []
    with path.open("r", encoding="utf-8-sig", errors="replace", newline="") as handle:
        reader = csv.reader(handle, delimiter=delimiter)
        for index, row in enumerate(reader):
            if index == 0:
                header = [str(item).strip() for item in row]
                continue
            sample.append(tuple(_coerce_text(value) for value in row))
            if len(sample) >= sample_rows:
                break
    headers = header or []
    columns = _profile_columns(headers, sample)
    return SheetInspection(
        name=path.stem,
        max_row=None,
        max_column=len(headers) or None,
        headers=tuple(headers),
        sample=tuple(sample),
        columns=tuple(columns),
        formula_count=0,
        merged_ranges=(),
        is_empty=not headers and not sample,
    )


def _sniff_delimiter(path: Path) -> str:
    try:
        with path.open("r", encoding="utf-8-sig", errors="replace") as handle:
            snippet = handle.read(8192)
        return csv.Sniffer().sniff(snippet, delimiters=",;\t|").delimiter
    except (OSError, csv.Error):
        return ","


# --------------------------------------------------------------------------- #
# Excel ancien (.xls) — via pandas/xlrd, échantillon borné
# --------------------------------------------------------------------------- #
def _inspect_legacy_excel(path: Path, sample_rows: int) -> SheetInspection:
    try:
        import pandas as pd  # noqa: PLC0415
    except ImportError as error:  # pragma: no cover
        raise UnsupportedSpreadsheetError(
            "pandas est requis pour inspecter un ancien classeur .xls."
        ) from error
    try:
        frame = pd.read_excel(path, sheet_name=0, nrows=sample_rows + 1)
    except Exception as error:  # noqa: BLE001
        raise UnsupportedSpreadsheetError("Cet ancien classeur .xls n'a pas pu être inspecté.") from error
    records = [
        tuple(_normalize_cell(value) for value in row)
        for row in frame.itertuples(index=False, name=None)
    ]
    headers, data_rows = _split_headers(records)
    columns = _profile_columns(headers, data_rows)
    return SheetInspection(
        name=str(frame.columns.name or "Sheet1"),
        max_row=None,
        max_column=len(headers) or None,
        headers=tuple(headers),
        sample=tuple(data_rows),
        columns=tuple(columns),
        formula_count=0,
        merged_ranges=(),
        is_empty=not headers and not data_rows,
    )


# --------------------------------------------------------------------------- #
# Parquet — métadonnées via DuckDB, aucun chargement de données
# --------------------------------------------------------------------------- #
def _inspect_parquet(path: Path, sample_rows: int) -> SheetInspection:
    try:
        import duckdb  # noqa: PLC0415
    except ImportError as error:  # pragma: no cover
        raise UnsupportedSpreadsheetError("DuckDB est requis pour inspecter un Parquet.") from error
    try:
        connection = duckdb.connect(":memory:")
        try:
            described = connection.execute(
                "DESCRIBE SELECT * FROM read_parquet(?)", [str(path)]
            ).fetchall()
            sample_rows_data = connection.execute(
                "SELECT * FROM read_parquet(?) LIMIT ?", [str(path), sample_rows]
            ).fetchall()
        finally:
            connection.close()
    except Exception as error:  # noqa: BLE001
        raise UnsupportedSpreadsheetError("Ce fichier Parquet n'a pas pu être inspecté.") from error
    headers = [str(row[0]) for row in described]
    declared = {str(row[0]): str(row[1]) for row in described}
    sample = [tuple(_normalize_cell(value) for value in row) for row in sample_rows_data]
    columns = [
        ColumnProfile(
            name=header,
            apparent_type=_type_from_sql(declared.get(header, "")),
            sampled=len(sample),
            non_empty=sum(1 for row in sample if row[index] is not None),
            formula_count=0,
        )
        for index, header in enumerate(headers)
    ]
    return SheetInspection(
        name=path.stem,
        max_row=None,
        max_column=len(headers) or None,
        headers=tuple(headers),
        sample=tuple(sample),
        columns=tuple(columns),
        formula_count=0,
        merged_ranges=(),
        is_empty=not headers,
    )


# --------------------------------------------------------------------------- #
# Extraction XML des plages fusionnées (léger)
# --------------------------------------------------------------------------- #
def _merged_ranges_from_xml(path: Path) -> dict[str, list[str]]:
    """Lit ``<mergeCell ref="..."/>`` par feuille sans charger les cellules."""
    result: dict[str, list[str]] = {}
    try:
        archive = zipfile.ZipFile(path)
    except (OSError, zipfile.BadZipFile):
        return result
    with archive:
        rels = _sheet_relationships(archive)
        try:
            workbook = ElementTree.fromstring(archive.read("xl/workbook.xml"))
        except (KeyError, ElementTree.ParseError):
            return result
        for sheet in workbook.findall(".//main:sheets/main:sheet", _XML_NS):
            name = sheet.get("name") or ""
            rel_id = sheet.get(f"{{{_XML_NS['rel']}}}id") or ""
            target = rels.get(rel_id)
            if not target:
                result[name] = []
                continue
            member = "xl/" + target.lstrip("/")
            if member not in archive.namelist():
                member = target.lstrip("/")
            result[name] = _read_merge_cells(archive, member)
    return result


def _sheet_relationships(archive: zipfile.ZipFile) -> dict[str, str]:
    try:
        rels = ElementTree.fromstring(archive.read("xl/_rels/workbook.xml.rels"))
    except (KeyError, ElementTree.ParseError):
        return {}
    mapping: dict[str, str] = {}
    for relationship in rels.findall("pkgrel:Relationship", _XML_NS):
        rel_id = relationship.get("Id") or ""
        target = relationship.get("Target") or ""
        mapping[rel_id] = target
    return mapping


def _read_merge_cells(archive: zipfile.ZipFile, member: str) -> list[str]:
    ranges: list[str] = []
    try:
        for event, element in ElementTree.iterparse(archive.open(member), events=("end",)):
            if element.tag == f"{{{_XML_NS['main']}}}mergeCell":
                ref = element.get("ref")
                if ref:
                    ranges.append(ref)
            element.clear()
    except (KeyError, ElementTree.ParseError, OSError):
        return ranges
    return ranges


# --------------------------------------------------------------------------- #
# Aides
# --------------------------------------------------------------------------- #
def _split_headers(sample: list[tuple[Any, ...]]) -> tuple[list[str], list[tuple[Any, ...]]]:
    if not sample:
        return [], []
    raw_header = sample[0]
    headers: list[str] = []
    for index, value in enumerate(raw_header):
        text = "" if value is None else str(value).strip()
        headers.append(text or f"colonne_{index + 1}")
    return headers, list(sample[1:])


def _profile_columns(headers: list[str], rows: list[tuple[Any, ...]]) -> list[ColumnProfile]:
    profiles: list[ColumnProfile] = []
    for index, header in enumerate(headers):
        values = [row[index] for row in rows if index < len(row)]
        non_empty = [value for value in values if value not in (None, "")]
        formulas = sum(1 for value in values if isinstance(value, str) and value.startswith("="))
        profiles.append(
            ColumnProfile(
                name=header,
                apparent_type=_infer_type(non_empty),
                sampled=len(values),
                non_empty=len(non_empty),
                formula_count=formulas,
            )
        )
    return profiles


def _infer_type(values: list[Any]) -> str:
    texts = [value for value in values if not isinstance(value, str) or not value.startswith("=")]
    if not values:
        return "empty"
    if all(isinstance(value, str) and value.startswith("=") for value in values):
        return "formula"
    if not texts:
        return "formula"
    if all(isinstance(value, bool) for value in texts):
        return "boolean"
    if all(isinstance(value, int) and not isinstance(value, bool) for value in texts):
        return "integer"
    if all(isinstance(value, (int, float)) and not isinstance(value, bool) for value in texts):
        return "float"
    if all(isinstance(value, (_dt.datetime, _dt.date)) for value in texts):
        return "date"
    if _all_numeric_text(texts):
        return "float"
    return "string"


def _all_numeric_text(values: list[Any]) -> bool:
    if not values:
        return False
    pattern = re.compile(r"^[+-]?(\d+\.?\d*|\.\d+)([eE][+-]?\d+)?$")
    return all(isinstance(value, str) and pattern.match(value.strip()) for value in values)


def _normalize_cell(value: Any) -> Any:
    if value is None:
        return None
    if isinstance(value, (_dt.datetime, _dt.date)):
        return value.isoformat()
    return value


def _coerce_text(value: str) -> Any:
    text = value.strip()
    if text.lower() in _MISSING_MARKERS:
        return None
    if _all_numeric_text([text]):
        try:
            return float(text) if ("." in text or "e" in text.lower()) else int(text)
        except ValueError:
            return text
    return text


def _type_from_sql(sql_type: str) -> str:
    kind = sql_type.upper()
    if any(token in kind for token in ("INT", "HUGEINT")):
        return "integer"
    if any(token in kind for token in ("DOUBLE", "FLOAT", "REAL", "DECIMAL", "NUMERIC")):
        return "float"
    if "BOOL" in kind:
        return "boolean"
    if "TIMESTAMP" in kind or "DATETIME" in kind:
        return "datetime"
    if "DATE" in kind:
        return "date"
    if "TIME" in kind:
        return "time"
    return "string"


__all__ = [
    "ColumnProfile",
    "LEGACY_EXCEL_SUFFIXES",
    "SUPPORTED_SUFFIXES",
    "SheetInspection",
    "WorkbookInspection",
    "inspect_file",
]
