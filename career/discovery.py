"""Bounded, read-only Greenhouse public-job-board discovery.

This is deliberately a narrow integration: it reads an explicitly configured
public Greenhouse board after a person presses the search button.  It never
performs a general web search, follows an arbitrary URL, logs in, reads
LinkedIn, or submits an application.  The transport is injectable, so all
tests remain offline.
"""

from __future__ import annotations

import html
import hashlib
import heapq
import inspect
import json
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
from typing import TYPE_CHECKING, Any, Protocol

from workspace_core import UserFacingError

from .models import canonical_url, clean_text, normalized_text
from .countries import (
    DEFAULT_COUNTRIES_EXCLUDE,
    geo_filter,
    resolve_published_country,
)
from .scoring import classify_job_family
from .stage_search import default_brief, score_brief_match, validate_brief
from .exploration import classify_internship, criteria_admit
from .offer_qualification import qualify_offer

if TYPE_CHECKING:  # pragma: no cover - typing only
    from .cv_quality.job_deduplication import DedupReport


GREENHOUSE_HOST = "boards-api.greenhouse.io"
GREENHOUSE_TIMEOUT_SECONDS = 8
# A public board with full posting descriptions is heavy: measured on a real
# board of 722 openings the payload is 5.6 MB, so a 4 MB cap rejected valid
# boards.  8 MB keeps the memory bound explicit while fitting real boards;
# larger ones are refused with a clear message instead of exhausting memory.
GREENHOUSE_MAX_RESPONSE_BYTES = 8 * 1024 * 1024
GREENHOUSE_MAX_JOBS = 150
# Refuse pathological feeds rather than silently evaluating a source prefix.
# Combined with the 8 MiB transport limit, this bounds parsing/scoring work.
GREENHOUSE_MAX_FEED_ROWS = 20_000
GREENHOUSE_TOKEN_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,119}$")


class PublicSourceError(UserFacingError):
    """Safe, source-level error; a failure never changes existing jobs."""

    def __init__(self, message: str, *, retryable: bool = False, code: str = ""):
        super().__init__(message)
        self.retryable = retryable
        self.code = code


@dataclass(frozen=True)
class GreenhouseBoard:
    id: str
    company: str
    board_token: str

    @property
    def endpoint(self) -> str:
        token = urllib.parse.quote(self.board_token, safe="")
        return f"https://{GREENHOUSE_HOST}/v1/boards/{token}/jobs?content=true"

    @property
    def public_url(self) -> str:
        return f"https://boards.greenhouse.io/{urllib.parse.quote(self.board_token, safe='')}"


@dataclass(frozen=True)
class DiscoveryPayload:
    jobs: tuple[dict[str, Any], ...]
    verified_at: str
    truncated: bool
    evaluated_count: int = 0
    invalid_count: int = 0
    raw_count: int = 0
    confirmed_count: int = 0
    uncertain_count: int = 0
    excluded_count: int = 0
    relevant_count: int = 0
    filtered_criteria_count: int = 0
    # Offers dropped because their country is excluded, counted per country.
    # They are part of ``excluded_count``: an excluded country is a
    # non-conforming offer, not a malformed one.
    country_excluded_count: int = 0
    excluded_by_country: dict[str, int] = field(default_factory=dict)

    @property
    def offers_filtered_geo(self) -> int:
        """Number of offers the source-side country filter dropped.

        This is the audit metric of the geographic filter: every offer the
        connector refused to return because of its country.  It is a
        property of ``country_excluded_count``, never a second counter that
        could drift from it.
        """
        return self.country_excluded_count


def parse_greenhouse_board_token(value: Any) -> str:
    """Accept a Greenhouse board token or a fixed-host public board URL.

    The resulting request URL is always constructed by :class:`GreenhouseBoard`.
    This is important: a supplied string can never turn into a request to an
    internal or unrelated host.
    """

    raw = clean_text(value, limit=2_000)
    if not raw:
        raise UserFacingError("Indique le lien public Greenhouse de l’entreprise ou son identifiant de board.")
    if "://" not in raw:
        token = raw
    else:
        parsed = urllib.parse.urlsplit(raw)
        hostname = (parsed.hostname or "").lower()
        if (
            parsed.scheme != "https"
            or parsed.username
            or parsed.password
            or parsed.port not in {None, 443}
            or hostname not in {"boards.greenhouse.io", "job-boards.greenhouse.io", GREENHOUSE_HOST}
        ):
            raise UserFacingError("Utilise une URL HTTPS publique de Greenhouse, sans identifiant ni mot de passe.")
        parts = [part for part in parsed.path.split("/") if part]
        if hostname == GREENHOUSE_HOST:
            expected = ["v1", "boards"]
            if (
                [part.lower() for part in parts[:2]] != expected
                or len(parts) != 4
                or parts[3].lower() != "jobs"
            ):
                raise UserFacingError("Cette URL Greenhouse ne contient pas un board public valide.")
            token = parts[2]
        else:
            if len(parts) != 1:
                raise UserFacingError("Cette URL Greenhouse ne désigne pas un board public unique.")
            token = parts[0]
    token = clean_text(token, limit=120)
    if not GREENHOUSE_TOKEN_RE.fullmatch(token):
        raise UserFacingError("L’identifiant Greenhouse doit contenir seulement lettres, chiffres, tirets ou underscores.")
    return token


class _PlainTextParser(HTMLParser):
    """Convert source HTML to inert, bounded plain text before it reaches UI/AI."""

    _BREAKS = {"p", "br", "div", "li", "h1", "h2", "h3", "h4", "tr"}
    _DROP = {"script", "style", "noscript"}

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._pieces: list[str] = []
        self._drop_depth = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        _ = attrs
        tag = tag.lower()
        if tag in self._DROP:
            self._drop_depth += 1
        if not self._drop_depth and tag in self._BREAKS:
            self._pieces.append("\n")

    def handle_endtag(self, tag: str) -> None:
        tag = tag.lower()
        if tag in self._DROP and self._drop_depth:
            self._drop_depth -= 1
        if not self._drop_depth and tag in self._BREAKS:
            self._pieces.append("\n")

    def handle_data(self, data: str) -> None:
        if not self._drop_depth:
            self._pieces.append(data)

    def value(self) -> str:
        text = "\n".join(line.strip() for line in "".join(self._pieces).splitlines() if line.strip())
        return clean_text(html.unescape(text), limit=30_000)


def source_html_to_text(value: Any) -> str:
    raw = clean_text(value, limit=100_000)
    if not raw:
        return ""
    # Some ATS feeds HTML-escape their already HTML-formatted description.
    # Decode at most twice before parsing: this removes display-only tags such
    # as ``&lt;li&gt;`` without turning the parser into an unbounded decoder.
    for _ in range(2):
        decoded = html.unescape(raw)
        if decoded == raw:
            break
        raw = decoded
    parser = _PlainTextParser()
    try:
        parser.feed(raw)
        parser.close()
        return parser.value()
    except Exception:
        # Malformed remote HTML remains untrusted data, not a reason to fail a
        # complete board refresh.  This fallback does not interpret it.
        return clean_text(re.sub(r"<[^>]+>", " ", raw), limit=30_000)


class GreenhouseTransport(Protocol):
    def get_json(self, endpoint: str, timeout_seconds: int) -> Any:
        """Read a JSON response from the fixed public Greenhouse API host."""


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    """Do not follow public API redirects to a different host."""

    def redirect_request(self, req: Any, fp: Any, code: int, msg: str, headers: Any, newurl: str) -> None:
        _ = (req, fp, code, msg, headers, newurl)
        return None


class UrllibGreenhouseTransport:
    """Small stdlib transport: one fixed host, timeout and body-size cap."""

    def __init__(self) -> None:
        # macOS Python installers often leave the system keychain without the
        # Mozilla root bundle, which makes a plain default context reject
        # every public board with CERTIFICATE_VERIFY_FAILED.  ``requests``
        # solves this with certifi; the same fallback is used here so public
        # discovery works out of the box, without weakening verification.
        context = ssl.create_default_context()
        try:
            import certifi  # noqa: PLC0415 - optional, keep stdlib-only fallback

            context = ssl.create_default_context(cafile=certifi.where())
        except ImportError:
            pass
        self._opener = urllib.request.build_opener(
            _NoRedirect(), urllib.request.HTTPSHandler(context=context)
        )

    def get_json(self, endpoint: str, timeout_seconds: int) -> Any:
        parsed = urllib.parse.urlsplit(endpoint)
        if parsed.scheme != "https" or parsed.hostname != GREENHOUSE_HOST:
            raise PublicSourceError("La source Greenhouse configurée est invalide.", code="invalid_source")
        request = urllib.request.Request(
            endpoint,
            method="GET",
            headers={
                "Accept": "application/json",
                "User-Agent": "Come-AI-Career/3.2 (local public job-board reader)",
            },
        )
        try:
            with self._opener.open(request, timeout=timeout_seconds) as response:  # nosec B310 fixed host above
                data = response.read(GREENHOUSE_MAX_RESPONSE_BYTES + 1)
        except urllib.error.HTTPError as error:
            if error.code == 429:
                raise PublicSourceError(
                    "Greenhouse limite temporairement les requêtes pour ce board (429). Réessaie plus tard.",
                    retryable=True,
                    code="429",
                ) from None
            if error.code in {500, 502, 503, 504}:
                raise PublicSourceError(
                    f"Greenhouse est temporairement indisponible pour ce board ({error.code}).",
                    retryable=True,
                    code=str(error.code),
                ) from None
            if error.code == 404:
                raise PublicSourceError("Ce board Greenhouse est introuvable ou n’est plus public.", code="404") from None
            if error.code in {401, 403}:
                raise PublicSourceError("Ce board Greenhouse ne donne pas accès à son flux public.", code=str(error.code)) from None
            raise PublicSourceError(f"Greenhouse a renvoyé une erreur ({error.code}).", code=str(error.code)) from None
        except (urllib.error.URLError, socket.timeout, TimeoutError) as error:
            raise PublicSourceError(
                "Le board Greenhouse ne répond pas dans le délai prévu.", retryable=True, code="timeout"
            ) from error
        if len(data) > GREENHOUSE_MAX_RESPONSE_BYTES:
            raise PublicSourceError("La réponse Greenhouse est trop volumineuse pour être importée en sécurité.", code="oversize")
        try:
            return json.loads(data.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise PublicSourceError("Greenhouse n’a pas renvoyé un flux JSON lisible.", code="invalid_json") from error


def _location_parts(value: Any, *, preserve_multi_locations: bool = False) -> tuple[str, str]:
    location = clean_text(value, limit=300)
    if not location:
        return "", ""
    pieces = [piece.strip() for piece in re.split(r"\s*[,|/]\s*", location) if piece.strip()]
    if preserve_multi_locations and ("/" in location or "|" in location):
        # Public boards can offer one posting in several cities (for example
        # London/Paris/HK/Tokyo). Do not drop middle locations or declare the
        # last city a country; the source wording remains visible as-is.
        return clean_text(location, limit=160), ""
    if preserve_multi_locations and len(pieces) >= 2:
        # ATSs also publish city, region, country. Keep an explicit country,
        # rather than calling a known mismatch "unknown". This is recognition
        # of source wording, never a city-to-country geographical inference.
        explicit_countries = {
            "france", "united kingdom", "uk", "united states", "united states of america", "usa",
            "netherlands", "germany", "belgium", "switzerland", "ireland", "italy", "spain",
            "portugal", "luxembourg", "austria", "poland", "sweden", "denmark", "norway",
            "finland", "canada", "australia", "singapore", "hong kong", "china", "india", "japan",
        }
        if normalized_text(pieces[-1]) in explicit_countries:
            return clean_text(", ".join(pieces[:-1]), limit=160), clean_text(pieces[-1], limit=120)
        return clean_text(location, limit=160), ""
    if len(pieces) >= 2:
        return clean_text(pieces[0], limit=160), clean_text(pieces[-1], limit=120)
    return clean_text(location, limit=160), ""


def _explicit_employment_type(raw: dict[str, Any]) -> str:
    """Read only named ATS contract metadata and explicitly recognized values.

    Time Type=Full Time is not a contract type: many genuine internships are
    full-time. Unknown/custom metadata never establishes stage admission.
    """
    entries = raw.get("metadata")
    if not isinstance(entries, list):
        return ""
    recognized: set[str] = set()
    values = {"intern": "internship", "internship": "internship", "internships": "internship",
              "stage": "internship", "stagiaire": "internship", "summer internship": "internship",
              "permanent": "permanent", "cdi": "CDI", "cdd": "CDD", "fixed term": "CDD",
              "vie": "VIE", "graduate": "graduate"}
    for entry in entries[:100]:
        if not isinstance(entry, dict) or normalized_text(entry.get("name")) not in {
            "employment type", "requisition type", "candidate type"}:
            continue
        raw_value = entry.get("value")
        candidates = raw_value[:10] if isinstance(raw_value, list) else [raw_value]
        for value in candidates:
            if isinstance(value, str):
                mapped = values.get(normalized_text(value))
                if mapped:
                    # Preserve the actual source wording in evidence quotes;
                    # the mapping above recognizes it, never rewrites it.
                    recognized.add(clean_text(value, limit=80))
    return clean_text(" / ".join(sorted(recognized, key=str.casefold)), limit=120)


class GreenhouseJobBoardConnector:
    """Read published openings from one known board, with one capped retry."""

    def __init__(self, transport: GreenhouseTransport | None = None) -> None:
        self.transport = transport or UrllibGreenhouseTransport()
        self._last_metrics: dict[str, Any] = {
            "raw_count": 0,
            "filtered_count": 0,
            "excluded_count": 0,
            "country_excluded_count": 0,
            "excluded_by_country": {},
        }
        self._last_error: str | None = None

    def discover(self, board: GreenhouseBoard) -> DiscoveryPayload:
        """Compatibility entry point: deterministic, preference-free selection."""
        return self.discover_ranked(board)

    def discover_ranked(
        self, board: GreenhouseBoard, *, selection_brief: dict[str, Any] | None = None,
        internships_only: bool = False, deadline: float | None = None,
        countries_exclude: list[str] | tuple[str, ...] | None = None,
        countries_include: list[str] | tuple[str, ...] | None = None,
    ) -> DiscoveryPayload:
        """Score the whole admissible feed before keeping its best 150 jobs.

        The person's criteria are used locally; the public HTTP request is
        unchanged and never contains profile or preference data.
        """
        brief = validate_brief(selection_brief) if selection_brief is not None else default_brief()
        error: PublicSourceError | None = None
        for attempt in range(2):
            try:
                remaining = deadline - time.monotonic() if deadline is not None else GREENHOUSE_TIMEOUT_SECONDS
                if remaining <= 0:
                    raise PublicSourceError("Le budget de recherche est atteint ; cette source n’a pas été relancée.", code="budget")
                payload = self.transport.get_json(board.endpoint, min(GREENHOUSE_TIMEOUT_SECONDS, remaining))
                result = self._normalise(
                    board, payload, selection_brief=brief, internships_only=internships_only,
                    countries_exclude=countries_exclude, countries_include=countries_include,
                )
                self._last_metrics = {
                    "raw_count": result.raw_count,
                    "filtered_count": result.invalid_count + result.filtered_criteria_count,
                    "excluded_count": result.excluded_count,
                    "country_excluded_count": result.country_excluded_count,
                    "excluded_by_country": dict(result.excluded_by_country),
                }
                self._last_error = None
                return result
            except PublicSourceError as caught:
                error = caught
                self._last_error = caught.code or "error"
                if not caught.retryable or attempt:
                    raise
                # One small retry accommodates temporary 429/503/network
                # failures without turning a refresh button into a loop.
                time.sleep(0.35)
        assert error is not None
        raise error

    def discover_internships(
        self, board: GreenhouseBoard, *, selection_brief: dict[str, Any], deadline: float | None = None,
        countries_exclude: list[str] | tuple[str, ...] | None = None,
        countries_include: list[str] | tuple[str, ...] | None = None,
    ) -> DiscoveryPayload:
        """Explorer entry point: classify and admit before the per-source cap."""
        return self.discover_ranked(board, selection_brief=selection_brief,
                                    internships_only=True, deadline=deadline,
                                    countries_exclude=countries_exclude,
                                    countries_include=countries_include)

    def health_check(self) -> dict[str, Any]:
        """Factual counters of the last read; no offer is ever invented here."""
        metrics = self._last_metrics
        return {
            "provider": "greenhouse",
            "last_error": self._last_error,
            "raw_count": int(metrics.get("raw_count", 0)),
            "filtered_count": int(metrics.get("filtered_count", 0)),
            "excluded_count": int(metrics.get("excluded_count", 0)),
            "country_excluded_count": int(metrics.get("country_excluded_count", 0)),
            "excluded_by_country": dict(metrics.get("excluded_by_country", {})),
        }

    @staticmethod
    def _normalise(
        board: GreenhouseBoard, payload: Any, *, selection_brief: dict[str, Any] | None = None,
        internships_only: bool = False,
        countries_exclude: list[str] | tuple[str, ...] | None = None,
        countries_include: list[str] | tuple[str, ...] | None = None,
    ) -> DiscoveryPayload:
        if not isinstance(payload, dict) or not isinstance(payload.get("jobs"), list):
            raise PublicSourceError("Greenhouse a renvoyé un format d’offres inattendu.", code="invalid_payload")
        raw_jobs = payload["jobs"]
        if len(raw_jobs) > GREENHOUSE_MAX_FEED_ROWS:
            raise PublicSourceError(
                "Le flux Greenhouse contient trop d’entrées pour être entièrement évalué en sécurité. "
                "Les offres déjà enregistrées sont conservées ; consulte le board officiel.",
                code="too_many_rows",
            )
        brief = validate_brief(selection_brief) if selection_brief is not None else default_brief()
        geo = geo_filter(countries_exclude, countries_include, brief)
        excluded_by_country: dict[str, int] = {}
        evaluated_count = invalid_count = 0
        confirmed_count = uncertain_count = excluded_count = relevant_count = filtered_criteria_count = 0
        country_excluded_count = 0

        def candidates():
            nonlocal evaluated_count, invalid_count, confirmed_count, uncertain_count, excluded_count
            nonlocal relevant_count, filtered_criteria_count, country_excluded_count
            for raw in raw_jobs:
                if not isinstance(raw, dict):
                    invalid_count += 1
                    continue
                job_id = clean_text(raw.get("id"), limit=240)
                title = clean_text(raw.get("title"), limit=300)
                official_url = clean_text(raw.get("absolute_url"), limit=2_000)
                if not job_id or not title or not official_url:
                    invalid_count += 1
                    continue
                # A malformed or credential-bearing URL must not occupy one
                # of the retained places only to fail later during import.
                try:
                    canonical = canonical_url(official_url)
                except (UserFacingError, ValueError):
                    invalid_count += 1
                    continue
                location = raw.get("location") if isinstance(raw.get("location"), dict) else {}
                city, country = _location_parts(location.get("name"), preserve_multi_locations=internships_only)
                # A board may state the country structurally (``office.country_code``)
                # instead of inside the location wording.  The structural code wins:
                # it is a published fact, while the location string is prose.
                office = location.get("office") if isinstance(location.get("office"), dict) else {}
                explicit_country = office.get("country_code") or location.get("country_code")
                country_canonical, excluded_code = resolve_published_country(
                    explicit_country, location.get("name"), geo
                )
                evaluated_count += 1
                if excluded_code:
                    # The country is excluded on the source side: the offer is
                    # dropped before its description is even parsed, before it
                    # can enter the local database or consume one of the
                    # retained places.
                    country_excluded_count += 1
                    excluded_count += 1
                    excluded_by_country[excluded_code] = (
                        excluded_by_country.get(excluded_code, 0) + 1
                    )
                    continue
                description = source_html_to_text(raw.get("content"))
                job = {
                    "company": board.company,
                    "title": title,
                    "source_name": "greenhouse",
                    "source_id": job_id,
                    "official_url": official_url,
                    "city": city,
                    "country": country,
                    "country_canonical": country_canonical,
                    # ``updated_at`` is source maintenance metadata, not a
                    # posting or internship date.  We deliberately leave the
                    # calendar unknown unless the ATS exposes it structurally.
                    "posted_date": "",
                    "deadline_date": "",
                    "start_date": "",
                    "end_date": "",
                    "duration_months": None,
                    "source_status": "open",
                    "employment_type": _explicit_employment_type(raw) if internships_only else "",
                    "role_level": "",
                    "requirements": "",
                    "languages_required": "",
                    "eligibility_requirement": "",
                    "description_original": description,
                    "job_family": classify_job_family(title, description),
                }
                match = score_brief_match(brief, job)
                if internships_only:
                    classification = classify_internship(job)
                    qualification = qualify_offer(
                        {**job, "source_verified": True},
                        allowed_contract_types=brief.get("contract_types"),
                        allowed_start_months=brief.get("start_months"),
                        minimum_stage_duration_months=brief.get("minimum_stage_duration_months", 6),
                        excluded_countries=brief.get("excluded_countries"),
                        excluded_cities=brief.get("excluded_cities"),
                        require_known_location=brief.get("require_known_location", False),
                        preferred_countries=brief.get("preferred_countries"),
                        geo_excluded_countries=brief.get("geo_excluded_countries"),
                    ).to_dict()
                    job["qualification"] = qualification
                    target = qualification["target_status"]
                    confirmed_count += int(target == "conforming")
                    uncertain_count += int(target == "to_verify")
                    excluded_count += int(target == "non_conforming")
                    if target == "non_conforming":
                        continue
                    if qualification["contract_type"] == "unknown" and not classification.get("evidence"):
                        filtered_criteria_count += 1
                        continue
                    if not criteria_admit(match, job, brief):
                        filtered_criteria_count += 1
                        continue
                    job["internship_classification"] = classification
                    relevant_count += 1
                else:
                    relevant_count += 1
                # The ranking uses the total score (relevance plus the
                # geographic signal).  An offer published in a penalized
                # country never leads the list, whatever its relevance.
                total_score = match.get("total_score")
                geo_score = int(match.get("geo_score") or 0)
                # Source identities, not arrival order or generated database
                # IDs, break ties. The content digest resolves conflicting
                # duplicate identities without depending on feed ordering.
                digest = hashlib.sha256(
                    json.dumps(job, sort_keys=True, ensure_ascii=False).encode("utf-8")
                ).hexdigest()
                status_rank = {"conforming": 0, "to_verify": 1}.get(
                    (job.get("qualification") or {}).get("target_status"), 0
                )
                education_rank = (match.get("education_access") or {}).get("priority_rank", 2)
                geo_rank = 1 if geo_score < 0 else 0
                key = (geo_rank, status_rank,
                       -(int(total_score) if total_score is not None else 0),
                       -geo_score,
                       education_rank, job_id, canonical, digest)
                yield key, job

        # nsmallest retains only a 150-item heap (O(N log 150)), not a second
        # list containing every normalised posting and its full description.
        selected = heapq.nsmallest(GREENHOUSE_MAX_JOBS, candidates(), key=lambda item: item[0])
        return DiscoveryPayload(
            jobs=tuple(job for _, job in selected),
            verified_at=datetime.now(timezone.utc).isoformat(timespec="microseconds"),
            truncated=relevant_count > GREENHOUSE_MAX_JOBS,
            evaluated_count=evaluated_count,
            invalid_count=invalid_count,
            raw_count=len(raw_jobs),
            confirmed_count=confirmed_count,
            uncertain_count=uncertain_count,
            excluded_count=excluded_count,
            relevant_count=relevant_count,
            filtered_criteria_count=filtered_criteria_count,
            country_excluded_count=country_excluded_count,
            excluded_by_country=excluded_by_country,
        )


def _deduplicate_stage_offers(jobs: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], "DedupReport"]:
    """Merge the offers collected from every public source.

    The multi-source collection happens upstream: each registered board is
    read once and every connector returns its own offer records.  This entry
    point is the deterministic, local merge step that runs right after that
    collection: the same offer published on several boards becomes a single
    offer, and each merged offer keeps the trace of its sources.

    Args:
        jobs: Offer records collected from every source (Greenhouse, Ashby,
            Lever, Welcome to the Jungle, JobTeaser, Talent.com, APEC).

    Returns:
        A tuple with the deduplicated offers and the merge report.
    """
    # Imported lazily: the deduplication module is only needed when several
    # sources are merged, and it must not slow down the import of discovery.
    from .cv_quality.job_deduplication import deduplicate_jobs

    return deduplicate_jobs(jobs)
def callable_geo_kwargs(method: Any, **kwargs: Any) -> dict[str, Any]:
    """The geographic arguments a connector method actually accepts.

    A connector is free to ignore the geographic filter, but it must never
    crash because the caller offered it a keyword it does not know.  Only
    the declared parameters are forwarded, so a third-party connector keeps
    working exactly as before.
    """
    try:
        parameters = inspect.signature(method).parameters
    except (TypeError, ValueError):
        return {}
    if any(parameter.kind is inspect.Parameter.VAR_KEYWORD for parameter in parameters.values()):
        return dict(kwargs)
    return {key: value for key, value in kwargs.items() if key in parameters}


def connector_geo_kwargs(connector: Any, **kwargs: Any) -> dict[str, Any]:
    """The geographic arguments a connector's exploration entry point accepts."""
    return callable_geo_kwargs(connector.discover_internships, **kwargs)


def discover_stage_offers(
    connectors: dict[str, Any] | list[dict[str, Any]],
    sources: list[dict[str, Any]] | None = None,
    *,
    selection_brief: dict[str, Any] | None = None,
    countries_exclude: list[str] | tuple[str, ...] | None = None,
    countries_include: list[str] | tuple[str, ...] | None = None,
    deadline: float | None = None,
) -> list[dict[str, Any]] | tuple[list[dict[str, Any]], "DedupReport"]:
    """Read every configured source and return the offers they publish.

    This is the single entry point of the internship explorer.  The excluded
    countries are forwarded to each connector, which applies them on its own
    side of the boundary: an excluded country is never materialised here and
    never reaches the local database.  ``countries_exclude`` defaults to
    France, the one country the person never wants.
    """
    if sources is None:
        if not isinstance(connectors, list):
            raise TypeError("sources is required when connectors is a mapping")
        return _deduplicate_stage_offers(connectors)
    if not isinstance(connectors, dict):
        raise TypeError("connectors must be a mapping when sources are provided")
    excluded = list(DEFAULT_COUNTRIES_EXCLUDE) if countries_exclude is None else list(countries_exclude)
    included = list(countries_include) if countries_include is not None else []
    brief = validate_brief(selection_brief) if selection_brief is not None else default_brief()
    offers: list[dict[str, Any]] = []
    for source in sources:
        provider = clean_text(source.get("provider"), limit=40)
        connector = connectors.get(provider)
        if connector is None or not callable(getattr(connector, "discover_internships", None)):
            continue
        if provider == "greenhouse":
            descriptor: Any = GreenhouseBoard(
                id=clean_text(source.get("id"), limit=160),
                company=clean_text(source.get("company"), limit=240),
                board_token=parse_greenhouse_board_token(source.get("board_token")),
            )
        else:
            descriptor = source
        geo_kwargs = connector_geo_kwargs(
            connector, countries_exclude=excluded, countries_include=included
        )
        payload = connector.discover_internships(
            descriptor, selection_brief=brief, deadline=deadline, **geo_kwargs
        )
        for job in getattr(payload, "jobs", ()):  # a connector returns a bounded tuple
            offers.append(job)
    return offers
