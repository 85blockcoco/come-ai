"""Provenance et journal d'audit pour la couche Excel avancée.

Principe : tracer au niveau **source**, **colonne** et **transformation**, jamais
par cellule ni par ligne sur des tables de plusieurs millions de lignes. Quand
une granularité ligne est nécessaire, on ajoute une colonne ``_source_row``
(valeur entière) plutôt qu'un objet de métadonnées par ligne.

Chaque résultat financier important peut ainsi être relié :

1. au fichier, à la feuille et à la plage de cellules source ;
2. aux transformations appliquées (chaîne d'opérations SQL) ;
3. aux hypothèses déclarées ;
4. à la formule ou à la fonction utilisée ;
5. aux contrôles de cohérence exécutés.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ENGINE_NAME = "come_excel"
ENGINE_VERSION = "0.1.0"

_HASH_CHUNK = 1 << 20  # 1 Mio


def fingerprint_file(path: str | Path) -> str:
    """Empreinte SHA-256 du contenu d'un fichier, lue en flux (RAM bornée)."""
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for block in iter(lambda: handle.read(_HASH_CHUNK), b""):
            digest.update(block)
    return digest.hexdigest()


def _timestamp() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


@dataclass(frozen=True)
class SourceRef:
    """Référence immuable à une source (fichier + feuille éventuelle)."""

    source_id: str
    file_name: str
    path: str
    kind: str
    fingerprint: str
    size_bytes: int
    sheet: str | None = None
    cell_range: str | None = None
    rows: int | None = None
    columns: int | None = None
    registered_table: str | None = None

    def as_dict(self, *, include_path: bool = False) -> dict[str, Any]:
        data: dict[str, Any] = {
            "source_id": self.source_id,
            "file_name": self.file_name,
            "kind": self.kind,
            "sheet": self.sheet,
            "cell_range": self.cell_range,
            "rows": self.rows,
            "columns": self.columns,
            "fingerprint": self.fingerprint,
            "size_bytes": self.size_bytes,
            "registered_table": self.registered_table,
        }
        if include_path:
            data["path"] = self.path
        return data


@dataclass(frozen=True)
class AuditEntry:
    """Une étape auditable : opération, entrées, sortie, hypothèses, contrôles."""

    step: int
    operation: str
    description: str
    inputs: tuple[str, ...] = ()
    output: str | None = None
    assumptions: tuple[str, ...] = ()
    checks: tuple[str, ...] = ()
    formula: str | None = None
    timestamp: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {
            "step": self.step,
            "operation": self.operation,
            "description": self.description,
            "inputs": list(self.inputs),
            "output": self.output,
            "assumptions": list(self.assumptions),
            "checks": list(self.checks),
            "formula": self.formula,
            "timestamp": self.timestamp,
        }


@dataclass
class AuditLog:
    """Journal d'audit append-only, sérialisable en JSON."""

    engine: str = ENGINE_NAME
    version: str = ENGINE_VERSION
    _entries: list[AuditEntry] = field(default_factory=list)

    def record(
        self,
        operation: str,
        description: str,
        *,
        inputs: tuple[str, ...] | list[str] = (),
        output: str | None = None,
        assumptions: tuple[str, ...] | list[str] = (),
        checks: tuple[str, ...] | list[str] = (),
        formula: str | None = None,
    ) -> AuditEntry:
        entry = AuditEntry(
            step=len(self._entries) + 1,
            operation=operation,
            description=description,
            inputs=tuple(inputs),
            output=output,
            assumptions=tuple(assumptions),
            checks=tuple(checks),
            formula=formula,
            timestamp=_timestamp(),
        )
        self._entries.append(entry)
        return entry

    def extend(self, other: "AuditLog") -> None:
        for entry in other._entries:
            self.record(
                entry.operation,
                entry.description,
                inputs=entry.inputs,
                output=entry.output,
                assumptions=entry.assumptions,
                checks=entry.checks,
                formula=entry.formula,
            )

    def entries(self) -> list[AuditEntry]:
        return list(self._entries)

    def steps(self) -> list[str]:
        return [f"{entry.operation}: {entry.description}" for entry in self._entries]

    def __len__(self) -> int:
        return len(self._entries)

    def as_dict(self) -> dict[str, Any]:
        return {
            "engine": self.engine,
            "version": self.version,
            "steps": len(self._entries),
            "entries": [entry.as_dict() for entry in self._entries],
        }


@dataclass(frozen=True)
class ColumnLineage:
    """Relie une colonne de sortie à ses colonnes sources et à la transformation."""

    output_column: str
    sources: tuple[str, ...]
    transform: str
    assumptions: tuple[str, ...] = ()

    def as_dict(self) -> dict[str, Any]:
        return {
            "output_column": self.output_column,
            "sources": list(self.sources),
            "transform": self.transform,
            "assumptions": list(self.assumptions),
        }


@dataclass(frozen=True)
class Provenance:
    """Provenance d'un tableau dérivé : sources, plage, empreintes, hypothèses."""

    label: str
    sources: tuple[SourceRef, ...]
    transform: str
    assumptions: tuple[str, ...] = ()
    checks: tuple[str, ...] = ()
    lineage: tuple[ColumnLineage, ...] = ()
    created_at: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {
            "label": self.label,
            "transform": self.transform,
            "sources": [source.as_dict() for source in self.sources],
            "assumptions": list(self.assumptions),
            "checks": list(self.checks),
            "lineage": [item.as_dict() for item in self.lineage],
            "created_at": self.created_at or _timestamp(),
        }


__all__ = [
    "ENGINE_NAME",
    "ENGINE_VERSION",
    "AuditEntry",
    "AuditLog",
    "ColumnLineage",
    "Provenance",
    "SourceRef",
    "fingerprint_file",
]
