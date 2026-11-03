"""Erreurs publiques de la couche ``come_excel``.

Elles dérivent de ``come_data.errors.DataEngineError`` afin que les appelants
(orchestrateur, chat) n'aient qu'une seule famille d'erreurs à connaître. Les
messages restent sûrs à afficher : ni chemin absolu, ni trace technique.
"""

from __future__ import annotations

from come_data.errors import DataEngineError


class ExcelEngineError(DataEngineError):
    """Erreur générique de la couche Excel avancée."""


class InspectionError(ExcelEngineError):
    """Un fichier n'a pas pu être inspecté sans être chargé entièrement."""


class UnsupportedSpreadsheetError(ExcelEngineError):
    """Le format de classeur demandé n'est pas pris en charge."""


class ConsolidationError(ExcelEngineError):
    """Une consolidation multi-classeurs ne peut pas être construite."""


__all__ = [
    "ExcelEngineError",
    "InspectionError",
    "UnsupportedSpreadsheetError",
    "ConsolidationError",
]
