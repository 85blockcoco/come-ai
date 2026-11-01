"""Noyau mathématique pur (academics) — statistiques, probabilités, numérique.

Functions pures, stdlib only (math, statistics). Aucun effet de bord,
aucune exception attendue : les entrées invalides renvoient ``None``.
"""

from __future__ import annotations

import math
import statistics
from collections.abc import Callable

_EPS = 1e-12

# Coefficients de l'approximation d'Acklam pour normal_inv.
_ACKLAM_A = (
    -39.696830286653757, 220.9460984245205, -275.9285104469687,
    138.3577518672690, -30.66479806614716, 2.506628277459239,
)
_ACKLAM_B = (
    -54.47609879822406, 161.5858368580409, -155.6989798598866,
    66.80131188771972, -13.28068155288572,
)
_ACKLAM_C = (
    -0.007784894002430293, -0.3223964580411365, -2.400758277161838,
    -2.549732529341458, 4.374664141464995, 2.938163982698783,
)
_ACKLAM_D = (
    7.784695709041462e-3, 0.3224671290700398, 2.445134137142995,
    3.754408661907416,
)


def mean(values: list[float] | tuple[float, ...]) -> float | None:
    """Moyenne arithmétique ; ``None`` si la série est vide."""
    if not values:
        return None
    return float(statistics.fmean(values))


def median(values: list[float] | tuple[float, ...]) -> float | None:
    """Médiane ; ``None`` si la série est vide."""
    if not values:
        return None
    return float(statistics.median(values))


def mode(values: list[float] | tuple[float, ...]) -> float | None:
    """Valeur la plus fréquente ; ``None`` si la série est vide."""
    if not values:
        return None
    return float(statistics.mode(values))


def percentile(values: list[float] | tuple[float, ...], p: float) -> float | None:
    """Percentile ``p`` (0..100) via ``statistics.quantiles`` ; ``None`` si vide."""
    if not values:
        return None
    if len(values) == 1:
        return float(values[0])
    if p <= 0:
        return float(min(values))
    if p >= 100:
        return float(max(values))
    cuts = statistics.quantiles(values, n=100, method="inclusive")
    return float(cuts[int(p) - 1])


def variance_sample(values: list[float] | tuple[float, ...]) -> float | None:
    """Variance d'échantillon (n-1) ; ``None`` si moins de 2 valeurs."""
    if len(values) < 2:
        return None
    return float(statistics.variance(values))


def values_std(values: list[float] | tuple[float, ...]) -> float | None:
    """Écart-type d'échantillon (n-1) ; ``None`` si moins de 2 valeurs."""
    if len(values) < 2:
        return None
    return float(statistics.stdev(values))


def zscore(value: float, mean: float, std: float) -> float | None:
    """Score z = (value - mean) / std ; ``None`` si std est nul."""
    if abs(std) < _EPS:
        return None
    return (value - mean) / std


def outliers_iqr(values: list[float] | tuple[float, ...], factor: float = 1.5) -> list[int]:
    """Indices des valeurs hors [Q1 - factor*IQR, Q3 + factor*IQR]."""
    if len(values) < 4:
        return []
    q1 = percentile(values, 25)
    q3 = percentile(values, 75)
    if q1 is None or q3 is None:
        return []
    iqr = q3 - q1
    low = q1 - factor * iqr
    high = q3 + factor * iqr
    return [i for i, v in enumerate(values) if v < low or v > high]


def binomial_pmf(k: int, n: int, p: float) -> float | None:
    """P(X = k) pour une binomiale B(n, p) ; ``None`` si p hors [0, 1]."""
    if not 0.0 <= p <= 1.0 or n < 0:
        return None
    if k < 0 or k > n:
        return 0.0
    return math.comb(n, k) * (p ** k) * ((1.0 - p) ** (n - k))


def normal_cdf(x: float, mu: float = 0.0, sigma: float = 1.0) -> float | None:
    """CDF normale N(mu, sigma) via l'approximation ``math.erf`` ; sigma nul → ``None``."""
    if sigma <= 0.0:
        return None
    return 0.5 * (1.0 + math.erf((x - mu) / (sigma * math.sqrt(2.0))))


def normal_inv(p: float) -> float | None:
    """Quantile normal inverse (approx. Acklam simplifiée, tolérance ~1e-3)."""
    if not 0.0 < p < 1.0:
        return None
    a, b, c, d = _ACKLAM_A, _ACKLAM_B, _ACKLAM_C, _ACKLAM_D
    p_low = 0.02425
    if p < p_low:
        q = math.sqrt(-2.0 * math.log(p))
        x = (((((c[0] * q + c[1]) * q + c[2]) * q + c[3]) * q + c[4]) * q + c[5]) / (
            (((d[0] * q + d[1]) * q + d[2]) * q + d[3]) * q + 1.0
        )
    elif p <= 1.0 - p_low:
        q = p - 0.5
        r = q * q
        num = ((((a[0] * r + a[1]) * r + a[2]) * r + a[3]) * r + a[4]) * r + a[5]
        den = ((((b[0] * r + b[1]) * r + b[2]) * r + b[3]) * r + b[4]) * r + 1.0
        x = num * q / den
    else:
        q = math.sqrt(-2.0 * math.log(1.0 - p))
        x = -(((((c[0] * q + c[1]) * q + c[2]) * q + c[3]) * q + c[4]) * q + c[5]) / (
            (((d[0] * q + d[1]) * q + d[2]) * q + d[3]) * q + 1.0
        )
    return x


_Z_TABLE: dict[float, float] = {0.90: 1.6449, 0.95: 1.9600, 0.98: 2.3263, 0.99: 2.5758}


def confidence_interval(
    values: list[float] | tuple[float, ...], confidence: float = 0.95
) -> dict[str, float] | None:
    """IC normal pour la moyenne {mean, low, high, margin} ; ``None`` si n < 2."""
    if len(values) < 2:
        return None
    std = values_std(values)
    if std is None or not 0.0 < confidence < 1.0:
        return None
    z = _Z_TABLE.get(round(confidence, 2))
    if z is None:
        z_inv = normal_inv(0.5 + confidence / 2.0)
        if z_inv is None:
            return None
        z = z_inv
    m = mean(values)
    if m is None:
        return None
    margin = z * std / math.sqrt(len(values))
    return {"mean": m, "margin": margin, "low": m - margin, "high": m + margin}


def linear_fit(xs: list[float] | tuple[float, ...], ys: list[float] | tuple[float, ...]) -> dict[str, float] | None:
    """Régression linéaire des moindres carrés → {slope, intercept, r2, n}.

    Renvoie ``None`` si n < 2 ou si tous les x sont identiques (pente indéfinie).
    """
    n = min(len(xs), len(ys))
    if n < 2:
        return None
    xs_n = xs[:n]
    ys_n = ys[:n]
    x_m = statistics.fmean(xs_n)
    y_m = statistics.fmean(ys_n)
    sxx = sum((x - x_m) ** 2 for x in xs_n)
    if abs(sxx) < _EPS:
        return None
    sxy = sum((x - x_m) * (y - y_m) for x, y in zip(xs_n, ys_n))
    syy = sum((y - y_m) ** 2 for y in ys_n)
    slope = sxy / sxx
    intercept = y_m - slope * x_m
    r2 = 1.0 if abs(syy) < _EPS else (sxy * sxy) / (sxx * syy)
    return {"slope": slope, "intercept": intercept, "r2": r2, "n": float(n)}


def derivative_forward(f: Callable[[float], float], x: float, h: float = 1e-6) -> float | None:
    """Dérivée par différence avant (f(x+h) - f(x)) / h ; ``None`` si h est nul."""
    if abs(h) < _EPS:
        return None
    return (f(x + h) - f(x)) / h


def solve_linear_system(
    matrix: list[list[float]], vector: list[float]
) -> list[float] | None:
    """Résout A·x = b par Gauss à pivot partiel ; ``None`` si singulier ou taille invalide."""
    n = len(matrix)
    if n == 0 or len(vector) != n or any(len(row) != n for row in matrix):
        return None
    aug = [list(row) + [vector[i]] for i, row in enumerate(matrix)]
    for col in range(n):
        pivot_row = max(range(col, n), key=lambda r: abs(aug[r][col]))
        if abs(aug[pivot_row][col]) < _EPS:
            return None
        if pivot_row != col:
            aug[col], aug[pivot_row] = aug[pivot_row], aug[col]
        pivot = aug[col][col]
        for r in range(col + 1, n):
            factor = aug[r][col] / pivot
            for c in range(col, n + 1):
                aug[r][c] -= factor * aug[col][c]
    solution = [0.0] * n
    for row in range(n - 1, -1, -1):
        acc = aug[row][n] - sum(aug[row][c] * solution[c] for c in range(row + 1, n))
        solution[row] = acc / aug[row][row]
    return solution


def polynomial_eval(poly: list[float] | tuple[float, ...], x: float) -> float:
    """Évalue un polynôme (coefficients ordre croissant : poly[i] * x**i) par Horner."""
    if not poly:
        return 0.0
    acc = 0.0
    for coef in reversed(poly):
        acc = acc * x + coef
    return acc


def roots_quadratic(a: float, b: float, c: float) -> dict[str, object] | None:
    """Racines de ax² + bx + c sans lever d'exception.

    - a == 0 et b != 0  → cas linéaire : {"kind": "linear", "real_roots": [...]}
    - a == 0 et b == 0  → ``None``
    - discriminant >= 0 → {"kind": "real", "discriminant": d, "real_roots": [r1, r2]}
    - discriminant < 0  → {"kind": "complex", "discriminant": d, "roots_raw": [z1, z2]}
    """
    if abs(a) < _EPS:
        if abs(b) < _EPS:
            return None
        return {"kind": "linear", "real_roots": [-c / b]}
    discriminant = b * b - 4.0 * a * c
    if discriminant >= 0.0:
        root = math.sqrt(discriminant)
        r1 = (-b + root) / (2.0 * a)
        r2 = (-b - root) / (2.0 * a)
        return {"kind": "real", "discriminant": discriminant, "real_roots": [r1, r2]}
    real = -b / (2.0 * a)
    imag = math.sqrt(-discriminant) / (2.0 * a)
    roots = [complex(real, imag), complex(real, -imag)]
    return {"kind": "complex", "discriminant": discriminant, "roots_raw": roots}
