"""Adaptateur d'intégration entre ``come_data`` et l'espace de travail Côme AI.

Ce module est **additif** : il ne modifie ni ``workspace_core``, ni
``v5_orchestrator``, ni le routeur IA, ni la mémoire. Il se contente de relier
la façade ``ComeDataEngine`` à un ``AppConfig`` / ``Workspace`` existant, pour
que les autres agents puissent l'appeler sans connaître DuckDB.

Utilisation typique depuis un agent ::

    from come_data.integration import engine_for_workspace, financial_analysis

    with engine_for_workspace(workspace) as engine:
        report = financial_analysis(engine, path, value_column="cloture", time_column="date")

La construction du moteur est isolée : aucun dossier utilisateur n'est créé
tant que le moteur n'est pas réellement utilisé.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from .api import ComeDataEngine
from .engine import is_available
from .errors import DataEngineUnavailableError

DEFAULT_MEMORY_LIMIT = "2GB"


def available() -> bool:
    """Indique si le moteur DuckDB est utilisable dans cet environnement."""
    return is_available()


def engine_for_workspace(
    workspace: Any,
    *,
    memory_limit: str = DEFAULT_MEMORY_LIMIT,
    spill_dir: str | Path | None = None,
    query_timeout_seconds: float = 30.0,
) -> ComeDataEngine:
    """Construit un moteur autorisé sur ``data_dir``/``output_dir`` du workspace.

    ``workspace`` est n'importe quel objet exposant ``config`` avec les attributs
    ``data_dir`` et ``output_dir`` (c'est le cas du ``Workspace`` de Côme AI).
    """
    if not available():
        raise DataEngineUnavailableError(
            "Le moteur DuckDB n'est pas disponible dans cet environnement. "
            "Installe 'duckdb>=1.1,<2' dans le venv pour activer l'analyse avancée."
        )
    config = getattr(workspace, "config", workspace)
    data_dir = Path(getattr(config, "data_dir"))
    output_dir = getattr(config, "output_dir", None)
    return ComeDataEngine(
        data_dir,
        Path(output_dir) if output_dir else None,
        memory_limit=memory_limit,
        temp_dir=Path(spill_dir) if spill_dir else None,
        query_timeout_seconds=query_timeout_seconds,
    )


def analyze_file(
    engine: ComeDataEngine,
    path: str | Path,
    *,
    sheet: str | None = None,
) -> dict[str, Any]:
    """Analyse descriptive d'un fichier (profil + statistiques), JSON-safe."""
    return engine.analyze(path, sheet=sheet).as_dict()


def financial_analysis(
    engine: ComeDataEngine,
    path: str | Path,
    *,
    value_column: str,
    time_column: str | None = None,
    sheet: str | None = None,
    periods_per_year: int = 252,
    risk_free_rate: float = 0.0,
) -> dict[str, Any]:
    """Performance d'une série : rendements, volatilité, Sharpe, drawdown."""
    return engine.performance(
        path,
        value_column,
        time_column=time_column,
        sheet=sheet,
        periods_per_year=periods_per_year,
        risk_free_rate=risk_free_rate,
    )


def cash_flow_analysis(
    engine: ComeDataEngine,
    path: str | Path,
    *,
    amount_column: str,
    date_column: str | None = None,
    sheet: str | None = None,
    discount_rate: float = 0.0,
) -> dict[str, Any]:
    """Analyse de flux de trésorerie : totaux, VAN et XIRR."""
    return engine.cash_flows(
        path, amount_column, date_column=date_column, sheet=sheet, discount_rate=discount_rate
    )
