"""``come_excel`` — moteur Excel avancé additif au-dessus de Côme Data.

Cette couche est **additive** : elle réutilise ``come_data`` (moteur DuckDB,
garde-fous SQL/chemins, sérialisation) et n'altère ni ``workspace_core`` ni
l'orchestrateur. Elle ajoute :

* l'inspection légère multi-classeurs (feuilles, entêtes, formules, plages
  fusionnées, noms définis) avant tout chargement massif ;
* un catalogue de sources traçables (empreinte SHA-256, feuille, plage) ;
* des contrôles qualité déterministes (manquants, doublons, types mixtes,
  anomalies numériques) ;
* une consolidation ``UNION``/``JOIN`` inter-classeurs alignée par nom, avec
  provenance ligne à ligne ;
* un journal d'audit et une traçabilité colonne → source.

La génération Excel professionnelle et la bibliothèque de calculs avancés sont
développées dans des lots ultérieurs (voir ``docs/COME_EXCEL_ARCHITECTURE.md``).
"""

from __future__ import annotations

from .catalog import SourceCatalog
from .consolidate import (
    ColumnAlignment,
    ConsolidationResult,
    align_sources,
    consolidate,
    normalize_name,
)
from .errors import (
    ConsolidationError,
    ExcelEngineError,
    InspectionError,
    UnsupportedSpreadsheetError,
)
from .inspect import (
    ColumnProfile,
    SheetInspection,
    WorkbookInspection,
    inspect_file,
)
from .provenance import (
    ENGINE_NAME,
    ENGINE_VERSION,
    AuditEntry,
    AuditLog,
    ColumnLineage,
    Provenance,
    SourceRef,
    fingerprint_file,
)
from .quality import ColumnQuality, QualityReport, analyze_quality

__all__ = [
    "AuditEntry",
    "AuditLog",
    "ColumnAlignment",
    "ColumnLineage",
    "ColumnProfile",
    "ColumnQuality",
    "ConsolidationError",
    "ConsolidationResult",
    "ENGINE_NAME",
    "ENGINE_VERSION",
    "ExcelEngineError",
    "InspectionError",
    "Provenance",
    "QualityReport",
    "SheetInspection",
    "SourceCatalog",
    "SourceRef",
    "UnsupportedSpreadsheetError",
    "WorkbookInspection",
    "align_sources",
    "analyze_quality",
    "consolidate",
    "fingerprint_file",
    "inspect_file",
    "normalize_name",
]
