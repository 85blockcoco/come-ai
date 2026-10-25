"""Tests du moteur DuckDB : lecture, profils, export, erreurs et compatibilité."""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import pytest

pytest.importorskip("duckdb")

from come_data import ComeDataEngine  # noqa: E402
from come_data.errors import DataEngineError, UnsafeQueryError, UnsupportedDataError  # noqa: E402


def make_engine(tmp_path: Path) -> ComeDataEngine:
    data = tmp_path / "data"
    output = tmp_path / "output"
    data.mkdir()
    output.mkdir()
    return ComeDataEngine(data, output)


def write_csv(directory: Path, name: str, text: str) -> Path:
    path = directory / name
    path.write_text(text, encoding="utf-8")
    return path


def test_analyze_csv_reports_shape_and_types(tmp_path: Path) -> None:
    engine = make_engine(tmp_path)
    try:
        path = write_csv(
            tmp_path / "data", "ventes.csv",
            "mois;revenus;couts\nJanvier;100;60\nFévrier;130;80\nMars;110;72\n",
        )
        result = engine.analyze(path).as_dict()
        assert result["rows"] == 3
        assert result["columns"] == 3
        assert result["column_names"] == ["mois", "revenus", "couts"]
        assert result["numeric_statistics"]["revenus"]["sum"] == pytest.approx(340.0)
        # Le résultat doit être sérialisable pour les autres agents.
        json.dumps(result)
    finally:
        engine.close()


def test_analyze_tsv_with_tab_delimiter(tmp_path: Path) -> None:
    engine = make_engine(tmp_path)
    try:
        path = write_csv(tmp_path / "data", "d.tsv", "a\tb\n1\t2\n3\t4\n")
        result = engine.analyze(path).as_dict()
        assert result["rows"] == 2
        assert result["column_names"] == ["a", "b"]
    finally:
        engine.close()


def test_preview_is_json_safe_and_bounded(tmp_path: Path) -> None:
    engine = make_engine(tmp_path)
    try:
        rows = "".join(f"2024-01-{day:02d},{day}\n" for day in range(1, 11))
        path = write_csv(tmp_path / "data", "dates.csv", "date,value\n" + rows)
        preview = engine.preview(path, rows=3)
        assert len(preview) == 3
        # La date doit être normalisée en texte ISO, jamais un Timestamp brut.
        assert isinstance(preview[0]["date"], str)
        assert preview[0]["date"].startswith("2024-01-01")
        json.dumps(preview)
    finally:
        engine.close()


def test_numeric_statistics_matches_pandas(tmp_path: Path) -> None:
    engine = make_engine(tmp_path)
    try:
        path = write_csv(
            tmp_path / "data", "m.csv",
            "x,y\n1,10\n2,20\n3,30\n4,40\n",
        )
        engine.register(path, name="m")
        stats = engine.engine.numeric_statistics("m")
        frame = pd.read_csv(path)
        for column in ("x", "y"):
            series = frame[column]
            # Les statistiques sont arrondies à 4 décimales comme dans workspace_core.
            assert stats[column]["sum"] == pytest.approx(round(float(series.sum()), 4))
            assert stats[column]["mean"] == pytest.approx(round(float(series.mean()), 4))
            assert stats[column]["median"] == pytest.approx(round(float(series.median()), 4))
            assert stats[column]["std_dev"] == pytest.approx(round(float(series.std(ddof=0)), 4))
    finally:
        engine.close()


def test_excel_round_trip(tmp_path: Path) -> None:
    engine = make_engine(tmp_path)
    try:
        source = tmp_path / "data" / "classeur.xlsx"
        pd.DataFrame({"produit": ["A", "B"], "prix": [10, 20]}).to_excel(source, index=False)
        result = engine.analyze(source).as_dict()
        assert result["rows"] == 2
        assert result["numeric_statistics"]["prix"]["sum"] == pytest.approx(30.0)
    finally:
        engine.close()


def test_corrupted_excel_is_rejected(tmp_path: Path) -> None:
    engine = make_engine(tmp_path)
    try:
        bad = tmp_path / "data" / "corrompu.xlsx"
        bad.write_bytes(b"ce n'est pas un zip valide")
        with pytest.raises(UnsupportedDataError):
            engine.analyze(bad)
    finally:
        engine.close()


def test_missing_file_is_rejected(tmp_path: Path) -> None:
    engine = make_engine(tmp_path)
    try:
        with pytest.raises(UnsupportedDataError):
            engine.analyze(tmp_path / "data" / "absent.csv")
    finally:
        engine.close()


def test_unsupported_suffix_is_rejected(tmp_path: Path) -> None:
    engine = make_engine(tmp_path)
    try:
        path = tmp_path / "data" / "note.txt"
        path.write_text("hello", encoding="utf-8")
        with pytest.raises(UnsupportedDataError):
            engine.analyze(path)
    finally:
        engine.close()


def test_register_outside_allowed_dirs_is_rejected(tmp_path: Path) -> None:
    engine = make_engine(tmp_path)
    try:
        outside = tmp_path / "hors_workspace.csv"
        outside.write_text("a\n1\n", encoding="utf-8")
        with pytest.raises(UnsafeQueryError):
            engine.register(outside)
    finally:
        engine.close()


def test_query_file_uses_alias_and_parameters(tmp_path: Path) -> None:
    engine = make_engine(tmp_path)
    try:
        path = write_csv(tmp_path / "data", "n.csv", "v\n1\n2\n3\n4\n")
        rows = engine.query_file(path, "SELECT v FROM data WHERE v > ? ORDER BY v", params=[2])
        assert rows == [{"v": 3}, {"v": 4}]
    finally:
        engine.close()


def test_query_rejects_write_sql(tmp_path: Path) -> None:
    engine = make_engine(tmp_path)
    try:
        with pytest.raises(UnsafeQueryError):
            engine.query("DROP TABLE data")
    finally:
        engine.close()


def test_register_frame_and_duplicate_names(tmp_path: Path) -> None:
    engine = make_engine(tmp_path)
    try:
        first = engine.register_frame(pd.DataFrame({"a": [1, 2, 3]}), "donnees")
        second = engine.register_frame(pd.DataFrame({"b": [4, 5]}), "donnees")
        assert first.name != second.name
        assert engine.engine.row_count(first.name) == 3
        assert engine.engine.row_count(second.name) == 2
    finally:
        engine.close()


def test_materialize_csv_view_into_table(tmp_path: Path) -> None:
    engine = make_engine(tmp_path)
    try:
        path = write_csv(tmp_path / "data", "v.csv", "v\n1\n2\n3\n")
        info = engine.register(path, name="v", )
        assert info.kind == "view"
        table = engine.engine.register_file(path, name="v_table", materialize=True)
        assert table.kind == "table"
        assert engine.engine.row_count(table.name) == 3
    finally:
        engine.close()


def test_export_rows_to_csv_and_xlsx_neutralizes_formulas(tmp_path: Path) -> None:
    engine = make_engine(tmp_path)
    try:
        rows = [{"nom": "=SUM(A1:A2)", "valeur": 3}]
        csv_path = engine.export_rows(rows, "rapport.csv")
        assert csv_path.is_file()
        assert csv_path.read_text(encoding="utf-8").splitlines()[1].startswith("'=SUM") or "'=SUM" in csv_path.read_text(encoding="utf-8")
        xlsx_path = engine.export_rows(rows, "rapport.xlsx")
        assert xlsx_path.is_file()
        loaded = pd.read_excel(xlsx_path)
        assert loaded.iloc[0]["nom"] == "'=SUM(A1:A2)"
    finally:
        engine.close()


def test_export_query_to_csv(tmp_path: Path) -> None:
    engine = make_engine(tmp_path)
    try:
        path = write_csv(tmp_path / "data", "x.csv", "a\n1\n2\n3\n")
        engine.register(path, name="x")
        target = engine.export_query("SELECT sum(a) AS total FROM x", "total.csv")
        assert target.is_file()
        assert "6" in target.read_text(encoding="utf-8")
    finally:
        engine.close()


def test_context_manager_closes_engine(tmp_path: Path) -> None:
    data = tmp_path / "data"
    data.mkdir()
    (tmp_path / "output").mkdir()
    with ComeDataEngine(data, tmp_path / "output") as engine:
        assert engine.engine is not None
    # Après fermeture, toute nouvelle requête doit échouer proprement.
    with pytest.raises(DataEngineError):
        engine.engine.row_count("inexistant")
