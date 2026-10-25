"""Consolidation multi-classeurs alignée par nom de colonne normalisé.

Fonctions :

* ``normalize_name`` : normalise un entête (accents, casse, ponctuation) pour
  rapprocher des colonnes issues de classeurs hétérogènes ;
* ``align_sources`` : produit l'alignement colonne canonique ↔ colonnes sources ;
* ``consolidate`` : construit une table DuckDB par ``UNION ALL`` (empilement) ou
  ``JOIN`` (rapprochement), en ajoutant des colonnes de provenance
  (``_source_file``, ``_source_sheet``, ``_source_row``) et une traçabilité
  colonne → source.

Les colonnes de provenance sont des scalaires par ligne (pas d'objets de
métadonnées) : le coût reste négligeable même sur plusieurs millions de lignes.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from typing import Any

from come_data.safety import quote_identifier, quote_literal

from .catalog import SourceCatalog
from .errors import ConsolidationError
from .provenance import AuditLog, ColumnLineage

_PROVENANCE_COLUMNS = ("_source_file", "_source_sheet", "_source_row")


def normalize_name(text: str) -> str:
    """Réduit un entête à une forme comparable (minuscules, sans accent)."""
    folded = unicodedata.normalize("NFKD", str(text))
    ascii_text = "".join(char for char in folded if not unicodedata.combining(char))
    ascii_text = ascii_text.lower()
    ascii_text = re.sub(r"[^a-z0-9]+", "_", ascii_text)
    return ascii_text.strip("_")


@dataclass(frozen=True)
class ColumnAlignment:
    """Alignement d'une colonne canonique à travers les sources."""

    canonical: str
    per_source: tuple[tuple[str, str | None], ...]
    missing_in: tuple[str, ...]

    def as_dict(self) -> dict[str, Any]:
        return {
            "canonical": self.canonical,
            "per_source": [{"source_id": sid, "column": col} for sid, col in self.per_source],
            "missing_in": list(self.missing_in),
        }


@dataclass(frozen=True)
class ConsolidationResult:
    """Résultat d'une consolidation, avec traçabilité complète."""

    table: str
    mode: str
    source_ids: tuple[str, ...]
    rows: int
    columns: tuple[str, ...]
    alignment: tuple[ColumnAlignment, ...]
    duplicate_rows: int
    lineage: tuple[ColumnLineage, ...]
    assumptions: tuple[str, ...]
    audit: AuditLog

    def as_dict(self) -> dict[str, Any]:
        return {
            "table": self.table,
            "mode": self.mode,
            "source_ids": list(self.source_ids),
            "rows": self.rows,
            "columns": list(self.columns),
            "alignment": [item.as_dict() for item in self.alignment],
            "duplicate_rows": self.duplicate_rows,
            "lineage": [item.as_dict() for item in self.lineage],
            "assumptions": list(self.assumptions),
            "audit": self.audit.as_dict(),
        }


def _source_column_map(catalog: SourceCatalog, source_ids: list[str]) -> dict[str, dict[str, str]]:
    """Pour chaque source : nom canonique → nom réel de colonne (première occurrence)."""
    mapping: dict[str, dict[str, str]] = {}
    for source_id in source_ids:
        per_source: dict[str, str] = {}
        for column in catalog.columns(source_id):
            canonical = normalize_name(column)
            if canonical and canonical not in per_source:
                per_source[canonical] = column
        mapping[source_id] = per_source
    return mapping


def align_sources(
    catalog: SourceCatalog, source_ids: list[str]
) -> tuple[list[str], list[ColumnAlignment], dict[str, dict[str, str]]]:
    """Renvoie (ordre canonique, alignements, map source→canonique→colonne)."""
    mapping = _source_column_map(catalog, source_ids)
    order: list[str] = []
    seen: set[str] = set()
    for source_id in source_ids:
        for canonical in mapping[source_id]:
            if canonical not in seen:
                seen.add(canonical)
                order.append(canonical)
    alignments: list[ColumnAlignment] = []
    for canonical in order:
        per_source = tuple((sid, mapping[sid].get(canonical)) for sid in source_ids)
        missing = tuple(sid for sid, column in per_source if column is None)
        alignments.append(ColumnAlignment(canonical, per_source, missing))
    return order, alignments, mapping


def consolidate(
    catalog: SourceCatalog,
    source_ids: list[str],
    *,
    mode: str = "union",
    on: list[str] | None = None,
    output_table: str | None = None,
    include_provenance: bool = True,
    align_keys: bool = True,
) -> ConsolidationResult:
    """Consolide plusieurs sources en une table DuckDB traçable.

    ``mode="union"`` empile les sources colonne par colonne (les colonnes
    absentes deviennent NULL). ``mode="join"`` rapproche les sources sur ``on``
    (noms canoniques), les colonnes homonymes étant suffixées par source.
    """
    if not source_ids:
        raise ConsolidationError("Au moins une source est nécessaire pour consolider.")
    for source_id in source_ids:
        catalog.source(source_id)  # valide l'existence

    order, alignments, mapping = align_sources(catalog, source_ids)
    if not order:
        raise ConsolidationError("Aucune colonne exploitable dans les sources fournies.")

    audit = AuditLog()
    table = output_table or _default_table_name(mode)
    qtable = quote_identifier(table)

    if mode == "union":
        core = _build_union(catalog, source_ids, order, mapping, include_provenance)
        lineage = _union_lineage(catalog, source_ids, order, mapping, include_provenance)
        assumptions = (
            "Rapprochement des colonnes par nom normalisé (minuscules, sans accent).",
            "Les colonnes absentes d'une source sont remplacées par NULL.",
        )
        join_keys: list[str] = []
    elif mode == "join":
        if len(source_ids) < 2:
            raise ConsolidationError("Un rapprochement exige au moins deux sources.")
        keys = [normalize_name(item) for item in (on or [])]
        if not keys:
            raise ConsolidationError("Le rapprochement exige une liste de colonnes « on ».")
        for key in keys:
            if any(mapping[source_id].get(key) is None for source_id in source_ids):
                raise ConsolidationError(
                    "Chaque source doit contenir toutes les colonnes de rapprochement."
                )
        core = _build_join(catalog, source_ids, keys, mapping, include_provenance)
        lineage = _join_lineage(catalog, source_ids, keys, mapping)
        assumptions = (
            "Rapprochement par jointure interne sur les colonnes « on » normalisées.",
            "Les colonnes homonymes hors clés sont suffixées par source.",
        )
        join_keys = keys
    else:
        raise ConsolidationError("Le mode doit être « union » ou « join ».")

    catalog.engine._con.execute(f"CREATE OR REPLACE TABLE {qtable} AS SELECT * FROM ({core}) AS consolidated")

    columns = [info["column_name"] for info in catalog.engine.columns(table)]
    rows = catalog.engine.row_count(table)
    data_columns = [column for column in columns if column not in _PROVENANCE_COLUMNS]
    duplicate_rows = _duplicate_rows(catalog, table, data_columns)

    audit.record(
        f"consolidate:{mode}",
        f"Consolidation de {len(source_ids)} source(s) vers {table}",
        inputs=tuple(source_id for source_id in source_ids),
        output=table,
        assumptions=assumptions,
        checks=(
            f"lignes={rows}",
            f"doublons_exacts={duplicate_rows}",
            f"colonnes={len(columns)}",
        ),
        formula=f"SELECT ... FROM ({mode})",
    )
    if duplicate_rows:
        audit.record(
            "quality:duplicates",
            f"{duplicate_rows} ligne(s) dupliquée(s) exactement détectée(s)",
            inputs=(table,),
            checks=("SELECT DISTINCT sur les colonnes de données",),
        )
    if join_keys:
        audit.record(
            "join_keys",
            "Clés de rapprochement utilisées",
            inputs=tuple(join_keys),
            assumptions=("Jointure interne ; les non-correspondances sont exclues.",),
        )

    return ConsolidationResult(
        table=table,
        mode=mode,
        source_ids=tuple(source_ids),
        rows=rows,
        columns=tuple(columns),
        alignment=tuple(alignments),
        duplicate_rows=duplicate_rows,
        lineage=tuple(lineage),
        assumptions=assumptions,
        audit=audit,
    )


# --------------------------------------------------------------------------- #
# Construction SQL
# --------------------------------------------------------------------------- #
def _build_union(
    catalog: SourceCatalog,
    source_ids: list[str],
    order: list[str],
    mapping: dict[str, dict[str, str]],
    include_provenance: bool,
) -> str:
    branches: list[str] = []
    for source_id in source_ids:
        source = catalog.source(source_id)
        per_source = mapping[source_id]
        selects: list[str] = []
        for canonical in order:
            actual = per_source.get(canonical)
            if actual is not None:
                selects.append(f"{quote_identifier(actual)} AS {quote_identifier(canonical)}")
            else:
                selects.append(f"NULL AS {quote_identifier(canonical)}")
        if include_provenance:
            selects.append(f"{quote_literal(source.file_name)} AS {quote_identifier('_source_file')}")
            selects.append(f"{quote_literal(source.sheet or '')} AS {quote_identifier('_source_sheet')}")
            selects.append(f"row_number() OVER () AS {quote_identifier('_source_row')}")
        branches.append(
            f"SELECT {', '.join(selects)} FROM {quote_identifier(source.registered_table or '')}"
        )
    return " UNION ALL ".join(branches)


def _build_join(
    catalog: SourceCatalog,
    source_ids: list[str],
    keys: list[str],
    mapping: dict[str, dict[str, str]],
    include_provenance: bool,
) -> str:
    base_id = source_ids[0]
    base = catalog.source(base_id)
    base_alias = "s0"
    base_map = mapping[base_id]
    used_suffixes: set[str] = set()
    selects: list[str] = []
    for key in keys:
        selects.append(
            f"{base_alias}.{quote_identifier(base_map[key])} AS {quote_identifier(key)}"
        )
    base_non_keys = [canonical for canonical in mapping[base_id] if canonical not in keys]
    for canonical in base_non_keys:
        selects.append(
            f"{base_alias}.{quote_identifier(base_map[canonical])} AS {quote_identifier(canonical)}"
        )
    if include_provenance:
        selects.append(f"{quote_literal(base.file_name)} AS {quote_identifier('_source_file')}")
        selects.append(f"{quote_literal(base.sheet or '')} AS {quote_identifier('_source_sheet')}")

    joins: list[str] = []
    existing = set(keys) | set(base_non_keys)
    for index, source_id in enumerate(source_ids[1:], start=1):
        source = catalog.source(source_id)
        alias = f"s{index}"
        per_source = mapping[source_id]
        condition = " AND ".join(
            f"{base_alias}.{quote_identifier(base_map[key])} = {alias}.{quote_identifier(per_source[key])}"
            for key in keys
        )
        joins.append(f"JOIN {quote_identifier(source.registered_table or '')} AS {alias} ON {condition}")
        suffix = _unique_suffix(source.file_name, index, used_suffixes)
        for canonical in per_source:
            if canonical in keys:
                continue
            output = canonical if canonical not in existing else canonical + suffix
            existing.add(output)
            selects.append(
                f"{alias}.{quote_identifier(per_source[canonical])} AS {quote_identifier(output)}"
            )
        if include_provenance:
            selects.append(f"{quote_literal(source.file_name)} AS {quote_identifier('_source_file' + suffix)}")
            selects.append(f"{quote_literal(source.sheet or '')} AS {quote_identifier('_source_sheet' + suffix)}")

    base_table = quote_identifier(base.registered_table or "")
    return f"SELECT {', '.join(selects)} FROM {base_table} AS {base_alias} " + " ".join(joins)


def _unique_suffix(file_name: str, index: int, used: set[str]) -> str:
    stem = normalize_name(file_name.rsplit(".", 1)[0]) or f"src{index}"
    candidate = f"__{stem}"
    if candidate in used:
        candidate = f"__{stem}_{index}"
    used.add(candidate)
    return candidate


# --------------------------------------------------------------------------- #
# Traçabilité colonne → source
# --------------------------------------------------------------------------- #
def _union_lineage(
    catalog: SourceCatalog,
    source_ids: list[str],
    order: list[str],
    mapping: dict[str, dict[str, str]],
    include_provenance: bool,
) -> list[ColumnLineage]:
    lineage: list[ColumnLineage] = []
    for canonical in order:
        references: list[str] = []
        for source_id in source_ids:
            actual = mapping[source_id].get(canonical)
            if actual is None:
                continue
            source = catalog.source(source_id)
            location = source.file_name + (f"#{source.sheet}" if source.sheet else "")
            references.append(f"{location}.{actual}")
        lineage.append(
            ColumnLineage(
                output_column=canonical,
                sources=tuple(references),
                transform="union aligné par nom normalisé ; NULL si colonne absente",
                assumptions=("Les unités et périodes doivent être vérifiées par source.",),
            )
        )
    if include_provenance:
        lineage.append(
            ColumnLineage(
                output_column="_source_file",
                sources=tuple(source.file_name for source in (catalog.source(sid) for sid in source_ids)),
                transform="littéral par branche ; identifie le classeur d'origine",
            )
        )
        lineage.append(
            ColumnLineage(
                output_column="_source_sheet",
                sources=tuple(source.sheet or "" for source in (catalog.source(sid) for sid in source_ids)),
                transform="littéral par branche ; identifie la feuille d'origine",
            )
        )
        lineage.append(
            ColumnLineage(
                output_column="_source_row",
                sources=tuple(catalog.source(sid).registered_table or "" for sid in source_ids),
                transform="row_number() OVER () par branche ; rang dans la source",
            )
        )
    return lineage


def _join_lineage(
    catalog: SourceCatalog,
    source_ids: list[str],
    keys: list[str],
    mapping: dict[str, dict[str, str]],
) -> list[ColumnLineage]:
    lineage: list[ColumnLineage] = []
    for canonical in keys:
        references = []
        for source_id in source_ids:
            actual = mapping[source_id].get(canonical)
            source = catalog.source(source_id)
            location = source.file_name + (f"#{source.sheet}" if source.sheet else "")
            references.append(f"{location}.{actual}")
        lineage.append(
            ColumnLineage(
                output_column=canonical,
                sources=tuple(references),
                transform="clé de jointure interne",
            )
        )
    return lineage


# --------------------------------------------------------------------------- #
# Aides
# --------------------------------------------------------------------------- #
def _duplicate_rows(catalog: SourceCatalog, table: str, data_columns: list[str]) -> int:
    if not data_columns:
        return 0
    qtable = quote_identifier(table)
    columns = ", ".join(quote_identifier(column) for column in data_columns)
    rows = catalog.engine.row_count(table)
    distinct = catalog.engine._con.execute(
        f"SELECT count(*) FROM (SELECT DISTINCT {columns} FROM {qtable}) AS d"
    ).fetchone()[0]
    return max(0, int(rows) - int(distinct or 0))


def _default_table_name(mode: str) -> str:
    import uuid  # noqa: PLC0415

    return f"consolidated_{mode}_{uuid.uuid4().hex[:8]}"


__all__ = [
    "ColumnAlignment",
    "ConsolidationResult",
    "align_sources",
    "consolidate",
    "normalize_name",
]
