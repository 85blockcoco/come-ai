"""Comportement du moteur sur des données volumineuses et corrompues.

Ces tests restent volontairement modestes en taille (quelques centaines de
milliers de lignes) pour tourner vite ; les mesures de mémoire isolées sont
dans ``benchmarks/benchmark_data_engine.py``.
"""

from __future__ import annotations

from pathlib import Path

import pytest

pytest.importorskip("duckdb")

import pandas as pd  # noqa: E402

from come_data import ComeDataEngine  # noqa: E402
from come_data.errors import DataEngineError, UnsupportedDataError  # noqa: E402

ROW_COUNT = 250_000


@pytest.fixture(scope="module")
def big_dataset(tmp_path_factory: pytest.TempPathFactory) -> tuple[Path, Path]:
    base = tmp_path_factory.mktemp("bigdata")
    data, output = base / "data", base / "output"
    data.mkdir()
    output.mkdir()
    path = data / "grand.csv"
    with path.open("w", encoding="utf-8") as handle:
        handle.write("id,date,valeur\n")
        for index in range(ROW_COUNT):
            day = (index % 28) + 1
            month = ((index // 28) % 12) + 1
            # Valeur strictement positive : aucun rendement n'est écarté par prev<>0.
            handle.write(f"{index},2024-{month:02d}-{day:02d},{1000 + index % 1000}\n")
    return base, path


def test_large_csv_aggregation_is_exact(big_dataset: tuple[Path, Path]) -> None:
    base, path = big_dataset
    engine = ComeDataEngine(base / "data", base / "output")
    try:
        assert engine.row_count(path) == ROW_COUNT
        # somme des (1000 + i % 1000) pour i de 0 à N-1 : calculable en Python.
        expected = sum(1000 + index % 1000 for index in range(ROW_COUNT))
        total = engine.engine.scalar(f'SELECT sum("valeur") FROM {_only_table(engine)}')
        assert int(total) == expected
    finally:
        engine.close()


def test_large_csv_performance_uses_time_column(big_dataset: tuple[Path, Path]) -> None:
    base, path = big_dataset
    engine = ComeDataEngine(base / "data", base / "output")
    try:
        report = engine.performance(path, "valeur", time_column="date")
        assert report["observations"] == ROW_COUNT
        assert report["return_observations"] == ROW_COUNT - 1
        assert report["max_drawdown"] is not None
    finally:
        engine.close()


def test_python_path_refuses_unbounded_huge_series(big_dataset: tuple[Path, Path]) -> None:
    base, path = big_dataset
    engine = ComeDataEngine(base / "data", base / "output")
    try:
        info = engine.register(path, name="grand")
        with pytest.raises(DataEngineError):
            engine.finance.performance(info.name, "valeur", max_series_rows=1000)
    finally:
        engine.close()


def test_corrupted_csv_is_reported_safely(tmp_path: Path) -> None:
    data = tmp_path / "data"
    output = tmp_path / "output"
    data.mkdir()
    output.mkdir()
    # Un contenu binaire aléatoire n'a pas d'en-tête CSV exploitable.
    (data / "casse.csv").write_bytes(bytes(range(1, 256)) * 4)
    engine = ComeDataEngine(data, output)
    try:
        with pytest.raises(UnsupportedDataError):
            engine.analyze(data / "casse.csv")
    finally:
        engine.close()


def test_large_aggregation_matches_pandas_sample(big_dataset: tuple[Path, Path]) -> None:
    """Le résultat DuckDB doit correspondre à la lecture Pandas bornée."""
    base, path = big_dataset
    engine = ComeDataEngine(base / "data", base / "output")
    try:
        info = engine.register(path, name="grand")
        duck_sum = engine.engine.scalar(f'SELECT sum("valeur") FROM "{info.name}"')
        pandas_sum = int(pd.read_csv(path, nrows=ROW_COUNT)["valeur"].sum())
        assert int(duck_sum) == pandas_sum
    finally:
        engine.close()


def _only_table(engine: ComeDataEngine) -> str:
    from come_data.safety import quote_identifier

    registered = engine.engine.registered()
    assert len(registered) == 1
    return quote_identifier(registered[0].name)
