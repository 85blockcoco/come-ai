"""Shared plumbing for the international sources (offers published outside France).

The four international connectors — LinkedIn Europe, EURES, JobTeaser
International and Glassdoor International — share the same boundary: a
bounded, polite, read-only read of one public source, a country filter
applied on the source side, and the same admission and ranking rules as the
French connectors.

This module holds that shared part **once**.  Each connector keeps its own
URL builder and its own parser, because a source publishes its facts in its
own shape; only the plumbing is shared.  Nothing here contacts a network on
its own: the HTTP layer is a small, explicit, injectable fetcher.

Two rules are non-negotiable and are implemented here:

* **The excluded country is never asked for.**  The request itself carries
  only the allowed countries, so an excluded country costs no quota and
  never enters the corpus.
* **The country is read, never guessed.**  A country comes from what the
  source publishes (an ISO code, a country name, or the country the request
  was made for).  A city never designates a country, and a missing country
  stays unknown instead of becoming a guess.

The country filter is applied twice on purpose: once when the request is
built, and once on the facts the source publishes.  The second pass is the
guarantee: a source that answers with a country nobody asked for is dropped
before the offer becomes a local record.
"""

from __future__ import annotations

import heapq
import re
import socket
import ssl
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from datetime import datetime, timezone
from html.parser import HTMLParser
from typing import Any, Callable, Iterator

from ..countries import canonical_country_codes, canonicalize_country, country_from_source, split_location
from ..discovery import DiscoveryPayload, PublicSourceError, source_html_to_text
from ..exploration import EXPLORATION_MAX_RESULTS, classify_internship, criteria_admit, ranking_key
from ..models import canonical_url, clean_text
from ..offer_qualification import qualify_offer
from ..stage_search import default_brief, score_brief_match, validate_brief


# --- vocabulary --------------------------------------------------------------

#: The source is an official public portal (a public service of a state).
SOURCE_TIER_OFFICIAL = "official"
#: The offer is published by the employer's own domain.
SOURCE_TIER_EMPLOYER = "employer"
#: A third-party portal republishes postings written by an employer.
SOURCE_TIER_AGGREGATOR = "aggregator"

#: A connector never claims ``employer`` unless the offer URL is published by
#: the employer's own domain.  A portal that republishes a posting is an
#: ``aggregator``: calling it an employer would assert a fact nobody
#: published, and would give it the highest deduplication priority on that
#: false basis.
SOURCE_TIERS: tuple[str, ...] = (SOURCE_TIER_OFFICIAL, SOURCE_TIER_EMPLOYER, SOURCE_TIER_AGGREGATOR)

#: Bodies are read with a hard cap: a source never fills the memory.
MAX_RESPONSE_BYTES = 8 * 1024 * 1024
#: A source never sends an unbounded number of offers.
MAX_ROWS = 400
#: A connector never walks more pages than this, whatever the configuration.
MAX_PAGES = 10
#: A connector never sends more requests than this in one run.
MAX_REQUESTS = 24


# --- health ------------------------------------------------------------------

@dataclass
class IntlHealth:
    """Factual counters of the last read of one international source."""

    last_ok: bool = False
    last_error: str | None = None
    consecutive_failures: int = 0
    raw_offers: int = 0
    valid_offers: int = 0
    finance_offers: int = 0
    stage_offers: int = 0
    conforming_offers: int = 0
    to_verify_offers: int = 0
    raw_count: int = 0
    filtered_count: int = 0
    excluded_count: int = 0
    excluded_by_country: dict[str, int] = field(default_factory=dict)
    countries_seen: dict[str, int] = field(default_factory=dict)
    requests: int = 0
    budget_exhausted: bool = False


def reset_health(health: IntlHealth) -> None:
    """Forget the counters of the previous run; the failure streak is kept."""
    health.raw_offers = 0
    health.valid_offers = 0
    health.finance_offers = 0
    health.stage_offers = 0
    health.conforming_offers = 0
    health.to_verify_offers = 0
    health.raw_count = 0
    health.filtered_count = 0
    health.excluded_count = 0
    health.excluded_by_country = {}
    health.countries_seen = {}
    health.budget_exhausted = False


def health_snapshot(health: IntlHealth) -> dict[str, Any]:
    """The factual state of the last read, as the interface reads it.

    ``countries_seen`` counts the offers that were kept, per canonical
    country, and ``france_ratio`` is the share of French offers in that
    corpus.  The filter is applied before the corpus is built, so a
    correctly working source reports ``0.0``.
    """
    countries = dict(health.countries_seen)
    total = sum(countries.values())
    france = countries.get("FR", 0)
    return {
        "last_ok": health.last_ok,
        "last_error": health.last_error,
        "consecutive_failures": health.consecutive_failures,
        "raw_offers": health.raw_offers,
        "valid_offers": health.valid_offers,
        "finance_offers": health.finance_offers,
        "stage_offers": health.stage_offers,
        "conforming_offers": health.conforming_offers,
        "to_verify_offers": health.to_verify_offers,
        "raw_count": health.raw_count,
        "filtered_count": health.filtered_count,
        "excluded_count": health.excluded_count,
        # ``country_excluded_count`` is the name the shared payload contract
        # uses; ``filtered_geo_count`` is the name this mission reads.  Both
        # describe the same fact: the offers dropped for their country.
        "country_excluded_count": health.excluded_count,
        "filtered_geo_count": health.excluded_count,
        "excluded_by_country": dict(health.excluded_by_country),
        "countries_seen": countries,
        "france_ratio": (france / total) if total else 0.0,
        "requests": health.requests,
        "budget_exhausted": health.budget_exhausted,
    }


# --- roles -------------------------------------------------------------------

_FINANCE_KEYWORDS = frozenset({
    "m&a", "mergers", "acquisitions", "fusion", "acquisition", "investment banking",
    "banque d'affaires", "corporate finance", "finance d'entreprise", "private equity",
    "capital investissement", "asset management", "gestion d'actifs", "portfolio management",
    "equity research", "fixed income", "sales & trading", "global markets", "trading",
    "transaction services", "due diligence", "financial due diligence", "audit",
    "audit financier", "fp&a", "financial planning", "controle de gestion", "treasury",
    "valuation", "strategic finance", "quantitative research", "quant", "risk management",
    "gestion de portefeuille", "analyse financiere", "banque", "finance", "comptabilite",
    "expertise comptable", "consolidation", "reporting", "controler", "business partner",
    "finanzwesen", "controlling", "rechnungswesen", "corporate finance intern",
})

_STAGE_KEYWORDS = frozenset({
    "stage", "stagiaire", "intern", "internship", "tirocinio", "praktikum",
    "werkstudent", "working student", "apprenti", "apprentissage", "alternance",
    "praktikant", "trainee", "traineeship", "graduate intern", "werkstudentin",
})


def is_finance_role(title: Any, description: Any) -> bool:
    """Whether the offer is a financial one, read from its own words."""
    text = f"{clean_text(title, limit=300)} {clean_text(description, limit=30_000)}".lower()
    return any(keyword in text for keyword in _FINANCE_KEYWORDS)


def is_stage_role(title: Any, description: Any, contract_type: Any) -> bool:
    """Whether the offer is an internship, read from its own words."""
    contract = clean_text(contract_type, limit=120).lower()
    text = f"{clean_text(title, limit=300)} {clean_text(description, limit=30_000)}".lower()
    if any(keyword in contract for keyword in _STAGE_KEYWORDS):
        return True
    return any(keyword in text for keyword in _STAGE_KEYWORDS)


# --- geography ---------------------------------------------------------------

def parse_location(value: Any) -> tuple[str, str]:
    """Read a published location as a city and a country wording.

    A source writes ``"Berlin, Germany"``, ``"Berlin (Germany)"`` or
    ``"Berlin - Germany"``.  Each part is read on its own.  A location that
    names no country keeps an empty country: a missing country is an unknown
    fact, never a guessed one.
    """
    text = clean_text(value, limit=300)
    if not text:
        return "", ""
    parts = split_location(text)
    if len(parts) >= 2:
        return parts[0], parts[-1]
    return text, ""


def canonical_country(country: Any, hint: Any = "") -> str:
    """The canonical country of a published wording, or of the request.

    The wording published by the source always wins.  The country the
    request was made for is only a fallback: it is used when the source
    published no country at all.
    """
    code = canonicalize_country(country)
    if code:
        return code
    return canonicalize_country(hint)


def excluded_country_codes(countries_exclude: Any, brief: dict[str, Any]) -> frozenset[str]:
    """The countries a connector must never return, as canonical codes."""
    raw = countries_exclude if countries_exclude is not None else brief.get("countries_exclude")
    return frozenset(canonical_country_codes(raw))


def allowed_countries(targets: Any, excluded: frozenset[str], preferred: Any = ()) -> list[str]:
    """The target countries, minus the excluded ones.

    The countries the person asked for come first: a search spends its
    limited requests where the offers are wanted.  The targets may be
    written as a list of codes or as a mapping of code to the wording the
    source publishes for them.
    """
    if isinstance(targets, dict):
        targets = list(targets)
    codes = [code for code in canonical_country_codes(targets) if code not in excluded]
    wanted = [code for code in canonical_country_codes(preferred) if code in codes]
    ordered = wanted + [code for code in codes if code not in wanted]
    return ordered


# --- polite HTTP -------------------------------------------------------------

class RobotsPolicy:
    """The rules a host publishes in ``robots.txt``.

    Only the two rules this product can honour are read: ``Allow`` and
    ``Disallow`` for the paths we request, and ``Crawl-delay`` for the pause
    between two requests.  A ``robots.txt`` that cannot be read is treated
    as "no rule published", and the connector then applies its own, stricter,
    interval.
    """

    def __init__(self, text: str | None) -> None:
        self._rules: list[tuple[str, bool]] = []
        self._crawl_delay: float | None = None
        self._parse(text or "")

    def _parse(self, text: str) -> None:
        groups: list[tuple[list[str], list[tuple[str, bool]]]] = []
        agents: list[str] = []
        rules: list[tuple[str, bool]] = []
        delay: float | None = None
        started = False

        def flush() -> None:
            nonlocal agents, rules, delay, started
            if agents:
                groups.append((list(agents), list(rules), delay))
            agents = []
            rules = []
            delay = None
            started = False

        for raw_line in text.splitlines():
            line = raw_line.split("#", 1)[0].strip()
            if not line or ":" not in line:
                continue
            name, _, value = line.partition(":")
            key = name.strip().lower()
            value = value.strip()
            if key == "user-agent":
                if started and rules:
                    flush()
                elif started:
                    flush()
                agents.append(value.lower())
                started = True
            elif key in {"disallow", "allow"} and agents:
                rules.append((value, key == "allow"))
            elif key == "crawl-delay" and agents:
                try:
                    delay = max(0.0, float(value))
                except ValueError:
                    delay = None
        flush()

        chosen: list[tuple[str, bool]] = []
        chosen_delay: float | None = None
        for names, group_rules, group_delay in groups:
            if "*" in names:
                if not chosen:
                    chosen = group_rules
                    chosen_delay = group_delay
                continue
            if chosen:
                continue
            chosen = group_rules
            chosen_delay = group_delay
        self._rules = chosen
        self._crawl_delay = chosen_delay

    @property
    def crawl_delay(self) -> float:
        """The published pause between two requests, in seconds."""
        return self._crawl_delay or 0.0

    def allows(self, url: str) -> bool:
        """Whether the host allows this URL to be read."""
        if not self._rules:
            return True
        path = urllib.parse.urlsplit(url).path or "/"
        best: tuple[str, bool] | None = None
        for pattern, allowed in self._rules:
            if not _rule_matches(pattern, path):
                continue
            if best is None or len(pattern) > len(best[0]) or (len(pattern) == len(best[0]) and allowed and not best[1]):
                best = (pattern, allowed)
        if best is None:
            return True
        return best[1]


def _rule_matches(pattern: str, path: str) -> bool:
    """Whether a robots.txt path pattern covers this path."""
    if not pattern:
        return False
    regex = re.escape(pattern).replace(r"\*", ".*")
    if regex.endswith(r"\$"):
        regex = regex[:-2] + "$"
    return re.match(regex, path) is not None


class PoliteFetcher:
    """A bounded, polite, read-only HTTPS GET.

    * only the hosts the connector declares are contacted;
    * a redirect to another host is refused;
    * the body is capped;
    * the host's ``robots.txt`` is honoured, including ``Crawl-delay``;
    * two requests are never closer than the configured interval.
    """

    def __init__(
        self,
        *,
        hosts: Any,
        user_agent: str,
        min_interval: float = 2.0,
        timeout: int = 15,
        accept: str = "text/html,application/xhtml+xml,application/json;q=0.9,*/*;q=0.8",
        accept_language: str = "en-GB,en;q=0.9,fr;q=0.8",
        max_bytes: int = MAX_RESPONSE_BYTES,
        transport: Callable[[str, dict[str, str], int], str | None] | None = None,
        sleeper: Callable[[float], None] = time.sleep,
        monotonic: Callable[[], float] = time.monotonic,
        respect_robots: bool = True,
        health: IntlHealth | None = None,
    ) -> None:
        self.hosts = frozenset(hosts)
        self.user_agent = user_agent
        self.min_interval = max(0.0, float(min_interval))
        self.timeout = max(1, int(timeout))
        self.accept = accept
        self.accept_language = accept_language
        self.max_bytes = max(1_024, int(max_bytes))
        self._transport = transport or self._urllib_transport
        self._sleeper = sleeper
        self._monotonic = monotonic
        self._respect_robots = respect_robots
        self._health = health
        self._last_request_at = 0.0
        self._requested = False
        self._robots: dict[str, RobotsPolicy] = {}
        self._requests = 0
        self._opener: urllib.request.OpenerDirector | None = None

    # -- transport ----------------------------------------------------------

    def _urllib_opener(self) -> urllib.request.OpenerDirector:
        if self._opener is None:
            context = ssl.create_default_context()
            try:
                import certifi  # noqa: PLC0415 - optional, keep the stdlib fallback

                context = ssl.create_default_context(cafile=certifi.where())
            except (ImportError, OSError):
                pass
            self._opener = urllib.request.build_opener(
                _NoRedirect(), urllib.request.HTTPSHandler(context=context)
            )
        return self._opener

    def _urllib_transport(self, url: str, headers: dict[str, str], timeout: int) -> str | None:
        request = urllib.request.Request(url, method="GET", headers=headers)
        try:
            with self._urllib_opener().open(request, timeout=timeout) as response:
                body = response.read(self.max_bytes + 1)
        except urllib.error.HTTPError as error:
            self._fail(f"HTTP {error.code}")
            return None
        except (urllib.error.URLError, TimeoutError, socket.timeout) as error:
            self._fail(f"Erreur réseau : {type(error).__name__}")
            return None
        except Exception as error:  # pragma: no cover - defensive
            self._fail(f"Erreur inattendue : {type(error).__name__}")
            return None
        if len(body) > self.max_bytes:
            self._fail("Réponse trop volumineuse")
            return None
        return body.decode("utf-8", errors="replace")

    # -- robots -------------------------------------------------------------

    def _policy_for(self, host: str) -> RobotsPolicy:
        policy = self._robots.get(host)
        if policy is None:
            # The robots.txt is a request like any other: it waits its turn.
            self._wait(self.min_interval)
            text = self._transport(
                f"https://{host}/robots.txt",
                {"User-Agent": self.user_agent, "Accept": "text/plain;q=0.9,*/*;q=0.8"},
                self.timeout,
            )
            policy = RobotsPolicy(text)
            self._robots[host] = policy
        return policy

    # -- public API ---------------------------------------------------------

    def fetch(self, url: str) -> str | None:
        """Read one URL, or return ``None`` when the source cannot answer."""
        parsed = urllib.parse.urlsplit(url)
        if parsed.scheme != "https" or not parsed.hostname or parsed.hostname not in self.hosts:
            self._fail("URL hors des hôtes autorisés")
            return None
        interval = self.min_interval
        if self._respect_robots:
            policy = self._policy_for(parsed.hostname)
            if not policy.allows(url):
                self._fail("Le robots.txt de la source interdit cette URL")
                return None
            interval = max(interval, policy.crawl_delay)
        self._wait(interval)
        self._requests += 1
        if self._health is not None:
            self._health.requests = self._requests
        headers = {
            "User-Agent": self.user_agent,
            "Accept": self.accept,
            "Accept-Language": self.accept_language,
        }
        body = self._transport(url, headers, self.timeout)
        if body is None:
            return None
        self._succeed()
        return body

    def _wait(self, interval: float) -> None:
        if interval <= 0:
            return
        if self._requested:
            elapsed = self._monotonic() - self._last_request_at
            if elapsed < interval:
                self._sleeper(interval - elapsed)
        self._last_request_at = self._monotonic()
        self._requested = True

    def _fail(self, message: str) -> None:
        if self._health is not None:
            self._health.last_error = message
            self._health.consecutive_failures += 1
            self._health.last_ok = False

    def _succeed(self) -> None:
        if self._health is not None:
            self._health.last_error = None
            self._health.consecutive_failures = 0
            self._health.last_ok = True


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    """Do not follow a public redirect to another host."""

    def redirect_request(self, req: Any, fp: Any, code: int, msg: str, headers: Any, newurl: str) -> None:
        _ = (req, fp, code, msg, headers, newurl)
        return None


# --- HTML result cards -------------------------------------------------------

@dataclass(frozen=True)
class CardSpec:
    """How one source publishes a result card.

    Each source names the same facts differently.  The parser is told which
    class names carry which fact and reads them; a class it does not know is
    ignored, so an unknown markup yields fewer facts rather than wrong ones.
    """

    container_tag: str = ""
    container_class: str = ""
    title_hints: tuple[str, ...] = ()
    company_hints: tuple[str, ...] = ()
    location_hints: tuple[str, ...] = ()
    contract_hints: tuple[str, ...] = ()
    description_hints: tuple[str, ...] = ()
    link_class: str = ""
    link_hints: tuple[str, ...] = ()
    time_attr: str = ""
    country_attr: str = ""


class JobCardParser(HTMLParser):
    """A tolerant reader for the result cards of the HTML sources."""

    def __init__(self, spec: CardSpec) -> None:
        super().__init__(convert_charrefs=True)
        self.spec = spec
        self.cards: list[dict[str, Any]] = []
        self._card: dict[str, Any] | None = None
        self._field = ""
        self._field_depth = 0
        self._depth = 0
        self._drop_depth = 0

    # -- helpers ------------------------------------------------------------

    def _starts_card(self, tag: str, classes: str) -> bool:
        if self.spec.container_tag and tag != self.spec.container_tag:
            return False
        if self.spec.container_class and self.spec.container_class not in classes:
            return False
        return bool(self.spec.container_tag or self.spec.container_class)

    def _field_for(self, classes: str) -> str:
        for field_name, hints in (
            ("title", self.spec.title_hints),
            ("company", self.spec.company_hints),
            ("location", self.spec.location_hints),
            ("contract_type", self.spec.contract_hints),
            ("description", self.spec.description_hints),
        ):
            if any(hint in classes for hint in hints):
                return field_name
        return ""

    def _is_link(self, href: str, classes: str) -> bool:
        if self.spec.link_class and self.spec.link_class in classes:
            return True
        return any(hint in href for hint in self.spec.link_hints)

    # -- HTMLParser ---------------------------------------------------------

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        values = {key: (value or "") for key, value in attrs}
        classes = values.get("class", "").lower()
        if self._card is None:
            if self._starts_card(tag, classes):
                self._card = {
                    "title": "", "company": "", "location": "", "contract_type": "",
                    "url": "", "description": "", "posted_date": "", "country": "",
                }
                self._depth = 1
                self._field = ""
                self._field_depth = 0
            return
        self._depth += 1
        if tag in {"script", "style", "noscript"}:
            self._drop_depth += 1
            return
        if self.spec.country_attr and values.get(self.spec.country_attr):
            self._card["country"] = values[self.spec.country_attr]
        if tag == "time" and self.spec.time_attr and values.get(self.spec.time_attr):
            self._card["posted_date"] = values[self.spec.time_attr]
        if tag == "a" and values.get("href") and self._is_link(values["href"], classes):
            self._card["url"] = values["href"]
        field = self._field_for(classes)
        if field:
            self._field = field
            self._field_depth = self._depth

    def handle_endtag(self, tag: str) -> None:
        if self._card is None:
            return
        if tag in {"script", "style", "noscript"} and self._drop_depth:
            self._drop_depth -= 1
        if self._field and self._depth <= self._field_depth:
            self._field = ""
            self._field_depth = 0
        self._depth -= 1
        if self._depth <= 0:
            self._close_card()

    def handle_data(self, data: str) -> None:
        if self._card is None or self._drop_depth or not self._field:
            return
        text = data.strip()
        if not text:
            return
        current = self._card.get(self._field, "")
        self._card[self._field] = clean_text(f"{current} {text}".strip(), limit=2_000)

    def _close_card(self) -> None:
        card = self._card
        self._card = None
        self._field = ""
        self._field_depth = 0
        self._depth = 0
        if card and card.get("title") and card.get("url"):
            self.cards.append(card)


# --- offers ------------------------------------------------------------------

def build_job(
    *,
    provider: str,
    source_tier: str,
    title: Any,
    company: Any,
    url: Any,
    location_text: Any = "",
    country_structural: Any = "",
    country_hint: Any = "",
    contract_type: Any = "",
    description: Any = "",
    posted_date: Any = "",
    start_date: Any = "",
    end_date: Any = "",
    duration_months: Any = None,
    source_id: Any = "",
    employment_type: Any = "",
    requirements: Any = "",
    languages_required: Any = "",
) -> dict[str, Any]:
    """Build the offer record the local database expects.

    The facts come from the source; nothing is completed by inference.  A
    country is read from what the source published, and stays empty when the
    source published none.
    """
    clean_title = clean_text(title, limit=300)
    clean_company = clean_text(company, limit=240)
    raw_url = clean_text(url, limit=2_000)
    if not clean_title or not clean_company or not raw_url:
        raise ValueError("An offer without a title, a company or a URL is not usable.")
    try:
        official_url = canonical_url(raw_url)
    except Exception as error:  # invalid URL, credential, unsupported scheme
        raise ValueError(f"URL d'offre invalide : {error}") from error
    city, country = parse_location(location_text)
    country_code = canonical_country(country_structural) or canonical_country(country, country_hint)
    identifier = clean_text(source_id, limit=120)
    if not identifier:
        identifier = urllib.parse.urlsplit(official_url).path.rstrip("/").rsplit("/", 1)[-1]
    if not identifier:
        identifier = str(abs(hash(official_url)))[-12:]
    duration = duration_months
    if type(duration) is not int or not 1 <= duration <= 24:
        duration = None
    return {
        "company": clean_company,
        "title": clean_title,
        "source_name": provider,
        "source_id": identifier,
        "source_tier": source_tier,
        "official_url": official_url,
        "apply_url": official_url,
        "city": city,
        "country": country,
        "country_canonical": country_code,
        "posted_date": clean_text(posted_date, limit=32),
        "deadline_date": "",
        "start_date": clean_text(start_date, limit=32),
        "end_date": clean_text(end_date, limit=32),
        "duration_months": duration,
        "source_status": "open",
        "source_verified": True,
        "employment_type": clean_text(employment_type or contract_type, limit=120),
        "role_level": "",
        "requirements": clean_text(requirements, limit=4_000),
        "languages_required": clean_text(languages_required, limit=1_000),
        "eligibility_requirement": "",
        "description_original": source_html_to_text(description),
    }


# --- the connector boundary --------------------------------------------------

class IntlConnector:
    """The boundary every international connector shares.

    A connector reads one public source, asks it only for the countries that
    are allowed, and hands the offers to the same admission and ranking
    rules as the French connectors.  A subclass implements
    :meth:`_iter_offers` and :meth:`_normalise_one`; everything else is
    shared.
    """

    provider = ""
    documentation_url = ""
    source_tier = SOURCE_TIER_AGGREGATOR
    hosts: frozenset[str] = frozenset()
    user_agent = "ComeAI-Career/1.0 (read-only public job source)"
    min_interval = 2.0
    timeout = 15
    accept = "text/html,application/xhtml+xml,application/json;q=0.9,*/*;q=0.8"
    accept_language = "en-GB,en;q=0.9,fr;q=0.8"
    #: How many requests one run may send.  The bound keeps a source inside
    #: the network budget of the exploration, which is shared by every
    #: source of the run.
    max_requests: int = MAX_REQUESTS

    _HEALTH = IntlHealth()

    def __init__(
        self,
        *,
        clock: Callable[[], str] | None = None,
        monotonic: Callable[[], float] = time.monotonic,
        sleeper: Callable[[float], None] = time.sleep,
        max_pages: int = 5,
        max_results: int = EXPLORATION_MAX_RESULTS,
        max_requests: int | None = None,
        fetch: Callable[[str], str | None] | None = None,
        enabled: bool = False,
        min_interval: float | None = None,
        respect_robots: bool = True,
    ) -> None:
        self.enabled = bool(enabled)
        self.clock = clock or (lambda: datetime.now(timezone.utc).isoformat(timespec="seconds"))
        self.monotonic = monotonic
        self.sleeper = sleeper
        self.max_pages = max(1, min(MAX_PAGES, int(max_pages)))
        self.max_results = max(1, min(EXPLORATION_MAX_RESULTS, int(max_results)))
        self.max_requests = max(1, min(MAX_REQUESTS, int(max_requests if max_requests is not None else self.max_requests)))
        self._fetch = fetch
        self._min_interval = self.min_interval if min_interval is None else max(0.0, float(min_interval))
        self._respect_robots = respect_robots
        self._fetcher: PoliteFetcher | None = None
        self._requests = 0

    # -- to implement in a subclass -----------------------------------------

    def _iter_offers(
        self, source: dict[str, Any], *, deadline: float | None, excluded: frozenset[str]
    ) -> Iterator[dict[str, Any]]:
        """Yield the raw offers published by the source."""
        raise NotImplementedError

    def _normalise_one(self, source: dict[str, Any], raw: dict[str, Any]) -> dict[str, Any]:
        """Turn one raw offer into the record the local database expects."""
        raise NotImplementedError

    # -- shared --------------------------------------------------------------

    def _read(self, url: str) -> str | None:
        """Read one URL, honouring the rate limit and the robots.txt."""
        if self._fetch is not None:
            self._requests += 1
            self._HEALTH.requests = self._requests
            body = self._fetch(url)
            if body is None:
                self._HEALTH.last_error = "La source n'a pas répondu."
                self._HEALTH.consecutive_failures += 1
                self._HEALTH.last_ok = False
            return body
        if self._fetcher is None:
            self._fetcher = PoliteFetcher(
                hosts=self.hosts,
                user_agent=self.user_agent,
                min_interval=self._min_interval,
                timeout=self.timeout,
                accept=self.accept,
                accept_language=self.accept_language,
                sleeper=self.sleeper,
                monotonic=self.monotonic,
                respect_robots=self._respect_robots,
                health=self._HEALTH,
            )
        return self._fetcher.fetch(url)

    def _check_source(self, source: Any) -> None:
        """Refuse a source that is not a verified public record of this provider."""
        if not isinstance(source, dict) or source.get("provider") != self.provider:
            raise PublicSourceError(
                f"La source ne correspond pas au connecteur {self.provider}.", code="invalid_source"
            )
        provenance = urllib.parse.urlsplit(clean_text(source.get("provenance_url"), limit=2_000))
        if (
            not clean_text(source.get("id"), limit=160)
            or not clean_text(source.get("company"), limit=240)
            or not clean_text(source.get("verified_at"), limit=80)
            or provenance.scheme != "https"
            or not provenance.hostname
        ):
            raise PublicSourceError(
                "Une source officielle vérifiée est requise avant toute consultation.",
                code="unverified_source",
            )

    def _budget_left(self, deadline: float | None) -> bool:
        return deadline is None or self.monotonic() < deadline

    def _iter_by_country(
        self,
        countries: list[str],
        *,
        deadline: float | None,
        build_url: Callable[[str, int], str],
        parse_page: Callable[[str], list[dict[str, Any]]],
        page_size: int,
    ) -> Iterator[dict[str, Any]]:
        """Read the countries one page at a time, round-robin.

        The countries are read round-robin so a limited request budget gives
        every country at least one page instead of giving every page to the
        first countries.  The country of the request travels with the offer:
        it is the fallback used only when the source published no country.
        """
        pending = list(countries)
        pages = {code: 0 for code in pending}
        while pending and self._requests < self.max_requests:
            for code in list(pending):
                if self._requests >= self.max_requests:
                    break
                if not self._budget_left(deadline):
                    self._HEALTH.budget_exhausted = True
                    return
                body = self._read(build_url(code, pages[code] * page_size))
                if body is None:
                    pending.remove(code)
                    continue
                items = parse_page(body)
                if not items:
                    pending.remove(code)
                    continue
                for item in items:
                    yield {**item, "country_hint": code}
                pages[code] += 1
                if len(items) < page_size:
                    pending.remove(code)

    def discover_internships(
        self,
        source: dict[str, Any],
        *,
        selection_brief: dict[str, Any],
        deadline: float | None = None,
        countries_exclude: list[str] | tuple[str, ...] | None = None,
    ) -> DiscoveryPayload:
        """Read the source and return the offers the person may apply to."""
        if not self.enabled:
            raise PublicSourceError("Ce connecteur est désactivé.", code="connector_disabled")
        self._check_source(source)
        brief = validate_brief(selection_brief) if selection_brief else default_brief()
        excluded = excluded_country_codes(countries_exclude, brief)
        health = self._HEALTH
        reset_health(health)
        self._requests = 0

        raw_count = evaluated = invalid = confirmed = uncertain = 0
        excluded_count = relevant = filtered = geo_excluded = 0
        excluded_by_country: dict[str, int] = {}
        ranked: list[tuple[tuple[Any, ...], dict[str, Any]]] = []

        for raw in self._iter_offers(source, deadline=deadline, excluded=excluded):
            if not self._budget_left(deadline):
                # The network budget is spent.  An international source reads
                # several countries in one run, so a cut-off is expected
                # rather than exceptional: the offers already read are kept
                # and the read is reported as incomplete.
                health.budget_exhausted = True
                break
            raw_count += 1
            health.raw_offers += 1
            if raw_count > MAX_ROWS:
                raise PublicSourceError(
                    "Le flux dépasse la limite d'offres évaluées.", code="too_many_rows"
                )
            try:
                job = self._normalise_one(source, raw)
            except (KeyError, TypeError, ValueError):
                invalid += 1
                health.filtered_count += 1
                continue

            evaluated += 1

            country_code = canonicalize_country(job.get("country_canonical"))
            if not country_code:
                country_code = country_from_source(job.get("country"))
            if country_code and country_code in excluded:
                # The excluded country is dropped here, on the source side: the
                # offer never becomes a local record and never consumes a slot.
                geo_excluded += 1
                excluded_count += 1
                health.excluded_count += 1
                health.filtered_count += 1
                excluded_by_country[country_code] = excluded_by_country.get(country_code, 0) + 1
                health.excluded_by_country[country_code] = health.excluded_by_country.get(country_code, 0) + 1
                continue

            health.valid_offers += 1
            if country_code:
                health.countries_seen[country_code] = health.countries_seen.get(country_code, 0) + 1

            finance = is_finance_role(job.get("title"), job.get("description_original"))
            stage = is_stage_role(job.get("title"), job.get("description_original"), job.get("employment_type"))
            if finance:
                health.finance_offers += 1
            if stage:
                health.stage_offers += 1
            conforming = finance and stage and bool(job.get("official_url"))
            if conforming:
                health.conforming_offers += 1
            else:
                health.to_verify_offers += 1

            classification = classify_internship(job)
            qualification = qualify_offer(
                job,
                allowed_contract_types=brief.get("contract_types"),
                allowed_start_months=brief.get("start_months"),
                minimum_stage_duration_months=brief.get("minimum_stage_duration_months", 6),
                excluded_countries=brief.get("excluded_countries"),
                excluded_cities=brief.get("excluded_cities"),
                require_known_location=brief.get("require_known_location", False),
            ).to_dict()
            job["qualification"] = qualification
            target = qualification["target_status"]
            confirmed += int(target == "conforming")
            uncertain += int(target == "to_verify")
            excluded_count += int(target == "non_conforming")
            if target == "non_conforming":
                continue
            if (
                not job.get("official_url")
                or (qualification["contract_type"] == "unknown" and not classification.get("evidence"))
            ):
                filtered += 1
                continue
            match = score_brief_match(brief, job)
            if not criteria_admit(match, job, brief):
                filtered += 1
                continue
            relevant += 1
            job["internship_classification"] = classification
            ranked.append((ranking_key(job, match), {"job": job, "match": match}))

        selected = heapq.nsmallest(self.max_results, ranked, key=lambda item: item[0])
        health.raw_count = raw_count
        health.last_ok = health.last_error is None
        return DiscoveryPayload(
            jobs=tuple(item[1]["job"] for item in selected),
            verified_at=self.clock(),
            truncated=relevant > self.max_results or health.budget_exhausted,
            raw_count=raw_count,
            evaluated_count=evaluated,
            invalid_count=invalid,
            confirmed_count=confirmed,
            uncertain_count=uncertain,
            excluded_count=excluded_count,
            relevant_count=relevant,
            filtered_criteria_count=filtered,
            country_excluded_count=geo_excluded,
            excluded_by_country=excluded_by_country,
        )

    @classmethod
    def health_check(cls) -> dict[str, Any]:
        """The factual state of the last read of this source."""
        return health_snapshot(cls._HEALTH)


__all__ = [
    "MAX_PAGES",
    "MAX_REQUESTS",
    "MAX_RESPONSE_BYTES",
    "MAX_ROWS",
    "SOURCE_TIER_AGGREGATOR",
    "SOURCE_TIER_EMPLOYER",
    "SOURCE_TIER_OFFICIAL",
    "SOURCE_TIERS",
    "CardSpec",
    "IntlConnector",
    "IntlHealth",
    "JobCardParser",
    "PoliteFetcher",
    "RobotsPolicy",
    "allowed_countries",
    "build_job",
    "canonical_country",
    "excluded_country_codes",
    "health_snapshot",
    "is_finance_role",
    "is_stage_role",
    "parse_location",
    "reset_health",
]
