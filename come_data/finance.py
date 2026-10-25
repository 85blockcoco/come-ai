"""Calculs financiers vérifiables : rendements, P&L, cash-flows, performance.

Deux niveaux complémentaires :

* des **fonctions pures** sur des séquences (``simple_returns``, ``cagr``,
  ``max_drawdown``, ``xirr``...) : formules explicites, testables exactement ;
* une classe ``FinancialAnalytics`` qui exécute ces mêmes métriques via SQL
  DuckDB quand une colonne temporelle existe, afin de ne jamais charger toute
  la série en mémoire.

Les définitions sont volontairement explicites (écart-type d'échantillon
``ddof=1`` pour la volatilité, rendements arithmétiques simple période, XIRR
sur base 365 jours) car ce sont des conventions qui changent les résultats.
Ce module est descriptif : il ne constitue pas un conseil en investissement.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any

from .engine import DataEngine
from .errors import DataEngineError
from .safety import quote_identifier

Number = float | int
DEFAULT_MAX_SERIES_ROWS = 1_000_000


# --------------------------------------------------------------------------- #
# Fonctions pures
# --------------------------------------------------------------------------- #
def _as_floats(values: Sequence[Any]) -> list[float]:
    result: list[float] = []
    for value in values:
        if value is None:
            continue
        try:
            number = float(value)
        except (TypeError, ValueError):
            continue
        if math.isnan(number) or math.isinf(number):
            continue
        result.append(number)
    return result


def simple_returns(values: Sequence[Number]) -> list[float]:
    """Rendements simples ``(v_t - v_{t-1}) / v_{t-1}``, zéro où ``v_{t-1}`` est nul."""
    series = _as_floats(values)
    return [
        (series[index] - series[index - 1]) / series[index - 1] if series[index - 1] != 0 else 0.0
        for index in range(1, len(series))
    ]


def log_returns(values: Sequence[Number]) -> list[float]:
    """Rendements logarithmiques ``ln(v_t / v_{t-1})`` sur valeurs strictement positives."""
    series = _as_floats(values)
    returns: list[float] = []
    for index in range(1, len(series)):
        previous, current = series[index - 1], series[index]
        if previous > 0 and current > 0:
            returns.append(math.log(current / previous))
    return returns


def total_return(values: Sequence[Number]) -> float | None:
    """Rendement cumulé simple ``v_last / v_first - 1``."""
    series = _as_floats(values)
    if len(series) < 2 or series[0] == 0:
        return None
    return series[-1] / series[0] - 1.0


def cagr(values: Sequence[Number], periods_per_year: int = 252) -> float | None:
    """Rendement annualisé ``(v_last / v_first) ** (pp / n) - 1``.

    ``n`` est le nombre de rendements, c'est-à-dire ``len(values) - 1``.
    """
    series = _as_floats(values)
    periods = len(series) - 1
    if periods <= 0 or series[0] <= 0 or series[-1] < 0:
        return None
    try:
        return (series[-1] / series[0]) ** (periods_per_year / periods) - 1.0
    except (OverflowError, ValueError):
        return None


def mean(values: Sequence[Number]) -> float | None:
    series = _as_floats(values)
    return sum(series) / len(series) if series else None


def sample_stdev(values: Sequence[Number], ddof: int = 1) -> float | None:
    series = _as_floats(values)
    if len(series) - ddof <= 0:
        return None
    average = sum(series) / len(series)
    variance = sum((item - average) ** 2 for item in series) / (len(series) - ddof)
    return math.sqrt(variance)


def annualized_volatility(returns: Sequence[Number], periods_per_year: int = 252, ddof: int = 1) -> float | None:
    """Volatilité annualisée ``stdev(r, ddof) * sqrt(pp)``."""
    deviation = sample_stdev(returns, ddof=ddof)
    return None if deviation is None else deviation * math.sqrt(periods_per_year)


def sharpe_ratio(
    returns: Sequence[Number],
    risk_free_rate: float = 0.0,
    periods_per_year: int = 252,
    ddof: int = 1,
) -> float | None:
    """Ratio de Sharpe annualisé ``(moyenne(r)*pp - rf) / (stdev(r,ddof)*sqrt(pp))``."""
    series = _as_floats(returns)
    deviation = sample_stdev(series, ddof=ddof)
    if deviation is None or deviation == 0:
        return None
    average = sum(series) / len(series)
    return (average * periods_per_year - risk_free_rate) / (deviation * math.sqrt(periods_per_year))


def drawdown_series(values: Sequence[Number]) -> list[float]:
    """Série de drawdown ``v_t / max(v_0..v_t) - 1`` (valeurs dans ``[-1, 0]``)."""
    series = _as_floats(values)
    result: list[float] = []
    running_peak: float | None = None
    for value in series:
        running_peak = value if running_peak is None else max(running_peak, value)
        result.append(0.0 if running_peak == 0 else value / running_peak - 1.0)
    return result


def max_drawdown(values: Sequence[Number]) -> dict[str, Any]:
    """Amplitude maximale de baisse depuis un sommet antérieur.

    Renvoie ``max_drawdown`` (négatif), l'indice du sommet et l'indice du creux.
    """
    series = _as_floats(values)
    peak_value: float | None = None
    peak_index = 0
    worst = 0.0
    worst_peak = 0
    worst_trough = 0
    for index, value in enumerate(series):
        if peak_value is None or value > peak_value:
            peak_value = value
            peak_index = index
        if peak_value is not None and peak_value != 0:
            drawdown = value / peak_value - 1.0
            if drawdown < worst:
                worst = drawdown
                worst_peak = peak_index
                worst_trough = index
    return {
        "max_drawdown": worst,
        "peak_index": worst_peak,
        "trough_index": worst_trough,
    }


def moving_average(values: Sequence[Number], window: int) -> list[float | None]:
    """Moyenne mobile simple, ``None`` tant que la fenêtre n'est pas complète."""
    if window <= 0:
        raise DataEngineError("La fenêtre d'une moyenne mobile doit être strictement positive.")
    series = _as_floats(values)
    result: list[float | None] = []
    running = 0.0
    for index, value in enumerate(series):
        running += value
        if index >= window:
            running -= series[index - window]
        result.append(running / window if index >= window - 1 else None)
    return result


def _to_days(dates: Sequence[Any]) -> list[float]:
    parsed: list[float] = []
    for value in dates:
        moment = _parse_date(value)
        if moment is None:
            raise DataEngineError("Une date de flux de trésorerie est invalide.")
        parsed.append(moment)
    return parsed


def _parse_date(value: Any) -> float | None:
    if isinstance(value, datetime):
        moment = value
    elif isinstance(value, date):
        moment = datetime(value.year, value.month, value.day)
    elif isinstance(value, str):
        text = value.strip().replace("Z", "+00:00")
        try:
            moment = datetime.fromisoformat(text)
        except ValueError:
            return None
    else:
        return None
    epoch = datetime(1970, 1, 1)
    if moment.tzinfo is not None:
        moment = moment.replace(tzinfo=None)
    return (moment - epoch).total_seconds() / 86_400.0


def npv(rate: float, cashflows: Sequence[Number], dates: Sequence[Any] | None = None) -> float:
    """Valeur actuelle nette. Sans dates, les périodes sont les indices 0, 1, 2..."""
    flows = _as_floats(cashflows)
    if dates is None:
        times = [float(index) for index in range(len(flows))]
    else:
        days = _to_days(dates)
        if len(days) != len(cashflows):
            raise DataEngineError("Autant de dates que de flux sont nécessaires.")
        base = days[0]
        times = [(day - base) / 365.0 for day in days]
    if rate <= -1:
        raise DataEngineError("Le taux d'actualisation doit être supérieur à -100 %.")
    return sum(flow / (1.0 + rate) ** time for flow, time in zip(flows, times))


def xirr(cashflows: Sequence[Number], dates: Sequence[Any], guess: float = 0.1) -> float | None:
    """Taux de rendement interne sur flux datés (base 365 jours), par bissection.

    Renvoie ``None`` si les flux ne changent pas de signe (pas de solution) ou
    si aucune racine n'est trouvée dans l'intervalle exploré.
    """
    flows = _as_floats(cashflows)
    days = _to_days(dates)
    if len(flows) != len(days):
        raise DataEngineError("Autant de dates que de flux sont nécessaires.")
    if len(flows) < 2:
        return None
    if not (any(flow > 0 for flow in flows) and any(flow < 0 for flow in flows)):
        return None

    def f(rate: float) -> float:
        return sum(flow / (1.0 + rate) ** ((day - days[0]) / 365.0) for flow, day in zip(flows, days))

    low, high = -0.9999, 10.0
    f_low, f_high = f(low), f(high)
    if math.isnan(f_low) or math.isnan(f_high) or f_low * f_high > 0:
        return None
    for _ in range(200):
        middle = (low + high) / 2.0
        f_middle = f(middle)
        if f_middle == 0 or (high - low) < 1e-10:
            return middle
        if f_low * f_middle < 0:
            high = middle
            f_high = f_middle
        else:
            low = middle
            f_low = f_middle
    return (low + high) / 2.0


def profit_and_loss(values: Sequence[Number], costs: Sequence[Number] | None = None) -> dict[str, Any]:
    """P&L agrégé et taux de réussite, à partir de valeurs et de coûts alignés."""
    series = _as_floats(values)
    if not series:
        return {"count": 0, "total_pnl": None, "win_rate": None}
    if costs is None:
        pnl = series
        total_cost = None
    else:
        cost_series = _as_floats(costs)
        pnl = [value - cost for value, cost in zip(series, cost_series)]
        total_cost = sum(cost_series)
    total = sum(pnl)
    wins = sum(1 for item in pnl if item > 0)
    return {
        "count": len(pnl),
        "total_pnl": round(total, 6),
        "total_cost": None if total_cost is None else round(total_cost, 6),
        "return_on_cost": None if not total_cost else round(total / total_cost, 6),
        "win_rate": round(wins / len(pnl), 6),
        "best": round(max(pnl), 6),
        "worst": round(min(pnl), 6),
    }


# --------------------------------------------------------------------------- #
# Analytique via DuckDB
# --------------------------------------------------------------------------- #
@dataclass
class PerformanceReport:
    """Résultat de ``FinancialAnalytics.performance`` (dictionnaire sérialisable)."""

    metrics: dict[str, Any]

    def as_dict(self) -> dict[str, Any]:
        return dict(self.metrics)


class FinancialAnalytics:
    """Métriques financières exécutées sur une table/vue du ``DataEngine``."""

    def __init__(self, engine: DataEngine) -> None:
        self.engine = engine

    # -- Performance d'une série (valeur dans le temps) --------------------- #
    def performance(
        self,
        table: str,
        value_column: str,
        *,
        time_column: str | None = None,
        periods_per_year: int = 252,
        risk_free_rate: float = 0.0,
        max_series_rows: int = DEFAULT_MAX_SERIES_ROWS,
    ) -> PerformanceReport:
        if time_column:
            metrics = self._performance_sql(
                table, value_column, time_column, periods_per_year, risk_free_rate
            )
        else:
            metrics = self._performance_python(
                table, value_column, periods_per_year, risk_free_rate, max_series_rows
            )
        return PerformanceReport(metrics)

    def _performance_python(
        self,
        table: str,
        value_column: str,
        periods_per_year: int,
        risk_free_rate: float,
        max_series_rows: int,
    ) -> dict[str, Any]:
        qcol = quote_identifier(value_column)
        total = self.engine.row_count(table)
        rows = self.engine.scalar(f"SELECT count(*) FROM {quote_identifier(table)} WHERE {qcol} IS NOT NULL")
        if int(rows or 0) > max_series_rows:
            raise DataEngineError(
                "Cette série est trop longue pour être analysée sans colonne temporelle explicite. "
                "Fournis une colonne de temps pour un calcul diffusé par le moteur."
            )
        values = self.engine.scalars(
            f"SELECT {qcol} AS value FROM {quote_identifier(table)} WHERE {qcol} IS NOT NULL"
        )
        series = [float(item) for item in values]
        return self._metrics_from_series(series, periods_per_year, risk_free_rate, total)

    def _performance_sql(
        self,
        table: str,
        value_column: str,
        time_column: str,
        periods_per_year: int,
        risk_free_rate: float,
    ) -> dict[str, Any]:
        qv, qt = quote_identifier(value_column), quote_identifier(time_column)
        qtable = quote_identifier(table)
        returns_sql = f"""
            WITH ordered AS (
                SELECT {qv} AS v, {qt} AS t
                FROM {qtable}
                WHERE {qv} IS NOT NULL
            ), with_prev AS (
                SELECT v, LAG(v) OVER (ORDER BY t) AS prev
                FROM ordered
            ), returns AS (
                SELECT (v - prev) / prev AS r
                FROM with_prev
                WHERE prev IS NOT NULL AND prev <> 0
            )
            SELECT count(*), avg(r), stddev_samp(r), min(r), max(r), sum(r) FROM returns
        """
        n_returns, mean_r, std_r, min_r, max_r, _sum_r = self.engine._con.execute(returns_sql).fetchone()
        extremes = self.engine._con.execute(
            f"SELECT arg_min({qv}, {qt}), arg_max({qv}, {qt}), count(*) FROM {qtable} WHERE {qv} IS NOT NULL"
        ).fetchone()
        first_value, last_value, observations = extremes
        drawdown = self.engine._con.execute(
            f"""
            WITH ordered AS (SELECT {qv} AS v, {qt} AS t FROM {qtable} WHERE {qv} IS NOT NULL),
            peaks AS (
                SELECT v, max(v) OVER (ORDER BY t ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW) AS runmax
                FROM ordered
            )
            SELECT min(v / runmax - 1) FROM peaks WHERE runmax <> 0
            """
        ).fetchone()[0]
        return self._assemble_metrics(
            observations=int(observations or 0),
            n_returns=int(n_returns or 0),
            first_value=first_value,
            last_value=last_value,
            mean_r=mean_r,
            std_r=std_r,
            min_r=min_r,
            max_r=max_r,
            drawdown=drawdown,
            periods_per_year=periods_per_year,
            risk_free_rate=risk_free_rate,
            ddof=1,
        )

    def _metrics_from_series(
        self,
        series: list[float],
        periods_per_year: int,
        risk_free_rate: float,
        total_rows: int,
    ) -> dict[str, Any]:
        returns = simple_returns(series)
        deviation = sample_stdev(returns, ddof=1)
        return self._assemble_metrics(
            observations=len(series),
            n_returns=len(returns),
            first_value=series[0] if series else None,
            last_value=series[-1] if series else None,
            mean_r=mean(returns),
            std_r=deviation,
            min_r=min(returns) if returns else None,
            max_r=max(returns) if returns else None,
            drawdown=max_drawdown(series)["max_drawdown"] if series else None,
            periods_per_year=periods_per_year,
            risk_free_rate=risk_free_rate,
            ddof=1,
            total_rows=total_rows,
        )

    @staticmethod
    def _assemble_metrics(
        *,
        observations: int,
        n_returns: int,
        first_value: Any,
        last_value: Any,
        mean_r: Any,
        std_r: Any,
        min_r: Any,
        max_r: Any,
        drawdown: Any,
        periods_per_year: int,
        risk_free_rate: float,
        ddof: int,
        total_rows: int | None = None,
    ) -> dict[str, Any]:
        total_ret = None
        if first_value not in (None, 0) and last_value is not None:
            total_ret = float(last_value) / float(first_value) - 1.0
        annualized = None
        if n_returns > 0 and first_value not in (None, 0, "") and last_value is not None and float(first_value) > 0 and float(last_value) >= 0:
            annualized = (float(last_value) / float(first_value)) ** (periods_per_year / n_returns) - 1.0
        ann_vol = None if std_r is None else float(std_r) * math.sqrt(periods_per_year)
        sharpe = None
        if std_r not in (None, 0) and mean_r is not None:
            sharpe = (float(mean_r) * periods_per_year - risk_free_rate) / (float(std_r) * math.sqrt(periods_per_year))
        return {
            "observations": observations,
            "return_observations": n_returns,
            "total_rows": total_rows,
            "first_value": _num(first_value),
            "last_value": _num(last_value),
            "total_return": _num(total_ret),
            "annualized_return": _num(annualized),
            "mean_return": _num(mean_r),
            "volatility": _num(std_r),
            "annualized_volatility": _num(ann_vol),
            "sharpe_ratio": _num(sharpe),
            "best_period_return": _num(max_r),
            "worst_period_return": _num(min_r),
            "max_drawdown": _num(drawdown),
            "periods_per_year": periods_per_year,
            "risk_free_rate": risk_free_rate,
            "stdev_ddof": ddof,
            # Réserve obligatoire côté produit : ceci est descriptif.
            "interpretation": "Métriques descriptives calculées localement ; ce n'est pas un conseil d'investissement.",
        }

    # -- Séries auxiliaires -------------------------------------------------- #
    def returns_frame(
        self,
        table: str,
        value_column: str,
        *,
        time_column: str | None = None,
    ) -> Any:
        qv = quote_identifier(value_column)
        qt = quote_identifier(time_column) if time_column else None
        qtable = quote_identifier(table)
        select_time = f"{qt} AS period," if qt else ""
        order = "ORDER BY period" if qt else ""
        sql = f"""
            WITH ordered AS (
                SELECT {select_time} {qv} AS value FROM {qtable} WHERE {qv} IS NOT NULL
            ), with_prev AS (
                SELECT period, value, LAG(value) OVER ({order}) AS prev FROM ordered
            )
            SELECT period, value, (value - prev) / prev AS r
            FROM with_prev
            WHERE prev IS NOT NULL AND prev <> 0
            {order}
        """ if qt else f"""
            WITH ordered AS (
                SELECT {qv} AS value FROM {qtable} WHERE {qv} IS NOT NULL
            ), with_prev AS (
                SELECT value, LAG(value) OVER () AS prev FROM ordered
            )
            SELECT value, (value - prev) / prev AS r
            FROM with_prev
            WHERE prev IS NOT NULL AND prev <> 0
        """
        return self.engine.query_frame(sql)

    def moving_average(
        self,
        table: str,
        value_column: str,
        window: int,
        *,
        time_column: str | None = None,
    ) -> Any:
        if window <= 0:
            raise DataEngineError("La fenêtre d'une moyenne mobile doit être strictement positive.")
        qv = quote_identifier(value_column)
        qt = quote_identifier(time_column) if time_column else None
        qtable = quote_identifier(table)
        order = f"ORDER BY {qt}" if qt else ""
        frame = f"{order} ROWS BETWEEN {window - 1} PRECEDING AND CURRENT ROW".strip()
        select_time = f"{qt} AS period," if qt else ""
        # La moyenne n'est publiée que lorsque la fenêtre est complète, comme la
        # fonction pure ``moving_average`` : les deux chemins restent cohérents.
        sql = f"""
            SELECT {select_time} {qv} AS value,
                   CASE WHEN count({qv}) OVER ({frame}) >= {window}
                        THEN avg({qv}) OVER ({frame}) END AS moving_average
            FROM {qtable} WHERE {qv} IS NOT NULL {order}
        """
        return self.engine.query_frame(sql)

    # -- Cash-flows ---------------------------------------------------------- #
    def cash_flow_metrics(
        self,
        table: str,
        amount_column: str,
        *,
        date_column: str | None = None,
        discount_rate: float = 0.0,
    ) -> dict[str, Any]:
        qa = quote_identifier(amount_column)
        qtable = quote_identifier(table)
        inflow, outflow, net, count = self.engine._con.execute(
            f"SELECT sum(CASE WHEN {qa} > 0 THEN {qa} ELSE 0 END), "
            f"sum(CASE WHEN {qa} < 0 THEN {qa} ELSE 0 END), sum({qa}), count(*) FROM {qtable}"
        ).fetchone()
        metrics: dict[str, Any] = {
            "count": int(count or 0),
            "total_inflows": _num(inflow),
            "total_outflows": _num(outflow),
            "net_cash_flow": _num(net),
            "discount_rate": discount_rate,
            "npv": None,
            "xirr": None,
        }
        if date_column:
            qd = quote_identifier(date_column)
            flows = self.engine.query(
                f"SELECT {qd} AS period, sum({qa}) AS amount FROM {qtable} "
                f"GROUP BY {qd} ORDER BY {qd}"
            )
            amounts = [float(item["amount"]) for item in flows]
            periods = [item["period"] for item in flows]
            try:
                metrics["npv"] = _num(npv(discount_rate, amounts, periods))
                metrics["xirr"] = _num(xirr(amounts, periods))
            except DataEngineError:
                metrics["npv"] = None
                metrics["xirr"] = None
            if periods:
                metrics["first_period"] = str(periods[0])
                metrics["last_period"] = str(periods[-1])
        else:
            amounts = [float(item["amount"]) for item in self.engine.query(f"SELECT {qa} AS amount FROM {qtable}")]
            if amounts:
                metrics["npv"] = _num(npv(discount_rate, amounts))
        metrics["interpretation"] = "Flux agrégés localement ; ce n'est pas un conseil d'investissement."
        return metrics

    def running_balance(
        self,
        table: str,
        amount_column: str,
        *,
        date_column: str | None = None,
    ) -> Any:
        qa = quote_identifier(amount_column)
        qt = quote_identifier(date_column) if date_column else None
        qtable = quote_identifier(table)
        order = f"ORDER BY {qt}" if qt else ""
        select_time = f"{qt} AS period," if qt else ""
        sql = f"""
            SELECT {select_time} {qa} AS amount,
                   sum({qa}) OVER ({order} ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW) AS balance
            FROM {qtable} {order}
        """
        return self.engine.query_frame(sql)

    # -- P&L ----------------------------------------------------------------- #
    def profit_and_loss(
        self,
        table: str,
        value_column: str,
        *,
        cost_column: str | None = None,
    ) -> dict[str, Any]:
        qv = quote_identifier(value_column)
        qtable = quote_identifier(table)
        if cost_column:
            qc = quote_identifier(cost_column)
            row = self.engine._con.execute(
                f"SELECT sum({qv} - {qc}), sum({qc}), count(*), "
                f"sum(CASE WHEN {qv} > {qc} THEN 1 ELSE 0 END), "
                f"max({qv} - {qc}), min({qv} - {qc}) FROM {qtable}"
            ).fetchone()
            total_pnl, total_cost, count, wins, best, worst = row
            return {
                "count": int(count or 0),
                "total_pnl": _num(total_pnl),
                "total_cost": _num(total_cost),
                "return_on_cost": _num(None if not total_cost else float(total_pnl) / float(total_cost)),
                "win_rate": _num(None if not count else int(wins) / int(count)),
                "best": _num(best),
                "worst": _num(worst),
                "interpretation": "P&L descriptif calculé localement ; ce n'est pas un conseil d'investissement.",
            }
        row = self.engine._con.execute(
            f"SELECT sum({qv}), count(*), sum(CASE WHEN {qv} > 0 THEN 1 ELSE 0 END), "
            f"max({qv}), min({qv}) FROM {qtable}"
        ).fetchone()
        total, count, wins, best, worst = row
        return {
            "count": int(count or 0),
            "total_pnl": _num(total),
            "total_cost": None,
            "return_on_cost": None,
            "win_rate": _num(None if not count else int(wins) / int(count)),
            "best": _num(best),
            "worst": _num(worst),
            "interpretation": "P&L descriptif calculé localement ; ce n'est pas un conseil d'investissement.",
        }

    # -- Résumé par période -------------------------------------------------- #
    def period_summary(
        self,
        table: str,
        date_column: str,
        *,
        period: str = "month",
        amount_column: str | None = None,
    ) -> Any:
        """Agrégation temporelle (``day``/``week``/``month``/``quarter``/``year``)."""
        grain = {"day": "day", "week": "week", "month": "month", "quarter": "quarter", "year": "year"}
        if period not in grain:
            raise DataEngineError("La période doit être day, week, month, quarter ou year.")
        qd = quote_identifier(date_column)
        qtable = quote_identifier(table)
        aggregate = f"sum({quote_identifier(amount_column)})" if amount_column else "count(*)"
        alias = "total" if amount_column else "count"
        sql = (
            f"SELECT date_trunc('{grain[period]}', {qd}) AS period, {aggregate} AS {quote_identifier(alias)} "
            f"FROM {qtable} GROUP BY 1 ORDER BY 1"
        )
        return self.engine.query_frame(sql)


def _num(value: Any) -> float | None:
    if value is None:
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if math.isnan(number) or math.isinf(number):
        return None
    return round(number, 8)
