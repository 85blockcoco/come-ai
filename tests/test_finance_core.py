"""Tests for finance core functions (NAGE-BALANCE-8H, Worker A)."""

from __future__ import annotations

import importlib
import math

import pytest

fc = importlib.import_module("academics.finance_core")

REL = 1e-6


def test_future_value_ecole() -> None:
    # 1000 EUR a 10% pendant 2 ans = 1210 EUR
    assert fc.future_value(1000, 0.10, 2) == pytest.approx(1210.0, rel=REL)


def test_future_value_inversible() -> None:
    fv = fc.future_value(750.0, 0.035, 12)
    assert fv is not None
    assert fc.present_value(fv, 0.035, 12) == pytest.approx(750.0, rel=REL)


def test_future_value_invalide() -> None:
    assert fc.future_value(1000, -1.5, 2) is None  # taux <= -1
    assert fc.future_value(1000, 0.10, -1) is None  # periodes negatives
    assert fc.future_value(1000, float("nan"), 2) is None
    assert fc.future_value(None, 0.10, 2) is None  # type ignore[call-arg]


def test_present_value() -> None:
    # 1210 EUR dans 2 ans a 10% valent 1000 EUR aujourd'hui
    assert fc.present_value(1210.0, 0.10, 2) == pytest.approx(1000.0, rel=REL)


def test_present_value_invalide() -> None:
    assert fc.present_value(1000, 0.10, -2) is None


def test_annuity_pv() -> None:
    # 1000 EUR/an a 5% pendant 5 ans
    assert fc.annuity_pv(1000, 0.05, 5) == pytest.approx(4329.476670630823, rel=REL)


def test_annuity_fv() -> None:
    assert fc.annuity_fv(1000, 0.05, 5) == pytest.approx(5525.631250000007, rel=REL)


def test_annuity_invalide() -> None:
    assert fc.annuity_pv(1000, 0.0, 5) == pytest.approx(5000.0, rel=REL)  # cas limite r=0
    assert fc.annuity_fv(1000, 0.0, 5) == pytest.approx(5000.0, rel=REL)
    assert fc.annuity_pv(1000, -1.0, 5) is None  # r <= -1
    assert fc.annuity_fv(1000, 0.05, 0) is None  # n < 1


def test_amortization_schedule_50000() -> None:
    rows = fc.amortization_schedule(50000, 0.05, 5)
    assert rows is not None
    assert len(rows) == 5
    # annuite constante
    paiements = {r["paiement"] for r in rows}
    assert len(paiements) == 1
    assert rows[0]["paiement"] == pytest.approx(11548.739906413399, rel=REL)
    # premiere ligne: interet = 50000 * 5%
    assert rows[0]["interet"] == pytest.approx(2500.0, rel=REL)
    # capital rembourse = principal
    assert sum(r["capital"] for r in rows) == pytest.approx(50000.0, rel=REL)
    # reste selon une decroissance stricte vers zero
    assert all(rows[k]["reste"] > rows[k + 1]["reste"] for k in range(4))
    assert rows[-1]["reste"] == pytest.approx(0.0, abs=1e-6)


def test_amortization_zero_rate() -> None:
    rows = fc.amortization_schedule(6000, 0.0, 3)
    assert rows is not None
    assert all(r["interet"] == 0.0 for r in rows)
    assert rows[0]["paiement"] == pytest.approx(2000.0, rel=REL)


def test_amortization_invalide() -> None:
    assert fc.amortization_schedule(-5000, 0.05, 5) is None
    assert fc.amortization_schedule(5000, 0.05, 0) is None
    assert fc.amortization_schedule(5000, -1.2, 5) is None  # type ignore[call-arg]


def test_npv_classique() -> None:
    # -1000, puis 500 et 600 a 10% -> VAN negative
    assert fc.npv([-1000, 500, 600], 0.10) == pytest.approx(-49.586776859504255, rel=REL)


def test_npv_flot_apres_t0() -> None:
    assert fc.npv([100.0], 0.10) == pytest.approx(100.0, rel=REL)


def test_npv_invalide() -> None:
    assert fc.npv([], 0.10) is None
    assert fc.npv([-1000, "x"], 0.10) is None  # type ignore[list-item]


def test_irr_un_an() -> None:
    # investir 1000 et recevoir 1100 -> 10%
    assert fc.irr([-1000, 1100]) == pytest.approx(0.10, rel=1e-4)


def test_irr_trois_ans_npv_nul() -> None:
    flows = [-1000.0, 500.0, 600.0, 200.0]
    r = fc.irr(flows)
    assert r is not None
    # verification par aller-retour: la VAN a TRI doit etre nulle
    assert fc.npv(flows, r) == pytest.approx(0.0, abs=1e-6)


def test_irr_meme_signe() -> None:
    assert fc.irr([100.0, 200.0, 300.0]) is None
    assert fc.irr([-100.0, -50.0]) is None
    assert fc.irr([100.0]) is None  # moins de deux flux


def test_irr_flux_non_numerique() -> None:
    assert fc.irr([-1000, None, 600]) is None  # type ignore[list-item]


def test_bond_prix_par() -> None:
    # coupon = rendement -> prix au pair
    assert fc.bond_price(1000, 0.05, 0.05, 10, freq=2) == pytest.approx(1000.0, rel=REL)


def test_bond_prime_annuel() -> None:
    # bond 6% coupon, 5% rendement, 3 ans
    assert fc.bond_price(1000, 0.06, 0.05, 3, freq=1) == pytest.approx(
        1027.2324802937048, rel=REL
    )


def test_bond_semestriel() -> None:
    assert fc.bond_price(1000, 0.05, 0.0425, 10, freq=2) == pytest.approx(
        1060.5845962904466, rel=REL
    )


def test_bond_invalide() -> None:
    assert fc.bond_price(-1000, 0.05, 0.05, 5) is None
    assert fc.bond_price(1000, -0.05, 0.05, 5) is None
    assert fc.bond_price(1000, 0.05, 0.05, 5, freq=0) is None


def test_ytm_prix_pair() -> None:
    # prix = pair -> rendement = taux coupon
    y = fc.ytm_from_price(1000.0, 1000.0, 0.06, 5, freq=2)
    assert y == pytest.approx(0.06, rel=1e-5)


def test_ytm_aller_retour() -> None:
    ytm = 0.0725
    p = fc.bond_price(1000, 0.06, ytm, 7, freq=1)
    assert p is not None
    back = fc.ytm_from_price(p, 1000.0, 0.06, 7, freq=1)
    assert back == pytest.approx(ytm, rel=1e-5)


def test_ytm_hors_bornes() -> None:
    # prix au dessus du prix a ytm = -0.99: non atteignable -> None
    assert fc.ytm_from_price(1e12, 1000.0, 0.06, 5, freq=2) is None


def test_macaulay_zero_coupon() -> None:
    # zero-coupon: duration = maturite exacte
    assert fc.macaulay_duration(1000, 0.0, 0.08, 5, freq=1) == pytest.approx(5.0, rel=REL)


def test_macaulay_par_3_ans() -> None:
    assert fc.macaulay_duration(1000, 0.06, 0.05, 3, freq=1) == pytest.approx(
        2.835765042257075, rel=REL
    )


def test_bond_result_dataclass_to_dict() -> None:
    r = fc.bond_evaluate(1000, 0.05, 0.0425, 10, freq=2)
    assert r is not None
    d = r.to_dict()
    assert set(d) == {"price", "macaulay_years"}
    assert d["price"] == pytest.approx(1060.5845962904466, rel=REL)
    # entre la maturite et la duree (10 ans) pour une obligation prime
    assert 0.0 < d["macaulay_years"] < 10.0


def test_current_ratio() -> None:
    assert fc.current_ratio(150000, 100000) == pytest.approx(1.5, rel=REL)


def test_quick_ratio() -> None:
    assert fc.quick_ratio(150000, 30000, 100000) == pytest.approx(1.2, rel=REL)


def test_debt_to_equity() -> None:
    assert fc.debt_to_equity(500000, 1000000) == pytest.approx(0.5, rel=REL)
    assert fc.debt_to_equity(500000, 0) is None


def test_net_margin_roe() -> None:
    assert fc.net_margin(50000, 400000) == pytest.approx(0.125, rel=REL)
    assert fc.roe(60000, 300000) == pytest.approx(0.2, rel=REL)


def test_ratios_denominateur_nul() -> None:
    assert fc.current_ratio(150000, 0) is None
    assert fc.quick_ratio(150000, 0, 0) is None
    assert fc.net_margin(50000, 0) is None
    assert fc.roe(60000, 0) is None


def test_ratios_perte_nette() -> None:
    # une perte donne une marge negative, pas une erreur
    assert fc.net_margin(-20000, 400000) == pytest.approx(-0.05, rel=REL)


def test_cagr_ecole() -> None:
    # 1000 -> 1210 en 2 ans = 10% par an
    assert fc.compound_rate(1000, 1210, 2) == pytest.approx(0.10, rel=1e-4)


def test_cagr_doublement() -> None:
    assert fc.compound_rate(10000, 20000, 5) == pytest.approx(
        2.0 ** 0.2 - 1.0, rel=REL
    )


def test_cagr_invalide() -> None:
    assert fc.compound_rate(0, 20000, 5) is None  # valeur initiale nulle
    assert fc.compound_rate(-1000, 20000, 5) is None
    assert fc.compound_rate(1000, 20000, 0) is None
    assert fc.compound_rate(1000, -500, 2) is None  # valeur finale negative


def test_aucune_nan_sortie() -> None:
    # garde-fou: aucune fonction valide ne doit produire NaN/inf
    for valeur in (fc.future_value(1000, 0.1, 2), fc.npv([-1000, 500], 0.05)):
        assert valeur is not None
        assert math.isfinite(valeur)
