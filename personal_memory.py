"""Controlled, local personal-memory foundation for C\u00f4me AI.

This module is deliberately independent from the web application and from all
model providers.  It stores only extracted text and local metadata in SQLite;
it never reads ``.env``, opens the network, recursively scans a directory, or
keeps an absolute path to an imported document.

The public API is intentionally small so that a future orchestrator can expose
opaque source/project identifiers to a model instead of exposing the user's
filesystem:

* :meth:`PersonalMemoryStore.import_file` imports one explicit file only;
* :meth:`PersonalMemoryStore.import_text` imports caller-supplied text;
* :meth:`PersonalMemoryStore.search` returns short local excerpts with a
  source/page/line citation;
* project/source listing and deletion stay local and deterministic.

The store is a foundation, not an OCR or arbitrary-file-execution system.
Scanned PDFs with no embedded text are reported honestly so that an explicit
local OCR stage can be added by the application later.
"""

from __future__ import annotations

import hashlib
import html
from io import StringIO
import os
import re
import sqlite3
import unicodedata
import uuid
import zipfile
from contextlib import contextmanager
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from html.parser import HTMLParser
from pathlib import Path
from threading import RLock
from typing import Any, Iterator, Sequence
from xml.etree import ElementTree as ET


SCHEMA_VERSION = 2

# These values preserve V5's existing default envelope on an older Intel Mac.
# They are defaults, not hidden product ceilings: a local deployment can pass
# ``MemoryResourceLimits`` to set an explicit envelope appropriate for its
# storage and RAM.  Every limit remains finite because document extractors are
# a boundary between untrusted office archives and the local process.
DEFAULT_MAX_SOURCE_BYTES = 25 * 1024 * 1024
DEFAULT_MAX_TEXT_CHARS = 1_000_000
DEFAULT_MAX_CHUNKS_PER_SOURCE = 2_000
DEFAULT_MAX_PDF_PAGES = 500
DEFAULT_MAX_DOCX_ARCHIVE_ENTRIES = 10_000
DEFAULT_MAX_DOCX_UNCOMPRESSED_BYTES = 25 * 1024 * 1024
DEFAULT_CHUNK_CHARS = 1_200
DEFAULT_MAX_EXCEL_SHEETS = 128
DEFAULT_MAX_EXCEL_ROWS_PER_SHEET = 200_000
DEFAULT_MAX_EXCEL_COLUMNS = 512
DEFAULT_MAX_EXCEL_ARCHIVE_ENTRIES = 20_000
DEFAULT_MAX_EXCEL_UNCOMPRESSED_BYTES = 100 * 1024 * 1024
MAX_FILENAME_CHARS = 240
MAX_TITLE_CHARS = 240
MAX_CATEGORY_CHARS = 80
MAX_PROJECT_NAME_CHARS = 120
MAX_PROJECT_DESCRIPTION_CHARS = 2_000
MAX_QUERY_CHARS = 500
MAX_QUERY_TERMS = 12
MAX_SEARCH_RESULTS = 50
MAX_LIST_RESULTS = 500
# Kept as a compatibility alias for code that imports the old module constant.
CHUNK_CHARS = DEFAULT_CHUNK_CHARS
MAX_SHEET_NAME_CHARS = 128

ALLOWED_FILE_SUFFIXES = frozenset(
    {".txt", ".md", ".csv", ".tsv", ".json", ".html", ".htm", ".pdf", ".docx", ".xlsx", ".xlsm"}
)
PLAIN_TEXT_SUFFIXES = frozenset({".txt", ".md", ".csv", ".tsv", ".json"})
_XML_WORD_NAMESPACE = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
_QUERY_TERM_RE = re.compile(r"\w+", flags=re.UNICODE)


class PersonalMemoryError(RuntimeError):
    """A safe, user-facing local-memory error with no implementation detail."""


class PersonalMemoryLimitError(PersonalMemoryError):
    """Raised when an explicit, bounded import/search input exceeds a limit."""


@dataclass(frozen=True)
class MemoryResourceLimits:
    """Explicit, documented local resource envelope for one memory store.

    Defaults keep the V5 behavior for existing callers.  Larger libraries can
    deliberately choose a larger envelope when the user has enough local disk
    and memory; no external service, model, or directory crawl is enabled by
    doing so.  The limits apply before or while extracting data so a malformed
    Office archive cannot silently consume unbounded resources.
    """

    max_source_bytes: int = DEFAULT_MAX_SOURCE_BYTES
    max_text_chars: int = DEFAULT_MAX_TEXT_CHARS
    max_chunks_per_source: int = DEFAULT_MAX_CHUNKS_PER_SOURCE
    max_pdf_pages: int = DEFAULT_MAX_PDF_PAGES
    max_docx_archive_entries: int = DEFAULT_MAX_DOCX_ARCHIVE_ENTRIES
    max_docx_uncompressed_bytes: int = DEFAULT_MAX_DOCX_UNCOMPRESSED_BYTES
    chunk_chars: int = DEFAULT_CHUNK_CHARS
    max_excel_sheets: int = DEFAULT_MAX_EXCEL_SHEETS
    max_excel_rows_per_sheet: int = DEFAULT_MAX_EXCEL_ROWS_PER_SHEET
    max_excel_columns: int = DEFAULT_MAX_EXCEL_COLUMNS
    max_excel_archive_entries: int = DEFAULT_MAX_EXCEL_ARCHIVE_ENTRIES
    max_excel_uncompressed_bytes: int = DEFAULT_MAX_EXCEL_UNCOMPRESSED_BYTES

    def __post_init__(self) -> None:
        for field_name, value in self.as_dict().items():
            if isinstance(value, bool) or not isinstance(value, int) or value < 1:
                raise ValueError(f"La limite {field_name} doit être un entier positif.")

    def as_dict(self) -> dict[str, int]:
        """Return a serialisable view suitable for a local settings screen."""
        return {
            "max_source_bytes": self.max_source_bytes,
            "max_text_chars": self.max_text_chars,
            "max_chunks_per_source": self.max_chunks_per_source,
            "max_pdf_pages": self.max_pdf_pages,
            "max_docx_archive_entries": self.max_docx_archive_entries,
            "max_docx_uncompressed_bytes": self.max_docx_uncompressed_bytes,
            "chunk_chars": self.chunk_chars,
            "max_excel_sheets": self.max_excel_sheets,
            "max_excel_rows_per_sheet": self.max_excel_rows_per_sheet,
            "max_excel_columns": self.max_excel_columns,
            "max_excel_archive_entries": self.max_excel_archive_entries,
            "max_excel_uncompressed_bytes": self.max_excel_uncompressed_bytes,
        }


@dataclass(frozen=True)
class _ExtractedPart:
    """Text extracted from one logical page, with line numbers local to it."""

    text: str
    page_number: int | None = None
    sheet_name: str | None = None
    line_start: int = 1


class _VisibleTextParser(HTMLParser):
    """Small, dependency-free HTML-to-text parser for explicit local files."""

    _BLOCK_TAGS = frozenset({"address", "article", "br", "div", "footer", "h1", "h2", "h3", "h4", "h5", "h6", "header", "li", "main", "p", "section", "table", "tr"})
    _SKIP_TAGS = frozenset({"script", "style", "template", "noscript"})

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._parts: list[str] = []
        self._skip_depth = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        del attrs
        lowered = tag.lower()
        if lowered in self._SKIP_TAGS:
            self._skip_depth += 1
        elif not self._skip_depth and lowered in self._BLOCK_TAGS:
            self._parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        lowered = tag.lower()
        if lowered in self._SKIP_TAGS and self._skip_depth:
            self._skip_depth -= 1
        elif not self._skip_depth and lowered in self._BLOCK_TAGS:
            self._parts.append("\n")

    def handle_data(self, data: str) -> None:
        if not self._skip_depth:
            self._parts.append(data)

    def text(self) -> str:
        return html.unescape("".join(self._parts))


class PersonalMemoryStore:
    """A bounded SQLite/FTS5 memory store which never invokes a model.

    ``base_dir`` is a caller-selected local directory.  Passing ``db_path``
    permits a different filename/location (for example an external SSD) while
    keeping the API fully local.  The SQLite database (and its normal SQLite
    journal sidecars while active) are the only persistent files created by
    this class; original documents remain untouched in their own locations and
    their absolute paths are never stored.
    """

    def __init__(
        self,
        base_dir: Path | str | None = None,
        *,
        db_path: Path | str | None = None,
        max_source_bytes: int | None = None,
        max_text_chars: int | None = None,
        resource_limits: MemoryResourceLimits | None = None,
    ) -> None:
        if db_path is None and base_dir is None:
            raise ValueError("Indique base_dir ou db_path pour la m\u00e9moire locale.")
        if resource_limits is not None and not isinstance(resource_limits, MemoryResourceLimits):
            raise ValueError("La configuration de ressources de la m\u00e9moire locale est invalide.")

        # The original two keyword arguments remain supported as targeted
        # overrides. ``None`` means to use the documented default (or the
        # value in ``resource_limits``), so existing callers retain the exact
        # V5 25 MiB / one-million-character envelope.
        limits = resource_limits or MemoryResourceLimits()
        try:
            overrides: dict[str, int] = {}
            if max_source_bytes is not None:
                overrides["max_source_bytes"] = int(max_source_bytes)
            if max_text_chars is not None:
                overrides["max_text_chars"] = int(max_text_chars)
            self.resource_limits = replace(limits, **overrides)
        except (TypeError, ValueError) as error:
            raise ValueError("Les limites de la m\u00e9moire locale doivent \u00eatre positives.") from error

        if db_path is not None:
            self.db_path = Path(db_path).expanduser().resolve()
            self.base_dir = self.db_path.parent
        else:
            self.base_dir = Path(base_dir).expanduser().resolve()  # type: ignore[arg-type]
            self.db_path = self.base_dir / "personal_memory.sqlite3"

        # Preserve existing attributes for integrations that read them.
        self.max_source_bytes = self.resource_limits.max_source_bytes
        self.max_text_chars = self.resource_limits.max_text_chars
        self._lock = RLock()
        self._ensure_storage()
        self._initialize()

    def _ensure_storage(self) -> None:
        try:
            self.base_dir.mkdir(parents=True, exist_ok=True)
            os.chmod(self.base_dir, 0o700)
        except OSError as error:
            raise PersonalMemoryError("Impossible de pr\u00e9parer le dossier de m\u00e9moire locale.") from error

    def _tighten_database_permissions(self) -> None:
        """Keep SQLite's database and active journal sidecars private when possible."""
        for candidate in (
            self.db_path,
            self.db_path.with_name(self.db_path.name + "-wal"),
            self.db_path.with_name(self.db_path.name + "-shm"),
            self.db_path.with_name(self.db_path.name + "-journal"),
        ):
            try:
                if candidate.exists():
                    os.chmod(candidate, 0o600)
            except OSError:
                # The containing directory is already private. Some mounted
                # external volumes do not support POSIX permissions.
                pass

    @contextmanager
    def _connection(self) -> Iterator[sqlite3.Connection]:
        connection: sqlite3.Connection | None = None
        try:
            connection = sqlite3.connect(self.db_path, timeout=5.0)
            connection.row_factory = sqlite3.Row
            connection.execute("PRAGMA foreign_keys = ON")
            connection.execute("PRAGMA busy_timeout = 5000")
            # Mémoire personnelle : les lignes supprimées doivent cesser
            # d'apparaître dans les pages libres et le journal WAL.
            connection.execute("PRAGMA secure_delete = ON")
            yield connection
            connection.commit()
            self._tighten_database_permissions()
        except sqlite3.Error as error:
            if connection is not None:
                try:
                    connection.rollback()
                except sqlite3.Error:
                    pass
            raise PersonalMemoryError("La base de m\u00e9moire locale a rencontr\u00e9 un probl\u00e8me.") from error
        except Exception:
            if connection is not None:
                try:
                    connection.rollback()
                except sqlite3.Error:
                    pass
            raise
        finally:
            if connection is not None:
                connection.close()

    def _initialize(self) -> None:
        with self._lock, self._connection() as connection:
            version = int(connection.execute("PRAGMA user_version").fetchone()[0])
            if version > SCHEMA_VERSION:
                raise PersonalMemoryError("Cette m\u00e9moire a \u00e9t\u00e9 cr\u00e9\u00e9e par une version plus r\u00e9cente de C\u00f4me AI.")
            if version == 0:
                try:
                    connection.execute("PRAGMA journal_mode = WAL")
                    connection.executescript(
                        """
                        CREATE TABLE projects (
                            id TEXT PRIMARY KEY,
                            name TEXT NOT NULL,
                            name_key TEXT NOT NULL UNIQUE,
                            description TEXT NOT NULL DEFAULT '',
                            created_at TEXT NOT NULL,
                            updated_at TEXT NOT NULL
                        );

                        CREATE TABLE sources (
                            id TEXT PRIMARY KEY,
                            content_hash TEXT NOT NULL UNIQUE,
                            title TEXT NOT NULL,
                            original_filename TEXT NOT NULL DEFAULT '',
                            source_kind TEXT NOT NULL CHECK (source_kind IN ('text', 'file')),
                            source_type TEXT NOT NULL,
                            category TEXT NOT NULL DEFAULT 'general',
                            char_count INTEGER NOT NULL,
                            chunk_count INTEGER NOT NULL,
                            imported_at TEXT NOT NULL,
                            updated_at TEXT NOT NULL
                        );

                        CREATE TABLE source_projects (
                            source_id TEXT NOT NULL REFERENCES sources(id) ON DELETE CASCADE,
                            project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
                            linked_at TEXT NOT NULL,
                            PRIMARY KEY (source_id, project_id)
                        );

                        CREATE TABLE memory_chunks (
                            id TEXT PRIMARY KEY,
                            source_id TEXT NOT NULL REFERENCES sources(id) ON DELETE CASCADE,
                            ordinal INTEGER NOT NULL,
                            page_number INTEGER,
                            sheet_name TEXT,
                            line_start INTEGER NOT NULL,
                            line_end INTEGER NOT NULL,
                            content TEXT NOT NULL,
                            UNIQUE (source_id, ordinal)
                        );

                        CREATE INDEX memory_chunks_source_idx ON memory_chunks(source_id, ordinal);
                        CREATE INDEX source_projects_project_idx ON source_projects(project_id, source_id);
                        CREATE INDEX sources_category_idx ON sources(category, imported_at DESC);

                        CREATE VIRTUAL TABLE memory_chunks_fts USING fts5(
                            chunk_id UNINDEXED,
                            source_id UNINDEXED,
                            title,
                            content,
                            tokenize = 'unicode61 remove_diacritics 2'
                        );
                        """
                    )
                except sqlite3.OperationalError as error:
                    if "fts5" in str(error).lower():
                        raise PersonalMemoryError(
                            "Cette installation de Python ne propose pas SQLite FTS5, n\u00e9cessaire \u00e0 la recherche locale."
                        ) from error
                    raise
                connection.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")
            elif version < SCHEMA_VERSION:
                # V2 adds a nullable sheet name. Existing V1 text/PDF chunks
                # remain valid and keep their historical citation shape.
                columns = {
                    row["name"]
                    for row in connection.execute("PRAGMA table_info(memory_chunks)").fetchall()
                }
                if "sheet_name" not in columns:
                    connection.execute("ALTER TABLE memory_chunks ADD COLUMN sheet_name TEXT")
                connection.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")
            try:
                os.chmod(self.db_path, 0o600)
            except OSError:
                # Permissions can be unavailable on some mounted external
                # volumes; the database remains usable, with no false claim.
                pass

    # ------------------------------------------------------------------
    # Project operations
    # ------------------------------------------------------------------
    def create_project(self, name: str, description: str = "") -> dict[str, Any]:
        """Create a named local project, or return the existing matching one."""
        project_name = self._clean_required_label(name, "Le nom du projet", MAX_PROJECT_NAME_CHARS)
        description_text = self._clean_optional_text(description, MAX_PROJECT_DESCRIPTION_CHARS)
        name_key = project_name.casefold()
        now = self._now()
        with self._lock, self._connection() as connection:
            existing = connection.execute(
                "SELECT * FROM projects WHERE name_key = ?", (name_key,)
            ).fetchone()
            if existing is not None:
                if description_text and description_text != existing["description"]:
                    connection.execute(
                        "UPDATE projects SET description = ?, updated_at = ? WHERE id = ?",
                        (description_text, now, existing["id"]),
                    )
                    existing = connection.execute("SELECT * FROM projects WHERE id = ?", (existing["id"],)).fetchone()
                return {"status": "existing", "project": self._project_dict(existing)}

            project_id = self._new_id("prj")
            connection.execute(
                "INSERT INTO projects (id, name, name_key, description, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?)",
                (project_id, project_name, name_key, description_text, now, now),
            )
            row = connection.execute("SELECT * FROM projects WHERE id = ?", (project_id,)).fetchone()
            return {"status": "created", "project": self._project_dict(row)}

    def list_projects(self) -> list[dict[str, Any]]:
        """Return local project metadata and linked-source counts, newest first."""
        with self._lock, self._connection() as connection:
            rows = connection.execute(
                """
                SELECT p.*, COUNT(sp.source_id) AS source_count
                FROM projects AS p
                LEFT JOIN source_projects AS sp ON sp.project_id = p.id
                GROUP BY p.id
                ORDER BY p.updated_at DESC, p.name_key ASC
                """
            ).fetchall()
            return [self._project_dict(row) for row in rows]

    def delete_project(self, project_id: str, *, delete_orphan_sources: bool = False) -> dict[str, Any]:
        """Delete a project; source records survive unless explicitly purged.

        The safe default preserves all source records.  Passing
        ``delete_orphan_sources=True`` removes only sources that become linked
        to no project at all; a source shared by another project is retained.
        """
        identifier = self._clean_id(project_id, "Projet")
        with self._lock, self._connection() as connection:
            project = connection.execute("SELECT id, name FROM projects WHERE id = ?", (identifier,)).fetchone()
            if project is None:
                raise PersonalMemoryError("Projet introuvable.")
            source_ids = [
                row["source_id"]
                for row in connection.execute(
                    "SELECT source_id FROM source_projects WHERE project_id = ?", (identifier,)
                ).fetchall()
            ]
            connection.execute("DELETE FROM projects WHERE id = ?", (identifier,))
            purged = 0
            if delete_orphan_sources:
                for source_id in source_ids:
                    linked_elsewhere = connection.execute(
                        "SELECT 1 FROM source_projects WHERE source_id = ? LIMIT 1", (source_id,)
                    ).fetchone()
                    if linked_elsewhere is None:
                        self._delete_source_in_connection(connection, source_id)
                        purged += 1
            return {
                "status": "deleted",
                "project_id": identifier,
                "project_name": project["name"],
                "unlinked_sources": len(source_ids),
                "orphan_sources_deleted": purged,
            }

    # ------------------------------------------------------------------
    # Controlled imports
    # ------------------------------------------------------------------
    def import_file(
        self,
        path: Path,
        *,
        project_id: str | None = None,
        title: str | None = None,
        category: str = "general",
    ) -> dict[str, Any]:
        """Index one explicitly selected local file without copying it.

        Paths must be absolute, point to a regular non-symlink file and use an
        allowlisted document suffix.  This deliberately does *not* accept a
        directory or perform recursive import.
        """
        if not isinstance(path, Path):
            path = Path(path)
        if not path.is_absolute():
            raise PersonalMemoryError("S\u00e9lectionne un chemin de fichier absolu et explicite.")
        try:
            if path.is_symlink():
                raise PersonalMemoryError("Les liens symboliques ne sont pas import\u00e9s. S\u00e9lectionne le fichier r\u00e9el.")
            resolved = path.resolve(strict=True)
            if not resolved.is_file():
                raise PersonalMemoryError("S\u00e9lectionne un fichier, pas un dossier.")
            size = resolved.stat().st_size
        except PersonalMemoryError:
            raise
        except OSError as error:
            raise PersonalMemoryError("Fichier introuvable ou illisible.") from error

        suffix = resolved.suffix.lower()
        if suffix not in ALLOWED_FILE_SUFFIXES:
            supported = ", ".join(sorted(ALLOWED_FILE_SUFFIXES))
            raise PersonalMemoryError(f"Format non pris en charge pour la m\u00e9moire locale ({supported}).")
        if size > self.max_source_bytes:
            raise PersonalMemoryLimitError(
                f"Fichier trop volumineux pour la m\u00e9moire locale (maximum {self._format_bytes(self.max_source_bytes)})."
            )

        parts = self._extract_file_parts(resolved, suffix)
        safe_filename = self._safe_filename(resolved.name)
        source_title = self._clean_title(title, MAX_TITLE_CHARS) or safe_filename
        return self._import_parts(
            parts,
            title=source_title,
            project_id=project_id,
            category=category,
            source_kind="file",
            source_type=suffix.lstrip("."),
            original_filename=safe_filename,
        )

    def import_text(
        self,
        text: str,
        *,
        title: str = "Texte import\u00e9",
        project_id: str | None = None,
        category: str = "general",
    ) -> dict[str, Any]:
        """Index caller-supplied text only; no path or external file is read."""
        if not isinstance(text, str):
            raise PersonalMemoryError("Le texte \u00e0 importer est invalide.")
        source_title = self._clean_title(title, MAX_TITLE_CHARS)
        if not source_title:
            raise PersonalMemoryError("Le titre est obligatoire.")
        return self._import_parts(
            [_ExtractedPart(text=text)],
            title=source_title,
            project_id=project_id,
            category=category,
            source_kind="text",
            source_type="text",
            original_filename="",
        )

    def _extract_file_parts(self, path: Path, suffix: str) -> list[_ExtractedPart]:
        if suffix in PLAIN_TEXT_SUFFIXES:
            return [_ExtractedPart(text=self._read_utf8_text(path))]
        if suffix in {".html", ".htm"}:
            parser = _VisibleTextParser()
            try:
                parser.feed(self._read_utf8_text(path))
                parser.close()
            except (OSError, ValueError) as error:
                raise PersonalMemoryError("Document HTML illisible.") from error
            return [_ExtractedPart(text=parser.text())]
        if suffix == ".docx":
            return [_ExtractedPart(text=self._extract_docx_text(path))]
        if suffix == ".pdf":
            return self._extract_pdf_parts(path)
        if suffix in {".xlsx", ".xlsm"}:
            return self._extract_excel_parts(path, suffix)
        raise PersonalMemoryError("Ce fichier ne contient pas de texte exploitable.")

    def _read_utf8_text(self, path: Path) -> str:
        try:
            raw = path.read_bytes()
        except OSError as error:
            raise PersonalMemoryError("Document texte illisible.") from error
        if len(raw) > self.max_source_bytes:
            raise PersonalMemoryLimitError(
                f"Fichier trop volumineux pour la m\u00e9moire locale (maximum {self._format_bytes(self.max_source_bytes)})."
            )
        try:
            return raw.decode("utf-8-sig")
        except UnicodeDecodeError as error:
            raise PersonalMemoryError("Le document texte doit \u00eatre encod\u00e9 en UTF-8.") from error

    def _extract_docx_text(self, path: Path) -> str:
        try:
            with zipfile.ZipFile(path) as archive:
                entries = archive.infolist()
                if len(entries) > self.resource_limits.max_docx_archive_entries:
                    raise PersonalMemoryLimitError("Le document Word contient trop d'\u00e9l\u00e9ments pour un import local s\u00fbr.")
                if (
                    sum(max(0, entry.file_size) for entry in entries)
                    > self.resource_limits.max_docx_uncompressed_bytes
                ):
                    raise PersonalMemoryLimitError("Le document Word d\u00e9compress\u00e9 est trop volumineux pour un import local s\u00fbr.")
                try:
                    xml_data = archive.read("word/document.xml")
                except KeyError as error:
                    raise PersonalMemoryError("Document Word invalide ou sans contenu lisible.") from error
        except PersonalMemoryError:
            raise
        except (OSError, zipfile.BadZipFile) as error:
            raise PersonalMemoryError("Document Word illisible ou prot\u00e9g\u00e9.") from error

        # ElementTree does not need DTD support for DOCX content. Reject one
        # explicitly instead of accepting a crafted document with entities.
        if b"<!DOCTYPE" in xml_data.upper():
            raise PersonalMemoryError("Document Word invalide ou sans contenu lisible.")
        try:
            root = ET.fromstring(xml_data)
        except ET.ParseError as error:
            raise PersonalMemoryError("Document Word invalide ou sans contenu lisible.") from error

        paragraphs: list[str] = []
        for paragraph in root.iter(f"{_XML_WORD_NAMESPACE}p"):
            fragments: list[str] = []
            for item in paragraph.iter():
                if item.tag == f"{_XML_WORD_NAMESPACE}t" and item.text:
                    fragments.append(item.text)
                elif item.tag == f"{_XML_WORD_NAMESPACE}tab":
                    fragments.append("\t")
                elif item.tag in {f"{_XML_WORD_NAMESPACE}br", f"{_XML_WORD_NAMESPACE}cr"}:
                    fragments.append("\n")
            text = "".join(fragments).strip()
            if text:
                paragraphs.append(text)
        return "\n".join(paragraphs)

    def _extract_excel_parts(self, path: Path, suffix: str) -> list[_ExtractedPart]:
        """Extract XLSX/XLSM visible cell values in read-only streaming mode.

        The workbook is not evaluated: formulas remain formula text and macros
        are never loaded or executed. One logical extracted line maps to one
        spreadsheet row, so a memory result can cite its original sheet and
        exact Excel row range.
        """
        self._check_excel_archive(path)
        try:
            from openpyxl import load_workbook  # type: ignore[import-not-found]
        except ImportError as error:
            raise PersonalMemoryError(
                "La lecture Excel locale n'est pas disponible : installe les dépendances de Côme AI avant d'importer un classeur."
            ) from error

        try:
            workbook = load_workbook(
                filename=str(path),
                read_only=True,
                data_only=False,
                keep_links=False,
            )
        except Exception as error:
            kind = "XLSM" if suffix == ".xlsm" else "Excel"
            raise PersonalMemoryError(f"Classeur {kind} illisible, protégé ou non pris en charge.") from error

        try:
            worksheets = list(workbook.worksheets)
            if len(worksheets) > self.resource_limits.max_excel_sheets:
                raise PersonalMemoryLimitError(
                    "Le classeur contient trop de feuilles pour la configuration locale de mémoire."
                )

            parts: list[_ExtractedPart] = []
            total_chars = 0
            for worksheet in worksheets:
                # These dimensions come from sheet metadata. Guard them before
                # iterating rows so a malformed sheet cannot build huge tuples.
                if worksheet.max_column > self.resource_limits.max_excel_columns:
                    raise PersonalMemoryLimitError(
                        "Une feuille contient trop de colonnes pour la configuration locale de mémoire."
                    )
                extracted = self._extract_excel_sheet(
                    worksheet,
                    max_text_chars=self.max_text_chars - total_chars,
                )
                if extracted is None:
                    continue
                total_chars += len(extracted.text)
                if total_chars > self.max_text_chars:
                    raise PersonalMemoryLimitError(
                        f"Le texte extrait du classeur dépasse la limite de {self.max_text_chars:,} caractères."
                    )
                parts.append(extracted)
        except PersonalMemoryError:
            raise
        except Exception as error:
            raise PersonalMemoryError("Classeur Excel illisible ou sans cellules exploitables.") from error
        finally:
            workbook.close()

        if not parts:
            raise PersonalMemoryError("Ce classeur ne contient pas de cellules textuelles ou numériques exploitables.")
        return parts

    def _check_excel_archive(self, path: Path) -> None:
        """Reject a malformed or disproportionate Office archive before XML parsing."""
        try:
            with zipfile.ZipFile(path) as archive:
                entries = archive.infolist()
                if len(entries) > self.resource_limits.max_excel_archive_entries:
                    raise PersonalMemoryLimitError(
                        "Le classeur contient trop d'éléments internes pour un import local sûr."
                    )
                uncompressed = sum(max(0, entry.file_size) for entry in entries)
                if uncompressed > self.resource_limits.max_excel_uncompressed_bytes:
                    raise PersonalMemoryLimitError(
                        "Le classeur décompressé est trop volumineux pour la configuration locale de mémoire."
                    )
        except PersonalMemoryError:
            raise
        except (OSError, zipfile.BadZipFile) as error:
            raise PersonalMemoryError("Classeur Excel illisible ou protégé.") from error

    def _extract_excel_sheet(self, worksheet: Any, *, max_text_chars: int) -> _ExtractedPart | None:
        """Stream one sheet while retaining only its content-bearing row interval."""
        sheet_name = self._safe_sheet_name(str(worksheet.title))
        buffer = StringIO()
        first_content_row: int | None = None
        previous_content_row: int | None = None

        for row_number, values in enumerate(worksheet.iter_rows(values_only=True), start=1):
            if row_number > self.resource_limits.max_excel_rows_per_sheet:
                raise PersonalMemoryLimitError(
                    "Une feuille dépasse le nombre maximal de lignes autorisé par la configuration locale de mémoire."
                )
            row_text = self._render_excel_row(values)
            if not row_text:
                continue
            gap_size = 0
            if first_content_row is None:
                first_content_row = row_number
            elif previous_content_row is not None:
                gap_size = row_number - previous_content_row
            if buffer.tell() + gap_size + len(row_text) > max_text_chars:
                raise PersonalMemoryLimitError(
                    f"Le texte extrait du classeur dépasse la limite de {self.max_text_chars:,} caractères."
                )
            if gap_size:
                # Keep interior blanks: combined with line_start, this keeps
                # citations aligned with native Excel row numbers.
                buffer.write("\n" * gap_size)
            buffer.write(row_text)
            previous_content_row = row_number

        if first_content_row is None:
            return None
        return _ExtractedPart(
            text=buffer.getvalue(),
            sheet_name=sheet_name,
            line_start=first_content_row,
        )

    @staticmethod
    def _render_excel_row(values: Sequence[Any]) -> str:
        cells: list[str] = []
        for column_index, value in enumerate(values, start=1):
            if value is None:
                continue
            rendered = unicodedata.normalize("NFC", str(value)).replace("\x00", "")
            rendered = re.sub(r"[\r\n\t]+", " ", rendered)
            rendered = "".join(character if character >= " " else " " for character in rendered).strip()
            if rendered:
                cells.append(f"{PersonalMemoryStore._excel_column_name(column_index)}={rendered}")
        return " | ".join(cells)

    @staticmethod
    def _excel_column_name(column_index: int) -> str:
        """Return Excel's A/AA column label without allocating cell objects."""
        label = ""
        number = column_index
        while number:
            number, remainder = divmod(number - 1, 26)
            label = chr(65 + remainder) + label
        return label

    @staticmethod
    def _safe_sheet_name(value: str) -> str:
        cleaned = value.replace("\x00", "")
        cleaned = re.sub(r"[\r\n\t]+", " ", cleaned).strip()
        return cleaned[:MAX_SHEET_NAME_CHARS] or "Feuille"

    def _extract_pdf_parts(self, path: Path) -> list[_ExtractedPart]:
        try:
            from pypdf import PdfReader  # type: ignore[import-not-found]
        except ImportError as error:
            raise PersonalMemoryError(
                "La lecture PDF locale n'est pas disponible : installe les d\u00e9pendances de C\u00f4me AI avant d'importer un PDF."
            ) from error
        try:
            reader = PdfReader(str(path), strict=False)
            page_count = len(reader.pages)
        except Exception as error:
            raise PersonalMemoryError("PDF illisible, prot\u00e9g\u00e9 ou non pris en charge.") from error
        if page_count > self.resource_limits.max_pdf_pages:
            raise PersonalMemoryLimitError(
                f"PDF trop long pour l'import local (maximum {self.resource_limits.max_pdf_pages} pages)."
            )

        parts: list[_ExtractedPart] = []
        total_chars = 0
        try:
            for index, page in enumerate(reader.pages, start=1):
                extracted = page.extract_text() or ""
                total_chars += len(extracted)
                if total_chars > self.max_text_chars:
                    raise PersonalMemoryLimitError(
                        f"Le texte extrait du PDF d\u00e9passe la limite de {self.max_text_chars:,} caract\u00e8res."
                    )
                if extracted.strip():
                    parts.append(_ExtractedPart(text=extracted, page_number=index))
        except PersonalMemoryError:
            raise
        except Exception as error:
            raise PersonalMemoryError("PDF illisible ou sans texte exploitable.") from error
        if not parts:
            raise PersonalMemoryError("Ce PDF ne contient pas de texte exploitable. Utilise d'abord un OCR local explicite.")
        return parts

    def _import_parts(
        self,
        parts: Sequence[_ExtractedPart],
        *,
        title: str,
        project_id: str | None,
        category: str,
        source_kind: str,
        source_type: str,
        original_filename: str,
    ) -> dict[str, Any]:
        normalized_parts = self._normalise_parts(parts)
        whole_text = "\n\n".join(part.text for part in normalized_parts)
        if not whole_text.strip():
            raise PersonalMemoryError("Le document ne contient pas de texte exploitable.")
        if len(whole_text) > self.max_text_chars:
            raise PersonalMemoryLimitError(
                f"Le texte extrait d\u00e9passe la limite de {self.max_text_chars:,} caract\u00e8res."
            )
        chunks = self._build_chunks(normalized_parts)
        if not chunks:
            raise PersonalMemoryError("Le document ne contient pas de texte indexable.")
        if len(chunks) > self.resource_limits.max_chunks_per_source:
            raise PersonalMemoryLimitError("Le document produit trop d'extraits pour la m\u00e9moire locale.")

        content_hash = hashlib.sha256(
            self._content_hash_material(normalized_parts, whole_text).encode("utf-8")
        ).hexdigest()
        category_text = self._clean_optional_label(category, MAX_CATEGORY_CHARS) or "general"
        project = self._validated_project_id(project_id) if project_id is not None else None
        now = self._now()

        with self._lock, self._connection() as connection:
            if project is not None:
                self._require_project(connection, project)
            existing = connection.execute("SELECT * FROM sources WHERE content_hash = ?", (content_hash,)).fetchone()
            if existing is not None:
                linked = self._link_source_to_project(connection, existing["id"], project, now)
                source = self._source_dict(connection, existing)
                return {
                    "status": "duplicate",
                    "source": source,
                    "source_id": existing["id"],
                    "project_linked": linked,
                    "message": "Ce contenu est d\u00e9j\u00e0 index\u00e9 localement ; aucun doublon n'a \u00e9t\u00e9 cr\u00e9\u00e9.",
                }

            source_id = self._new_id("src")
            connection.execute(
                """
                INSERT INTO sources (
                    id, content_hash, title, original_filename, source_kind,
                    source_type, category, char_count, chunk_count, imported_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    source_id,
                    content_hash,
                    title,
                    original_filename,
                    source_kind,
                    source_type,
                    category_text,
                    len(whole_text),
                    len(chunks),
                    now,
                    now,
                ),
            )
            for ordinal, chunk in enumerate(chunks, start=1):
                chunk_id = self._new_id("chk")
                connection.execute(
                    """
                    INSERT INTO memory_chunks (
                        id, source_id, ordinal, page_number, sheet_name,
                        line_start, line_end, content
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        chunk_id,
                        source_id,
                        ordinal,
                        chunk["page_number"],
                        chunk["sheet_name"],
                        chunk["line_start"],
                        chunk["line_end"],
                        chunk["content"],
                    ),
                )
                connection.execute(
                    "INSERT INTO memory_chunks_fts (chunk_id, source_id, title, content) VALUES (?, ?, ?, ?)",
                    (chunk_id, source_id, self._fts_title(title, chunk["sheet_name"]), chunk["content"]),
                )
            linked = self._link_source_to_project(connection, source_id, project, now)
            row = connection.execute("SELECT * FROM sources WHERE id = ?", (source_id,)).fetchone()
            return {
                "status": "indexed",
                "source": self._source_dict(connection, row),
                "source_id": source_id,
                "project_linked": linked,
                "message": "Document index\u00e9 dans la m\u00e9moire locale.",
            }

    # ------------------------------------------------------------------
    # Search/list/delete operations
    # ------------------------------------------------------------------
    def search(
        self,
        query: str,
        *,
        project_id: str | None = None,
        limit: int = 8,
    ) -> dict[str, Any]:
        """Search FTS5 using safe literal terms and return cited excerpts only."""
        fts_query, display_query, terms = self._safe_fts_query(query)
        result_limit = self._bounded_limit(limit, default=8, maximum=MAX_SEARCH_RESULTS)
        project = self._validated_project_id(project_id) if project_id is not None else None
        with self._lock, self._connection() as connection:
            if project is not None:
                self._require_project(connection, project)
            rows = connection.execute(
                """
                SELECT
                    c.id AS chunk_id,
                    c.page_number,
                    c.sheet_name,
                    c.line_start,
                    c.line_end,
                    c.content,
                    s.id AS source_id,
                    s.title,
                    s.category,
                    s.source_type,
                    bm25(memory_chunks_fts, 0.0, 0.0, 2.0, 1.0) AS relevance
                FROM memory_chunks_fts
                JOIN memory_chunks AS c ON c.id = memory_chunks_fts.chunk_id
                JOIN sources AS s ON s.id = c.source_id
                WHERE memory_chunks_fts MATCH ?
                  AND (
                    ? IS NULL
                    OR EXISTS (
                        SELECT 1 FROM source_projects AS sp
                        WHERE sp.source_id = s.id AND sp.project_id = ?
                    )
                  )
                ORDER BY relevance ASC, s.imported_at DESC, c.ordinal ASC
                LIMIT ?
                """,
                (fts_query, project, project, result_limit),
            ).fetchall()
            relaxed_note = ""
            if not rows and len(terms) > 1:
                # Honest widening: no document contained every term, so we
                # retry with "at least one term" and say so in the response
                # instead of leaving the user with a bare zero.
                or_query = " OR ".join(f'"{term}"' for term in terms)
                rows = connection.execute(
                    """
                    SELECT
                        c.id AS chunk_id,
                        c.page_number,
                        c.sheet_name,
                        c.line_start,
                        c.line_end,
                        c.content,
                        s.id AS source_id,
                        s.title,
                        s.category,
                        s.source_type,
                        bm25(memory_chunks_fts, 0.0, 0.0, 2.0, 1.0) AS relevance
                    FROM memory_chunks_fts
                    JOIN memory_chunks AS c ON c.id = memory_chunks_fts.chunk_id
                    JOIN sources AS s ON s.id = c.source_id
                    WHERE memory_chunks_fts MATCH ?
                      AND (
                        ? IS NULL
                        OR EXISTS (
                            SELECT 1 FROM source_projects AS sp
                            WHERE sp.source_id = s.id AND sp.project_id = ?
                        )
                      )
                    ORDER BY relevance ASC, s.imported_at DESC, c.ordinal ASC
                    LIMIT ?
                    """,
                    (or_query, project, project, result_limit),
                ).fetchall()
                if rows:
                    relaxed_note = (
                        "Aucun document ne contenait tous les termes : "
                        "correspondance élargie à au moins un terme."
                    )
            results = [self._search_result_dict(row, terms) for row in rows]
            result: dict[str, Any] = {"query": display_query, "count": len(results), "results": results}
            if relaxed_note:
                result["note"] = relaxed_note
            return result

    def list_sources(
        self,
        *,
        project_id: str | None = None,
        category: str | None = None,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        """List local source metadata without returning external paths/content."""
        project = self._validated_project_id(project_id) if project_id is not None else None
        category_text = self._clean_optional_label(category, MAX_CATEGORY_CHARS) if category is not None else None
        result_limit = self._bounded_limit(limit, default=100, maximum=MAX_LIST_RESULTS)
        with self._lock, self._connection() as connection:
            if project is not None:
                self._require_project(connection, project)
            rows = connection.execute(
                """
                SELECT s.*
                FROM sources AS s
                WHERE (? IS NULL OR s.category = ?)
                  AND (
                    ? IS NULL
                    OR EXISTS (
                        SELECT 1 FROM source_projects AS sp
                        WHERE sp.source_id = s.id AND sp.project_id = ?
                    )
                  )
                ORDER BY s.imported_at DESC, s.title COLLATE NOCASE ASC
                LIMIT ?
                """,
                (category_text, category_text, project, project, result_limit),
            ).fetchall()
            return [self._source_dict(connection, row) for row in rows]

    def delete_source(self, source_id: str) -> dict[str, Any]:
        """Delete extracted local text/index data, never the original source file."""
        identifier = self._clean_id(source_id, "Document")
        with self._lock, self._connection() as connection:
            row = connection.execute("SELECT id, title FROM sources WHERE id = ?", (identifier,)).fetchone()
            if row is None:
                raise PersonalMemoryError("Document introuvable.")
            self._delete_source_in_connection(connection, identifier)
            return {"status": "deleted", "source_id": identifier, "title": row["title"]}

    def add_source_to_project(self, source_id: str, project_id: str) -> dict[str, Any]:
        """Link an existing opaque source ID to an existing opaque project ID."""
        source = self._clean_id(source_id, "Document")
        project = self._clean_id(project_id, "Projet")
        with self._lock, self._connection() as connection:
            source_row = connection.execute("SELECT id FROM sources WHERE id = ?", (source,)).fetchone()
            if source_row is None:
                raise PersonalMemoryError("Document introuvable.")
            self._require_project(connection, project)
            linked = self._link_source_to_project(connection, source, project, self._now())
            return {"status": "linked" if linked else "existing", "source_id": source, "project_id": project}

    def stats(self) -> dict[str, int]:
        """Return bounded local counts useful for a future dashboard."""
        with self._lock, self._connection() as connection:
            return {
                "projects": int(connection.execute("SELECT COUNT(*) FROM projects").fetchone()[0]),
                "sources": int(connection.execute("SELECT COUNT(*) FROM sources").fetchone()[0]),
                "chunks": int(connection.execute("SELECT COUNT(*) FROM memory_chunks").fetchone()[0]),
            }

    # ------------------------------------------------------------------
    # Internal database/value helpers
    # ------------------------------------------------------------------
    @staticmethod
    def _now() -> str:
        return datetime.now(timezone.utc).isoformat(timespec="seconds")

    @staticmethod
    def _new_id(prefix: str) -> str:
        return f"{prefix}_{uuid.uuid4().hex}"

    @staticmethod
    def _format_bytes(value: int) -> str:
        if value >= 1024 * 1024:
            return f"{value / (1024 * 1024):.0f} Mo"
        return f"{value / 1024:.0f} Ko"

    @staticmethod
    def _clean_optional_text(value: str, maximum: int) -> str:
        if not isinstance(value, str):
            raise PersonalMemoryError("La valeur fournie est invalide.")
        normalized = unicodedata.normalize("NFC", value).replace("\x00", "")
        normalized = "".join(character if character >= " " or character in "\n\t" else " " for character in normalized)
        normalized = normalized.strip()
        if len(normalized) > maximum:
            raise PersonalMemoryLimitError(f"Le texte d\u00e9passe la limite de {maximum} caract\u00e8res.")
        return normalized

    @classmethod
    def _clean_optional_label(cls, value: str | None, maximum: int) -> str:
        if value is None:
            return ""
        normalized = cls._clean_optional_text(value, maximum)
        normalized = re.sub(r"\s+", " ", normalized).strip()
        return normalized

    @classmethod
    def _clean_title(cls, value: str | None, maximum: int) -> str:
        """Clean a source title without ever retaining an absolute path."""
        cleaned = cls._clean_optional_label(value, maximum)
        if cleaned.startswith(("/", "\\")) or re.match(r"^[A-Za-z]:[/\\\\]", cleaned):
            cleaned = re.split(r"[/\\\\]+", cleaned)[-1]
        return cleaned

    @classmethod
    def _clean_required_label(cls, value: str, field_name: str, maximum: int) -> str:
        cleaned = cls._clean_optional_label(value, maximum)
        if not cleaned:
            raise PersonalMemoryError(f"{field_name} est obligatoire.")
        return cleaned

    @staticmethod
    def _clean_id(value: str, label: str) -> str:
        if not isinstance(value, str) or not re.fullmatch(r"(?:prj|src|chk)_[0-9a-f]{32}", value):
            raise PersonalMemoryError(f"{label} invalide.")
        return value

    def _validated_project_id(self, value: str) -> str:
        return self._clean_id(value, "Projet")

    @staticmethod
    def _safe_filename(value: str) -> str:
        name = Path(value).name.replace("\x00", "")
        name = re.sub(r"[\r\n\t]+", " ", name).strip()
        if not name:
            return "document"
        return name[:MAX_FILENAME_CHARS]

    @staticmethod
    def _fts_title(title: str, sheet_name: str | None) -> str:
        """Make a worksheet name discoverable without exposing filesystem data."""
        return title if sheet_name is None else f"{title} {sheet_name}"

    @staticmethod
    def _content_hash_material(parts: Sequence[_ExtractedPart], whole_text: str) -> str:
        """Include worksheet identity in an Excel content fingerprint.

        Two workbooks with the same cell values but different worksheet names
        have different citation contexts, so they must not silently collapse
        into one source. Text/PDF imports keep the original V5 hash material
        to preserve duplicate detection for existing databases.
        """
        if not any(part.sheet_name is not None for part in parts):
            return whole_text
        return "\x1d".join(
            "\x1e".join((part.sheet_name or "", str(part.line_start), part.text))
            for part in parts
        )

    def _normalise_parts(self, parts: Sequence[_ExtractedPart]) -> list[_ExtractedPart]:
        cleaned: list[_ExtractedPart] = []
        total = 0
        for part in parts:
            if not isinstance(part.text, str):
                continue
            text = unicodedata.normalize("NFC", part.text.replace("\r\n", "\n").replace("\r", "\n"))
            text = "".join(character if character >= " " or character in "\n\t" else " " for character in text)
            # Preserve logical lines for citations while discarding only
            # leading/trailing empty lines. For Excel, ``line_start`` carries
            # the first native row number after leading blanks are removed.
            lines = text.split("\n")
            first = 0
            last = len(lines)
            while first < last and not lines[first].strip():
                first += 1
            while last > first and not lines[last - 1].strip():
                last -= 1
            if first == last:
                continue
            text = "\n".join(lines[first:last])
            total += len(text)
            if total > self.max_text_chars:
                raise PersonalMemoryLimitError(
                    f"Le texte extrait d\u00e9passe la limite de {self.max_text_chars:,} caract\u00e8res."
                )
            try:
                line_start = max(1, int(part.line_start)) + first
            except (TypeError, ValueError):
                line_start = 1 + first
            cleaned.append(
                _ExtractedPart(
                    text=text,
                    page_number=part.page_number,
                    sheet_name=self._safe_sheet_name(part.sheet_name) if part.sheet_name else None,
                    line_start=line_start,
                )
            )
        return cleaned

    def _build_chunks(self, parts: Sequence[_ExtractedPart]) -> list[dict[str, Any]]:
        chunks: list[dict[str, Any]] = []
        for part in parts:
            lines = part.text.split("\n")
            current: list[str] = []
            start_line = part.line_start
            current_size = 0

            def flush(end_line: int) -> None:
                nonlocal current, current_size
                content = "\n".join(current).strip()
                if content:
                    chunks.append(
                        {
                            "page_number": part.page_number,
                            "sheet_name": part.sheet_name,
                            "line_start": start_line,
                            "line_end": max(start_line, end_line),
                            "content": content,
                        }
                    )
                current = []
                current_size = 0

            for line_number, raw_line in enumerate(lines, start=part.line_start):
                line = raw_line.strip()
                if not line:
                    if current and current_size + 1 > self.resource_limits.chunk_chars:
                        flush(line_number - 1)
                    continue
                # A single extremely long line still receives a stable line
                # citation.  It is split only for bounded search/index size.
                pieces = [
                    line[index : index + self.resource_limits.chunk_chars]
                    for index in range(0, len(line), self.resource_limits.chunk_chars)
                ] or [""]
                for piece in pieces:
                    added_size = len(piece) + (1 if current else 0)
                    if current and current_size + added_size > self.resource_limits.chunk_chars:
                        flush(line_number - 1)
                        start_line = line_number
                    if not current:
                        start_line = line_number
                    current.append(piece)
                    current_size += len(piece) + (1 if len(current) > 1 else 0)
                    if len(piece) >= self.resource_limits.chunk_chars:
                        flush(line_number)
            if current:
                flush(part.line_start + len(lines) - 1)
        return chunks

    def _safe_fts_query(self, query: str) -> tuple[str, str, list[str]]:
        cleaned = self._clean_optional_text(query, MAX_QUERY_CHARS)
        if not cleaned:
            raise PersonalMemoryError("La recherche ne peut pas \u00eatre vide.")
        terms = [term for term in _QUERY_TERM_RE.findall(cleaned.casefold()) if any(character.isalnum() for character in term)]
        if not terms:
            raise PersonalMemoryError("La recherche doit contenir au moins un mot ou un nombre.")
        terms = [term[:64] for term in terms[:MAX_QUERY_TERMS]]
        # Terms arise only from ``\w+`` and are quoted, so users cannot inject
        # FTS operators (NEAR, prefix wildcard, column selectors, etc.).
        return " AND ".join(f'"{term}"' for term in terms), cleaned, terms

    @staticmethod
    def _bounded_limit(value: int, *, default: int, maximum: int) -> int:
        if isinstance(value, bool):
            raise PersonalMemoryError("La limite demand\u00e9e est invalide.")
        try:
            number = int(value)
        except (TypeError, ValueError) as error:
            raise PersonalMemoryError("La limite demand\u00e9e est invalide.") from error
        if number < 1:
            raise PersonalMemoryError("La limite demand\u00e9e doit \u00eatre positive.")
        return min(number or default, maximum)

    @staticmethod
    def _require_project(connection: sqlite3.Connection, project_id: str) -> sqlite3.Row:
        project = connection.execute("SELECT * FROM projects WHERE id = ?", (project_id,)).fetchone()
        if project is None:
            raise PersonalMemoryError("Projet introuvable.")
        return project

    def _link_source_to_project(
        self,
        connection: sqlite3.Connection,
        source_id: str,
        project_id: str | None,
        linked_at: str,
    ) -> bool:
        if project_id is None:
            return False
        cursor = connection.execute(
            "INSERT OR IGNORE INTO source_projects (source_id, project_id, linked_at) VALUES (?, ?, ?)",
            (source_id, project_id, linked_at),
        )
        linked = cursor.rowcount > 0
        if linked:
            connection.execute("UPDATE projects SET updated_at = ? WHERE id = ?", (linked_at, project_id))
        return linked

    def _delete_source_in_connection(self, connection: sqlite3.Connection, source_id: str) -> None:
        connection.execute("DELETE FROM memory_chunks_fts WHERE source_id = ?", (source_id,))
        connection.execute("DELETE FROM sources WHERE id = ?", (source_id,))

    def _project_dict(self, row: sqlite3.Row) -> dict[str, Any]:
        return {
            "id": row["id"],
            "name": row["name"],
            "description": row["description"],
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
            "source_count": int(row["source_count"]) if "source_count" in row.keys() else 0,
        }

    def _source_dict(self, connection: sqlite3.Connection, row: sqlite3.Row) -> dict[str, Any]:
        projects = connection.execute(
            """
            SELECT p.id, p.name
            FROM projects AS p
            JOIN source_projects AS sp ON sp.project_id = p.id
            WHERE sp.source_id = ?
            ORDER BY p.name_key ASC
            """,
            (row["id"],),
        ).fetchall()
        return {
            "id": row["id"],
            "title": row["title"],
            "original_filename": row["original_filename"],
            "source_kind": row["source_kind"],
            "source_type": row["source_type"],
            "category": row["category"],
            "char_count": int(row["char_count"]),
            "chunk_count": int(row["chunk_count"]),
            "imported_at": row["imported_at"],
            "updated_at": row["updated_at"],
            "projects": [{"id": item["id"], "name": item["name"]} for item in projects],
        }

    @staticmethod
    def _search_result_dict(row: sqlite3.Row, terms: Sequence[str]) -> dict[str, Any]:
        source_title = row["title"]
        page_number = row["page_number"]
        sheet_name = row["sheet_name"] if "sheet_name" in row.keys() else None
        line_start = int(row["line_start"])
        line_end = int(row["line_end"])
        if sheet_name:
            location = f"feuille « {sheet_name} », lignes {line_start}–{line_end}"
        else:
            location = (
                f"p. {page_number}, lignes {line_start}\u2013{line_end}"
                if page_number is not None
                else f"lignes {line_start}\u2013{line_end}"
            )
        citation: dict[str, Any] = {
            "source_id": row["source_id"],
            "title": source_title,
            "page": int(page_number) if page_number is not None else None,
            "line_start": line_start,
            "line_end": line_end,
            "label": f"{source_title} \u2014 {location}",
        }
        if sheet_name:
            # ``line_*`` remains the stable cross-format API; explicit row
            # aliases make spreadsheet citations self-describing to the UI.
            citation.update(
                {
                    "sheet": str(sheet_name),
                    "row_start": line_start,
                    "row_end": line_end,
                }
            )
        return {
            "source_id": row["source_id"],
            "title": source_title,
            "category": row["category"],
            "source_type": row["source_type"],
            "excerpt": PersonalMemoryStore._excerpt(row["content"], terms),
            "citation": citation,
        }

    @staticmethod
    def _excerpt(content: str, terms: Sequence[str], maximum: int = 420) -> str:
        collapsed = re.sub(r"\s+", " ", content).strip()
        lowered = collapsed.casefold()
        positions = [lowered.find(term.casefold()) for term in terms]
        positions = [position for position in positions if position >= 0]
        if not positions or len(collapsed) <= maximum:
            return collapsed[:maximum] + ("\u2026" if len(collapsed) > maximum else "")
        start = max(0, min(positions) - maximum // 3)
        end = min(len(collapsed), start + maximum)
        prefix = "\u2026" if start else ""
        suffix = "\u2026" if end < len(collapsed) else ""
        return prefix + collapsed[start:end].strip() + suffix


__all__ = [
    "ALLOWED_FILE_SUFFIXES",
    "MemoryResourceLimits",
    "PersonalMemoryError",
    "PersonalMemoryLimitError",
    "PersonalMemoryStore",
]
