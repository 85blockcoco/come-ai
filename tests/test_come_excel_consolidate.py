"""Tests de consolidation multi-classeurs (Test A : structures différentes)."""

from __future__ import annotations

from pathlib import Path

import pytest

pytest.importorskip("duckdb")
pytest.importorskip("openpyxl")

from come_excel.catalog import SourceCatalog  # noqa: E402
from come_excel.consolidate import consolidate, normalize_name  # noqa: E402
from come_excel.errors import ConsolidationError  # noqa: E402
from tests.come_excel_helpers import write_csv, write_workbook  # noqa: E402


def make_catalog(tmp_path: Path) -> SourceCatalog:
    data = tmp_path / "data"
    output = tmp_path / "output"
    data.mkdir(exist_ok=True)
    output.mkdir(exist_ok=True)
    return SourceCatalog(data, output)


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("Montant HT", "montant_ht"),
        ("Chiffre d'affaires", "chiffre_d_affaires"),
        ("Résultat net", "resultat_net"),
        ("  TVA  ", "tva"),
        ("Montant_HT", "montant_ht"),
    ],
)
def test_normalize_name(raw: str, expected: str) -> None:
    assert normalize_name(raw) == expected


def test_union_aligns_heterogeneous_headers(tmp_path: Path) -> None:
    catalog = make_catalog(tmp_path)
    try:
        # Trois structures différentes : casse, espace, séparateur, colonne en plus.
        jan = write_workbook(
            catalog.data_dir / "janvier.xlsx",
            {"Janvier": [["poste", "montant"], ["A", 10], ["B", 20]]},
        )
        fev = write_workbook(
            catalog.data_dir / "fevrier.xlsx",
            {"Fevrier": [["Poste", "Montant", "TVA"], ["C", 30, 6], ["D", 40, 8]]},
        )
        mars = write_csv(catalog.data_dir / "mars.csv", "poste;montant\nE;50\nF;60\n")

        sources = [catalog.add(jan), catalog.add(fev), catalog.add(mars)]
        result = consolidate(catalog, [s.source_id for s in sources], output_table="ventes")

        assert result.rows == 6
        assert result.mode == "union"
        assert {"poste", "montant", "tva", "_source_file", "_source_sheet", "_source_row"} <= set(
            result.columns
        )

        # Provenance complète : chaque ligne sait d'où elle vient.
        rows = catalog.query(
            'SELECT _source_file, _source_sheet, count(*) AS n FROM "ventes" '
            "GROUP BY 1, 2 ORDER BY 1"
        )
        assert {row["_source_file"] for row in rows} == {"janvier.xlsx", "fevrier.xlsx", "mars.csv"}

        # Traçabilité colonne → sources.
        lineage = {item.output_column: item for item in result.lineage}
        assert any(ref.startswith("mars.csv") for ref in lineage["montant"].sources)
        assert any(ref.startswith("fevrier.xlsx#Fevrier") for ref in lineage["tva"].sources)
        assert lineage["tva"].sources  # TVA absente de janvier → source non listée
    finally:
        catalog.close()


def test_union_reports_duplicate_rows_across_sources(tmp_path: Path) -> None:
    catalog = make_catalog(tmp_path)
    try:
        a = write_csv(catalog.data_dir / "a.csv", "poste;montant\nA;10\n")
        b = write_csv(catalog.data_dir / "b.csv", "poste;montant\nA;10\n")
        sources = [catalog.add(a), catalog.add(b)]
        result = consolidate(catalog, [s.source_id for s in sources], output_table="u")
        assert result.rows == 2
        assert result.duplicate_rows == 1
        assert any(entry.operation == "quality:duplicates" for entry in result.audit.entries())
    finally:
        catalog.close()


def test_join_matches_on_normalized_key(tmp_path: Path) -> None:
    catalog = make_catalog(tmp_path)
    try:
        ventes = write_csv(catalog.data_dir / "ventes.csv", "produit;montant\nA;10\nB;20\n")
        prix = write_csv(catalog.data_dir / "prix.csv", "Produit;prix\nA;1.5\nB;2.5\n")
        left = catalog.add(ventes)
        right = catalog.add(prix)
        result = consolidate(
            catalog,
            [left.source_id, right.source_id],
            mode="join",
            on=["produit"],
            output_table="joint",
        )
        assert result.rows == 2
        joined = catalog.query('SELECT produit, montant, prix FROM "joint" ORDER BY produit')
        assert joined[0] == {"produit": "A", "montant": 10, "prix": 1.5}
        assert result.columns  # colonne homonyme éventuelle suffixée
    finally:
        catalog.close()


def test_join_requires_all_keys_in_every_source(tmp_path: Path) -> None:
    catalog = make_catalog(tmp_path)
    try:
        a = write_csv(catalog.data_dir / "a.csv", "id;x\n1;10\n")
        b = write_csv(catalog.data_dir / "b.csv", "autre;y\n1;20\n")
        left = catalog.add(a)
        right = catalog.add(b)
        with pytest.raises(ConsolidationError):
            consolidate(catalog, [left.source_id, right.source_id], mode="join", on=["id"], output_table="j")
    finally:
        catalog.close()


def test_consolidation_result_is_json_serializable(tmp_path: Path) -> None:
    import json

    catalog = make_catalog(tmp_path)
    try:
        a = write_csv(catalog.data_dir / "a.csv", "poste;montant\nA;10\n")
        source = catalog.add(a)
        result = consolidate(catalog, [source.source_id], output_table="solo")
        payload = json.dumps(result.as_dict())
        assert json.loads(payload)["rows"] == 1
    finally:
        catalog.close()
