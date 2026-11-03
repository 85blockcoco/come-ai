"""Tests for math core (academics) — statistiques, probabilités, numérique."""

from __future__ import annotations

import math

from academics.math_core import (
    binomial_pmf,
    confidence_interval,
    derivative_forward,
    linear_fit,
    mean,
    median,
    mode,
    normal_cdf,
    normal_inv,
    outliers_iqr,
    percentile,
    polynomial_eval,
    roots_quadratic,
    solve_linear_system,
    values_std,
    variance_sample,
    zscore,
)


# --- Statistiques descriptives -------------------------------------------------


def test_mean_known() -> None:
    assert mean([1, 2, 3, 4, 5]) == 3.0


def test_median_odd() -> None:
    assert median([1, 3, 5, 7, 9]) == 5.0


def test_median_even() -> None:
    assert median([1, 2, 3, 4]) == 2.5


def test_mode_basic() -> None:
    assert mode([1, 2, 2, 3]) == 2.0


def test_percentile_median_matches() -> None:
    assert percentile([1, 2, 3, 4, 5], 50) == 3.0


def test_variance_sample_known() -> None:
    # variance d'échantillon de [1, 2, 3, 4] = 1.6666...
    assert abs(variance_sample([1, 2, 3, 4]) - 5.0 / 3.0) < 1e-9


def test_std_of_ones_is_zero() -> None:
    assert values_std([4, 4, 4, 4]) == 0.0


def test_zscore_known() -> None:
    assert zscore(15, mean=10.0, std=2.5) == 2.0


def test_zscore_zero_std() -> None:
    assert zscore(15, mean=10.0, std=0.0) is None


def test_outliers_iqr_detects_outlier() -> None:
    # 100 est nettement hors de [Q1-1.5*IQR, Q3+1.5*IQR]
    values = [2, 3, 4, 5, 6, 7, 8, 100]
    assert outliers_iqr(values) == [7]


def test_outliers_iqr_no_outlier() -> None:
    assert outliers_iqr([1, 2, 3, 4, 5]) == []


def test_outliers_iqr_small_series() -> None:
    assert outliers_iqr([1, 2]) == []


# --- Probabilités ---------------------------------------------------------------


def test_binomial_pmf_fair_coin() -> None:
    assert abs(binomial_pmf(2, 3, 0.5) - 0.375) < 1e-12


def test_binomial_pmf_k_equals_n() -> None:
    assert abs(binomial_pmf(3, 3, 0.5) - 0.125) < 1e-12


def test_binomial_pmf_out_of_range() -> None:
    assert binomial_pmf(4, 3, 0.5) == 0.0


def test_normal_cdf_at_mean() -> None:
    assert abs(normal_cdf(0) - 0.5) < 1e-9


def test_normal_cdf_shifted() -> None:
    assert abs(normal_cdf(10, mu=10, sigma=2) - 0.5) < 1e-9


def test_normal_cdf_one_sigma() -> None:
    assert abs(normal_cdf(1) - 0.8413447) < 1e-5


def test_normal_inv_median() -> None:
    assert abs(normal_inv(0.5)) < 1e-3


def test_normal_inv_symmetry() -> None:
    p_inv = normal_inv(0.975)
    assert p_inv is not None
    assert abs(p_inv - 1.9600) < 1e-3


def test_normal_inv_extreme_side() -> None:
    lo = normal_inv(0.01)
    assert lo is not None
    assert abs(lo + 2.326) < 1e-3


# --- Intervalle de confiance ----------------------------------------------------


def test_confidence_interval_known() -> None:
    values = [20.0, 24.0, 28.0, 32.0, 40.0]
    ci = confidence_interval(values, confidence=0.95)
    assert ci is not None
    assert abs(ci["mean"] - 28.8) < 1e-9
    assert abs(ci["high"] - ci["low"] - 2 * ci["margin"]) < 1e-9
    assert ci["low"] < ci["mean"] < ci["high"]


def test_confidence_interval_too_few_values() -> None:
    assert confidence_interval([1.0]) is None


# --- Régression linéaire --------------------------------------------------------


def test_linear_fit_perfect_line() -> None:
    fit = linear_fit([1, 2, 3, 4], [2, 4, 6, 8])
    assert fit is not None
    assert abs(fit["slope"] - 2.0) < 1e-9
    assert abs(fit["intercept"]) < 1e-9
    assert abs(fit["r2"] - 1.0) < 1e-9
    assert fit["n"] == 4.0


def test_linear_fit_with_intercept() -> None:
    # y = 3x + 1
    fit = linear_fit([0, 1, 2], [1, 4, 7])
    assert fit is not None
    assert abs(fit["slope"] - 3.0) < 1e-9
    assert abs(fit["intercept"] - 1.0) < 1e-9


def test_linear_fit_constant_y() -> None:
    fit = linear_fit([1, 2, 3], [5, 5, 5])
    assert fit is not None
    assert abs(fit["slope"]) < 1e-9
    assert fit["r2"] == 1.0


def test_linear_fit_degenerate_x() -> None:
    assert linear_fit([2, 2, 2], [1, 2, 3]) is None


# --- Analyse numérique ----------------------------------------------------------


def test_derivative_of_square() -> None:
    value = derivative_forward(lambda x: x * x, 3.0)
    assert value is not None
    assert abs(value - 6.0) < 1e-3


def test_derivative_of_cos() -> None:
    value = derivative_forward(math.cos, 0.0)
    assert value is not None
    assert abs(value) < 1e-5


def test_solve_linear_system_known() -> None:
    # x + y = 5 ; 2x - y = 1  →  x = 2, y = 3
    solution = solve_linear_system([[1, 1], [2, -1]], [5, 1])
    assert solution is not None
    assert abs(solution[0] - 2.0) < 1e-9
    assert abs(solution[1] - 3.0) < 1e-9


def test_solve_linear_system_singular() -> None:
    assert solve_linear_system([[1, 2], [2, 4]], [1, 2]) is None


def test_polynomial_eval_cubic() -> None:
    # 2 + 1*x + 0*x^2 + 3*x^3 à x = 2 → 2 + 2 + 24 = 28
    assert polynomial_eval([2, 1, 0, 3], 2.0) == 28.0


def test_polynomial_eval_empty() -> None:
    assert polynomial_eval([], 5.0) == 0.0


# --- Racines quadratiques --------------------------------------------------------


def test_quadratic_two_real_roots() -> None:
    # x² - 3x + 2 = 0 → racines 1 et 2
    res = roots_quadratic(1, -3, 2)
    assert res is not None
    assert res["kind"] == "real"
    assert sorted(res["real_roots"]) == [1.0, 2.0]  # type: ignore[type-var]


def test_quadratic_double_root() -> None:
    res = roots_quadratic(1, -2, 1)
    assert res is not None
    assert res["kind"] == "real"
    assert abs(res["real_roots"][0] - 1.0) < 1e-9  # type: ignore[index]


def test_quadratic_complex_roots() -> None:
    res = roots_quadratic(1, 0, 1)
    assert res is not None
    assert res["kind"] == "complex"
    assert res["discriminant"] < 0  # type: ignore[operator]
    roots = res["roots_raw"]
    assert isinstance(roots, list)
    assert abs(roots[0].real) < 1e-9 and abs(roots[0].imag - 1.0) < 1e-9


def test_quadratic_linear_case() -> None:
    res = roots_quadratic(0, 2, -4)
    assert res is not None
    assert res["kind"] == "linear"
    assert abs(res["real_roots"][0] - 2.0) < 1e-9  # type: ignore[index]


def test_quadratic_degenerate() -> None:
    assert roots_quadratic(0, 0, 5) is None
