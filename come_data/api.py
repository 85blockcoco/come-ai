"""Façade haut niveau du moteur de données Côme IA.

Les autres agents n'ont pas besoin de connaître DuckDB : ils utilisent
``ComeDataEngine`` avec des chemins de fichiers, des noms de colonnes et des
dictionnaires. La façade orchestre l'enregistrement du fichier, l'exécution des
calculs et l'export, et renvoie des structures sérialisables (JSON-safe) comme
le reste de Côme IA.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .engine import DataEngine, RegisteredTable
from .errors import DataEngineError, UnsafeQueryError
from .finance import FinancialAnalytics
from .safety import quote_identifier, resolve_within
from .serialize import to_jsonable


@dataclass
class AnalysisResult:
    """Résultat d'analyse prêt à être affiché ou exporté."""

    file: str
    table: str
    rows: int
    columns: int
    column_names: list[str]
    data_types: dict[str, str]
    profile: list[dict[str, Any]]
    numeric_statistics: dict[str, Any]
    note: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "file": self.file,
            "table": self.table,
            "rows": self.rows,
            "columns": self.columns,
            "column_names": self.column_names,
            "data_types": self.data_types,
            "profile": to_jsonable(self.profile),
            "numeric_statistics": to_jsonable(self.numeric_statistics),
            "note": self.note,
        }


class ComeDataEngine:
    """API simple pour les agents : fichiers, SQL en lecture, finance, export."""

    def __init__(
        self,
        data_dir: str | Path,
        output_dir: str | Path | None = None,
        *,
        memory_limit: str = "2GB",
        threads: int | None = None,
        temp_dir: str | Path | None = None,
        query_timeout_seconds: float = 30.0,
    ) -> None:
        self.data_dir = Path(data_dir).expanduser().resolve()
        self.output_dir = Path(output_dir).expanduser().resolve() if output_dir else None
        roots = [self.data_dir] + ([self.output_dir] if self.output_dir else [])
        self.engine = DataEngine(
            roots,
            memory_limit=memory_limit,
            threads=threads,
            temp_dir=Path(temp_dir) if temp_dir else None,
            query_timeout_seconds=query_timeout_seconds,
        )
        self.finance = FinancialAnalytics(self.engine)

    # -- Cycle de vie -------------------------------------------------------- #
    def close(self) -> None:
        self.engine.close()

    def __enter__(self) -> "ComeDataEngine":
        return self

    def __exit__(self, *_exc: object) -> None:
        self.close()

    # -- Chargement ---------------------------------------------------------- #
    def register(self, path: str | Path, *, name: str | None = None, sheet: str | None = None) -> RegisteredTable:
        """Enregistre un fichier en vue paresseuse (un seul balayage par requête)."""
        return self.engine.register_file(path, name=name, sheet=sheet)

    def _analysis_table(
        self, path: str | Path, *, sheet: str | None = None, name: str | None = None, materialize: bool = True
    ) -> RegisteredTable:
        """Table d'analyse : matérialisée par défaut pour éviter de relire le fichier
        à chaque métrique (une analyse composite enchaîne plusieurs requêtes)."""
        return self.engine.register_file(path, name=name, sheet=sheet, materialize=materialize)

    # -- Analyse d'un fichier ------------------------------------------------ #
    def analyze(
        self, path: str | Path, *, sheet: str | None = None, name: str | None = None, materialize: bool = True
    ) -> AnalysisResult:
        info = self._analysis_table(path, sheet=sheet, name=name, materialize=materialize)
        columns = self.engine.columns(info.name)
        column_names = [item["column_name"] for item in columns]
        data_types = {item["column_name"]: str(item["column_type"]) for item in columns}
        return AnalysisResult(
            file=Path(path).name,
            table=info.name,
            rows=self.engine.row_count(info.name),
            columns=len(columns),
            column_names=column_names,
            data_types=data_types,
            profile=self.engine.profile(info.name),
            numeric_statistics=self.engine.numeric_statistics(info.name),
            note=(
                "Analyse descriptive calculée localement avec DuckDB. Les valeurs restent dans l'espace de travail ; "
                "ce n'est pas un conseil en investissement."
            ),
        )

    def describe(
        self, path: str | Path, *, sheet: str | None = None, name: str | None = None, materialize: bool = True
    ) -> dict[str, Any]:
        info = self._analysis_table(path, sheet=sheet, name=name, materialize=materialize)
        columns = self.engine.columns(info.name)
        return {
            "file": Path(path).name,
            "table": info.name,
            "kind": info.kind,
            "rows": self.engine.row_count(info.name),
            "columns": [
                {"name": item["column_name"], "type": str(item["column_type"])} for item in columns
            ],
        }

    def preview(self, path: str | Path, *, rows: int = 20, sheet: str | None = None) -> list[dict[str, Any]]:
        info = self.engine.register_file(path, sheet=sheet)
        return to_jsonable(self.engine.preview(info.name, rows))

    def columns(self, path: str | Path, *, sheet: str | None = None, name: str | None = None) -> list[dict[str, Any]]:
        info = self._analysis_table(path, sheet=sheet, name=name)
        return to_jsonable(self.engine.columns(info.name))

    def row_count(self, path: str | Path, *, sheet: str | None = None, name: str | None = None) -> int:
        info = self._analysis_table(path, sheet=sheet, name=name)
        return self.engine.row_count(info.name)

    def numeric_statistics(
        self, path: str | Path, *, sheet: str | None = None, name: str | None = None
    ) -> dict[str, Any]:
        info = self._analysis_table(path, sheet=sheet, name=name)
        return to_jsonable(self.engine.numeric_statistics(info.name))

    # -- SQL en lecture ------------------------------------------------------ #
    def query_file(
        self,
        path: str | Path,
        sql: str,
        *,
        params: Sequence[Any] | None = None,
        sheet: str | None = None,
        alias: str = "data",
    ) -> list[dict[str, Any]]:
        """Exécute un SELECT sur le fichier, exposé sous ``alias`` (défaut ``data``)."""
        self.engine.register_file(path, name=alias, sheet=sheet)
        return to_jsonable(self.engine.query(sql, params))

    def query(self, sql: str, params: Sequence[Any] | None = None) -> list[dict[str, Any]]:
        return to_jsonable(self.engine.query(sql, params))

    # -- Finance ------------------------------------------------------------- #
    def performance(
        self,
        path: str | Path,
        value_column: str,
        *,
        time_column: str | None = None,
        sheet: str | None = None,
        periods_per_year: int = 252,
        risk_free_rate: float = 0.0,
    ) -> dict[str, Any]:
        info = self._analysis_table(path, sheet=sheet)
        return self.finance.performance(
            info.name,
            value_column,
            time_column=time_column,
            periods_per_year=periods_per_year,
            risk_free_rate=risk_free_rate,
        ).as_dict()

    def cash_flows(
        self,
        path: str | Path,
        amount_column: str,
        *,
        date_column: str | None = None,
        sheet: str | None = None,
        discount_rate: float = 0.0,
    ) -> dict[str, Any]:
        info = self._analysis_table(path, sheet=sheet)
        return self.finance.cash_flow_metrics(
            info.name, amount_column, date_column=date_column, discount_rate=discount_rate
        )

    def profit_and_loss(
        self,
        path: str | Path,
        value_column: str,
        *,
        cost_column: str | None = None,
        sheet: str | None = None,
    ) -> dict[str, Any]:
        info = self._analysis_table(path, sheet=sheet)
        return self.finance.profit_and_loss(info.name, value_column, cost_column=cost_column)

    def group_summary(
        self,
        path: str | Path,
        group_column: str,
        *,
        aggregate: str = "count(*)",
        sheet: str | None = None,
        order_by: str | None = None,
    ) -> list[dict[str, Any]]:
        """Résumé par groupe : ``aggregate`` doit être une expression SQL d'agrégation simple."""
        info = self._analysis_table(path, sheet=sheet)
        group = quote_identifier(group_column)
        order = f" ORDER BY {quote_identifier(order_by)}" if order_by else f" ORDER BY {group}"
        sql = f"SELECT {group} AS group_value, {aggregate} AS value FROM {quote_identifier(info.name)} GROUP BY 1{order}"
        return to_jsonable(self.engine.query(sql))

    def period_summary(
        self,
        path: str | Path,
        date_column: str,
        *,
        period: str = "month",
        amount_column: str | None = None,
        sheet: str | None = None,
    ) -> list[dict[str, Any]]:
        info = self._analysis_table(path, sheet=sheet)
        return to_jsonable(
            self.finance.period_summary(
                info.name, date_column, period=period, amount_column=amount_column
            ).to_dict(orient="records")
        )


    # -- Export -------------------------------------------------------------- #
    def export_rows(
        self,
        rows: Iterable[dict[str, Any]],
        target_name: str,
        *,
        format: str | None = None,
    ) -> Path:
        """Exporte une liste de dictionnaires vers CSV ou XLSX dans ``output``."""
        if self.output_dir is None:
            raise UnsafeQueryError("Aucun dossier de sortie n'est configuré pour l'export.")
        import pandas as pd  # noqa: PLC0415

        suffix = Path(target_name).suffix.lower()
        if format:
            suffix = "." + format.lstrip(".").lower()
        if suffix not in {".csv", ".xlsx"}:
            raise DataEngineError("L'export accepte .csv ou .xlsx.")
        target = self.output_dir / Path(target_name).with_suffix(suffix).name
        return self.engine.export_frame(pd.DataFrame(list(rows)), target)

    def export_query(self, sql: str, target_name: str, *, delimiter: str = ",") -> Path:
        if self.output_dir is None:
            raise UnsafeQueryError("Aucun dossier de sortie n'est configuré pour l'export.")
        target = self.output_dir / Path(target_name).name
        return self.engine.export_query_to_csv(sql, target, delimiter=delimiter)

    # -- Import d'un DataFrame existant (intégration Pandas) ----------------- #
    def register_frame(self, frame: Any, name: str) -> RegisteredTable:
        return self.engine.register_frame(frame, name)


def resolve_allowed(allowed_roots: Iterable[Path], candidate: str | Path) -> Path:
    """Réexport pratique pour les appelants qui veulent valider un chemin seuls."""
    return resolve_within(allowed_roots, candidate)
