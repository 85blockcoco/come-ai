"""Course sources for the Study Coach engine.

The engine never parses a PDF itself: it consumes a :class:`StudyDocument`
produced by an adapter.  Two adapters ship with the MVP:

* :class:`InMemoryDocumentSource` -- offline, used by the tests and the demo.
* :class:`PersonalMemorySourceAdapter` -- reads the existing Côme AI document
  store (``personal_memory.PersonalMemoryStore``) through its public
  ``list_sources`` / ``search`` contract only, so Codex can wire it without any
  modification to the memory engine.

A third adapter can be added later (V5 chat, workspace files, OCR results)
without touching the engine: it only has to return a :class:`StudyDocument`.
"""

from __future__ import annotations

import hashlib
import re
from typing import Any, Protocol, runtime_checkable

from .errors import SourceError
from .models import StudyDocument, clean_text, normalize_text


@runtime_checkable
class DocumentSource(Protocol):
    """Contract every course provider must honour."""

    def load_document(self, document_id: str) -> StudyDocument:
        """Return a citable course document or raise :class:`SourceError`."""


def document_id_for(text: str, title: str = "") -> str:
    """Stable, content-addressed document id (no path, no personal data)."""

    digest = hashlib.sha256(clean_text(text, limit=200_000).encode("utf-8")).hexdigest()[:12]
    return f"doc_{digest}"


def document_from_text(
    text: str,
    *,
    title: str,
    source_id: str = "",
    document_id: str = "",
    base_line: int = 1,
    metadata: dict[str, Any] | None = None,
) -> StudyDocument:
    """Build a :class:`StudyDocument` from raw course text.

    Raises :class:`SourceError` when the text is empty: an empty course cannot
    produce grounded notions.
    """

    body = clean_text(text, limit=400_000)
    if not body:
        raise SourceError("Le texte du cours est vide : aucune notion ne peut être extraite.")
    heading = clean_text(title, limit=200)
    if not heading:
        first_line = body.split("\n", 1)[0].strip()
        heading = first_line[:120] or "Cours sans titre"
    resolved_source_id = clean_text(source_id, limit=120) or document_id_for(body, heading)
    return StudyDocument(
        document_id=clean_text(document_id, limit=120) or document_id_for(body, heading),
        title=heading,
        text=body,
        source_id=resolved_source_id,
        base_line=base_line,
        metadata=dict(metadata or {}),
    )


class InMemoryDocumentSource:
    """Offline document source: a dict of courses held in memory."""

    def __init__(self, documents: dict[str, StudyDocument] | None = None) -> None:
        self._documents: dict[str, StudyDocument] = dict(documents or {})

    def add_text(self, text: str, *, title: str, source_id: str = "") -> StudyDocument:
        document = document_from_text(text, title=title, source_id=source_id)
        self._documents[document.document_id] = document
        return document

    def list_documents(self) -> list[str]:
        return sorted(self._documents)

    def load_document(self, document_id: str) -> StudyDocument:
        try:
            return self._documents[document_id]
        except KeyError as error:
            raise SourceError(f"Cours inconnu : {document_id}.") from error


REDUNDANCY_THRESHOLD = 0.85


def _is_redundant(excerpt: str, kept: list[dict[str, Any]]) -> bool:
    """True when an excerpt repeats what an already-kept passage says."""

    tokens = set(normalize_text(excerpt).split())
    if not tokens:
        return True
    for passage in kept:
        existing = set(normalize_text(passage["text"]).split())
        if not existing:
            continue
        overlap = len(tokens & existing) / len(tokens)
        if overlap >= REDUNDANCY_THRESHOLD:
            return True
    return False


class PersonalMemorySourceAdapter:
    """Adapter over the existing Côme AI personal-memory document store.

    Only the public read API is used (``list_sources`` and ``search``); the
    memory engine is never imported at module import time, so the package stays
    usable without it and the tests stay hermetic.

    Three properties of the real contract drive the reconstruction:

    * ``search`` combines its terms with ``AND`` and returns at most a 420
      character window per chunk, therefore queries are **single terms** and
      excerpts are **fragments**, possibly cut at either end (marked ``…``);
    * an excerpt has its white space collapsed, so the structure of the course
      (headings, bullets) is glued to the sentences: inline markers are split
      back into their own reconstructed lines;
    * ``citation`` carries the *original* ``page`` / ``line_start`` /
      ``line_end``, which are preserved as-is and never replaced by the
      reconstructed line numbers.
    """

    def __init__(self, store: Any, *, category: str = "cours", default_limit: int = 12) -> None:
        self._store = store
        self.category = clean_text(category, limit=64) or "cours"
        self.default_limit = max(1, min(int(default_limit or 12), 50))

    def list_courses(self) -> list[dict[str, Any]]:
        try:
            sources = self._store.list_sources(category=self.category, limit=100)
        except TypeError:
            sources = self._store.list_sources()
        return [dict(item) for item in sources or []]

    def load_document(self, document_id: str, *, queries: list[str] | None = None) -> StudyDocument:
        """Rebuild a course from the passages the memory store already indexed.

        Returns a document whose lines are reconstructed fragments, each one
        keeping the citation (page, original lines) of the chunk it came from.
        """

        source_id = clean_text(document_id, limit=120)
        if not source_id:
            raise SourceError("Aucun identifiant de source fourni.")

        title = source_id
        for item in self.list_courses():
            if item.get("source_id") == source_id or item.get("id") == source_id:
                title = str(item.get("title") or source_id)
                break

        passages = self._retrieve(source_id, title, queries)
        if not passages:
            raise SourceError(
                f"Aucun passage indexé pour la source « {title} » : le cours doit être importé dans le "
                "système documentaire avant de pouvoir réviser."
            )

        lines: list[str] = []
        kept_passages: list[dict[str, Any]] = []
        line_flags: list[str] = []
        for passage in passages:
            segments = _split_structural_markers(passage["text"])
            if not segments:
                continue
            first_line = len(lines) + 1
            for content, truncated_start, truncated_end in segments:
                lines.append(content)
                flag = ("truncated_start" if truncated_start else "") + (
                    "truncated_end" if truncated_end else ""
                )
                line_flags.append(flag)
            kept_passages.append(
                {
                    "citation": dict(passage["citation"]),
                    "line_start": first_line,
                    "line_end": len(lines),
                    "truncated_start": segments[0][1],
                    "truncated_end": segments[-1][2],
                }
            )

        if not lines:
            raise SourceError(
                f"Les passages indexés pour « {title} » sont vides ou illisibles : aucune révision possible."
            )

        document = document_from_text("\n".join(lines), title=title, source_id=source_id, base_line=1)
        document.metadata["passages"] = kept_passages
        document.metadata["line_flags"] = line_flags
        document.metadata["rebuilt_from"] = "personal_memory"
        document.metadata["queries"] = [str(query) for query in (queries or [])]
        return document

    def _retrieve(self, source_id: str, title: str, queries: list[str] | None) -> list[dict[str, Any]]:
        found_passages: list[dict[str, Any]] = []
        seen: set[tuple[Any, ...]] = set()
        for query in self._search_terms(title, queries):
            try:
                found = self._store.search(query, limit=self.default_limit)
            except Exception:  # a store without FTS must not break ingestion
                continue
            for result in (found or {}).get("results", []):
                citation = dict(result.get("citation") or {})
                result_source = citation.get("source_id") or result.get("source_id")
                if result_source != source_id:
                    continue
                excerpt = str(result.get("excerpt") or "")
                if not excerpt.strip():
                    continue
                key = (result_source, citation.get("page"), citation.get("line_start"), citation.get("line_end"), excerpt)
                if key in seen:
                    continue
                if _is_redundant(excerpt, found_passages):
                    # Several queries often return overlapping windows of the same
                    # chunk: keeping them all would duplicate the course.
                    continue
                seen.add(key)
                found_passages.append({"text": excerpt, "citation": citation})
        return found_passages

    @staticmethod
    def _search_terms(title: str, queries: list[str] | None) -> list[str]:
        """Single terms only: the store combines them with ``AND``."""

        if queries:
            cleaned = [clean_text(query, limit=80) for query in queries]
            return [query for query in cleaned if query][:12]
        words = [word for word in str(title).split() if len(word) > 3][:6]
        return words or [clean_text(title, limit=60)]


# Inline structure markers produced when the store collapsed the white space of
# a chunk (a heading or a bullet glued to the sentence that follows it).
# Each pattern is deliberately conservative: it must look like course structure,
# never like ordinary prose that happens to contain a number.
_INLINE_MARKERS = (
    re.compile(r"\s#{1,6}\s+"),
    re.compile(r"(?<=[^\s\d])\s+(?=\d{1,2}(?:\.\d+)*[.)]\s+[A-ZÀ-ÖØ-Ý])"),
    re.compile(
        r"(?<=[^\s\d])\s+(?=[A-ZÀ-ÖØ-Ý][A-ZÀ-ÖØ-Ý '\-/]{3,40}\s+"
        r"(?:est|sont|désigne|représente|signifie|=|:|vaut|indique|indiquent)\b)"
    ),
    re.compile(r"(?<=[^\s\d])\s+(?=[-*•]\s+[A-ZÀ-ÖØ-Ý0-9])"),
)


def _split_doubled_title(text: str) -> list[str]:
    """Split ``"1. La VAN  La VAN (VAN) est…"`` into its heading and its body.

    Collapsing the white space of a chunk leaves the course title immediately
    followed by the sentence that defines it.  The repetition is detected by an
    exact word match, so ordinary prose is never split.
    """

    words = text.split(" ")
    for boundary in range(2, min(len(words), 9)):
        for size in range(2, 8):
            before = words[boundary - size:boundary]
            after = words[boundary:boundary + size]
            if before and before == after:
                head = " ".join(words[:boundary]).strip()
                tail = " ".join(words[boundary:]).strip()
                if len(head) >= 6 and len(tail) >= 6:
                    return [head, tail]
    return [text]


def _split_structural_markers(excerpt: str) -> list[tuple[str, bool, bool]]:
    """Split a collapsed excerpt into reconstructed lines.

    Returns ``[(text, truncated_start, truncated_end), …]``.  The truncation
    flags come from the ``…`` marker the document store adds when it cuts an
    excerpt: a sentence cut in half must never become a notion.
    """

    text = re.sub(r"\s+", " ", str(excerpt or "")).strip()
    if not text:
        return []
    truncated_start = text.startswith("…")
    truncated_end = text.endswith("…")
    text = text.strip("…").strip()
    if not text:
        return []

    pieces = [text]
    for pattern in _INLINE_MARKERS:
        expanded: list[str] = []
        for piece in pieces:
            expanded.extend(part for part in pattern.split(piece) if part.strip())
        pieces = expanded

    segments: list[tuple[str, bool, bool]] = []
    last_index = len(pieces) - 1
    for index, piece in enumerate(pieces):
        parts = _split_doubled_title(piece.strip())
        for part_index, content in enumerate(parts):
            if not content:
                continue
            segments.append(
                (
                    content,
                    truncated_start and index == 0 and part_index == 0,
                    truncated_end and index == last_index and part_index == len(parts) - 1,
                )
            )
    return segments
