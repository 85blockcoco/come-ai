"""Venture Capital formulas, unit normalization and deterministic grading."""

from __future__ import annotations

import math
import random
import re
from typing import Any, Iterable, Sequence

from academics.finance_core import irr as _finance_irr

from .errors import InputError
from .models import FormulaDrill

MONEY_FACTORS = {"eur": 1.0, "k_eur": 1_000.0, "m_eur": 1_000_000.0}
UNIT_LABELS = {
    "eur": "€",
    "k_eur": "k€",
    "m_eur": "M€",
    "percent": "%",
    "ratio": "x",
    "years": "ans",
}


def _number(value: Any, label: str) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError) as error:
        raise InputError(f"{label} must be a number.") from error
    if not math.isfinite(number):
        raise InputError(f"{label} must be finite.")
    return number


def parse_number(raw: str, default_unit: str = "eur") -> tuple[float, str]:
    """Parse a learner answer into a value and a display unit.

    Accepted examples: ``10``, ``10 M€``, ``10m€``, ``12 %``, ``2.5x``,
    ``1 000``, ``1,000``.  A comma followed by exactly three digits is treated
    as a thousands separator; otherwise it is a decimal comma.
    """
    if not isinstance(raw, str):
        raw = str(raw)
    text = raw.strip().replace("\u00a0", " ").replace("\u202f", " ").lower()
    if not text:
        raise ValueError("Empty answer: provide a number.")

    unit = default_unit
    if "%" in text:
        unit = "percent"
        text = text.replace("%", "")
    elif "k€" in text or "keur" in text or "k eur" in text:
        unit = "k_eur"
        text = re.sub(r"k\s*€|k\s*eur", "", text)
    elif "m€" in text or "meur" in text or "m eur" in text:
        unit = "m_eur"
        text = re.sub(r"m\s*€|m\s*eur", "", text)
    elif "€" in text or "eur" in text:
        unit = "eur"
        text = re.sub(r"€|eur", "", text)
    elif text.endswith("x"):
        unit = "ratio"
        text = text[:-1]

    text = text.replace(" ", "").replace("_", "")
    if "," in text and "." in text:
        text = text.replace(",", "")
    elif "," in text:
        before, _, after = text.partition(",")
        if len(after) == 3 and before and len(before.replace("-", "")) <= 3:
            text = before + after
        else:
            text = before + "." + after
    text = text.replace("+", "")
    if not re.fullmatch(r"-?\d+(?:\.\d+)?", text):
        raise ValueError(f"Non-numeric answer: {raw!r}.")
    return float(text), unit


def normalize_to_unit(value: float, unit: str, target: str) -> float:
    if unit == target:
        return value
    if unit in MONEY_FACTORS and target in MONEY_FACTORS:
        return value * MONEY_FACTORS[unit] / MONEY_FACTORS[target]
    if {unit, target} == {"percent", "ratio"}:
        return value / 100.0 if unit == "percent" else value * 100.0
    raise ValueError(f"Incompatible unit: {unit} to {target}.")


def _non_negative(value: Any, label: str) -> float:
    number = _number(value, label)
    if number < 0:
        raise InputError(f"{label} cannot be negative.")
    return number


def post_money(pre_money: float, investment: float) -> float:
    return _non_negative(pre_money, "pre-money") + _non_negative(investment, "investissement")


def pre_money(post_money_value: float, investment: float) -> float:
    result = _non_negative(post_money_value, "post-money") - _non_negative(
        investment, "investissement"
    )
    if result < 0:
        raise InputError("Post-money cannot be lower than the investment.")
    return result


def ownership_after(investment: float, post_money_value: float) -> float:
    post = _non_negative(post_money_value, "post-money")
    if post == 0:
        raise InputError("Post-money must be positive.")
    return _non_negative(investment, "investissement") / post


def dilution(existing_shares: float, new_shares: float) -> float:
    existing = _non_negative(existing_shares, "actions existantes")
    new = _non_negative(new_shares, "nouvelles actions")
    total = existing + new
    if total == 0:
        raise InputError("Total shares must be positive.")
    return new / total


def option_pool(pre_money_value: float, investment: float, pool_percent: float) -> dict[str, float]:
    """Return the post-money, pool value and ownership after the pool.

    ``pool_percent`` accepts ``12`` or ``0.12`` for 12 %.  The pool is taken
    from the post-money and is therefore borne by the founders before the
    round, which is the usual pre-money option-pool convention.
    """
    pre = _non_negative(pre_money_value, "pre-money")
    inv = _non_negative(investment, "investissement")
    pool = _number(pool_percent, "option pool")
    if pool > 1:
        pool = pool / 100.0
    if not 0 <= pool < 1:
        raise InputError("Option pool must be between 0 and 100%.")
    post = pre + inv
    pool_value = post * pool
    investor = inv / post if post else 0.0
    founders = 1.0 - investor - pool
    return {
        "post_money": post,
        "pool_value": pool_value,
        "investor_ownership": investor,
        "founder_ownership": founders,
    }


def cap_table(
    holders: Sequence[dict[str, Any]], new_shares: float = 0
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    total = _non_negative(new_shares, "nouvelles actions")
    for holder in holders:
        shares = _non_negative(holder.get("shares", 0), "actions")
        total += shares
        rows.append({"name": str(holder.get("name", "actionnaire")), "shares": shares})
    if total == 0:
        raise InputError("Total shares must be positive.")
    if new_shares:
        rows.append({"name": "Nouveaux investisseurs", "shares": float(new_shares)})
    return [
        {
            "name": row["name"],
            "shares": row["shares"],
            "ownership": round(row["shares"] / total, 6),
        }
        for row in rows
    ]


def liquidation_waterfall(
    proceeds: float,
    holders: Sequence[dict[str, Any]],
    *,
    participating: bool = False,
    cap_multiple: float | None = None,
) -> list[dict[str, Any]]:
    """Allocate exit proceeds with seniority and optional participation.

    Convention: non-participating preferred receives its preference only;
    common holders share the residual.  Participating preferred shares the
    residual pro-rata, optionally capped at ``invested * cap_multiple``.
    """
    remaining = _non_negative(proceeds, "produit de sortie")
    if cap_multiple is not None and cap_multiple <= 0:
        raise InputError("Cap multiple must be positive.")
    prepared: list[dict[str, Any]] = []
    for holder in holders:
        shares = _non_negative(holder.get("shares", 0), "actions")
        invested = _non_negative(holder.get("invested", 0), "investissement")
        multiple = _number(holder.get("preference_multiple", 1.0), "preference multiple")
        if multiple < 0:
            raise InputError("Le preference multiple cannot be negative.")
        prepared.append(
            {
                "name": str(holder.get("name", "actionnaire")),
                "shares": shares,
                "invested": invested,
                "preference_multiple": multiple,
                "seniority": int(holder.get("seniority", 0)),
                "preference": 0.0,
                "residual": 0.0,
            }
        )
    prepared.sort(key=lambda item: (item["seniority"], item["name"]))

    for row in prepared:
        if row["invested"] > 0 and remaining > 0:
            amount = min(remaining, row["invested"] * row["preference_multiple"])
            row["preference"] = amount
            remaining -= amount

    if remaining > 0:
        if participating:
            eligible = [row for row in prepared if row["shares"] > 0]
            for _ in range(10):
                if remaining <= 0 or not eligible:
                    break
                total_shares = sum(row["shares"] for row in eligible)
                if total_shares <= 0:
                    break
                capped: list[dict[str, Any]] = []
                for row in eligible:
                    proposed = remaining * row["shares"] / total_shares
                    cap = row["invested"] * cap_multiple if cap_multiple and row["invested"] else None
                    if cap is not None and row["preference"] + row["residual"] + proposed > cap:
                        capped.append(row)
                if not capped:
                    for row in eligible:
                        row["residual"] += remaining * row["shares"] / total_shares
                    remaining = 0.0
                    break
                for row in capped:
                    cap = row["invested"] * cap_multiple
                    room = min(remaining, max(0.0, cap - row["preference"] - row["residual"]))
                    row["residual"] += room
                    remaining -= room
                    eligible.remove(row)
            if remaining > 0 and eligible:
                total_shares = sum(row["shares"] for row in eligible)
                if total_shares > 0:
                    for row in eligible:
                        row["residual"] += remaining * row["shares"] / total_shares
                    remaining = 0.0
        else:
            common = [row for row in prepared if row["invested"] == 0 and row["shares"] > 0]
            pool = common or [row for row in prepared if row["shares"] > 0]
            total_shares = sum(row["shares"] for row in pool)
            if total_shares > 0:
                for row in pool:
                    row["residual"] += remaining * row["shares"] / total_shares
                remaining = 0.0

    result: list[dict[str, Any]] = []
    for row in sorted(prepared, key=lambda item: item["name"]):
        total = row["preference"] + row["residual"]
        result.append(
            {
                "name": row["name"],
                "preference": round(row["preference"], 2),
                "residual": round(row["residual"], 2),
                "total": round(total, 2),
                "multiple": round(total / row["invested"], 4) if row["invested"] else None,
            }
        )
    return result


def moic(invested: float, exit_value: float) -> float:
    base = _non_negative(invested, "investissement")
    if base == 0:
        raise InputError("Investment must be positive.")
    return _non_negative(exit_value, "valeur de sortie") / base


def irr(cashflows: Sequence[float]) -> float | None:
    values = [_number(value, "flux") for value in cashflows]
    if len(values) < 2:
        raise InputError("At least two cash flows are required.")
    return _finance_irr(values)


def tvpi(contributions: float, distributions: float, residual: float) -> float:
    base = _non_negative(contributions, "contributions")
    if base == 0:
        raise InputError("Contributions must be positive.")
    return (
        _non_negative(distributions, "distributions")
        + _non_negative(residual, "residual value")
    ) / base


def dpi(contributions: float, distributions: float) -> float:
    base = _non_negative(contributions, "contributions")
    if base == 0:
        raise InputError("Contributions must be positive.")
    return _non_negative(distributions, "distributions") / base


def rvpi(contributions: float, residual: float) -> float:
    base = _non_negative(contributions, "contributions")
    if base == 0:
        raise InputError("Contributions must be positive.")
    return _non_negative(residual, "residual value") / base


def grade_drill(drill: FormulaDrill, raw_answer: str) -> dict[str, Any]:
    expected = float(drill.answer)
    tolerance = max(float(drill.tolerance), abs(expected) * 1e-6)
    steps = [dict(step) for step in drill.steps]
    if not drill.variables or any(value is None for value in drill.variables.values()):
        return {
            "drill_id": drill.id,
            "accepted": False,
            "expected": expected,
            "expected_unit": drill.answer_unit,
            "given": None,
            "steps": steps,
            "diagnostic": "missing_data",
            "message": "Incomplete variables: the statement does not allow a calculation.",
            "alternative": None,
        }
    try:
        value, unit = parse_number(raw_answer, drill.answer_unit)
        given = normalize_to_unit(value, unit, drill.answer_unit)
    except (ValueError, InputError) as error:
        return {
            "drill_id": drill.id,
            "accepted": False,
            "expected": expected,
            "expected_unit": drill.answer_unit,
            "given": None,
            "steps": steps,
            "diagnostic": "unit",
            "message": str(error),
            "alternative": None,
        }

    if abs(given - expected) <= tolerance:
        return {
            "drill_id": drill.id,
            "accepted": True,
            "expected": expected,
            "expected_unit": drill.answer_unit,
            "given": {"value": round(given, 6), "unit": drill.answer_unit},
            "steps": steps,
            "diagnostic": None,
            "message": "Correct answer.",
            "alternative": None,
        }

    for alternative in drill.alternative_conventions:
        alt_value = float(alternative.get("value", 0))
        if abs(given - alt_value) <= tolerance:
            return {
                "drill_id": drill.id,
                "accepted": True,
                "expected": expected,
                "expected_unit": drill.answer_unit,
                "given": {"value": round(given, 6), "unit": drill.answer_unit},
                "steps": steps,
                "diagnostic": None,
                "message": "Alternative convention accepted.",
                "alternative": dict(alternative),
            }

    for path in drill.error_paths:
        path_value = float(path.get("value", 0))
        if abs(given - path_value) <= tolerance:
            return {
                "drill_id": drill.id,
                "accepted": False,
                "expected": expected,
                "expected_unit": drill.answer_unit,
                "given": {"value": round(given, 6), "unit": drill.answer_unit},
                "steps": steps,
                "diagnostic": path.get("category", "formula"),
                "message": path.get("message", "Incorrect answer."),
                "alternative": None,
            }

    return {
        "drill_id": drill.id,
        "accepted": False,
        "expected": expected,
        "expected_unit": drill.answer_unit,
        "given": {"value": round(given, 6), "unit": drill.answer_unit},
        "steps": steps,
        "diagnostic": "formula",
        "message": "The answer does not match the expected formula.",
        "alternative": None,
    }


def random_drill(
    drills: Iterable[FormulaDrill], *, topic_id: str | None = None, seed: int = 0
) -> FormulaDrill:
    pool = sorted(
        [drill for drill in drills if topic_id is None or drill.topic_id == topic_id],
        key=lambda item: item.id,
    )
    if not pool:
        raise InputError("Aucun drill disponible pour ce topic.")
    return random.Random(seed).choice(pool)


def drill_payload(drill: FormulaDrill, *, reveal: bool = False) -> dict[str, Any]:
    payload = {
        "drill_id": drill.id,
        "topic_id": drill.topic_id,
        "prompt": drill.prompt,
        "variables": drill.variables,
        "answer_unit": drill.answer_unit,
        "difficulty": drill.difficulty,
    }
    if reveal:
        payload["answer"] = drill.answer
        payload["steps"] = [dict(step) for step in drill.steps]
    return payload
