"""Catalogue de sources multi-classeurs au-dessus du moteur DuckDB.

``SourceCatalog`` enregistre de nombreux fichiers (CSV, XLSX, XLSM, XLS,
Parquet) comme vues/tables DuckDB paresseuses, tout en conservant pour chacun
une ``SourceRef`` traçable (fichier, feuille, plage, empreinte SHA-256,
dimensions). Les fichiers sources ne sont jamais modifiés.

Convention : l'inspection légère précède l'enregistrement ; on ne réalise un
comptage de lignes que sur demande explicite (``count_rows=True``), car il
parcourt le fichier.
"""

from __future__ import annotations

import hashlib
from collections.abc import Iterable, Sequence
from pathlib import Path
from typing import Any

from come_data.engine import DataEngine
from come_data.safety import resolve_within

from .errors import ConsolidationError, UnsupportedSpreadsheetError
from .inspect import WorkbookInspection, inspect_file
from .provenance import AuditLog, SourceRef

_EXCEL_KINDS = {"xlsx", "xlsm", "xls"}


class SourceCatalog:
    """Registre de sources tabulaires, avec provenance et audit.

    Le catalogue est un gestionnaire de contexte : ``with SourceCatalog(...)``
    ferme la connexion DuckDB à la sortie.
    """

    def __init__(
        self,
        data_dir: str | Path,
        output_dir: str | Path | None = None,
        *,
        memory_limit: str = "2GB",
        temp_dir: str | Path | None = None,
        query_timeout_seconds: float = 30.0,
        engine: DataEngine | None = None,
    ) -> None:
        self.data_dir = Path(data_dir).expanduser().resolve()
        self.output_dir = Path(output_dir).expanduser().resolve() if output_dir else None
        roots = [self.data_dir] + ([self.output_dir] if self.output_dir else [])
        self.engine = engine if engine is not None else DataEngine(
            roots,
            memory_limit=memory_limit,
            temp_dir=Path(temp_dir) if temp_dir else None,
            query_timeout_seconds=query_timeout_seconds,
        )
        self.audit = AuditLog()
        self._sources: dict[str, SourceRef] = {}
        self._by_path_sheet: dict[tuple[str, str | None], str] = {}
        self._inspections: dict[str, WorkbookInspection] = {}

    # ------------------------------------------------------------------ #
    # Cycle de vie
    # ------------------------------------------------------------------ #
    def close(self) -> None:
        self.engine.close()

    def __enter__(self) -> "SourceCatalog":
        return self

    def __exit__(self, *_exc: object) -> None:
        self.close()

    # ------------------------------------------------------------------ #
    # Inspection
    # ------------------------------------------------------------------ #
    def inspect(self, path: str | Path, *, refresh: bool = False) -> WorkbookInspection:
        """Inspection légère, mise en cache par empreinte de fichier."""
        resolved = self._resolve(path)
        key = str(resolved)
        cached = self._inspections.get(key)
        if cached is not None and not refresh:
            return cached
        inspection = inspect_file(resolved)
        self._inspections[str(resolved)] = inspection
        return inspection

    def sheet_names(self, path: str | Path) -> list[str]:
        return [sheet.name for sheet in self.inspect(path).sheets]

    # ------------------------------------------------------------------ #
    # Enregistrement
    # ------------------------------------------------------------------ #
    def add(
        self,
        path: str | Path,
        *,
        sheet: str | None = None,
        name: str | None = None,
        count_rows: bool = False,
    ) -> SourceRef:
        """Enregistre un fichier (une feuille si Excel) et renvoie sa provenance."""
        resolved = self._resolve(path)
        inspection = self.inspect(resolved)
        suffix = resolved.suffix.lower().lstrip(".")

        if suffix in _EXCEL_KINDS:
            available = [item.name for item in inspection.sheets]
            if not available:
                raise UnsupportedSpreadsheetError("Ce classeur ne contient aucune feuille lisible.")
            selected = sheet or available[0]
            if selected not in available:
                raise UnsupportedSpreadsheetError("La feuille demandée n'existe pas dans ce classeur.")
        else:
            selected = sheet

        source_id = self._source_id(inspection.fingerprint, selected)
        existing = self._sources.get(source_id)
        if existing is not None:
            return existing

        try:
            info = self.engine.register_file(resolved, name=name, sheet=selected)
        except Exception as error:  # noqa: BLE001 - message générique
            raise ConsolidationError("Ce fichier n'a pas pu être enregistré dans le moteur.") from error

        cell_range = None
        columns: int | None = None
        rows: int | None = None
        for item in inspection.sheets:
            if selected is None or item.name == selected:
                cell_range = item.cell_range
                columns = len(item.headers) or item.max_column
                rows = item.max_row
                break

        if count_rows:
            rows = self.engine.row_count(info.name)

        source = SourceRef(
            source_id=source_id,
            file_name=resolved.name,
            path=str(resolved),
            kind=suffix,
            fingerprint=inspection.fingerprint,
            size_bytes=inspection.size_bytes,
            sheet=selected,
            cell_range=cell_range,
            rows=rows,
            columns=columns,
            registered_table=info.name,
        )
        self._sources[source_id] = source
        self._by_path_sheet[(str(resolved), selected)] = source_id
        self.audit.record(
            "register",
            f"Enregistrement de {resolved.name}"
            + (f" (feuille {selected})" if selected else ""),
            inputs=(resolved.name,),
            output=info.name,
            assumptions=(
                "Le fichier source n'est pas modifié ; il est exposé comme vue ou table DuckDB.",
            ),
            checks=(
                f"empreinte sha256={inspection.fingerprint[:12]}",
                f"dimensions collées={columns or '?'} colonnes",
            ),
        )
        return source

    def add_many(
        self,
        paths: Iterable[str | Path],
        *,
        count_rows: bool = False,
    ) -> list[SourceRef]:
        return [self.add(path, count_rows=count_rows) for path in paths]

    def add_all_sheets(
        self,
        path: str | Path,
        *,
        count_rows: bool = False,
    ) -> list[SourceRef]:
        """Enregistre chaque feuille d'un classeur comme source distincte."""
        resolved = self._resolve(path)
        inspection = self.inspect(resolved)
        return [
            self.add(resolved, sheet=item.name, count_rows=count_rows)
            for item in inspection.sheets
            if not item.is_empty
        ]

    # ------------------------------------------------------------------ #
    # Accès
    # ------------------------------------------------------------------ #
    def sources(self) -> list[SourceRef]:
        return list(self._sources.values())

    def source(self, source_id: str) -> SourceRef:
        try:
            return self._sources[source_id]
        except KeyError as error:
            raise ConsolidationError("Source inconnue dans le catalogue.") from error

    def table(self, source_id: str) -> str:
        return self.source(source_id).registered_table or ""

    def row_count(self, source_id: str) -> int:
        return self.engine.row_count(self.table(source_id))

    def columns(self, source_id: str) -> list[str]:
        return [item["column_name"] for item in self.engine.columns(self.table(source_id))]

    def query(self, sql: str, params: Sequence[Any] | None = None) -> list[dict[str, Any]]:
        return self.engine.query(sql, params)

    def query_frame(self, sql: str, params: Sequence[Any] | None = None) -> Any:
        return self.engine.query_frame(sql, params)

    # ------------------------------------------------------------------ #
    # Aides internes
    # ------------------------------------------------------------------ #
    def _resolve(self, path: str | Path) -> Path:
        roots = [self.data_dir] + ([self.output_dir] if self.output_dir else [])
        try:
            return resolve_within(roots, path)
        except Exception as error:  # noqa: BLE001 - message générique
            raise UnsupportedSpreadsheetError(
                "Ce fichier est introuvable dans les dossiers autorisés."
            ) from error

    @staticmethod
    def _source_id(fingerprint: str, sheet: str | None) -> str:
        material = f"{fingerprint}:{sheet or ''}".encode("utf-8")
        return "src_" + hashlib.sha1(material).hexdigest()[:12]


__all__ = ["SourceCatalog"]
