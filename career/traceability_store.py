"""Persistance locale du registre de traçabilité (SPEC-011).

Le registre est un fichier JSON local, écrit de façon atomique, sans réseau
et sans base partagée : il appartient à l'utilisateur et il se transporte
(l'export JSON est ré-importable tel quel).

FORMAT DU FICHIER (``registry.json``) ::

    {
      "schema_version": 1,
      "updated_at": "2026-10-22T09:00:00+00:00",
      "traces":  [ … RequirementTrace … ],
      "deleted": [ … RequirementTrace … ]
    }

GARANTIES
- Écriture atomique : le fichier est écrit dans un temporaire puis
  ``os.replace`` : un registre ne se corrompt jamais à moitié.
- Lecture stricte : un fichier illisible lève une erreur explicite plutôt
  que de faire croire à un registre vide (une piste d'audit ne s'efface pas
  dans le silence).
- Export CSV : une ligne par exigence, séparateur ``;`` (Excel FR), avec
  l'historique résumé.
"""

from __future__ import annotations

import csv
import io
import json
import os
import tempfile
from pathlib import Path
from typing import Any, Iterable, Mapping

from workspace_core import UserFacingError

from .traceability import RequirementTrace, TraceabilityRegistry

__all__ = [
    "STORE_ENV_VAR",
    "STORE_SCHEMA_VERSION",
    "TraceabilityStore",
    "default_store_path",
]


STORE_SCHEMA_VERSION = 1
STORE_ENV_VAR = "CAREER_TRACEABILITY_PATH"

#: Colonnes de l'export CSV, dans l'ordre.
CSV_COLUMNS: tuple[str, ...] = (
    "trace_id",
    "requirement_id",
    "requirement_text",
    "source",
    "offer_id",
    "cv_id",
    "category",
    "criticality",
    "status",
    "evidence_id",
    "evidence_quote",
    "created_at",
    "updated_at",
    "tags",
    "history_count",
)


def default_store_path() -> Path:
    """Return the default location of the registry file.

    The environment variable wins so a test (or a second workspace) can
    point the registry somewhere else without touching the code.
    """

    override = os.environ.get(STORE_ENV_VAR, "").strip()
    if override:
        return Path(override).expanduser()
    root = Path(__file__).resolve().parent.parent
    return root / "career_data" / "traceability" / "registry.json"


class TraceabilityStore:
    """Read/write access to the local registry file."""

    def __init__(self, path: Path | str | None = None) -> None:
        self.path = Path(path) if path is not None else default_store_path()

    # ── Fichier ─────────────────────────────────────────────────────────────
    def exists(self) -> bool:
        return self.path.is_file()

    def load(self) -> TraceabilityRegistry:
        """Load the registry; an empty registry is returned when no file exists."""

        if not self.path.is_file():
            return TraceabilityRegistry()
        try:
            raw = self.path.read_text(encoding="utf-8")
        except OSError as error:
            raise UserFacingError(
                f"Le registre de traçabilité local n'a pas pu être lu : {self.path.name}."
            ) from error
        if not raw.strip():
            return TraceabilityRegistry()
        try:
            payload = json.loads(raw)
        except (TypeError, ValueError) as error:
            raise UserFacingError(
                "Le registre de traçabilité local est illisible ; il n'a pas été replaced."
            ) from error
        if not isinstance(payload, Mapping):
            raise UserFacingError("Le registre de traçabilité local est illisible.")
        version = payload.get("schema_version")
        if version is not None and int(version) > STORE_SCHEMA_VERSION:
            raise UserFacingError(
                "Le registre de traçabilité local a été écrit par une version plus récente."
            )
        try:
            return TraceabilityRegistry.from_dict(payload)
        except UserFacingError:
            raise
        except (TypeError, ValueError) as error:
            raise UserFacingError(
                "Le registre de traçabilité local contient des entrées invalides ; il n'a pas été remplacé."
            ) from error

    def save(self, registry: TraceabilityRegistry) -> Path:
        """Write the registry atomically and return the file path."""

        self.path.parent.mkdir(parents=True, exist_ok=True)
        stamps = [trace.updated_at for trace in registry.traces(include_deleted=True)]
        payload = {
            "schema_version": STORE_SCHEMA_VERSION,
            "updated_at": max(stamps) if stamps else "",
            "traces": [trace.to_dict() for trace in registry.traces()],
            "deleted": [trace.to_dict() for trace in registry.deleted_traces()],
        }
        content = json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True)
        handle, temporary = tempfile.mkstemp(
            dir=str(self.path.parent), prefix=self.path.name, suffix=".tmp"
        )
        try:
            with os.fdopen(handle, "w", encoding="utf-8") as stream:
                stream.write(content)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, self.path)
        except OSError as error:
            try:
                os.unlink(temporary)
            except OSError:
                pass
            raise UserFacingError(
                "Le registre de traçabilité n'a pas pu être enregistré sur le disque."
            ) from error
        return self.path

    # ── Requêtes ────────────────────────────────────────────────────────────
    def query(self, registry: TraceabilityRegistry | None = None, **filters: Any) -> list[RequirementTrace]:
        """Return the traces matching the filters (see ``TraceabilityRegistry.filter``)."""

        active = registry if registry is not None else self.load()
        return active.filter(**filters)

    # ── Export / import ─────────────────────────────────────────────────────
    def export_json(
        self,
        registry: TraceabilityRegistry | None = None,
        *,
        indent: int = 2,
    ) -> str:
        """Export the whole registry as JSON (re-importable)."""

        active = registry if registry is not None else self.load()
        payload = {
            "schema_version": STORE_SCHEMA_VERSION,
            "traces": [trace.to_dict() for trace in active.traces()],
            "deleted": [trace.to_dict() for trace in active.deleted_traces()],
        }
        return json.dumps(payload, ensure_ascii=False, indent=indent, sort_keys=True)

    def export_csv(
        self,
        registry: TraceabilityRegistry | None = None,
        *,
        include_deleted: bool = False,
    ) -> str:
        """Export the registry as CSV (semicolon separated, Excel friendly)."""

        active = registry if registry is not None else self.load()
        buffer = io.StringIO()
        writer = csv.DictWriter(buffer, fieldnames=list(CSV_COLUMNS), delimiter=";")
        writer.writeheader()
        for trace in active.traces(include_deleted=include_deleted):
            payload = trace.to_dict()
            writer.writerow(
                {
                    "trace_id": payload["trace_id"],
                    "requirement_id": payload["requirement_id"],
                    "requirement_text": payload["requirement_text"],
                    "source": payload["source"],
                    "offer_id": payload["offer_id"],
                    "cv_id": payload["cv_id"],
                    "category": payload["category"],
                    "criticality": payload["criticality"],
                    "status": payload["status"],
                    "evidence_id": payload["evidence_id"] or "",
                    "evidence_quote": payload["evidence_quote"] or "",
                    "created_at": payload["created_at"],
                    "updated_at": payload["updated_at"],
                    "tags": ",".join(payload["tags"]),
                    "history_count": len(payload["history"]),
                }
            )
        return buffer.getvalue()

    def import_json(self, payload: str | Mapping[str, Any]) -> TraceabilityRegistry:
        """Import a registry previously exported by ``export_json``."""

        if isinstance(payload, str):
            try:
                data = json.loads(payload)
            except (TypeError, ValueError) as error:
                raise UserFacingError("Le contenu importé n'est pas un JSON valide.") from error
        else:
            data = payload
        if not isinstance(data, Mapping):
            raise UserFacingError("Le contenu importé doit être un objet JSON.")
        return TraceabilityRegistry.from_dict(data)

    def import_csv(self, content: str) -> TraceabilityRegistry:
        """Import traces from a CSV export (the history is not restored)."""

        reader = csv.DictReader(io.StringIO(content), delimiter=";")
        registry = TraceabilityRegistry()
        for row in reader:
            payload = {key: row.get(key, "") for key in CSV_COLUMNS if key in row}
            if not payload.get("requirement_text"):
                continue
            try:
                trace = RequirementTrace.from_dict(payload)
            except UserFacingError:
                continue
            registry.add(trace)
        return registry


def iter_export_rows(traces: Iterable[RequirementTrace]) -> list[dict[str, Any]]:
    """Return the export rows of the given traces (helper for reports)."""

    return [trace.to_dict() for trace in traces]
