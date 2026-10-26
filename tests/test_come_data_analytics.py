"""Tests des métriques financières exécutées par DuckDB.

On vérifie que le chemin SQL (grandes séries) et le chemin Python (fonctions
pures) donnent exactement les mêmes résultats sur une petite série connue.
"""

from __future__ import annotations

import math
from pathlib import Path

import pytest

pytest.importorskip("duckdb")

from come_data import ComeDataEngine  # noqa: E402
from come_data import finance  # noqa: E402

SERIES = [100.0, 110.0, 99.0, 120.0, 115.0, 130.0]


def make_engine_with_series(tmp_path: Path) -> tuple[ComeDataEngine, Path]:
    data = tmp_path / "data"
    output = tmp_path / "output"
    data.mkdir()
    output.mkdir()
    lines = ["date,price"]
    for index, value in enumerate(SERIES):
        lines.append(f"2024-01-{index + 1:02d},{value}")
    path = data / "prix.csv"
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return ComeDataEngine(data, output), path


def test_sql_and_python_performance_paths_agree(tmp_path: Path) -> None:
    engine, path = make_engine_with_series(tmp_path)
    try:
        via_time = engine.performance(path, "price", time_column="date")
        via_order = engine.performance(path, "price")
        for key in ("total_return", "annualized_return", "annualized_volatility", "sharpe_ratio", "max_drawdown"):
            assert via_time[key] == pytest.approx(via_order[key]), f"désaccord sur {key}"
        # Vérification indépendante par les fonctions pures.
        returns = finance.simple_returns(SERIES)
        assert via_time["total_return"] == pytest.approx(finance.total_return(SERIES))
        assert via_time["mean_return"] == pytest.approx(sum(returns) / len(returns))
        assert via_time["annualized_volatility"] == pytest.approx(
            finance.annualized_volatility(returns, periods_per_year=252)
        )
        assert via_time["max_drawdown"] == pytest.approx(finance.max_drawdown(SERIES)["max_drawdown"])
    finally:
        engine.close()


def test_performance_reports_risk_free_rate_and_note(tmp_path: Path) -> None:
    engine, path = make_engine_with_series(tmp_path)
    try:
        report = engine.performance(path, "price", time_column="date", risk_free_rate=0.02)
        assert report["risk_free_rate"] == 0.02
        assert "conseil" in report["interpretation"]
        assert report["observations"] == len(SERIES)
        assert report["return_observations"] == len(SERIES) - 1
    finally:
        engine.close()


def test_moving_average_and_returns_frames(tmp_path: Path) -> None:
    engine, path = make_engine_with_series(tmp_path)
    try:
        info = engine.register(path, name="prix")
        ma = engine.finance.moving_average(info.name, "price", 3, time_column="date")
        assert ma["moving_average"].tolist()[2] == pytest.approx((100 + 110 + 99) / 3)
        assert math.isnan(ma["moving_average"].tolist()[0])
        returns = engine.finance.returns_frame(info.name, "price", time_column="date")
        assert returns["r"].tolist()[0] == pytest.approx(0.10)
    finally:
        engine.close()


def test_cash_flow_metrics_with_dates(tmp_path: Path) -> None:
    data = tmp_path / "data"
    output = tmp_path / "output"
    data.mkdir()
    output.mkdir()
    (data / "flux.csv").write_text(
        "date,amount\n2023-01-01,-1000\n2024-01-01,1100\n", encoding="utf-8"
    )
    engine = ComeDataEngine(data, output)
    try:
        metrics = engine.cash_flows(data / "flux.csv", "amount", date_column="date")
        assert metrics["total_outflows"] == pytest.approx(-1000.0)
        assert metrics["total_inflows"] == pytest.approx(1100.0)
        assert metrics["net_cash_flow"] == pytest.approx(100.0)
        # XIRR sur exactement 365 jours : 10 %.
        assert metrics["xirr"] == pytest.approx(0.10, abs=1e-6)
    finally:
        engine.close()


def test_period_summary_and_running_balance(tmp_path: Path) -> None:
    data = tmp_path / "data"
    output = tmp_path / "output"
    data.mkdir()
    output.mkdir()
    (data / "mouvements.csv").write_text(
        "date,montant\n2024-01-05,100\n2024-01-20,-30\n2024-02-10,50\n", encoding="utf-8"
    )
    engine = ComeDataEngine(data, output)
    try:
        monthly = engine.period_summary(data / "mouvements.csv", "date", period="month", amount_column="montant")
        assert {row["total"] for row in monthly} == {70, 50}
        info = engine.register(data / "mouvements.csv", name="mouv")
        balance = engine.finance.running_balance(info.name, "montant", date_column="date")
        assert balance["balance"].tolist() == [100, 70, 120]
    finally:
        engine.close()


def test_profit_and_loss_with_costs(tmp_path: Path) -> None:
    data = tmp_path / "data"
    output = tmp_path / "output"
    data.mkdir()
    output.mkdir()
    (data / "trades.csv").write_text(
        "valeur,cout\n120,100\n90,100\n150,100\n", encoding="utf-8"
    )
    engine = ComeDataEngine(data, output)
    try:
        result = engine.profit_and_loss(data / "trades.csv", "valeur", cost_column="cout")
        assert result["total_pnl"] == pytest.approx(60.0)
        assert result["win_rate"] == pytest.approx(2 / 3)
    finally:
        engine.close()


def test_group_summary(tmp_path: Path) -> None:
    engine, path = make_engine_with_series(tmp_path)
    try:
        rows = engine.group_summary(path, "date", aggregate="count(*)")
        assert len(rows) == len(SERIES)
    finally:
        engine.close()
