"""Per-offer web research with a 24 h cache and quotable evidence (SPEC-018).

The researcher turns an offer into :class:`WebFacts` — company stack, values,
recent public news, GitHub summary — and cites every fact through
:mod:`career.web_evidence`.  Three properties matter more than coverage:

1. **Nothing is invented.**  A stack/values fact exists only when a sentence
   from a fetched page (or an explicitly labelled GitHub field, search snippet
   or user sheet) supports it.  ``evidence_ids`` is the only way to consume a
   fact downstream.
2. **Offline is a normal outcome.**  Every network failure is caught, reported
   as a warning, and served from the last cache when one exists.  With no
   cache the result is an explicit ``offline`` fact set with confidence ``0``.
3. **Determinism.**  Same pages + same clock => same facts, ids and ordering.
   The clock is injectable; no randomness, no language model, no hidden state.

Caching is layered: raw documents are cached per host (``documents/``) and the
composed facts per offer for :data:`DEFAULT_TTL_HOURS`.  A manual "provide"
sheet is merged into the cached facts and resets freshness.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import unicodedata
import urllib.parse
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from .web_evidence import (
    WebEvidence,
    WebEvidenceCenter,
    canonical_url,
    make_evidence,
    normalize_excerpt,
)
from .web_sources import (
    DEFAULT_TIMEOUT_SECONDS,
    DuckDuckGoSearch,
    GithubSnapshot,
    Page,
    RobotsPolicy,
    SearchHit,
    SearchProvider,
    UrllibWebTransport,
    WebDocument,
    WebSourceError,
    WebTransport,
    build_search_queries,
    extract_sentences,
    fetch_company_pages,
    fetch_github_org,
    is_public_http_url,
    iso_timestamp,
    resolve_github_org,
    stack_sentences,
    value_sentences,
)

DEFAULT_TTL_HOURS = 24.0
MAX_NEWS_ITEMS = 5
MAX_STACK_ITEMS = 40
MAX_VALUE_ITEMS = 40
MAX_SOURCES = 20
MAX_PROVIDED_NOTES = 4_000
MAX_WARNINGS = 8
_FACT_KINDS = {"stack", "values", "news", "repo", "about"}


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _parse_iso(value: Any) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _company_key(company: Any) -> str:
    normalized = unicodedata.normalize("NFKD", str(company or ""))
    ascii_text = "".join(char for char in normalized if not unicodedata.combining(char)).lower()
    return "".join(re.findall(r"[a-z0-9]+", ascii_text))[:60] or "unknown"


def offer_cache_key(offer: dict[str, Any]) -> str:
    """A stable cache key: the local offer id, else the company name."""
    offer_id = str(offer.get("id") or offer.get("offer_id") or "").strip()
    if offer_id:
        return f"offer:{offer_id}"
    return f"company:{_company_key(offer.get('company'))}"


@dataclass(frozen=True)
class WebNewsHit:
    title: str
    url: str
    date: str | None
    excerpt: str

    def as_dict(self) -> dict[str, Any]:
        return {"title": self.title, "url": self.url, "date": self.date, "excerpt": self.excerpt}


@dataclass
class WebFacts:
    """The documented SPEC-018 contract, plus explicit provenance fields."""

    company: str
    stack: list[str] = field(default_factory=list)
    values: list[str] = field(default_factory=list)
    recent_news: list[WebNewsHit] = field(default_factory=list)
    repos_summary: dict[str, Any] = field(default_factory=dict)
    evidence_ids: list[str] = field(default_factory=list)
    fetched_at: str = ""
    confidence: float = 0.0
    status: str = "empty"
    from_cache: bool = False
    stale: bool = False
    evidence: list[dict[str, Any]] = field(default_factory=list)
    sources: list[dict[str, Any]] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    provided_at: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {
            "company": self.company,
            "stack": list(self.stack),
            "values": list(self.values),
            "recent_news": [hit.as_dict() for hit in self.recent_news],
            "repos_summary": dict(self.repos_summary),
            "evidence_ids": list(self.evidence_ids),
            "fetched_at": self.fetched_at,
            "confidence": round(max(0.0, min(1.0, float(self.confidence))), 3),
            "status": self.status,
            "from_cache": bool(self.from_cache),
            "stale": bool(self.stale),
            "evidence": [dict(item) for item in self.evidence],
            "sources": [dict(source) for source in self.sources],
            "warnings": list(self.warnings),
            "provided_at": self.provided_at,
        }


class ResearchCache:
    """Small JSON cache: atomic, private, corruption-tolerant."""

    def __init__(self, directory: Path, *, ttl_hours: float = DEFAULT_TTL_HOURS, clock: Callable[[], datetime] | None = None) -> None:
        self.directory = Path(directory)
        self.ttl_seconds = max(0.0, float(ttl_hours)) * 3600
        self._clock = clock or _utc_now

    def _path(self, key: str) -> Path:
        digest = hashlib.sha256(key.encode("utf-8")).hexdigest()[:40]
        return self.directory / f"{digest}.json"

    def read(self, key: str) -> dict[str, Any] | None:
        path = self._path(key)
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None
        return payload if isinstance(payload, dict) else None

    def write(self, key: str, payload: dict[str, Any]) -> None:
        self.directory.mkdir(parents=True, exist_ok=True)
        try:
            os.chmod(self.directory, 0o700)
        except OSError:
            pass
        path = self._path(key)
        temporary = path.with_suffix(f".{os.getpid()}.tmp")
        body = dict(payload)
        body["key"] = key
        body["stored_at"] = iso_timestamp(self._clock())
        temporary.write_text(json.dumps(body, ensure_ascii=False, indent=1), encoding="utf-8")
        try:
            os.chmod(temporary, 0o600)
        except OSError:
            pass
        os.replace(temporary, path)

    def stored_at(self, payload: dict[str, Any] | None) -> datetime | None:
        return _parse_iso((payload or {}).get("stored_at"))

    def is_fresh(self, payload: dict[str, Any] | None) -> bool:
        stored = self.stored_at(payload)
        if stored is None:
            return False
        return (self._clock() - stored).total_seconds() < self.ttl_seconds

    def age_seconds(self, payload: dict[str, Any] | None) -> float | None:
        stored = self.stored_at(payload)
        if stored is None:
            return None
        return max(0.0, (self._clock() - stored).total_seconds())


class CachingTransport:
    """Cache raw documents per host so a 24 h re-run is offline-capable."""

    def __init__(
        self,
        transport: WebTransport,
        directory: Path,
        *,
        ttl_hours: float = DEFAULT_TTL_HOURS,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._transport = transport
        self.directory = Path(directory)
        self.ttl_seconds = max(0.0, float(ttl_hours)) * 3600
        self._clock = clock or _utc_now

    def _path(self, host: str) -> Path:
        digest = hashlib.sha256(host.encode("utf-8")).hexdigest()[:16]
        safe = re.sub(r"[^a-z0-9.-]+", "-", host.lower())[:60]
        return self.directory / f"{digest}-{safe or 'host'}.json"

    def _read(self, host: str) -> dict[str, Any]:
        try:
            payload = json.loads(self._path(host).read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}
        documents = payload.get("documents") if isinstance(payload, dict) else None
        return documents if isinstance(documents, dict) else {}

    def fetch(self, url: str, *, timeout_seconds: int = DEFAULT_TIMEOUT_SECONDS) -> WebDocument:
        parsed = urllib.parse.urlsplit(url)
        host = (parsed.hostname or "").lower()
        entry = self._read(host).get(url) if host else None
        if isinstance(entry, dict):
            stored = _parse_iso(entry.get("stored_at"))
            if stored is not None and (self._clock() - stored).total_seconds() < self.ttl_seconds:
                document = entry.get("document")
                if isinstance(document, dict):
                    return WebDocument.from_dict(document)
        document = self._transport.fetch(url, timeout_seconds=timeout_seconds)
        if host:
            documents = self._read(host)
            documents[url] = {"stored_at": iso_timestamp(self._clock()), "document": document.as_dict()}
            self._write(host, documents)
        return document

    def _write(self, host: str, documents: dict[str, Any]) -> None:
        self.directory.mkdir(parents=True, exist_ok=True)
        path = self._path(host)
        temporary = path.with_suffix(f".{os.getpid()}.tmp")
        temporary.write_text(json.dumps({"host": host, "documents": documents}, ensure_ascii=False), encoding="utf-8")
        try:
            os.chmod(temporary, 0o600)
        except OSError:
            pass
        os.replace(temporary, path)


def _dedupe(values: list[str], *, limit: int) -> list[str]:
    result: list[str] = []
    for value in values:
        text = re.sub(r"\s+", " ", str(value or "")).strip()
        if text and text not in result:
            result.append(text[:120])
        if len(result) >= limit:
            break
    return result


class WebResearcher:
    """Compose, cache and cite public web facts for one Career offer."""

    def __init__(
        self,
        *,
        cache_dir: Path,
        transport: WebTransport | None = None,
        search_provider: SearchProvider | None = None,
        clock: Callable[[], datetime] | None = None,
        ttl_hours: float = DEFAULT_TTL_HOURS,
        timeout_seconds: int = DEFAULT_TIMEOUT_SECONDS,
        robots: RobotsPolicy | None = None,
        max_queries: int = 2,
    ) -> None:
        self.clock = clock or _utc_now
        self.cache_dir = Path(cache_dir)
        self.timeout_seconds = int(timeout_seconds)
        self.max_queries = max(0, int(max_queries))
        self.cache = ResearchCache(self.cache_dir, ttl_hours=ttl_hours, clock=self.clock)
        base_transport = transport if transport is not None else UrllibWebTransport(clock=self.clock)
        self.transport = CachingTransport(
            base_transport, self.cache_dir / "documents", ttl_hours=ttl_hours, clock=self.clock
        )
        self.robots = robots or RobotsPolicy(self.transport, clock=self.clock)
        self.search = search_provider if search_provider is not None else DuckDuckGoSearch(
            self.transport, timeout_seconds=self.timeout_seconds
        )

    # ------------------------------------------------------------ public API

    def research(self, offer: dict[str, Any], *, refresh: bool = False) -> WebFacts:
        """Return facts for ``offer``, cached for 24 h unless ``refresh``."""
        key = offer_cache_key(offer)
        cached = self.cache.read(key)
        if cached is not None and not refresh and self.cache.is_fresh(cached):
            return self._facts_from_payload(cached, status="cached", from_cache=True, stale=False)
        facts, successes = self._collect(offer)
        if successes == 0:
            if cached is not None:
                cache_is_fresh = self.cache.is_fresh(cached)
                if cache_is_fresh:
                    stale_warnings = list(facts.warnings)
                else:
                    stale_warnings = list(facts.warnings) + [
                        "Recherche en ligne indisponible : les dernières preuves en cache sont réutilisées."
                    ]
                return self._facts_from_payload(
                    cached,
                    status="cached",
                    from_cache=True,
                    stale=not cache_is_fresh,
                    extra_warnings=stale_warnings,
                )
            facts.status = "offline"
            facts.confidence = 0.0
            return facts
        facts.status = "ok" if facts.evidence_ids and not facts.warnings else ("partial" if facts.evidence_ids else "empty")
        self._store(key, facts)
        return facts

    def provide(self, offer: dict[str, Any], payload: dict[str, Any]) -> WebFacts:
        """Merge a user-provided company sheet into the cached research."""
        key = offer_cache_key(offer)
        cached = self.cache.read(key)
        if cached is not None:
            facts = self._facts_from_payload(cached, status="cached", from_cache=True, stale=False)
        else:
            facts = WebFacts(
                company=normalize_excerpt(offer.get("company") or payload.get("company"), limit=240),
                fetched_at=iso_timestamp(self.clock()),
                status="empty",
            )
        provided = _sanitize_provided(payload)
        warnings = list(facts.warnings)
        center = WebEvidenceCenter()
        for item in facts.evidence:
            try:
                center.add(_evidence_from_dict(item))
            except (TypeError, ValueError):
                continue
        now_iso = iso_timestamp(self.clock())
        slug = _company_key(payload.get("company") or facts.company)

        if provided["company"]:
            facts.company = provided["company"]
        if provided["notes"]:
            center.add(
                make_evidence(
                    url=f"user:notes:{slug}",
                    title="Fiche entreprise fournie par la personne",
                    excerpt=provided["notes"],
                    source_kind="user_provided",
                    fact_kind="about",
                    retrieved_at=now_iso,
                    confidence=0.9,
                )
            )
        if provided["stack"]:
            center.add(
                make_evidence(
                    url=f"user:sheet:{slug}",
                    title="Stack fournie par la personne",
                    excerpt=", ".join(provided["stack"]),
                    source_kind="user_provided",
                    fact_kind="stack",
                    retrieved_at=now_iso,
                    confidence=0.85,
                )
            )
        if provided["values"]:
            center.add(
                make_evidence(
                    url=f"user:sheet:{slug}",
                    title="Valeurs fournies par la personne",
                    excerpt=", ".join(provided["values"]),
                    source_kind="user_provided",
                    fact_kind="values",
                    retrieved_at=now_iso,
                    confidence=0.85,
                )
            )
        for source in provided["sources"]:
            if not is_public_http_url(source["url"]):
                warnings.append("Une source fournie a été ignorée : son adresse n’est pas publique.")
                continue
            try:
                center.add(
                    make_evidence(
                        url=source["url"],
                        title=source["title"] or urllib.parse.urlsplit(source["url"]).hostname or "",
                        excerpt=source["excerpt"] or source["title"],
                        source_kind="user_provided",
                        fact_kind=source["fact_kind"],
                        retrieved_at=now_iso,
                        confidence=0.85,
                    )
                )
            except ValueError:
                warnings.append("Une source fournie a été ignorée : extrait vide.")
        for news in provided["news"]:
            if not is_public_http_url(news["url"]):
                warnings.append("Une actualité fournie a été ignorée : son adresse n’est pas publique.")
                continue
            excerpt = news["excerpt"] or news["title"]
            try:
                center.add(
                    make_evidence(
                        url=news["url"],
                        title=news["title"],
                        excerpt=excerpt,
                        source_kind="user_provided",
                        fact_kind="news",
                        retrieved_at=now_iso,
                        confidence=0.85,
                    )
                )
            except ValueError:
                continue

        facts.stack = _dedupe(provided["stack"] + facts.stack, limit=MAX_STACK_ITEMS)
        facts.values = _dedupe(provided["values"] + facts.values, limit=MAX_VALUE_ITEMS)
        merged_news = [WebNewsHit(**item) for item in provided["news"]] + list(facts.recent_news)
        deduped_news: list[WebNewsHit] = []
        seen: set[tuple[str, str]] = set()
        for hit in merged_news:
            marker = (hit.url, hit.title)
            if marker in seen:
                continue
            seen.add(marker)
            deduped_news.append(hit)
            if len(deduped_news) >= MAX_NEWS_ITEMS:
                break
        facts.recent_news = deduped_news
        facts.evidence = center.to_list()
        facts.evidence_ids = center.ids
        facts.sources = _sources_from_evidence(center)
        facts.warnings = _bounded_warnings(warnings)
        if provided["stack"] or provided["values"] or provided["notes"] or provided["sources"] or provided["news"]:
            facts.confidence = min(0.95, max(facts.confidence, 0.8))
        facts.fetched_at = facts.fetched_at or now_iso
        facts.provided_at = now_iso
        facts.status = "ok" if facts.evidence_ids else facts.status
        facts.from_cache = False
        facts.stale = False
        self._store(key, facts)
        return facts

    def freshness(self, offer: dict[str, Any]) -> dict[str, Any]:
        """Report whether the cached research is still inside its 24 h window."""
        key = offer_cache_key(offer)
        payload = self.cache.read(key)
        if payload is None:
            return {
                "offer_id": str(offer.get("id") or offer.get("offer_id") or ""),
                "available": False,
                "status": "not_found",
                "fetched_at": None,
                "stored_at": None,
                "age_seconds": None,
                "ttl_hours": round(self.cache.ttl_seconds / 3600, 2),
                "fresh": False,
                "stale": True,
                "provided_at": None,
                "evidence_count": 0,
                "source_count": 0,
            }
        facts = payload.get("facts") if isinstance(payload.get("facts"), dict) else {}
        age = self.cache.age_seconds(payload)
        fresh = self.cache.is_fresh(payload)
        return {
            "offer_id": str(offer.get("id") or offer.get("offer_id") or ""),
            "available": True,
            "status": "fresh" if fresh else "stale",
            "fetched_at": facts.get("fetched_at"),
            "stored_at": payload.get("stored_at"),
            "age_seconds": None if age is None else int(age),
            "ttl_hours": round(self.cache.ttl_seconds / 3600, 2),
            "fresh": fresh,
            "stale": not fresh,
            "provided_at": payload.get("provided_at"),
            "evidence_count": len(facts.get("evidence_ids") or []),
            "source_count": len(facts.get("sources") or []),
        }

    # ----------------------------------------------------------- collection

    def _collect(self, offer: dict[str, Any]) -> tuple[WebFacts, int]:
        company = normalize_excerpt(offer.get("company"), limit=240)
        now_iso = iso_timestamp(self.clock())
        warnings: list[str] = []
        center = WebEvidenceCenter()
        pages: list[Page] = []
        successes = 0

        official_url = str(offer.get("official_url") or "").strip()
        if official_url and is_public_http_url(official_url):
            try:
                site = fetch_company_pages(
                    official_url,
                    self.transport,
                    robots=self.robots,
                    timeout_seconds=self.timeout_seconds,
                )
                pages.extend(site.pages)
                successes += len(site.pages)
                warnings.extend(site.warnings)
                for skipped_url, reason in site.skipped:
                    if reason == "robots":
                        warnings.append(f"Page non lue (robots.txt) : {urllib.parse.urlsplit(skipped_url).path}")
            except WebSourceError as error:
                warnings.append(f"Site entreprise : {error}")
        elif official_url:
            warnings.append("L’adresse de l’entreprise a été ignorée : elle n’est pas publique ou pas HTTPS.")

        github: GithubSnapshot | None = None
        links = tuple(link for page in pages for link in page.links)
        slug, slug_origin = resolve_github_org(company, links)
        if slug:
            try:
                github = fetch_github_org(slug, self.transport, timeout_seconds=self.timeout_seconds)
                if github is not None:
                    successes += 1
            except WebSourceError as error:
                warnings.append(f"GitHub : {error}")

        hits: list[SearchHit] = []
        for query in build_search_queries(offer)[: self.max_queries]:
            try:
                found = self.search.search(query, limit=4)
            except (WebSourceError, ValueError) as error:
                warnings.append(f"Recherche : {error}")
                continue
            if found:
                successes += 1
                hits.extend(found)

        stack_excerpts: dict[str, tuple[str, str, str, str, str]] = {}
        for page in pages:
            source_label = page.title or page.final_url
            for term, sentence in stack_sentences(page.text).items():
                stack_excerpts.setdefault(
                    term, (page.final_url, source_label, sentence, page.text, page.fetched_at or now_iso)
                )
            for term, sentence in value_sentences(page.text).items():
                try:
                    center.add(
                        make_evidence(
                            url=page.final_url,
                            title=source_label,
                            excerpt=sentence,
                            source_kind="company_site",
                            fact_kind="values",
                            retrieved_at=page.fetched_at or now_iso,
                            confidence=0.6,
                            source_text=page.text,
                        )
                    )
                except ValueError:
                    continue
            first_sentence = next(iter(extract_sentences(page.text)), "")
            if first_sentence:
                try:
                    center.add(
                        make_evidence(
                            url=page.final_url,
                            title=source_label,
                            excerpt=first_sentence,
                            source_kind="company_site",
                            fact_kind="about",
                            retrieved_at=page.fetched_at or now_iso,
                            confidence=0.5,
                            source_text=page.text,
                        )
                    )
                except ValueError:
                    pass

        for term, (url, title, sentence, source_text, retrieved_at) in sorted(stack_excerpts.items()):
            try:
                center.add(
                    make_evidence(
                        url=url,
                        title=title,
                        excerpt=sentence,
                        source_kind="company_site",
                        fact_kind="stack",
                        retrieved_at=retrieved_at,
                        confidence=0.65,
                        source_text=source_text,
                    )
                )
            except ValueError:
                continue

        stack: list[str] = list(stack_excerpts)
        values = sorted(value_sentences("\n".join(page.text for page in pages)))

        if github is not None:
            if github.description:
                try:
                    center.add(
                        make_evidence(
                            url=github.url,
                            title=f"GitHub · {github.org}",
                            excerpt=github.description,
                            source_kind="github",
                            fact_kind="about",
                            retrieved_at=now_iso,
                            confidence=0.7,
                        )
                    )
                except ValueError:
                    pass
            for repo in github.repos:
                if repo["language"]:
                    if repo["language"].lower() not in {item.lower() for item in stack}:
                        stack.append(repo["language"].lower())
                    try:
                        center.add(
                            make_evidence(
                                url=repo["url"] or github.url,
                                title=f"GitHub · {github.org}/{repo['name']}",
                                excerpt=f"{repo['name']} · langage principal : {repo['language']}",
                                source_kind="github",
                                fact_kind="stack",
                                retrieved_at=now_iso,
                                confidence=0.75,
                            )
                        )
                    except ValueError:
                        pass
                try:
                    center.add(
                        make_evidence(
                            url=repo["url"] or github.url,
                            title=f"GitHub · {github.org}/{repo['name']}",
                            excerpt=(
                                f"{repo['name']} · ★{repo['stars']} · "
                                f"{repo['language'] or 'langage non déclaré'} · poussé le {str(repo['pushed_at'])[:10] or 'date inconnue'}"
                            ),
                            source_kind="github",
                            fact_kind="repo",
                            retrieved_at=now_iso,
                            confidence=0.8,
                        )
                    )
                except ValueError:
                    pass
            for release in github.releases:
                try:
                    center.add(
                        make_evidence(
                            url=release["url"] or github.url,
                            title=f"GitHub · {github.org}/{release['repo']}",
                            excerpt=(
                                f"{release['repo']} · {release['name']} · "
                                f"publié le {release['published_at'][:10] or 'date inconnue'}"
                            ),
                            source_kind="github",
                            fact_kind="repo",
                            retrieved_at=now_iso,
                            confidence=0.8,
                        )
                    )
                except ValueError:
                    continue

        news: list[WebNewsHit] = []
        for hit in hits:
            title = normalize_excerpt(hit.title, limit=300)
            excerpt = normalize_excerpt(hit.excerpt or hit.title)
            if not is_public_http_url(hit.url) or not excerpt:
                continue
            try:
                center.add(
                    make_evidence(
                        url=hit.url,
                        title=title,
                        excerpt=excerpt,
                        source_kind="search",
                        fact_kind="news",
                        retrieved_at=now_iso,
                        confidence=0.5,
                    )
                )
            except ValueError:
                continue
            candidate = WebNewsHit(
                title=title,
                url=canonical_url(hit.url),
                date=str(hit.date)[:32] if hit.date else None,
                excerpt=excerpt,
            )
            if candidate not in news:
                news.append(candidate)
        dated = sorted((hit for hit in news if hit.date), key=lambda hit: (hit.date or "", hit.title), reverse=True)
        undated = sorted((hit for hit in news if not hit.date), key=lambda hit: hit.title)
        news = (dated + undated)[:MAX_NEWS_ITEMS]

        repos_summary: dict[str, Any] = {}
        if github is not None:
            repos_summary = {
                "org": github.org,
                "url": github.url,
                "repo_count": len(github.repos),
                "languages": dict(github.languages),
                "top_repos": [
                    {
                        "name": repo["name"],
                        "url": repo["url"],
                        "stars": repo["stars"],
                        "language": repo["language"],
                        "pushed_at": repo["pushed_at"],
                    }
                    for repo in sorted(github.repos, key=lambda item: (-item["stars"], item["name"]))[:10]
                ],
                "recent_releases": [dict(release) for release in github.releases[:6]],
            }

        confidence = _confidence(center)
        facts = WebFacts(
            company=company,
            stack=_dedupe(sorted(stack), limit=MAX_STACK_ITEMS),
            values=_dedupe(values, limit=MAX_VALUE_ITEMS),
            recent_news=news,
            repos_summary=repos_summary,
            evidence_ids=center.ids,
            fetched_at=now_iso,
            confidence=confidence,
            status="ok" if center.items else "empty",
            evidence=center.to_list(),
            sources=_sources_from_evidence(center),
            warnings=_bounded_warnings(warnings),
        )
        if not center.items:
            facts.warnings = _bounded_warnings(
                list(facts.warnings)
                + ["Aucune preuve publique n’a pu être citée : aucune entreprise n’est inventée."]
            )
        return facts, successes

    # -------------------------------------------------------------- helpers

    def _store(self, key: str, facts: WebFacts) -> None:
        self.cache.write(
            key,
            {"facts": facts.as_dict(), "provided_at": facts.provided_at or None},
        )

    def _facts_from_payload(
        self,
        payload: dict[str, Any],
        *,
        status: str,
        from_cache: bool,
        stale: bool,
        extra_warnings: list[str] | None = None,
    ) -> WebFacts:
        raw = payload.get("facts") if isinstance(payload.get("facts"), dict) else {}
        news: list[WebNewsHit] = []
        for item in raw.get("recent_news") or []:
            if not isinstance(item, dict):
                continue
            news.append(
                WebNewsHit(
                    title=str(item.get("title") or ""),
                    url=str(item.get("url") or ""),
                    date=item.get("date") or None,
                    excerpt=str(item.get("excerpt") or ""),
                )
            )
        warnings = [str(item) for item in raw.get("warnings") or []]
        warnings.extend(extra_warnings or [])
        return WebFacts(
            company=str(raw.get("company") or ""),
            stack=[str(item) for item in raw.get("stack") or []],
            values=[str(item) for item in raw.get("values") or []],
            recent_news=news,
            repos_summary=dict(raw.get("repos_summary") or {}),
            evidence_ids=[str(item) for item in raw.get("evidence_ids") or []],
            fetched_at=str(raw.get("fetched_at") or ""),
            confidence=float(raw.get("confidence") or 0.0),
            status=status,
            from_cache=from_cache,
            stale=stale,
            evidence=[dict(item) for item in raw.get("evidence") or [] if isinstance(item, dict)],
            sources=[dict(item) for item in raw.get("sources") or [] if isinstance(item, dict)],
            warnings=_bounded_warnings(warnings),
            provided_at=str(payload.get("provided_at") or raw.get("provided_at") or ""),
        )


def _confidence(center: WebEvidenceCenter) -> float:
    if not center.items:
        return 0.0
    source_kinds = {item.source_kind for item in center.items}
    return round(min(0.95, 0.15 * len(source_kinds) + 0.04 * len(center.items)), 3)


def _sources_from_evidence(center: WebEvidenceCenter) -> list[dict[str, Any]]:
    sources: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for item in center.sorted():
        marker = (item.url, item.title)
        if marker in seen:
            continue
        seen.add(marker)
        sources.append({"url": item.url, "title": item.title, "source_kind": item.source_kind})
    return sources[:MAX_SOURCES]


def _bounded_warnings(warnings: list[str]) -> list[str]:
    result: list[str] = []
    for warning in warnings:
        text = normalize_excerpt(warning, limit=300)
        if text and text not in result:
            result.append(text)
        if len(result) >= MAX_WARNINGS:
            break
    return result


def _evidence_from_dict(payload: dict[str, Any]) -> WebEvidence:
    return WebEvidence(
        id=str(payload.get("id") or ""),
        url=str(payload.get("url") or ""),
        title=str(payload.get("title") or ""),
        excerpt=str(payload.get("excerpt") or ""),
        source_kind=str(payload.get("source_kind") or "company_site"),
        fact_kind=str(payload.get("fact_kind") or "about"),
        retrieved_at=str(payload.get("retrieved_at") or ""),
        confidence=float(payload.get("confidence") or 0.0),
    )


def _sanitize_provided(payload: dict[str, Any]) -> dict[str, Any]:
    def _text(value: Any, limit: int) -> str:
        return normalize_excerpt(value, limit=limit)

    stack = _dedupe([str(item) for item in payload.get("stack") or []], limit=MAX_STACK_ITEMS)
    values = _dedupe([str(item) for item in payload.get("values") or []], limit=MAX_VALUE_ITEMS)
    sources: list[dict[str, str]] = []
    for item in (payload.get("sources") or [])[:MAX_SOURCES]:
        if not isinstance(item, dict):
            continue
        fact_kind = str(item.get("fact_kind") or "about")
        sources.append(
            {
                "url": _text(item.get("url"), 2_000),
                "title": _text(item.get("title"), 300),
                "excerpt": _text(item.get("excerpt"), 600),
                "fact_kind": fact_kind if fact_kind in _FACT_KINDS else "about",
            }
        )
    news: list[dict[str, Any]] = []
    for item in (payload.get("news") or [])[:MAX_NEWS_ITEMS]:
        if not isinstance(item, dict):
            continue
        news.append(
            {
                "title": _text(item.get("title"), 300),
                "url": _text(item.get("url"), 2_000),
                "date": _text(item.get("date"), 32) or None,
                "excerpt": _text(item.get("excerpt"), 600),
            }
        )
    return {
        "company": _text(payload.get("company"), 240),
        "stack": stack,
        "values": values,
        "notes": _text(payload.get("notes"), MAX_PROVIDED_NOTES),
        "sources": sources,
        "news": news,
    }
