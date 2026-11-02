from decimal import Decimal

import pytest

from academics.vc.drills import (
    dilution,
    grade_numeric,
    irr,
    moic,
    option_pool_adjusted_ownership,
    ownership_after_investment,
    post_money,
    parse_vc_number,
    tvpi,
)


def test_post_money_and_investor_ownership_are_explicit():
    assert post_money(8, 2)["value"] == Decimal("10")
    ownership = ownership_after_investment(8, 2)
    assert ownership["investor"] == Decimal("0.2")
    assert ownership["founders"] == Decimal("0.8")
    assert len(ownership["steps"]) == 3


def test_dilution_and_option_pool_keep_fraction_units():
    assert dilution("0.8", "0.2")["value"] == Decimal("0.64")
    assert option_pool_adjusted_ownership("0.8", "0.1")["value"] == Decimal("0.72")


def test_fund_return_multiples_are_consistent():
    assert moic(30, 10)["value"] == Decimal("3")
    assert tvpi(20, 10, 10)["value"] == Decimal("3")


def test_irr_uses_periodic_cash_flows_and_annualizes():
    result = irr([-100, 0, 121], periods_per_year=1)
    assert abs(result["value"] - Decimal("0.1")) < Decimal("0.0000001")


def test_grading_distinguishes_tolerance_and_non_numeric_answers():
    assert grade_numeric("10", "10.00005", tolerance="0.001").correct
    wrong = grade_numeric("10", "9", steps=["Post-money = pre-money + investment"])
    assert not wrong.correct and wrong.diagnosis.startswith("valeur:")
    invalid = grade_numeric("10", "dix")
    assert invalid.actual is None and invalid.diagnosis.startswith("format:")


def test_vc_units_are_normalized_without_losing_percent_or_multiple():
    assert parse_vc_number("2 M€") == Decimal("2000000")
    assert parse_vc_number("500 k€") == Decimal("500000")
    assert parse_vc_number("20 %") == Decimal("0.2")
    assert parse_vc_number("3x") == Decimal("3")


@pytest.mark.parametrize("arguments", [((-1, 2),), ((8, -2),)])
def test_invalid_money_is_rejected(arguments):
    with pytest.raises(ValueError):
        post_money(*arguments[0])
