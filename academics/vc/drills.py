"""Calculs VC déterministes et corrections étape par étape.

Les fonctions utilisent ``Decimal`` pour éviter les erreurs binaires visibles
dans une copie d'examen. Elles ne supposent aucune convention silencieuse :
les unités et les flux sont fournis explicitement par l'appelant.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation, getcontext
from typing import Any

getcontext().prec = 28


def _d(value: Decimal | int | float | str) -> Decimal:
    try:
        result = Decimal(str(value))
    except (InvalidOperation, ValueError):
        raise ValueError("Valeur numérique VC invalide.") from None
    if not result.is_finite():
        raise ValueError("Une valeur VC doit être finie.")
    return result


def post_money(pre_money: Decimal | int | float | str, investment: Decimal | int | float | str) -> dict[str, Any]:
    pre, invest = _d(pre_money), _d(investment)
    if pre < 0 or invest < 0:
        raise ValueError("Pre-money et investissement doivent être positifs.")
    total = pre + invest
    return {"value": total, "unit": "currency", "steps": [
        f"Post-money = pre-money + investissement = {pre} + {invest}",
        f"Post-money = {total}",
    ]}


def ownership_after_investment(pre_money: Decimal | int | float | str, investment: Decimal | int | float | str) -> dict[str, Any]:
    pre, invest = _d(pre_money), _d(investment)
    total = post_money(pre, invest)["value"]
    if total <= 0:
        raise ValueError("La post-money doit être positive.")
    investor = invest / total
    founder = Decimal(1) - investor
    return {"investor": investor, "founders": founder, "unit": "fraction", "steps": [
        f"Part investisseur = investissement / post-money = {invest} / {total}",
        f"Part investisseur = {investor}",
        f"Part fondateurs = 1 - {investor} = {founder}",
    ]}


def dilution(existing_ownership: Decimal | int | float | str, new_investor_ownership: Decimal | int | float | str) -> dict[str, Any]:
    existing, investor = _d(existing_ownership), _d(new_investor_ownership)
    if not 0 <= existing <= 1 or not 0 <= investor <= 1:
        raise ValueError("Les parts doivent être comprises entre 0 et 1.")
    result = existing * (Decimal(1) - investor)
    return {"value": result, "unit": "fraction", "steps": [
        f"Part après dilution = part avant × (1 - nouvelle part) = {existing} × (1 - {investor})",
        f"Part après dilution = {result}",
    ]}


def option_pool_adjusted_ownership(existing_ownership: Decimal | int | float | str, pool_percentage: Decimal | int | float | str) -> dict[str, Any]:
    existing, pool = _d(existing_ownership), _d(pool_percentage)
    if not 0 <= existing <= 1 or not 0 <= pool < 1:
        raise ValueError("La part existante doit être entre 0 et 1 et le pool entre 0 et 1 exclus.")
    result = existing * (Decimal(1) - pool)
    return {"value": result, "unit": "fraction", "steps": [
        f"Part après option pool = part existante × (1 - pool) = {existing} × (1 - {pool})",
        f"Part après option pool = {result}",
    ]}


def moic(distributions: Decimal | int | float | str, paid_in: Decimal | int | float | str) -> dict[str, Any]:
    distributed, paid = _d(distributions), _d(paid_in)
    if distributed < 0 or paid <= 0:
        raise ValueError("Distributions positives et paid-in strictement positif requis.")
    value = distributed / paid
    return {"value": value, "unit": "x", "steps": [f"MOIC = distributions / paid-in = {distributed} / {paid}", f"MOIC = {value}"]}


def dpi(distributions: Decimal | int | float | str, paid_in: Decimal | int | float | str) -> dict[str, Any]:
    result = moic(distributions, paid_in)
    return {**result, "steps": [result["steps"][0].replace("MOIC", "DPI"), result["steps"][1].replace("MOIC", "DPI")]}


def rvpi(residual_value: Decimal | int | float | str, paid_in: Decimal | int | float | str) -> dict[str, Any]:
    residual, paid = _d(residual_value), _d(paid_in)
    if residual < 0 or paid <= 0:
        raise ValueError("Résiduel positif et paid-in strictement positif requis.")
    value = residual / paid
    return {"value": value, "unit": "x", "steps": [f"RVPI = valeur résiduelle / paid-in = {residual} / {paid}", f"RVPI = {value}"]}


def tvpi(distributions: Decimal | int | float | str, residual_value: Decimal | int | float | str, paid_in: Decimal | int | float | str) -> dict[str, Any]:
    distributed, residual, paid = _d(distributions), _d(residual_value), _d(paid_in)
    if distributed < 0 or residual < 0 or paid <= 0:
        raise ValueError("Valeurs positives et paid-in strictement positif requis.")
    value = (distributed + residual) / paid
    return {"value": value, "unit": "x", "steps": [f"TVPI = (distributions + résiduel) / paid-in = ({distributed} + {residual}) / {paid}", f"TVPI = {value}"]}


def irr(cash_flows: list[Decimal | int | float | str], *, periods_per_year: int = 1) -> dict[str, Any]:
    flows = [_d(item) for item in cash_flows]
    if len(flows) < 2 or not any(item < 0 for item in flows) or not any(item > 0 for item in flows):
        raise ValueError("Il faut au moins un flux négatif et un flux positif.")
    if isinstance(periods_per_year, bool) or periods_per_year < 1:
        raise ValueError("La fréquence doit être un entier positif.")

    def npv(rate: Decimal) -> Decimal:
        return sum(value / (Decimal(1) + rate) ** index for index, value in enumerate(flows))

    low, high = Decimal("-0.9999"), Decimal("1000")
    if npv(low) * npv(high) > 0:
        raise ValueError("Les flux ne permettent pas de trouver un IRR dans la borne calculée.")
    for _ in range(160):
        middle = (low + high) / 2
        if npv(low) * npv(middle) <= 0:
            high = middle
        else:
            low = middle
    periodic = (low + high) / 2
    annual = (Decimal(1) + periodic) ** periods_per_year - Decimal(1)
    return {"value": annual, "unit": "fraction", "steps": [
        "IRR : taux qui annule la valeur actuelle nette des flux.",
        f"Flux utilisés : {flows}",
        f"IRR annualisé = {annual}",
    ]}


@dataclass(frozen=True)
class GradeResult:
    correct: bool
    expected: Decimal
    actual: Decimal | None
    tolerance: Decimal
    diagnosis: str
    steps: tuple[str, ...]


def grade_numeric(expected: Decimal | int | float | str, actual: Decimal | int | float | str, *, tolerance: Decimal | int | float | str = "0.0001", steps: list[str] | None = None) -> GradeResult:
    expected_value, tolerance_value = _d(expected), abs(_d(tolerance))
    try:
        actual_value = _d(actual)
    except ValueError:
        return GradeResult(False, expected_value, None, tolerance_value, "format: réponse non numérique", tuple(steps or ()))
    difference = abs(actual_value - expected_value)
    diagnosis = "correct" if difference <= tolerance_value else "valeur: résultat numérique différent"
    return GradeResult(diagnosis == "correct", expected_value, actual_value, tolerance_value, diagnosis, tuple(steps or ()))
