"""Local-only ingestion and retrieval for the NAGe course corpus.

The learning loop deliberately uses a small lexical vector index instead of a
remote embedding service.  Every retrieved chunk keeps its source file, page
range and detected section so downstream tutor/quiz features cannot lose
provenance.  The implementation accepts normal text-layer PDFs; OCR is not
silently attempted because a fabricated or incomplete source is worse than a
clear refusal.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
import sqlite3
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Sequence

DEFAULT_CORPUS_ROOT = Path("/Users/comedelavenne/.nage/vc/course_corpus")
MAX_SOURCE_BYTES = 50 * 1024 * 1024
MAX_CHUNK_CHARS = 2_400
MIN_CHUNK_CHARS = 20

_TOKEN_RE = re.compile(r"[\wÀ-ÿ]+", re.UNICODE)
_NUMBERED_SECTION_RE = re.compile(r"^\d+(?:\.\d+)*\s+.{3,}$")
_STOPWORDS = {
    "a", "à", "au", "aux", "avec", "ce", "ces", "dans", "de", "des", "du", "elle", "en", "et",
    "for", "from", "il", "in", "la", "le", "les", "of", "on", "or", "par", "pour", "que", "qui",
    "sur", "the", "un", "une", "what", "which", "why", "with",
}


def _tokens(text: str) -> list[str]:
    return [item.lower() for item in _TOKEN_RE.findall(text) if item.lower() not in _STOPWORDS and len(item) > 1]


def _vector(text: str) -> dict[str, float]:
    counts: dict[str, float] = {}
    for token in _tokens(text):
        counts[token] = counts.get(token, 0.0) + 1.0
    norm = math.sqrt(sum(value * value for value in counts.values())) or 1.0
    return {key: round(value / norm, 8) for key, value in counts.items()}


def _cosine(query: dict[str, float], vector: dict[str, float]) -> float:
    return sum(query.get(key, 0.0) * value for key, value in vector.items())


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _topic_from_name(name: str) -> str | None:
    """Return a stable topic prefix for filenames such as ``Topic_3_...``."""
    match = re.search(r"(?:^|[^a-z])topic[_ -]?(\d+)(?=$|[^0-9])", name, re.IGNORECASE)
    return f"TOPIC {match.group(1)}" if match else None


def _normalize_section(value: str, source_name: str = "") -> str:
    """Keep human headings readable while making topic filters deterministic."""
    clean = re.sub(r"\s+", " ", value).strip(" -•\t")
    topic = _topic_from_name(source_name)
    match = re.match(r"^topic\s*(\d+)\b(?:\s*[—–:-]\s*(.*))?$", clean, re.IGNORECASE)
    if match:
        suffix = f" — {match.group(2).strip()}" if match.group(2) else ""
        return f"TOPIC {match.group(1)}{suffix}"
    if topic:
        # Topic PDFs often use numbered slide headings ("3. Valuation")
        # instead of repeating their filename's topic label. Keep both so
        # ``TOPIC 3`` remains a stable filter while the slide title is useful
        # in the UI and citations.
        return f"{topic} — {clean}" if clean and clean != "Document" else topic
    return clean or _topic_from_name(source_name) or "Document"


@dataclass(frozen=True)
class SourcePage:
    source_id: str
    source_path: str
    page: int
    text: str
    section: str


@dataclass(frozen=True)
class SourceChunk:
    chunk_id: str
    source_id: str
    source_path: str
    page_start: int
    page_end: int
    section: str
    text: str
    score: float = 0.0

    def citation(self) -> dict[str, Any]:
        return {
            "chunk_id": self.chunk_id,
            "source_id": self.source_id,
            "source": Path(self.source_path).name,
            "page": self.page_start if self.page_start == self.page_end else f"{self.page_start}-{self.page_end}",
            "section": self.section,
            "excerpt": self.text[:500].strip(),
        }


@dataclass(frozen=True)
class IngestReport:
    corpus_root: str
    documents: int
    pages: int
    chunks: int
    characters: int
    skipped: list[str]
    errors: list[str]
    local_only: bool = True

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class CorpusError(ValueError):
    """A source is not an authorized local course document."""


class CorpusIndex:
    """Persistent SQLite lexical/vector index for authorized course PDFs."""

    def __init__(self, storage_path: str | Path | None = None, *, corpus_root: str | Path | None = None):
        configured = Path(storage_path) if storage_path is not None else Path(".nage_learning")
        if configured.suffix.lower() in {".sqlite", ".sqlite3", ".db"}:
            self.db_path = configured
            self.storage_dir = configured.parent
        else:
            self.storage_dir = configured
            self.db_path = configured / "corpus.sqlite3"
        self.storage_dir.mkdir(parents=True, exist_ok=True)
        self.corpus_root = Path(corpus_root or DEFAULT_CORPUS_ROOT).expanduser()
        self._conn = sqlite3.connect(str(self.db_path), check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.executescript(
            """
            PRAGMA foreign_keys = ON;
            CREATE TABLE IF NOT EXISTS metadata (key TEXT PRIMARY KEY, value TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS documents (
                source_id TEXT PRIMARY KEY, source_path TEXT NOT NULL, sha256 TEXT NOT NULL,
                pages INTEGER NOT NULL, characters INTEGER NOT NULL, ingested_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS chunks (
                chunk_id TEXT PRIMARY KEY, source_id TEXT NOT NULL REFERENCES documents(source_id) ON DELETE CASCADE,
                source_path TEXT NOT NULL, page_start INTEGER NOT NULL, page_end INTEGER NOT NULL,
                section TEXT NOT NULL, text TEXT NOT NULL, vector_json TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_chunks_source ON chunks(source_id);
            """
        )
        self._conn.execute("INSERT OR REPLACE INTO metadata(key,value) VALUES('corpus_root',?)", (str(self.corpus_root),))
        self._conn.commit()

    def close(self) -> None:
        self._conn.close()

    def __enter__(self) -> "CorpusIndex":
        return self

    def __exit__(self, *_: Any) -> None:
        self.close()

    def _authorized(self, path: Path) -> Path:
        candidate = path.expanduser().resolve()
        root = self.corpus_root.expanduser().resolve()
        try:
            candidate.relative_to(root)
        except ValueError as error:
            raise CorpusError("Ce fichier est hors du corpus de cours autorisé.") from error
        allowed = candidate.suffix.lower() in {".pdf", ".xlsx"} or candidate.name.lower().endswith((".pdf.txt", ".xlsx.txt"))
        if not allowed:
            raise CorpusError("Le corpus pédagogique accepte uniquement des PDF ou XLSX locaux.")
        if not candidate.is_file():
            raise CorpusError("Le document de cours demandé est introuvable.")
        if candidate.stat().st_size > MAX_SOURCE_BYTES:
            raise CorpusError("Le document de cours dépasse la taille locale autorisée.")
        return candidate

    @staticmethod
    def _read_pages(path: Path) -> list[SourcePage]:
        if path.name.lower().endswith((".pdf.txt", ".xlsx.txt")):
            raw = path.read_text(encoding="utf-8", errors="replace")
            source_id = hashlib.sha256(raw.encode("utf-8")).hexdigest()[:24]
            is_xlsx = path.name.lower().endswith(".xlsx.txt")
            marker = r"^===\s*SHEET\s+(.+?)\s*===\s*$" if is_xlsx else r"^===\s*PAGE\s+(\d+)\s*===\s*$"
            matches = list(re.finditer(marker, raw, re.MULTILINE | re.IGNORECASE))
            if not matches:
                source_name = path.name[:-4]
                return [SourcePage(source_id, str(path.with_name(source_name)), 1, raw.strip(), _topic_from_name(source_name) or "Document")]
            pages: list[SourcePage] = []
            for index, marker in enumerate(matches):
                start = marker.end()
                end = matches[index + 1].start() if index + 1 < len(matches) else len(raw)
                page_number = index + 1 if is_xlsx else int(marker.group(1))
                text = raw[start:end].strip()
                lines = [re.sub(r"\s+", " ", line).strip() for line in text.splitlines() if line.strip()]
                source_name = path.name[:-4]
                section = _topic_from_name(source_name) or (marker.group(1).strip() if is_xlsx else "Document")
                for line in lines[:12]:
                    lower = line.lower()
                    if lower.startswith(("topic ", "chapter ", "section ", "session ", "part ")) or (line == line.upper() and sum(char.isalpha() for char in line) >= 5):
                        section = line[:180]
                        break
                pages.append(SourcePage(source_id, str(path.with_name(source_name)), page_number, "\n".join(lines), _normalize_section(section, source_name)))
            return pages
        if path.suffix.lower() == ".xlsx":
            try:
                from openpyxl import load_workbook
            except ImportError as error:  # pragma: no cover - packaging failure
                raise CorpusError("La lecture des XLSX nécessite openpyxl localement.") from error
            try:
                workbook = load_workbook(path, data_only=False, read_only=True)
            except Exception as error:
                raise CorpusError(f"XLSX illisible : {path.name}.") from error
            source_id = hashlib.sha256(path.read_bytes()).hexdigest()[:24]
            pages: list[SourcePage] = []
            for number, sheet in enumerate(workbook.worksheets, start=1):
                rows: list[str] = []
                for row in sheet.iter_rows(values_only=True):
                    values = [str(value).strip() for value in row if value is not None and str(value).strip()]
                    if values:
                        rows.append(" | ".join(values))
                pages.append(SourcePage(source_id, str(path), number, "\n".join(rows), _normalize_section(sheet.title, path.name)))
            workbook.close()
            return pages
        try:
            from pypdf import PdfReader
        except ImportError as error:  # pragma: no cover - packaging failure
            raise CorpusError("La lecture des PDF nécessite le paquet local pypdf.") from error
        try:
            reader = PdfReader(str(path))
        except Exception as error:
            raise CorpusError(f"PDF illisible : {path.name}.") from error
        source_id = hashlib.sha256(path.read_bytes()).hexdigest()[:24]
        pages: list[SourcePage] = []
        current_section = "Document"
        for number, raw_page in enumerate(reader.pages, start=1):
            text = (raw_page.extract_text() or "").replace("\x00", "").strip()
            lines = [re.sub(r"\s+", " ", line).strip() for line in text.splitlines() if line.strip()]
            for line in lines[:12]:
                lower = line.lower()
                is_heading = lower.startswith(("topic ", "chapter ", "section ", "session ", "part ")) or bool(_NUMBERED_SECTION_RE.match(line))
                is_heading = is_heading or (line == line.upper() and sum(char.isalpha() for char in line) >= 5)
                if is_heading and len(line) <= 180:
                    current_section = _normalize_section(line[:180], path.name)
                    break
            if current_section == "Document":
                current_section = _topic_from_name(path.name) or current_section
            pages.append(SourcePage(source_id, str(path), number, "\n".join(lines), current_section))
        return pages

    @staticmethod
    def _chunk_pages(pages: Sequence[SourcePage]) -> list[SourceChunk]:
        chunks: list[SourceChunk] = []
        for page in pages:
            text = page.text.strip()
            if not text:
                continue
            paragraphs = [part.strip() for part in re.split(r"\n{2,}", text) if part.strip()]
            if not paragraphs:
                paragraphs = [text]
            buffer = ""
            for paragraph in paragraphs:
                if len(buffer) and len(buffer) + len(paragraph) + 1 > MAX_CHUNK_CHARS:
                    chunk_text = buffer.strip()
                    if len(chunk_text) >= MIN_CHUNK_CHARS:
                        chunk_id = hashlib.sha256(f"{page.source_id}:{page.page}:{len(chunks)}:{chunk_text}".encode()).hexdigest()[:24]
                        chunks.append(SourceChunk(chunk_id, page.source_id, page.source_path, page.page, page.page, page.section, chunk_text))
                    buffer = ""
                buffer = f"{buffer}\n{paragraph}".strip()
            if len(buffer) >= MIN_CHUNK_CHARS:
                chunk_id = hashlib.sha256(f"{page.source_id}:{page.page}:{len(chunks)}:{buffer}".encode()).hexdigest()[:24]
                chunks.append(SourceChunk(chunk_id, page.source_id, page.source_path, page.page, page.page, page.section, buffer))
        return chunks

    def ingest_file(self, path: str | Path) -> IngestReport:
        authorized = self._authorized(Path(path))
        pages = self._read_pages(authorized)
        source_id = pages[0].source_id if pages else hashlib.sha256(authorized.read_bytes()).hexdigest()[:24]
        existing = self._conn.execute("SELECT sha256 FROM documents WHERE source_id = ?", (source_id,)).fetchone()
        if existing is not None:
            return IngestReport(str(self.corpus_root), 0, 0, 0, 0, [authorized.name], [])
        chunks = self._chunk_pages(pages)
        digest = hashlib.sha256(authorized.read_bytes()).hexdigest()
        characters = sum(len(page.text) for page in pages)
        with self._conn:
            self._conn.execute(
                "INSERT INTO documents(source_id,source_path,sha256,pages,characters,ingested_at) VALUES(?,?,?,?,?,?)",
                (source_id, pages[0].source_path if pages else str(authorized), digest, len(pages), characters, _now()),
            )
            self._conn.executemany(
                "INSERT INTO chunks(chunk_id,source_id,source_path,page_start,page_end,section,text,vector_json) VALUES(?,?,?,?,?,?,?,?)",
                [(item.chunk_id, item.source_id, item.source_path, item.page_start, item.page_end, item.section, item.text, json.dumps(_vector(item.text))) for item in chunks],
            )
        return IngestReport(str(self.corpus_root), 1, len(pages), len(chunks), characters, [], [])

    def ingest_directory(self, root: str | Path | None = None) -> IngestReport:
        if root is not None:
            self.corpus_root = Path(root).expanduser().resolve()
            self._conn.execute("INSERT OR REPLACE INTO metadata(key,value) VALUES('corpus_root',?)", (str(self.corpus_root),))
            self._conn.commit()
        if not self.corpus_root.is_dir():
            raise CorpusError("Le dossier du corpus local est introuvable.")
        totals = [0, 0, 0, 0]
        skipped: list[str] = []
        errors: list[str] = []
        paths = sorted(self.corpus_root.rglob("*.pdf"))
        # The authorized private corpus also exposes extracted, page-marked
        # ``.pdf.txt`` mirrors so indexing can run without copying personal
        # documents into Git or requiring a second read of the source folder.
        paths.extend(sorted(self.corpus_root.rglob("*.pdf.txt")))
        paths.extend(sorted(self.corpus_root.rglob("*.xlsx")))
        paths.extend(sorted(self.corpus_root.rglob("*.xlsx.txt")))
        seen_stems: set[str] = set()
        for path in paths:
            mirror = path.name.lower().endswith((".pdf.txt", ".xlsx.txt"))
            stem = path.name[:-4] if mirror else path.name
            if stem in seen_stems and mirror:
                continue
            seen_stems.add(stem)
            try:
                report = self.ingest_file(path)
            except CorpusError as error:
                errors.append(f"{path.name}: {error}")
                continue
            if report.documents == 0:
                skipped.extend(report.skipped)
            for index, value in enumerate((report.documents, report.pages, report.chunks, report.characters)):
                totals[index] += value
        return IngestReport(str(self.corpus_root), *totals, skipped, errors)

    def document_count(self) -> int:
        return int(self._conn.execute("SELECT COUNT(*) FROM documents").fetchone()[0])

    def chunk_count(self) -> int:
        return int(self._conn.execute("SELECT COUNT(*) FROM chunks").fetchone()[0])

    def manifest(self) -> dict[str, Any]:
        rows = self._conn.execute("SELECT source_id,source_path,sha256,pages,characters,ingested_at FROM documents ORDER BY source_path").fetchall()
        return {
            "schema_version": 1,
            "corpus_root": str(self.corpus_root),
            "local_only": True,
            "documents": [dict(row) for row in rows],
            "pages": sum(int(row["pages"]) for row in rows),
            "characters": sum(int(row["characters"]) for row in rows),
            "chunks": self.chunk_count(),
        }

    def search(self, query: str, *, limit: int = 5, section: str | None = None) -> list[SourceChunk]:
        terms = _tokens(query)
        if not terms:
            return []
        query_vector = _vector(query)
        sql = "SELECT * FROM chunks"
        parameters: tuple[Any, ...] = ()
        if section:
            sql += " WHERE lower(section) LIKE ?"
            parameters = (f"%{section.lower()}%",)
        rows = self._conn.execute(sql, parameters).fetchall()
        scored: list[SourceChunk] = []
        for row in rows:
            vector = json.loads(row["vector_json"] or "{}")
            overlap = sum(1 for term in set(terms) if term in vector) / max(1, len(set(terms)))
            score = 0.75 * _cosine(query_vector, vector) + 0.25 * overlap
            if score <= 0:
                continue
            scored.append(SourceChunk(row["chunk_id"], row["source_id"], row["source_path"], int(row["page_start"]), int(row["page_end"]), row["section"], row["text"], round(score, 6)))
        scored.sort(key=lambda item: (-item.score, item.source_path, item.page_start, item.chunk_id))
        return scored[: max(1, min(limit, 20))]

    def chunks_for_section(self, section: str) -> list[SourceChunk]:
        """Return all indexed chunks in a section without scoring the heading.

        Topic labels are metadata, not necessarily words in the extracted body;
        filtering through ``search()`` therefore used to make valid chapters
        look empty (especially for spreadsheet sheets and sparse PDF pages).
        """
        needle = str(section or "").strip().lower()
        if not needle:
            return []
        rows = self._conn.execute(
            "SELECT * FROM chunks WHERE lower(section) LIKE ? ORDER BY source_path, page_start, chunk_id LIMIT 100",
            (f"%{needle}%",),
        ).fetchall()
        return [
            SourceChunk(
                row["chunk_id"], row["source_id"], row["source_path"],
                int(row["page_start"]), int(row["page_end"]), row["section"], row["text"], 0.0,
            )
            for row in rows
        ]

    def sections(self) -> list[str]:
        rows = self._conn.execute("SELECT DISTINCT section FROM chunks WHERE trim(section) <> '' ORDER BY section").fetchall()
        return [str(row[0]) for row in rows]


def default_index(storage_dir: str | Path | None = None, *, corpus_root: str | Path | None = None) -> CorpusIndex:
    """Create the app's private local index; no source is read on startup."""
    return CorpusIndex(storage_dir or Path(".nage_learning"), corpus_root=corpus_root)


__all__ = [
    "CorpusError", "CorpusIndex", "DEFAULT_CORPUS_ROOT", "IngestReport", "SourceChunk", "SourcePage", "default_index",
]
