"""``come_data`` — couche de données DuckDB additive pour Côme IA.

API publique :

* ``ComeDataEngine`` : façade haut niveau (analyse, SQL lecture, finance, export).
* ``DataEngine`` : couche DuckDB bas niveau (vues paresseuses, profils).
* ``FinancialAnalytics`` : métriques financières sur une table du moteur.
* ``finance`` : fonctions pures testables (rendements, CAGR, drawdown, XIRR...).

Le module est **additif** : il ne remplace aucune fonctionnalité existante et
n'est pas importé par ``workspace_core`` tant que l'intégration n'est pas
explicitement activée.
"""

from __future__ import annotations

from .api import AnalysisResult, ComeDataEngine
from .engine import DataEngine, RegisteredTable, is_available
from .errors import (
    DataEngineError,
    DataEngineUnavailableError,
    DataLimitError,
    UnsafeQueryError,
    UnsupportedDataError,
)
from .finance import FinancialAnalytics
from . import finance
from .safety import resolve_within, validate_readonly_query

__all__ = [
    "AnalysisResult",
    "ComeDataEngine",
    "DataEngine",
    "DataEngineError",
    "DataEngineUnavailableError",
    "DataLimitError",
    "FinancialAnalytics",
    "RegisteredTable",
    "UnsafeQueryError",
    "UnsupportedDataError",
    "finance",
    "is_available",
    "resolve_within",
    "validate_readonly_query",
]

__version__ = "0.1.0"
