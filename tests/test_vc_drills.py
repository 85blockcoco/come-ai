from __future__ import annotations

import time

import pytest

from academics.vc.content import load_content
from academics.vc.drills import (
    cap_table,
    dilution,
    dpi,
    grade_drill,
    irr,
    liquidation_waterfall,
    moic,
    option_pool,
    ownership_after,
    parse_number,
    post_money,
    pre_money,
    random_drill,
    rvpi,
    tvpi,
)
from academics.vc.errors import InputError
from academics.vc.models import FormulaDrill


def test_core_valuation_formulas() -> None:
    assert post_money(8, 2) == 10
    assert pre_money(10, 2) == 8
    assert ownership_after(2, 10) == pytest.approx(0.2)
    assert dilution(8, 2) == pytest.approx(0.2)
    with pytest.raises(InputError):
        pre_money(1, 2)


def test_dilution_with_existing_and_new_shares() -> None:
    assert dilution(80, 20) == pytest.approx(0.2)
    assert dilution(90, 10) == pytest.approx(0.1)
    assert dilution(0, 10) == pytest.approx(1.0)
    with pytest.raises(InputError):
        dilution(0, 0)


def test_option_pool_pre_money_convention() -> None:
    result = option_pool(8, 2, 10)
    assert result["post_money"] == 10
    assert result["pool_value"] == pytest.approx(1.0)
    assert result["investor_ownership"] == pytest.approx(0.2)
    assert result["founder_ownership"] == pytest.approx(0.7)


def test_cap_table_fully_diluted() -> None:
    rows = cap_table(
        [
            {"name": "Fondateurs", "shares": 6},
            {"name": "Pool", "shares": 1},
        ],
        new_shares=3,
    )
    assert sum(row["shares"] for row in rows) == 10
    investor = next(row for row in rows if row["name"] == "Nouveaux investisseurs")
    assert investor["ownership"] == pytest.approx(0.3)
    assert sum(row["ownership"] for row in rows) == pytest.approx(1.0)


def test_non_participating_waterfall() -> None:
    rows = liquidation_waterfall(
        6,
        [
            {"name": "A", "shares": 20, "invested": 2, "preference_multiple": 1},
            {"name": "commun", "shares": 80, "invested": 0},
        ],
    )
    by_name = {row["name"]: row for row in rows}
    assert by_name["A"]["total"] == 2
    assert by_name["commun"]["total"] == 4


def test_participating_waterfall_with_cap() -> None:
    holders = [
        {"name": "A", "shares": 20, "invested": 2, "preference_multiple": 1},
        {"name": "commun", "shares": 80, "invested": 0},
    ]
    uncapped = {row["name"]: row for row in liquidation_waterfall(6, holders, participating=True)}
    assert uncapped["A"]["total"] == pytest.approx(2.8)

    capped = {
        row["name"]: row
        for row in liquidation_waterfall(6, holders, participating=True, cap_multiple=1.2)
    }
    assert capped["A"]["total"] == pytest.approx(2.4)
    assert capped["commun"]["total"] == pytest.approx(3.6)


def test_waterfall_respects_seniority() -> None:
    rows = liquidation_waterfall(
        4,
        [
            {"name": "junior", "shares": 30, "invested": 3, "seniority": 2},
            {"name": "senior", "shares": 20, "invested": 2, "seniority": 1},
        ],
    )
    by_name = {row["name"]: row for row in rows}
    assert by_name["senior"]["total"] == 2
    assert by_name["junior"]["total"] == 2


def test_return_metrics() -> None:
    assert moic(2, 10) == pytest.approx(5)
    assert tvpi(100, 60, 80) == pytest.approx(1.4)
    assert dpi(100, 60) == pytest.approx(0.6)
    assert rvpi(100, 80) == pytest.approx(0.8)
    assert irr([-100, 0, 0, 150]) == pytest.approx(0.144714, rel=1e-4)
    assert irr([1, 2, 3]) is None


def test_parse_number_units_and_separators() -> None:
    assert parse_number("10") == (10.0, "eur")
    assert parse_number("10 M€") == (10.0, "m_eur")
    assert parse_number("10m€") == (10.0, "m_eur")
    assert parse_number("250 k€") == (250.0, "k_eur")
    assert parse_number("12 %") == (12.0, "percent")
    assert parse_number("2,5x") == (2.5, "ratio")
    assert parse_number("1 000") == (1000.0, "eur")
    assert parse_number("1,000") == (1000.0, "eur")
    assert parse_number("1,5") == (1.5, "eur")
    with pytest.raises(ValueError):
        parse_number("")
    with pytest.raises(ValueError):
        parse_number("beaucoup")


def test_non_numeric_answer_is_rejected_without_state() -> None:
    drill = load_content().drill("VC04-D001")
    result = grade_drill(drill, "beaucoup")
    assert result["accepted"] is False
    assert result["diagnostic"] == "unit"
    assert result["given"] is None
    assert drill.answer == 10


def test_error_diagnostics() -> None:
    content = load_content()
    formula = grade_drill(content.drill("VC04-D003"), "25")
    assert formula["diagnostic"] == "formula"
    unit = grade_drill(content.drill("VC04-D003"), "0.2")
    assert unit["diagnostic"] == "unit"
    order = grade_drill(content.drill("VC07-D005"), "3")
    assert order["diagnostic"] == "order"
    missing = grade_drill(content.drill("VC05-D004"), "80")
    assert missing["diagnostic"] == "missing_data"
    convention = grade_drill(content.drill("VC04-D006"), "2")
    assert convention["diagnostic"] == "convention"


def test_alternative_convention_is_accepted_only_when_declared() -> None:
    drill = FormulaDrill(
        id="VC04-D999",
        topic_id="VC04",
        prompt="Un pre-money de 8 M€ et 2 M€ investis. Post-money ?",
        variables={"pre_money": 8, "investment": 2},
        answer=10,
        answer_unit="m_eur",
        tolerance=0.01,
        steps=({"label": "Formule", "expression": "8 + 2", "result": 10},),
        alternative_conventions=({"value": 10.5, "explanation": "Convention déclarée."},),
    )
    accepted = grade_drill(drill, "10.5")
    assert accepted["accepted"] is True
    assert accepted["alternative"] is not None

    undeclared = grade_drill(drill, "11")
    assert undeclared["accepted"] is False
    assert undeclared["alternative"] is None


def test_tolerance_boundaries() -> None:
    drill = load_content().drill("VC04-D001")
    assert grade_drill(drill, "10.01")["accepted"] is True
    assert grade_drill(drill, "10.02")["accepted"] is False
    assert grade_drill(drill, "10 M€")["accepted"] is True


def test_random_drill_is_deterministic() -> None:
    content = load_content()
    first = random_drill(content.drills, topic_id="VC04", seed=7)
    second = random_drill(content.drills, topic_id="VC04", seed=7)
    assert first.id == second.id
    assert first.topic_id == "VC04"
    with pytest.raises(InputError):
        random_drill(content.drills, topic_id="VC99", seed=7)


def test_incomplete_variables_return_missing_data() -> None:
    drill = FormulaDrill(
        id="VC04-D998",
        topic_id="VC04",
        prompt="Énoncé incomplet.",
        variables={},
        answer=10,
        answer_unit="m_eur",
        tolerance=0.01,
        steps=({"label": "Formule", "expression": "?", "result": 10},),
    )
    result = grade_drill(drill, "10")
    assert result["accepted"] is False
    assert result["diagnostic"] == "missing_data"


def test_wrong_answer_never_reveals_another_drill() -> None:
    content = load_content()
    drill = content.drill("VC04-D002")
    result = grade_drill(drill, "3")
    assert result["drill_id"] == drill.id
    assert all(step in [dict(item) for item in drill.steps] for step in result["steps"])
    assert "answer" not in result


def test_grading_one_thousand_drills_is_fast() -> None:
    drill = load_content().drill("VC04-D001")
    started = time.perf_counter()
    for _ in range(1000):
        grade_drill(drill, "10 M€")
    assert time.perf_counter() - started < 1.0
