"""Contrôles qualité déterministes exécutés par DuckDB (jamais par un LLM).

Détecte, sur une table du moteur :

* les **valeurs manquantes** par colonne (NULL), avec ratio ;
* les **doublons** de lignes exactes ;
* les **types mixtes** : colonnes textuelles contenant un mélange de valeurs
  numériques et non numériques ;
* les **anomalies numériques** au sens de Tukey (hors ``[Q1 - k*IQR, Q3 + k*IQR]``).

Toutes les agrégations sont diffusées par DuckDB : aucune table n'est chargée en
mémoire côté Python.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from come_data.engine import DataEngine
from come_data.safety import quote_identifier

_NUMERIC_TOKENS = (
    "INT",
    "BIGINT",
    "SMALLINT",
    "TINYINT",
    "INTEGER",
    "HUGEINT",
    "DOUBLE",
    "FLOAT",
    "REAL",
    "DECIMAL",
    "NUMERIC",
)


@dataclass(frozen=True)
class ColumnQuality:
    """Qualité observée d'une colonne."""

    column: str
    data_type: str
    total: int
    missing: int
    missing_ratio: float
    distinct: int | None
    non_numeric: int
    outliers: int
    lower_bound: float | None
    upper_bound: float | None

    def is_flagged(self) -> bool:
        return (
            self.missing > 0
            or self.outliers > 0
            or self.non_numeric > 0
        )

    def as_dict(self) -> dict[str, Any]:
        return {
            "column": self.column,
            "data_type": self.data_type,
            "total": self.total,
            "missing": self.missing,
            "missing_ratio": round(self.missing_ratio, 6),
            "distinct": self.distinct,
            "non_numeric": self.non_numeric,
            "outliers": self.outliers,
            "lower_bound": self.lower_bound,
            "upper_bound": self.upper_bound,
        }


@dataclass(frozen=True)
class QualityReport:
    """Rapport qualité sérialisable, avec anomalies explicites."""

    table: str
    rows: int
    duplicate_rows: int
    columns: tuple[ColumnQuality, ...]
    checks: tuple[str, ...]

    @property
    def duplicate_ratio(self) -> float:
        return (self.duplicate_rows / self.rows) if self.rows else 0.0

    def anomalies(self) -> list[dict[str, Any]]:
        findings: list[dict[str, Any]] = []
        if self.duplicate_rows:
            findings.append(
                {
                    "kind": "duplicate_rows",
                    "severity": "warning",
                    "count": self.duplicate_rows,
                    "message": f"{self.duplicate_rows} ligne(s) dupliquée(s) exactement.",
                }
            )
        for column in self.columns:
            if column.missing:
                findings.append(
                    {
                        "kind": "missing_values",
                        "severity": "info",
                        "column": column.column,
                        "count": column.missing,
                        "ratio": round(column.missing_ratio, 6),
                        "message": f"{column.missing} valeur(s) manquante(s) dans « {column.column} ».",
                    }
                )
            if column.non_numeric:
                findings.append(
                    {
                        "kind": "mixed_types",
                        "severity": "warning",
                        "column": column.column,
                        "count": column.non_numeric,
                        "message": (
                            f"« {column.column} » mélange {column.non_numeric} valeur(s) "
                            "non numérique(s) avec des valeurs numériques."
                        ),
                    }
                )
            if column.outliers:
                findings.append(
                    {
                        "kind": "numeric_outliers",
                        "severity": "info",
                        "column": column.column,
                        "count": column.outliers,
                        "lower_bound": column.lower_bound,
                        "upper_bound": column.upper_bound,
                        "message": (
                            f"{column.outliers} valeur(s) hors bornes Tukey dans « {column.column} »."
                        ),
                    }
                )
        return findings

    def as_dict(self) -> dict[str, Any]:
        return {
            "table": self.table,
            "rows": self.rows,
            "duplicate_rows": self.duplicate_rows,
            "duplicate_ratio": round(self.duplicate_ratio, 6),
            "columns": [column.as_dict() for column in self.columns],
            "checks": list(self.checks),
            "anomalies": self.anomalies(),
        }


def _is_numeric(sql_type: str) -> bool:
    upper = sql_type.upper()
    return any(token in upper for token in _NUMERIC_TOKENS)


def analyze_quality(
    engine: DataEngine,
    table: str,
    *,
    numeric_columns: list[str] | None = None,
    outlier_k: float = 1.5,
    include_duplicates: bool = True,
    include_distinct: bool = False,
) -> QualityReport:
    """Exécute les contrôles qualité sur ``table`` et renvoie un rapport."""
    qtable = quote_identifier(table)
    columns = engine.columns(table)
    rows = engine.row_count(table)
    checks: list[str] = []

    # 1) Valeurs manquantes par colonne, en un seul balayage.
    if columns:
        selection = ", ".join(
            f"count({quote_identifier(info['column_name'])})" for info in columns
        )
        counted = engine._con.execute(f"SELECT {selection} FROM {qtable}").fetchone()
        non_null = {info["column_name"]: int(counted[index] or 0) for index, info in enumerate(columns)}
    else:
        non_null = {}
    checks.append("missing_values: count(col) sur toutes les colonnes")

    # 2) Doublons de lignes exactes.
    duplicate_rows = 0
    if include_duplicates and rows:
        distinct = engine._con.execute(
            f"SELECT count(*) FROM (SELECT DISTINCT * FROM {qtable}) AS d"
        ).fetchone()[0]
        duplicate_rows = max(0, int(rows) - int(distinct or 0))
        checks.append("duplicates: SELECT DISTINCT *")

    # 3) Profil par colonne.
    profiles: list[ColumnQuality] = []
    for info in columns:
        name = info["column_name"]
        sql_type = str(info["column_type"])
        qcol = quote_identifier(name)
        column_non_null = non_null.get(name, 0)
        missing = max(0, int(rows) - column_non_null)
        distinct_value = None
        if include_distinct and rows:
            distinct_value = int(
                engine._con.execute(
                    f"SELECT count(DISTINCT {qcol}) FROM {qtable}"
                ).fetchone()[0]
                or 0
            )

        non_numeric = 0
        outliers = 0
        lower_bound = upper_bound = None
        if _is_numeric(sql_type):
            if name in (numeric_columns or []) or numeric_columns is None:
                non_numeric = 0
        elif "VARCHAR" in sql_type.upper() or "TEXT" in sql_type.upper():
            non_numeric = int(
                engine._con.execute(
                    f"SELECT count(*) FROM {qtable} "
                    f"WHERE {qcol} IS NOT NULL AND TRY_CAST({qcol} AS DOUBLE) IS NULL"
                ).fetchone()[0]
                or 0
            )
            # Un texte purement non numérique n'est pas un « type mixte ».
            numeric_like = column_non_null - non_numeric
            if numeric_like <= 0:
                non_numeric = 0

        want_numeric = numeric_columns is None or name in (numeric_columns or [])
        if want_numeric and _is_numeric(sql_type) and column_non_null:
            q1, q3 = engine._con.execute(
                f"SELECT quantile_cont({qcol}, 0.25), quantile_cont({qcol}, 0.75) "
                f"FROM {qtable} WHERE {qcol} IS NOT NULL"
            ).fetchone()
            if q1 is not None and q3 is not None:
                iqr = float(q3) - float(q1)
                lower_bound = float(q1) - outlier_k * iqr
                upper_bound = float(q3) + outlier_k * iqr
                outliers = int(
                    engine._con.execute(
                        f"SELECT count(*) FROM {qtable} WHERE {qcol} IS NOT NULL "
                        f"AND ({qcol} < ? OR {qcol} > ?)",
                        [lower_bound, upper_bound],
                    ).fetchone()[0]
                    or 0
                )

        profiles.append(
            ColumnQuality(
                column=name,
                data_type=sql_type,
                total=int(rows),
                missing=missing,
                missing_ratio=(missing / rows) if rows else 0.0,
                distinct=distinct_value,
                non_numeric=non_numeric,
                outliers=outliers,
                lower_bound=lower_bound,
                upper_bound=upper_bound,
            )
        )
    checks.append("outliers: bornes de Tukey (Q1 - k*IQR, Q3 + k*IQR)")
    checks.append("mixed_types: TRY_CAST(col AS DOUBLE) IS NULL")

    return QualityReport(
        table=table,
        rows=int(rows),
        duplicate_rows=duplicate_rows,
        columns=tuple(profiles),
        checks=tuple(checks),
    )


__all__ = ["ColumnQuality", "QualityReport", "analyze_quality"]
