"""Core finance functions (NAGE-BALANCE-8H, Worker A).

Formules pures de finance: capitalisation, annuités, amortissement,
VAN/TRI, obligations, duration de Macaulay, ratios bancaires et TCAC.

Convention d'erreurs: toute entrée invalide (valeur non numérique,
non finie, périodes négatives, division par zéro, signe incompatible)
retourne None. Aucune exception n'est levée pour une entrée invalide
(choix documenté: le module est destiné à un agent Excel où les cellules
peuvent être vides ou fautives); le None permet un test `is None` simple.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

_YIELD_BOUNDS = (-0.99, 10.0)  # bornes de bisection communes (TRI / rendement)


def _num(x: object) -> float | None:
    """Valide un nombre: accepte int/float finis, sinon None."""
    if isinstance(x, bool) or not isinstance(x, (int, float)):
        return None
    v = float(x)
    if not math.isfinite(v):
        return None
    return v


def future_value(pv: float, rate: float, periods: float) -> float | None:
    """Valeur future: pv * (1 + rate) ** periods."""
    p = _num(pv)
    r = _num(rate)
    n = _num(periods)
    if p is None or r is None or n is None or r <= -1.0 or n < 0:
        return None
    return p * (1.0 + r) ** n


def present_value(fv: float, rate: float, periods: float) -> float | None:
    """Valeur présente: fv / (1 + rate) ** periods."""
    p = _num(fv)
    r = _num(rate)
    n = _num(periods)
    if p is None or r is None or n is None or r <= -1.0 or n < 0:
        return None
    return p / (1.0 + r) ** n


def annuity_pv(pmt: float, rate: float, periods: float) -> float | None:
    """Valeur présente d'une annuité constante fin de période."""
    p = _num(pmt)
    r = _num(rate)
    n = _num(periods)
    if p is None or r is None or n is None or r <= -1.0 or n < 1:
        return None
    if r == 0.0:  # cas limite: pas d'actualisation, PV = pmt * n
        return p * n
    return p * (1.0 - (1.0 + r) ** -n) / r


def annuity_fv(pmt: float, rate: float, periods: float) -> float | None:
    """Valeur future d'une annuité constante fin de période."""
    p = _num(pmt)
    r = _num(rate)
    n = _num(periods)
    if p is None or r is None or n is None or r <= -1.0 or n < 1:
        return None
    if r == 0.0:  # cas limite: pas de capitalisation, FV = pmt * n
        return p * n
    return p * ((1.0 + r) ** n - 1.0) / r


def amortization_schedule(principal: float, rate: float,
                          years: int) -> list[dict[str, float]] | None:
    """Tableau d'amortissement annuel: capital, intérêt, reste dû.

    Retourne une liste de dicts (clés: annee, paiement, capital, interet,
    reste) ou None si entrées invalides (principal > 0, rate > -1, années >= 1).
    """
    p = _num(principal)
    r = _num(rate)
    if p is None or r is None or p <= 0 or r <= -1.0:
        return None
    if not isinstance(years, int) or isinstance(years, bool) or years < 1:
        return None
    if r == 0.0:
        payment = p / years
        reste = p
        rows = []
        for i in range(1, years + 1):
            reste -= payment
            rows.append({
                "annee": float(i),
                "paiement": payment,
                "capital": payment,
                "interet": 0.0,
                "reste": max(reste, 0.0),
            })
        return rows
    a = (1.0 + r) ** -years
    payment = p * r / (1.0 - a)
    reste = p
    rows: list[dict[str, float]] = []
    for i in range(1, years + 1):
        interet = reste * r
        capital = payment - interet
        reste -= capital
        rows.append({
            "annee": float(i),
            "paiement": payment,
            "capital": capital,
            "interet": interet,
            "reste": max(reste, 0.0),
        })
    return rows


def npv(cashflows: list[float], rate: float) -> float | None:
    """Valeur actuelle nette: somme des flux actualisés, t=0 au taux 1."""
    if not isinstance(cashflows, list) or not cashflows:
        return None
    r = _num(rate)
    if r is None or r <= -1.0:
        return None
    total = 0.0
    for t, cf in enumerate(cashflows):
        v = _num(cf)
        if v is None:
            return None
        total += v / (1.0 + r) ** t
    return total


def irr(cashflows: list[float], tol: float = 1e-9) -> float | None:
    """Taux de rendement interne par bisection sur [-0.99, 10.0].

    Retourne None si les flux sont invalides, si tous les flux sont du
    même signe, ou si la bisection ne converge pas (plus de 200 itérations).
    """
    if not isinstance(cashflows, list) or len(cashflows) < 2:
        return None
    flows = []
    for cf in cashflows:
        v = _num(cf)
        if v is None:
            return None
        flows.append(v)
    t = _num(tol)
    if t is None or t <= 0:
        return None
    has_pos = any(v > 0 for v in flows)
    has_neg = any(v < 0 for v in flows)
    if not (has_pos and has_neg):
        return None

    def f(rate: float) -> float:
        return sum(v / (1.0 + rate) ** i for i, v in enumerate(flows))

    lo, hi = _YIELD_BOUNDS
    flo, fhi = f(lo), f(hi)
    if flo * fhi > 0:
        return None  # pas de changement de signe dans les bornes
    for _ in range(200):
        mid = (lo + hi) / 2.0
        fm = f(mid)
        if abs(fm) < tol * max(1.0, abs(flo), abs(fhi)):
            return mid
        if flo * fm <= 0:
            hi, fhi = mid, fm
        else:
            lo, flo = mid, fm
        if hi - lo < tol:
            return (lo + hi) / 2.0
    return None


@dataclass
class BondResult:
    """Résultat d'évaluation d'obligation: prix et duration de Macaulay (années)."""

    price: float
    macaulay_years: float

    def to_dict(self) -> dict[str, float]:
        """Sérialisation simple pour l'agent Excel."""
        return {"price": self.price, "macaulay_years": self.macaulay_years}


def _bond_cashflows(face: float, coupon_rate: float, years: int,
                    freq: int) -> tuple[float, list[tuple[float, float]]] | None:
    """Flux périodiques (temps en années, montant), None si invalide."""
    f = _num(face)
    c = _num(coupon_rate)
    if f is None or c is None or f <= 0 or c < 0:
        return None
    if not isinstance(years, int) or isinstance(years, bool) or years < 1:
        return None
    if not isinstance(freq, int) or isinstance(freq, bool) or freq < 1:
        return None
    n = years * freq
    coupon = f * c / freq
    flows = [(k / freq, coupon) for k in range(1, n)]
    flows.append((years, coupon + f))
    return f, flows


def bond_price(face: float, coupon_rate: float, ytm: float, years: int,
               freq: int = 2) -> float | None:
    """Prix d'une obligation à flux fixes: coupons + nominal actualisés."""
    y = _num(ytm)
    if y is None or y <= -1.0:
        return None
    base = _bond_cashflows(face, coupon_rate, years, freq)
    if base is None:
        return None
    _face, flows = base
    per = 1.0 + y / freq
    return sum(amount / per ** (t * freq) for t, amount in flows)


def macaulay_duration(face: float, coupon_rate: float, ytm: float,
                      years: int, freq: int = 2) -> float | None:
    """Duration de Macaulay en années: moyenne des temps pondérée par prix actualisé."""
    y = _num(ytm)
    if y is None or y <= -1.0:
        return None
    base = _bond_cashflows(face, coupon_rate, years, freq)
    if base is None:
        return None
    _face, flows = base
    per = 1.0 + y / freq
    price = 0.0
    weighted = 0.0
    for t, amount in flows:
        pv_t = amount / per ** (t * freq)
        price += pv_t
        weighted += pv_t * t
    if price == 0.0:
        return None
    return weighted / price


def bond_evaluate(face: float, coupon_rate: float, ytm: float, years: int,
                  freq: int = 2) -> BondResult | None:
    """Prix + duration en un appel (dataclass BondResult)."""
    price = bond_price(face, coupon_rate, ytm, years, freq)
    dur = macaulay_duration(face, coupon_rate, ytm, years, freq)
    if price is None or dur is None:
        return None
    return BondResult(price=price, macaulay_years=dur)


def ytm_from_price(price: float, face: float, coupon_rate: float,
                   years: int, freq: int = 2) -> float | None:
    """Rendement à maturité implicite par bisection sur [-0.99, 10.0].

    Le prix est décroissant en fonction du rendement, la bisection est donc
    adaptée; retourne None si entrées invalides ou non-convergence.
    """
    p = _num(price)
    f = _num(face)
    c = _num(coupon_rate)
    if (p is None or f is None or c is None or p <= 0 or f <= 0 or c < 0
            or not isinstance(years, int) or isinstance(years, bool) or years < 1
            or not isinstance(freq, int) or isinstance(freq, bool) or freq < 1):
        return None
    lo, hi = _YIELD_BOUNDS
    plo = bond_price(face, coupon_rate, lo, years, freq)
    phi = bond_price(face, coupon_rate, hi, years, freq)
    if plo is None or phi is None:
        return None
    # prix décroissant quand le rendement augmente
    if p > plo or p < phi:
        return None
    for _ in range(200):
        mid = (lo + hi) / 2.0
        pmid = bond_price(face, coupon_rate, mid, years, freq)
        if pmid is None:
            return None
        if abs(pmid - p) <= 1e-9 * max(1.0, abs(p)):
            return mid
        if pmid > p:
            lo = mid
        else:
            hi = mid
    return None


def current_ratio(current_assets: float, current_liabilities: float) -> float | None:
    """Ratio de liquidité générale: actif court terme / passif court terme."""
    a = _num(current_assets)
    l = _num(current_liabilities)
    if a is None or l is None or l <= 0:
        return None
    return a / l


def quick_ratio(current_assets: float, inventory: float,
                current_liabilities: float) -> float | None:
    """Ratio de liquidité réduite: (actif court terme - stocks) / passif court terme."""
    a = _num(current_assets)
    s = _num(inventory)
    l = _num(current_liabilities)
    if a is None or s is None or l is None or l <= 0:
        return None
    return (a - s) / l


def debt_to_equity(total_debt: float, equity: float) -> float | None:
    """Ratio d'endettement: dette totale / fonds propres."""
    d = _num(total_debt)
    e = _num(equity)
    if d is None or e is None or e <= 0:
        return None
    return d / e


def net_margin(net_income: float, revenue: float) -> float | None:
    """Marge nette: résultat net / chiffre d'affaires."""
    ni = _num(net_income)
    rev = _num(revenue)
    if ni is None or rev is None or rev <= 0:
        return None
    return ni / rev


def roe(net_income: float, equity: float) -> float | None:
    """Rentabilité des fonds propres: résultat net / capitaux propres."""
    ni = _num(net_income)
    e = _num(equity)
    if ni is None or e is None or e <= 0:
        return None
    return ni / e


def compound_rate(start_value: float, end_value: float,
                  periods: int) -> float | None:
    """TCAC (CAGR): (valeur_finale / valeur_initiale) ** (1/n) - 1."""
    s = _num(start_value)
    e = _num(end_value)
    if s is None or e is None or s <= 0 or e < 0:
        return None
    if not isinstance(periods, int) or isinstance(periods, bool) or periods < 1:
        return None
    return (e / s) ** (1.0 / periods) - 1.0
