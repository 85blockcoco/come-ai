"""Traceable web evidence for the Career web researcher (SPEC-018).

Every fact produced by :mod:`career.web_research` must be quotable: a public
URL, a verbatim excerpt and the retrieval timestamp.  This module is the single
place where that contract is enforced.  It performs no network request, no
model call and no clock read.

DESIGN RULES
------------
* ``excerpt`` is **verbatim source text** (only whitespace is normalised).  A
  caller that passes ``source_text`` gets a hard failure when the excerpt is
  not a substring of it: web facts cannot be invented here.
* Ids are deterministic: ``web_`` + the first 16 hex chars of
  ``sha256("<canonical url>|<fact kind>|<normalised excerpt>")``.  Re-running a
  research on unchanged pages therefore yields the same ids, which lets the
  evidence centre cite a web proof across runs.
* A user-provided sheet is explicitly labelled ``user_provided``.  Its URL may
  use the ``user:`` scheme because it is not a fetched web page; consumers can
  tell it apart with :attr:`WebEvidence.verifiable`.
* Duplicates (same url + fact + excerpt) collapse to one item.  Ordering is
  stable: ``(fact_kind, url, excerpt)``.

The evidence "centre" is intentionally small: :class:`WebEvidenceCenter` groups
items by fact kind (``stack``, ``values``, ``news``, ``repo``, ``about``) and
returns their ids.  It can be handed to a future cross-source evidence index
without knowing anything about HTTP.
"""

from __future__ import annotations

import hashlib
import re
import urllib.parse
from dataclasses import dataclass, field
from typing import Any, Iterable

ID_PREFIX = "web_"
SOURCE_KINDS: frozenset[str] = frozenset({"company_site", "github", "search", "user_provided"})
FACT_KINDS: frozenset[str] = frozenset({"stack", "values", "news", "repo", "about"})
MAX_TITLE_CHARS = 300
MAX_EXCERPT_CHARS = 600
MAX_URL_CHARS = 2_000

_CONTROL_CHARS = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
_WHITESPACE = re.compile(r"\s+")


class EvidenceNotVerifiable(ValueError):
    """Raised when an excerpt is not present in the declared source text."""


def normalize_excerpt(value: Any, *, limit: int = MAX_EXCERPT_CHARS) -> str:
    """Collapse whitespace and drop control characters, never invent words."""
    text = _CONTROL_CHARS.sub(" ", str(value or ""))
    text = _WHITESPACE.sub(" ", text).strip()
    if len(text) > limit:
        text = text[:limit].rstrip()
    return text


def canonical_url(raw: Any) -> str:
    """Return a stable URL form usable in an evidence id.

    Only the fragment and default port are removed; the query string is kept
    because it can select the exact page that was quoted.
    """
    text = str(raw or "").strip()
    if not text:
        return ""
    try:
        parsed = urllib.parse.urlsplit(text)
    except ValueError:
        return ""
    if not parsed.scheme or not parsed.hostname:
        return text
    scheme = parsed.scheme.lower()
    host = parsed.hostname.lower().rstrip(".")
    port = parsed.port
    if port and not ((scheme == "https" and port == 443) or (scheme == "http" and port == 80)):
        netloc = f"{host}:{port}"
    else:
        netloc = host
    if parsed.username:
        netloc = f"{parsed.username}@{netloc}"
    path = parsed.path or "/"
    return urllib.parse.urlunsplit((scheme, netloc, path, parsed.query, ""))


def is_web_url(raw: Any) -> bool:
    try:
        parsed = urllib.parse.urlsplit(str(raw or "").strip())
    except ValueError:
        return False
    return parsed.scheme in {"http", "https"} and bool(parsed.hostname)


def is_user_url(raw: Any) -> bool:
    return str(raw or "").strip().startswith("user:")


def evidence_id(url: str, fact_kind: str, excerpt: str) -> str:
    """Deterministic, collision-resistant id for one quotable fact."""
    digest = hashlib.sha256(
        f"{canonical_url(url)}|{fact_kind}|{normalize_excerpt(excerpt)}".encode("utf-8")
    ).hexdigest()
    return f"{ID_PREFIX}{digest[:16]}"


@dataclass(frozen=True)
class WebEvidence:
    """One quotable web fact, ready for an evidence centre."""

    id: str
    url: str
    title: str
    excerpt: str
    source_kind: str
    fact_kind: str
    retrieved_at: str
    confidence: float

    @property
    def verifiable(self) -> bool:
        """True only for a real fetched HTTP(S) page; user sheets say so."""
        return is_web_url(self.url)

    def as_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "url": self.url,
            "title": self.title,
            "excerpt": self.excerpt,
            "source_kind": self.source_kind,
            "fact_kind": self.fact_kind,
            "retrieved_at": self.retrieved_at,
            "confidence": round(float(self.confidence), 3),
            "verifiable": self.verifiable,
        }


def make_evidence(
    *,
    url: Any,
    title: Any,
    excerpt: Any,
    source_kind: str,
    fact_kind: str,
    retrieved_at: str,
    confidence: float,
    source_text: str | None = None,
) -> WebEvidence:
    """Build one evidence item, refusing to quote text absent from its source.

    ``source_text`` is optional because structured sources (GitHub JSON fields,
    search-engine snippets, user sheets) are rendered by their provider rather
    than copied from a prose document.  When it is supplied, the excerpt must
    be a whitespace-normalised substring of it.
    """
    if source_kind not in SOURCE_KINDS:
        raise ValueError(f"Unknown web evidence source kind: {source_kind}")
    if fact_kind not in FACT_KINDS:
        raise ValueError(f"Unknown web fact kind: {fact_kind}")
    clean_excerpt = normalize_excerpt(excerpt)
    if not clean_excerpt:
        raise ValueError("A web evidence excerpt cannot be empty.")
    clean_url = canonical_url(url)
    if not (is_web_url(clean_url) or (source_kind == "user_provided" and is_user_url(clean_url))):
        raise ValueError("A web evidence URL must be http(s) (or user: for a user-provided sheet).")
    if source_text is not None:
        haystack = normalize_excerpt(source_text, limit=10**9)
        if clean_excerpt not in haystack:
            raise EvidenceNotVerifiable("The excerpt is not present verbatim in the declared source text.")
    bounded_confidence = max(0.0, min(1.0, float(confidence)))
    return WebEvidence(
        id=evidence_id(clean_url, fact_kind, clean_excerpt),
        url=clean_url,
        title=normalize_excerpt(title, limit=MAX_TITLE_CHARS),
        excerpt=clean_excerpt,
        source_kind=source_kind,
        fact_kind=fact_kind,
        retrieved_at=str(retrieved_at or ""),
        confidence=round(bounded_confidence, 3),
    )


@dataclass
class WebEvidenceCenter:
    """A deterministic, de-duplicated collection of :class:`WebEvidence`."""

    items: list[WebEvidence] = field(default_factory=list)

    def add(self, item: WebEvidence) -> bool:
        if any(existing.id == item.id for existing in self.items):
            return False
        self.items.append(item)
        return True

    def extend(self, items: Iterable[WebEvidence]) -> int:
        added = 0
        for item in items:
            if self.add(item):
                added += 1
        return added

    @property
    def ids(self) -> list[str]:
        return [item.id for item in self.sorted()]

    def sorted(self) -> list[WebEvidence]:
        return sorted(self.items, key=lambda item: (item.fact_kind, item.url, item.excerpt, item.id))

    def by_fact(self) -> dict[str, list[str]]:
        buckets: dict[str, list[str]] = {}
        for item in self.sorted():
            buckets.setdefault(item.fact_kind, []).append(item.id)
        return buckets

    def to_list(self) -> list[dict[str, Any]]:
        return [item.as_dict() for item in self.sorted()]

    def __len__(self) -> int:
        return len(self.items)
