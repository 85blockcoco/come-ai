"""Tests d'exactitude des fonctions financières pures (sans DuckDB).

Les valeurs attendues sont calculées à la main dans les commentaires afin que
chaque assertion soit vérifiable sans faire confiance à l'implémentation.
"""

from __future__ import annotations

import math

import pytest

from come_data import finance


def test_simple_returns_are_exact() -> None:
    # (110-100)/100=0.10 ; (99-110)/110=-0.10 ; (120-99)/99=0.212121...
    returns = finance.simple_returns([100, 110, 99, 120])
    assert returns[0] == pytest.approx(0.10)
    assert returns[1] == pytest.approx(-0.10)
    assert returns[2] == pytest.approx(21 / 99)


def test_simple_returns_handle_zero_start() -> None:
    # Une valeur précédente nulle ne doit pas lever ZeroDivisionError.
    assert finance.simple_returns([0, 5, 10]) == [0.0, 1.0]


def test_log_returns_ignore_non_positive() -> None:
    values = finance.log_returns([1.0, math.e, 0.0])
    assert values == pytest.approx([1.0])  # ln(e/1)=1, la paire avec 0 est ignorée


def test_total_return_and_cagr() -> None:
    assert finance.total_return([100, 121]) == pytest.approx(0.21)
    # Une seule période, périodicité annuelle : CAGR = 121/100 - 1 = 0.21.
    assert finance.cagr([100, 121], periods_per_year=1) == pytest.approx(0.21)
    # Deux périodes sur un an : (121/100)**(1/2) - 1 = 0.10.
    assert finance.cagr([100, 110, 121], periods_per_year=1) == pytest.approx(0.10)


def test_volatility_and_sharpe_are_annualized() -> None:
    returns = [0.01, 0.02, -0.01, 0.03]
    expected_std = finance.sample_stdev(returns, ddof=1)
    assert finance.annualized_volatility(returns, periods_per_year=252) == pytest.approx(
        expected_std * math.sqrt(252)
    )
    expected_mean = sum(returns) / len(returns)
    expected_sharpe = (expected_mean * 252 - 0.0) / (expected_std * math.sqrt(252))
    assert finance.sharpe_ratio(returns, 0.0, 252) == pytest.approx(expected_sharpe)
    # Un écart-type nul ne doit pas produire de division par zéro.
    assert finance.sharpe_ratio([0.0, 0.0, 0.0], 0.0, 252) is None


def test_max_drawdown_matches_manual_computation() -> None:
    # Série 100 -> 120 (sommet) -> 90 (creux) : drawdown = 90/120 - 1 = -0.25.
    result = finance.max_drawdown([100, 120, 90, 130])
    assert result["max_drawdown"] == pytest.approx(-0.25)
    assert result["peak_index"] == 1
    assert result["trough_index"] == 2


def test_drawdown_series_bounds() -> None:
    series = finance.drawdown_series([100, 110, 99, 105])
    assert series[0] == 0.0
    assert series[2] == pytest.approx(99 / 110 - 1)
    assert all(-1.0 <= item <= 0.0 for item in series)


def test_moving_average_window() -> None:
    values = finance.moving_average([1, 2, 3, 4, 5], 3)
    assert values[0] is None and values[1] is None
    assert values[2] == pytest.approx(2.0)  # (1+2+3)/3
    assert values[4] == pytest.approx(4.0)  # (3+4+5)/3
    with pytest.raises(Exception):
        finance.moving_average([1, 2, 3], 0)


def test_npv_of_known_flows() -> None:
    # -1000 aujourd'hui, +1100 l'année suivante à 10 % : VAN = 0.
    assert finance.npv(0.10, [-1000, 1100], ["2023-01-01", "2024-01-01"]) == pytest.approx(0.0, abs=1e-6)


def test_xirr_exact_one_year() -> None:
    # 2023-01-01 -> 2024-01-01 = 365 jours exactement : XIRR = 10 %.
    rate = finance.xirr([-1000, 1100], ["2023-01-01", "2024-01-01"])
    assert rate == pytest.approx(0.10, abs=1e-6)


def test_xirr_returns_none_without_sign_change() -> None:
    assert finance.xirr([100, 200], ["2023-01-01", "2024-01-01"]) is None
    assert finance.xirr([-100], ["2023-01-01"]) is None


def test_xirr_matches_npv_root() -> None:
    flows = [-5000, 1500, 1500, 1500, 1500]
    dates = ["2024-01-01", "2024-07-01", "2025-01-01", "2025-07-01", "2026-01-01"]
    rate = finance.xirr(flows, dates)
    assert rate is not None
    assert finance.npv(rate, flows, dates) == pytest.approx(0.0, abs=1e-5)


def test_profit_and_loss_with_costs() -> None:
    result = finance.profit_and_loss([120, 90, 150], [100, 100, 100])
    assert result["count"] == 3
    assert result["total_pnl"] == pytest.approx(60.0)  # (20 - 10 + 50)
    assert result["win_rate"] == pytest.approx(2 / 3)
    assert result["best"] == pytest.approx(50.0)


def test_profit_and_loss_without_costs_uses_series() -> None:
    result = finance.profit_and_loss([5, -2, 3])
    assert result["total_pnl"] == pytest.approx(6.0)
    assert result["win_rate"] == pytest.approx(2 / 3)
