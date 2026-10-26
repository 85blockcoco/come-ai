"""Erreurs publiques du moteur de données Côme IA.

Toutes ces erreurs sont sûres à afficher à l'utilisateur : elles ne contiennent
jamais de chemin local absolu, de secret ni de trace technique brute.
"""

from __future__ import annotations


class DataEngineError(RuntimeError):
    """Erreur générique, sans détail technique sensible."""


class DataEngineUnavailableError(DataEngineError):
    """Le moteur DuckDB n'est pas installé ou ne peut pas démarrer."""


class UnsupportedDataError(DataEngineError):
    """Le fichier ou le format demandé n'est pas pris en charge."""


class UnsafeQueryError(DataEngineError):
    """La requête SQL ou le chemin demandé est refusé pour des raisons de sûreté."""


class DataLimitError(DataEngineError):
    """La demande dépasse une limite de volume ou de mémoire volontaire."""
