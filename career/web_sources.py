"""Public web sources for the Career web researcher (SPEC-018).

This module owns **all** network access used by SPEC-018:

* a small stdlib HTTPS transport with a body-size cap, a bounded redirect
  chain and a guard against private/local hosts;
* a ``robots.txt`` policy that allows the usual case when the file is missing
  or unreachable, and refuses a disallowed path otherwise;
* HTML parsing (stdlib only) and deterministic vocabulary detection;
* company-site, GitHub-organisation and search-provider readers.

Nothing here decides what a *fact* is: it returns documents and field
renderings.  ``career.web_evidence`` turns those into quotable evidence, and
``career.web_research`` composes the final :class:`WebFacts`.  That separation
keeps "no invented excerpt" enforceable in one place.

The transport is injectable, so every test runs fully offline.
"""

from __future__ import annotations

import html
import ipaddress
import json
import re
import socket
import ssl
import unicodedata
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timezone
from html.parser import HTMLParser
from typing import Any, Callable, Protocol

USER_AGENT = "Come-AI-Career/3.3 (local-first public web reader)"
MAX_BODY_BYTES = 1_500_000
MAX_TEXT_CHARS = 200_000
MAX_REDIRECTS = 3
DEFAULT_TIMEOUT_SECONDS = 8
DEFAULT_PATHS: tuple[str, ...] = ("/", "/about", "/careers", "/engineering-blog")
GITHUB_API_HOST = "api.github.com"
_GITHUB_RESERVED = frozenset(
    {
        "about", "apps", "collections", "contact", "features", "join", "login",
        "marketplace", "orgs", "pricing", "search", "settings", "site", "sponsors",
        "topics", "trending", "users",
    }
)


class WebSourceError(RuntimeError):
    """A public-source read failed in a way the caller can report honestly."""

    def __init__(self, message: str, *, code: str = "error", retryable: bool = False) -> None:
        super().__init__(message)
        self.code = code
        self.retryable = retryable


# --------------------------------------------------------------- transport


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def iso_timestamp(moment: datetime) -> str:
    return moment.astimezone(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def is_public_http_url(raw: Any) -> bool:
    """Reject credentials, bare intranet names and private/local addresses."""
    try:
        parsed = urllib.parse.urlsplit(str(raw or "").strip())
    except ValueError:
        return False
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        return False
    if parsed.username or parsed.password:
        return False
    host = parsed.hostname.lower().rstrip(".")
    if host == "localhost" or host.endswith((".localhost", ".local", ".internal", ".home.arpa")):
        return False
    if "." not in host:
        return False
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        return True
    return bool(address.is_global)


def origin_of(raw: Any) -> str:
    parsed = urllib.parse.urlsplit(str(raw or "").strip())
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        return ""
    return urllib.parse.urlunsplit((parsed.scheme.lower(), parsed.hostname.lower(), "/", "", ""))


@dataclass(frozen=True)
class WebDocument:
    """One fetched document, with everything an evidence item needs."""

    url: str
    final_url: str
    status_code: int
    content_type: str
    text: str
    fetched_at: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "url": self.url,
            "final_url": self.final_url,
            "status_code": self.status_code,
            "content_type": self.content_type,
            "text": self.text,
            "fetched_at": self.fetched_at,
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "WebDocument":
        return cls(
            url=str(payload.get("url") or ""),
            final_url=str(payload.get("final_url") or payload.get("url") or ""),
            status_code=int(payload.get("status_code") or 200),
            content_type=str(payload.get("content_type") or ""),
            text=str(payload.get("text") or ""),
            fetched_at=str(payload.get("fetched_at") or ""),
        )


class WebTransport(Protocol):
    """Minimal injectable transport: one public URL in, one document out."""

    def fetch(self, url: str, *, timeout_seconds: int = DEFAULT_TIMEOUT_SECONDS) -> WebDocument:
        ...


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    """Follow redirects in :meth:`UrllibWebTransport.fetch`, not inside urllib."""

    def redirect_request(self, req: Any, fp: Any, code: int, msg: str, headers: Any, newurl: str) -> None:
        _ = (req, fp, code, msg, headers, newurl)
        return None


def _decode_body(data: bytes, content_type: str) -> str:
    match = re.search(r"charset=([A-Za-z0-9_.:-]+)", content_type or "", re.IGNORECASE)
    candidates = [match.group(1)] if match else []
    candidates.extend(["utf-8", "latin-1"])
    for encoding in candidates:
        try:
            return data.decode(encoding, errors="replace")
        except LookupError:
            continue
    return data.decode("utf-8", errors="replace")


class UrllibWebTransport:
    """Small stdlib HTTPS reader: public hosts only, bounded body, no leaks."""

    def __init__(self, *, max_bytes: int = MAX_BODY_BYTES, clock: Callable[[], datetime] | None = None) -> None:
        # macOS Python installers often ship without a usable system CA bundle;
        # ``certifi`` is used when present, exactly like the Greenhouse reader.
        context = ssl.create_default_context()
        try:
            import certifi  # noqa: PLC0415 - optional, stdlib fallback kept

            context = ssl.create_default_context(cafile=certifi.where())
        except ImportError:
            pass
        self._opener = urllib.request.build_opener(
            _NoRedirect(), urllib.request.HTTPSHandler(context=context)
        )
        self._max_bytes = max(1_024, int(max_bytes))
        self._clock = clock or _utc_now

    def fetch(self, url: str, *, timeout_seconds: int = DEFAULT_TIMEOUT_SECONDS) -> WebDocument:
        current = str(url or "").strip()
        if not is_public_http_url(current):
            raise WebSourceError("Cette adresse web n’est pas publique.", code="invalid_url")
        if urllib.parse.urlsplit(current).scheme != "https":
            raise WebSourceError("Seules les adresses HTTPS publiques sont lues.", code="insecure_url")
        request_url = current
        for _ in range(MAX_REDIRECTS + 1):
            document = self._fetch_once(request_url, timeout_seconds)
            if document.status_code not in {301, 302, 303, 307, 308}:
                return WebDocument(
                    url=current,
                    final_url=document.final_url,
                    status_code=document.status_code,
                    content_type=document.content_type,
                    text=document.text,
                    fetched_at=document.fetched_at,
                )
            target = urllib.parse.urljoin(document.final_url, document.text.strip())
            if not is_public_http_url(target) or urllib.parse.urlsplit(target).scheme != "https":
                raise WebSourceError("La redirection sort des adresses publiques autorisées.", code="invalid_redirect")
            request_url = target
        raise WebSourceError("Trop de redirections successives.", code="too_many_redirects")

    def _fetch_once(self, url: str, timeout_seconds: int) -> WebDocument:
        request = urllib.request.Request(
            url,
            method="GET",
            headers={
                "Accept": "text/html,application/xhtml+xml,application/json;q=0.9,text/plain;q=0.8",
                "Accept-Language": "fr,en;q=0.8",
                "User-Agent": USER_AGENT,
            },
        )
        try:
            with self._opener.open(request, timeout=timeout_seconds) as response:  # nosec B310 URL validated above
                status = int(getattr(response, "status", 200) or 200)
                content_type = str(response.headers.get("Content-Type") or "")
                data = response.read(self._max_bytes + 1)
                final_url = str(response.geturl() or url)
        except urllib.error.HTTPError as error:
            location = str(error.headers.get("Location") or "") if error.headers else ""
            if error.code in {301, 302, 303, 307, 308}:
                return WebDocument(
                    url=url,
                    final_url=url,
                    status_code=error.code,
                    content_type="text/plain",
                    text=location,
                    fetched_at=iso_timestamp(self._clock()),
                )
            if error.code == 404:
                raise WebSourceError("Cette page publique n’existe pas (404).", code="404") from None
            if error.code == 429:
                raise WebSourceError("La source limite temporairement les requêtes (429).", code="429", retryable=True) from None
            if error.code in {401, 403}:
                raise WebSourceError("Cette page publique refuse la lecture (accès protégé).", code=str(error.code)) from None
            if error.code in {500, 502, 503, 504}:
                raise WebSourceError("La source est temporairement indisponible.", code=str(error.code), retryable=True) from None
            raise WebSourceError(f"La source a renvoyé une erreur ({error.code}).", code=str(error.code)) from None
        except (urllib.error.URLError, socket.timeout, TimeoutError, ssl.SSLError) as error:
            raise WebSourceError("La source ne répond pas dans le délai prévu.", code="offline", retryable=True) from error
        if len(data) > self._max_bytes:
            raise WebSourceError("La page est trop volumineuse pour être lue en sécurité.", code="oversize")
        return WebDocument(
            url=url,
            final_url=final_url,
            status_code=status,
            content_type=content_type,
            text=_decode_body(data, content_type),
            fetched_at=iso_timestamp(self._clock()),
        )


# ------------------------------------------------------------------- robots


@dataclass(frozen=True)
class RobotsRules:
    allow: tuple[str, ...] = ()
    disallow: tuple[str, ...] = ()
    crawl_delay: float | None = None

    @staticmethod
    def _matches(pattern: str, path: str) -> bool:
        anchored = pattern.endswith("$")
        core = pattern[:-1] if anchored else pattern
        if not core:
            return False
        regex = "^" + ".*".join(re.escape(piece) for piece in core.split("*"))
        if anchored:
            regex += "$"
        return re.match(regex, path) is not None

    def allows(self, path: str) -> bool:
        target = path or "/"
        best_length = -1
        best_is_allow = True
        for pattern in self.disallow:
            if self._matches(pattern, target) and len(pattern) >= best_length:
                best_length = len(pattern)
                best_is_allow = False
        for pattern in self.allow:
            if self._matches(pattern, target) and len(pattern) >= best_length:
                best_length = len(pattern)
                best_is_allow = True
        if best_length == -1:
            return True
        return best_is_allow


ALLOW_ALL = RobotsRules()


def parse_robots(text: str, *, user_agent_token: str = "come-ai-career") -> RobotsRules:
    """Read the group for our agent, else ``*``; merge matching groups."""
    groups: list[dict[str, Any]] = []
    current: dict[str, Any] | None = None
    for raw_line in str(text or "").splitlines():
        line = raw_line.split("#", 1)[0].strip()
        if not line or ":" not in line:
            continue
        key, value = (piece.strip() for piece in line.split(":", 1))
        key = key.lower()
        if key == "user-agent":
            if current is None or current["rules"] or current["crawl"] is not None:
                current = {"agents": [], "rules": [], "crawl": None}
                groups.append(current)
            current["agents"].append(value.lower())
        elif current is not None and key in {"allow", "disallow"}:
            if value:
                current["rules"].append((key, value))
        elif current is not None and key == "crawl-delay":
            try:
                current["crawl"] = float(value)
            except ValueError:
                pass
    named = [group for group in groups if user_agent_token in group["agents"]]
    selected = named or [group for group in groups if "*" in group["agents"]]
    allow: list[str] = []
    disallow: list[str] = []
    delays: list[float] = []
    for group in selected:
        for directive, pattern in group["rules"]:
            (allow if directive == "allow" else disallow).append(pattern)
        if group["crawl"] is not None:
            delays.append(float(group["crawl"]))
    return RobotsRules(
        allow=tuple(allow),
        disallow=tuple(disallow),
        crawl_delay=min(delays) if delays else None,
    )


class RobotsPolicy:
    """Cached ``robots.txt`` reader that never blocks the usual case.

    A missing, unreachable or unreadable ``robots.txt`` means "allow": that is
    what the standard says for a 404 and it keeps a transient outage from
    making every company site unreadable.  A parsed ``Disallow`` is honoured.
    """

    def __init__(
        self,
        transport: WebTransport,
        *,
        clock: Callable[[], datetime] | None = None,
        ttl_hours: float = 24.0,
        user_agent_token: str = "come-ai-career",
    ) -> None:
        self._transport = transport
        self._clock = clock or _utc_now
        self._ttl_seconds = max(0.0, float(ttl_hours)) * 3600
        self._token = user_agent_token
        self._cache: dict[str, tuple[datetime, RobotsRules]] = {}

    def rules_for(self, url: str) -> RobotsRules:
        origin = origin_of(url)
        if not origin:
            return ALLOW_ALL
        cached = self._cache.get(origin)
        now = self._clock()
        if cached and (now - cached[0]).total_seconds() < self._ttl_seconds:
            return cached[1]
        rules = ALLOW_ALL
        try:
            document = self._transport.fetch(urllib.parse.urljoin(origin, "/robots.txt"), timeout_seconds=4)
            rules = parse_robots(document.text, user_agent_token=self._token)
        except (WebSourceError, ValueError):
            rules = ALLOW_ALL
        self._cache[origin] = (now, rules)
        return rules

    def can_fetch(self, url: str) -> bool:
        parsed = urllib.parse.urlsplit(url)
        path = urllib.parse.urlunsplit(("", "", parsed.path or "/", parsed.query, ""))
        return self.rules_for(url).allows(path)


# --------------------------------------------------------------------- HTML


class _PageParser(HTMLParser):
    _SKIP = frozenset({"script", "style", "noscript", "svg", "template"})
    _BLOCK = frozenset({"p", "div", "br", "li", "ul", "ol", "h1", "h2", "h3", "h4", "h5", "h6", "tr", "section", "article", "header", "footer"})

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._skip_depth = 0
        self._in_title = False
        self._parts: list[str] = []
        self.links: list[str] = []
        self.title = ""
        self.description = ""

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attributes = {key.lower(): (value or "") for key, value in attrs}
        if tag in self._SKIP:
            self._skip_depth += 1
            return
        if tag == "title":
            self._in_title = True
        elif tag == "a" and attributes.get("href"):
            self.links.append(attributes["href"])
        elif tag == "meta" and attributes.get("name", "").lower() == "description":
            self.description = html.unescape(attributes.get("content", "")).strip()
        if tag in self._BLOCK:
            self._parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag in self._SKIP:
            self._skip_depth = max(0, self._skip_depth - 1)
            return
        if tag == "title":
            self._in_title = False
        if tag in self._BLOCK:
            self._parts.append("\n")

    def handle_data(self, data: str) -> None:
        if self._skip_depth:
            return
        if self._in_title:
            self.title += data
        else:
            self._parts.append(data)

    @property
    def text(self) -> str:
        return "\n".join(piece.strip() for piece in "".join(self._parts).splitlines() if piece.strip())


@dataclass(frozen=True)
class ParsedPage:
    url: str
    title: str
    description: str
    text: str
    links: tuple[str, ...]


def parse_html(raw_html: str, url: str) -> ParsedPage:
    parser = _PageParser()
    try:
        parser.feed(str(raw_html or ""))
        parser.close()
    except Exception:
        # Malformed remote HTML is untrusted data, not a crash: fall back to a
        # plain tag strip.  It is never interpreted as instructions.
        plain = re.sub(r"<(script|style)\b[^>]*>.*?</\1>", " ", str(raw_html or ""), flags=re.IGNORECASE | re.DOTALL)
        plain = re.sub(r"<[^>]+>", " ", plain)
        return ParsedPage(
            url=url,
            title="",
            description="",
            text=html.unescape(plain)[:MAX_TEXT_CHARS],
            links=(),
        )
    links: list[str] = []
    for link in parser.links:
        absolute = urllib.parse.urljoin(url, link)
        if absolute not in links:
            links.append(absolute)
    return ParsedPage(
        url=url,
        title=re.sub(r"\s+", " ", parser.title).strip()[:300],
        description=re.sub(r"\s+", " ", parser.description).strip()[:600],
        text=parser.text[:MAX_TEXT_CHARS],
        links=tuple(links),
    )


@dataclass(frozen=True)
class Page:
    url: str
    final_url: str
    title: str
    description: str
    text: str
    links: tuple[str, ...]
    fetched_at: str


@dataclass(frozen=True)
class CompanySite:
    pages: tuple[Page, ...]
    skipped: tuple[tuple[str, str], ...]  # (url, reason): robots/404
    warnings: tuple[str, ...]


def _page_from_document(document: WebDocument) -> Page:
    parsed = parse_html(document.text, document.final_url)
    return Page(
        url=document.url,
        final_url=document.final_url,
        title=parsed.title,
        description=parsed.description,
        text=parsed.text,
        links=parsed.links,
        fetched_at=document.fetched_at,
    )


def fetch_company_pages(
    official_url: str,
    transport: WebTransport,
    *,
    robots: RobotsPolicy | None = None,
    paths: tuple[str, ...] = DEFAULT_PATHS,
    timeout_seconds: int = DEFAULT_TIMEOUT_SECONDS,
) -> CompanySite:
    """Read the public company pages around an offer URL (never the offer page)."""
    origin = origin_of(official_url)
    if not origin:
        raise WebSourceError("Cette offre n’a pas d’adresse d’entreprise publique.", code="invalid_url")
    pages: list[Page] = []
    seen: set[str] = set()
    skipped: list[tuple[str, str]] = []
    warnings: list[str] = []
    for path in paths:
        candidate = urllib.parse.urljoin(origin, path)
        if robots is not None and not robots.can_fetch(candidate):
            skipped.append((candidate, "robots"))
            continue
        try:
            document = transport.fetch(candidate, timeout_seconds=timeout_seconds)
        except WebSourceError as error:
            if error.code == "404":
                skipped.append((candidate, "404"))
            else:
                warnings.append(f"{urllib.parse.urlsplit(candidate).path}: {error}")
            continue
        page = _page_from_document(document)
        if page.final_url in seen:
            continue
        seen.add(page.final_url)
        pages.append(page)
    return CompanySite(pages=tuple(pages), skipped=tuple(skipped), warnings=tuple(warnings))


# --------------------------------------------------------------- vocabulary


STACK_ALIASES: dict[str, tuple[str, ...]] = {
    "python": ("python",),
    "java": ("java",),
    "javascript": ("javascript", "node.js", "nodejs", "node js"),
    "typescript": ("typescript",),
    "c++": ("c++", "cpp"),
    "c#": ("c#", "csharp"),
    "go": ("golang", "go lang"),
    "rust": ("rust",),
    "ruby": ("ruby",),
    "php": ("php",),
    "scala": ("scala",),
    "kotlin": ("kotlin",),
    "swift": ("swift",),
    "sql": ("sql",),
    "postgresql": ("postgresql", "postgres"),
    "mysql": ("mysql",),
    "mongodb": ("mongodb", "mongo"),
    "redis": ("redis",),
    "kafka": ("kafka",),
    "spark": ("apache spark", "spark"),
    "hadoop": ("hadoop",),
    "airflow": ("airflow",),
    "docker": ("docker",),
    "kubernetes": ("kubernetes", "k8s"),
    "terraform": ("terraform",),
    "aws": ("aws", "amazon web services"),
    "gcp": ("gcp", "google cloud"),
    "azure": ("azure",),
    "react": ("react.js", "reactjs", "react"),
    "vue": ("vue.js", "vuejs", "vue"),
    "angular": ("angular",),
    "django": ("django",),
    "flask": ("flask",),
    "fastapi": ("fastapi",),
    "spring": ("spring boot", "spring"),
    "tensorflow": ("tensorflow",),
    "pytorch": ("pytorch",),
    "pandas": ("pandas",),
    "numpy": ("numpy",),
    "graphql": ("graphql",),
    "rest": ("rest api", "restful"),
    "microservices": ("microservices", "micro-services"),
    "ci/cd": ("ci/cd", "cicd", "continuous integration"),
    "mlops": ("mlops",),
    "llm": ("llm", "large language model"),
    "nlp": ("nlp", "natural language processing"),
    "git": ("git",),
    "linux": ("linux",),
}

VALUE_ALIASES: dict[str, tuple[str, ...]] = {
    "innovation": ("innovation", "innovant", "innovative"),
    "impact": ("impact", "impactful"),
    "diversité": ("diversité", "diversity", "diverse"),
    "inclusion": ("inclusion", "inclusif", "inclusive"),
    "autonomie": ("autonomie", "autonomy", "autonomous"),
    "collaboration": ("collaboration", "collaboratif", "collaborative", "travailler ensemble"),
    "excellence": ("excellence", "excellent"),
    "apprentissage": ("apprentissage", "learning", "formation continue"),
    "transparence": ("transparence", "transparency", "transparent"),
    "durabilité": ("durabilité", "sustainability", "sustainable"),
    "équilibre": ("équilibre vie professionnelle", "work-life balance", "work life balance"),
    "ambition": ("ambition", "ambitieux", "ambitious"),
    "curiosité": ("curiosité", "curiosity", "curious"),
    "responsabilité": ("responsabilité", "responsibility", "ownership", "accountability"),
    "sécurité": ("sécurité", "security", "safety"),
}

_SENTENCE_SPLIT = re.compile(r"(?<=[.!?])\s+|\n+")
_BULLET_PREFIX = re.compile(r"^[\s•●▪◦·‣\-–—*]+")


def extract_sentences(text: str, *, limit: int = 500) -> list[str]:
    """Split prose into short, quotable sentences without rewriting them."""
    sentences: list[str] = []
    seen: set[str] = set()
    for raw in _SENTENCE_SPLIT.split(str(text or "")):
        sentence = re.sub(r"\s+", " ", _BULLET_PREFIX.sub("", raw)).strip()
        if len(sentence) < 4 or len(sentence) > 500:
            continue
        if sentence in seen:
            continue
        seen.add(sentence)
        sentences.append(sentence)
        if len(sentences) >= limit:
            break
    return sentences


def _term_pattern(alias: str) -> re.Pattern[str]:
    return re.compile(r"(?<![\w])" + re.escape(alias) + r"(?![\w])", re.IGNORECASE)


def _matched_terms(text: str, vocabulary: dict[str, tuple[str, ...]]) -> dict[str, str]:
    """Return ``{canonical: first matching excerpt}`` in vocabulary order."""
    matches: dict[str, str] = {}
    sentences = extract_sentences(text)
    for term, aliases in vocabulary.items():
        patterns = [_term_pattern(alias) for alias in aliases]
        for sentence in sentences:
            if any(pattern.search(sentence) for pattern in patterns):
                matches[term] = sentence
                break
    return matches


def stack_sentences(text: str) -> dict[str, str]:
    return _matched_terms(text, STACK_ALIASES)


def value_sentences(text: str) -> dict[str, str]:
    return _matched_terms(text, VALUE_ALIASES)


def stack_terms(text: str) -> list[str]:
    return sorted(stack_sentences(text))


def value_terms(text: str) -> list[str]:
    return sorted(value_sentences(text))


# ------------------------------------------------------------------- GitHub


def _slugify_company(company: str) -> str:
    normalized = unicodedata.normalize("NFKD", str(company or ""))
    ascii_text = "".join(char for char in normalized if not unicodedata.combining(char)).lower()
    words = re.findall(r"[a-z0-9]+", ascii_text)
    legal = {"inc", "ltd", "limited", "llc", "plc", "corp", "corporation", "company", "group", "holding", "holdings",
             "sa", "sas", "sarl", "gmbh", "ag", "bv", "nv", "spa", "srl", "france"}
    while words and words[-1] in legal:
        words.pop()
    return "".join(words[:4])


def resolve_github_org(company: str, links: tuple[str, ...] | list[str]) -> tuple[str, str]:
    """Return ``(slug, origin)``; ``origin`` is ``linked`` or ``inferred``."""
    for link in links:
        parsed = urllib.parse.urlsplit(str(link or ""))
        if parsed.hostname and parsed.hostname.lower() in {"github.com", "www.github.com"}:
            pieces = [piece for piece in parsed.path.split("/") if piece]
            if pieces and pieces[0].lower() not in _GITHUB_RESERVED:
                candidate = pieces[0]
                if re.fullmatch(r"[A-Za-z0-9](?:[A-Za-z0-9-]{0,38})", candidate):
                    return candidate, "linked"
    slug = _slugify_company(company)
    return (slug, "inferred") if len(slug) >= 2 else ("", "")


@dataclass(frozen=True)
class GithubSnapshot:
    org: str
    url: str
    description: str
    repos: tuple[dict[str, Any], ...]
    languages: dict[str, int]
    releases: tuple[dict[str, Any], ...]
    fetched_at: str


def _github_json(transport: WebTransport, path: str, *, timeout_seconds: int) -> Any:
    endpoint = f"https://{GITHUB_API_HOST}{path}"
    document = transport.fetch(endpoint, timeout_seconds=timeout_seconds)
    try:
        return json.loads(document.text)
    except json.JSONDecodeError as error:
        raise WebSourceError("GitHub n’a pas renvoyé un flux JSON lisible.", code="invalid_json") from error


def fetch_github_org(
    slug: str,
    transport: WebTransport,
    *,
    timeout_seconds: int = DEFAULT_TIMEOUT_SECONDS,
    max_repos: int = 20,
    max_release_repos: int = 2,
) -> GithubSnapshot | None:
    """Read a public GitHub organisation; ``None`` when the org does not exist."""
    if not re.fullmatch(r"[A-Za-z0-9](?:[A-Za-z0-9-]{0,38})", str(slug or "")):
        return None
    try:
        organisation = _github_json(transport, f"/orgs/{slug}", timeout_seconds=timeout_seconds)
    except WebSourceError as error:
        if error.code == "404":
            return None
        raise
    if not isinstance(organisation, dict):
        return None
    try:
        raw_repos = _github_json(
            transport, f"/orgs/{slug}/repos?per_page={max(1, min(max_repos, 30))}&sort=pushed", timeout_seconds=timeout_seconds
        )
    except WebSourceError:
        raw_repos = []
    repos: list[dict[str, Any]] = []
    language_counts: dict[str, int] = {}
    for raw in raw_repos if isinstance(raw_repos, list) else []:
        if not isinstance(raw, dict):
            continue
        language = str(raw.get("language") or "").strip()
        name = str(raw.get("name") or "").strip()
        if not name:
            continue
        repos.append(
            {
                "name": name,
                "url": str(raw.get("html_url") or ""),
                "description": str(raw.get("description") or "").strip()[:600],
                "language": language,
                "stars": max(0, int(raw.get("stargazers_count") or 0)),
                "topics": tuple(sorted(str(topic) for topic in raw.get("topics") or [] if str(topic)))[:10],
                "pushed_at": str(raw.get("pushed_at") or ""),
                "updated_at": str(raw.get("updated_at") or ""),
            }
        )
        if language:
            language_counts[language] = language_counts.get(language, 0) + 1
    releases: list[dict[str, Any]] = []
    most_starred = sorted(repos, key=lambda repo: (-repo["stars"], repo["name"]))[:max(0, max_release_repos)]
    for repo in most_starred:
        try:
            raw_releases = _github_json(
                transport, f"/repos/{slug}/{repo['name']}/releases?per_page=3", timeout_seconds=timeout_seconds
            )
        except WebSourceError:
            continue
        for raw in raw_releases if isinstance(raw_releases, list) else []:
            if not isinstance(raw, dict) or not raw.get("name") and not raw.get("tag_name"):
                continue
            releases.append(
                {
                    "repo": repo["name"],
                    "name": str(raw.get("name") or raw.get("tag_name") or "").strip()[:200],
                    "tag": str(raw.get("tag_name") or "").strip()[:80],
                    "published_at": str(raw.get("published_at") or ""),
                    "url": str(raw.get("html_url") or repo["url"]),
                }
            )
    releases.sort(key=lambda release: (release["published_at"], release["repo"], release["name"]), reverse=True)
    return GithubSnapshot(
        org=str(organisation.get("login") or slug),
        url=str(organisation.get("html_url") or f"https://github.com/{slug}"),
        description=str(organisation.get("description") or "").strip()[:600],
        repos=tuple(repos),
        languages=dict(sorted(language_counts.items())),
        releases=tuple(releases[:6]),
        fetched_at="",
    )


# ------------------------------------------------------------------- search


@dataclass(frozen=True)
class SearchHit:
    title: str
    url: str
    excerpt: str
    date: str | None = None


class SearchProvider(Protocol):
    def search(self, query: str, *, limit: int = 5) -> list[SearchHit]:
        """Return public result snippets; never invent a missing date."""


class NullSearchProvider:
    """Explicit "no search engine configured" provider."""

    def search(self, query: str, *, limit: int = 5) -> list[SearchHit]:
        _ = (query, limit)
        return []


class StaticSearchProvider:
    """Deterministic provider used by tests and offline fixtures."""

    def __init__(self, hits: list[SearchHit] | tuple[SearchHit, ...]) -> None:
        self._hits = list(hits)

    def search(self, query: str, *, limit: int = 5) -> list[SearchHit]:
        _ = query
        return self._hits[: max(0, limit)]


class DuckDuckGoSearch:
    """Keyless public search snippets (DuckDuckGo Instant Answer API).

    The API returns encyclopaedic/related snippets rather than a news feed, so
    each hit is cited as-is and ``date`` stays ``None`` unless the provider
    actually supplied one.
    """

    def __init__(self, transport: WebTransport, *, timeout_seconds: int = DEFAULT_TIMEOUT_SECONDS) -> None:
        self._transport = transport
        self._timeout = timeout_seconds

    def search(self, query: str, *, limit: int = 5) -> list[SearchHit]:
        endpoint = "https://api.duckduckgo.com/?" + urllib.parse.urlencode(
            {"q": query, "format": "json", "no_html": "1", "skip_disambig": "1"}
        )
        document = self._transport.fetch(endpoint, timeout_seconds=self._timeout)
        try:
            payload = json.loads(document.text)
        except json.JSONDecodeError as error:
            raise WebSourceError("Le moteur de recherche n’a pas renvoyé un flux lisible.", code="invalid_json") from error
        hits: list[SearchHit] = []
        abstract = str(payload.get("AbstractText") or "").strip()
        abstract_url = str(payload.get("AbstractURL") or "").strip()
        if abstract and is_public_http_url(abstract_url):
            hits.append(
                SearchHit(
                    title=str(payload.get("Heading") or query).strip()[:300],
                    url=abstract_url,
                    excerpt=abstract[:600],
                    date=None,
                )
            )
        stack: list[Any] = list(payload.get("RelatedTopics") or [])
        while stack and len(hits) < limit:
            item = stack.pop(0)
            if not isinstance(item, dict):
                continue
            if "Topics" in item:
                stack = list(item.get("Topics") or []) + stack
                continue
            url = str(item.get("FirstURL") or "").strip()
            excerpt = str(item.get("Text") or "").strip()
            if url and excerpt and is_public_http_url(url):
                hits.append(SearchHit(title=excerpt[:120], url=url, excerpt=excerpt[:600], date=None))
        return hits[: max(0, limit)]


def build_search_queries(offer: dict[str, Any]) -> list[str]:
    """Local query strings built from the offer's own wording."""
    company = re.sub(r"\s+", " ", str(offer.get("company") or "")).strip()
    city = re.sub(r"\s+", " ", str(offer.get("city") or "")).strip()
    title = re.sub(r"\s+", " ", str(offer.get("title") or "")).strip()
    if not company:
        return []
    queries = [f'"{company}" actualités']
    if city:
        queries.append(f'"{company}" {city} ingénierie')
    if title:
        queries.append(f'"{company}" "{title}"')
    queries.append(f'"{company}" engineering blog stack')
    deduped: list[str] = []
    for query in queries:
        if query not in deduped:
            deduped.append(query)
    return deduped[:3]
