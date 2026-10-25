"""Cas financiers complexes : XIRR irrégulier, séries désordonnées, valeurs manquantes, dates dupliquées."""

from __future__ import annotations

from pathlib import Path

import pytest

pytest.importorskip("duckdb")

from come_data import ComeDataEngine  # noqa: E402
from come_data import finance  # noqa: E402


def make_engine(tmp_path: Path) -> ComeDataEngine:
    data = tmp_path / "data"
    output = tmp_path / "output"
    data.mkdir()
    output.mkdir()
    return ComeDataEngine(data, output)


def test_xirr_irregular_intervals(tmp_path: Path) -> None:
    # Flux irréguliers : 2024-01-01 -1000, 2024-03-01 +600, 2025-01-01 +600
    engine = make_engine(tmp_path)
    try:
        path = tmp_path / "data" / "irr.csv"
        path.write_text("date,amount\n2024-01-01,-1000\n2024-03-01,600\n2025-01-01,600\n", encoding="utf-8")
        metrics = engine.cash_flows(path, "amount", date_column="date")
        assert metrics["xirr"] is not None
        # La valeur actuelle nette autour de ce taux doit être proche de 0
        xirr = metrics["xirr"]
        npv = finance.npv(xirr, [-1000, 600, 600], ["2024-01-01", "2024-03-01", "2025-01-01"])
        assert npv == pytest.approx(0.0, abs=1e-4)
    finally:
        engine.close()


def test_xirr_no_sign_change_returns_none(tmp_path: Path) -> None:
    engine = make_engine(tmp_path)
    try:
        path = tmp_path / "data" / "pos.csv"
        path.write_text("date,amount\n2024-01-01,100\n2024-07-01,200\n", encoding="utf-8")
        metrics = engine.cash_flows(path, "amount", date_column="date")
        assert metrics["xirr"] is None
    finally:
        engine.close()


def test_performance_handles_unsorted_time_column(tmp_path: Path) -> None:
    # Données désordonnées : la performance doit fonctionner (trie implicite ou cohérente)
    engine = make_engine(tmp_path)
    try:
        path = tmp_path / "data" / "unsorted.csv"
        path.write_text("date,prix\n2024-01-03,110\n2024-01-01,100\n2024-01-02,105\n", encoding="utf-8")
        # Avec time_column, notre SQL fait ORDER BY t → tri correct.
        report = engine.performance(path, "prix", time_column="date")
        assert report["first_value"] == pytest.approx(100.0)
        assert report["last_value"] == pytest.approx(110.0)
    finally:
        engine.close()


def test_performance_without_time_column_preserves_input_order(tmp_path: Path) -> None:
    engine = make_engine(tmp_path)
    try:
        path = tmp_path / "data" / "order.csv"
        path.write_text("prix\n100\n110\n105\n", encoding="utf-8")
        report = engine.performance(path, "prix")
        assert report["first_value"] == pytest.approx(100.0)
        assert report["last_value"] == pytest.approx(105.0)
    finally:
        engine.close()


def test_series_with_missing_values_ignored(tmp_path: Path) -> None:
    engine = make_engine(tmp_path)
    try:
        path = tmp_path / "data" / "missing.csv"
        path.write_text("date,prix\n2024-01-01,100\n2024-01-02,\n2024-01-03,120\n2024-01-04,NA\n", encoding="utf-8")
        report = engine.performance(path, "prix", time_column="date")
        # La valeur vide et 'NA' sont converties en NULL par le moteur (nullstr),
        # donc deux observations numériques subsistent : 100 et 120. Sans cette
        # conversion la colonne serait inférée VARCHAR et le calcul échouerait.
        assert report["observations"] == 2
    finally:
        engine.close()


def test_duplicates_dates_handled_consistently(tmp_path: Path) -> None:
    engine = make_engine(tmp_path)
    try:
        path = tmp_path / "data" / "dupes.csv"
        path.write_text("date,prix\n2024-01-01,100\n2024-01-01,110\n2024-01-02,120\n", encoding="utf-8")
        # ORDER BY date sans second critère donne résultat déterministe (DuckDB garde ordre stable)
        report = engine.performance(path, "prix", time_column="date")
        assert report["observations"] == 3
    finally:
        engine.close()


def test_pure_xirr_leap_year_dates(tmp_path: Path) -> None:
    # 2024 est bissextile, différence 2024-01-01 à 2025-01-01 = 366 jours
    rate = finance.xirr([-1000, 1200], ["2024-01-01", "2025-01-01"])
    assert rate == pytest.approx(0.20, abs=1e-2)  # tolérance raisonnable (base 365 jours exacte)
