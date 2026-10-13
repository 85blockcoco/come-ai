"""Bounded, read-only Greenhouse public-job-board discovery.

This is deliberately a narrow integration: it reads an explicitly configured
public Greenhouse board after a person presses the search button.  It never
performs a general web search, follows an arbitrary URL, logs in, reads
LinkedIn, or submits an application.  The transport is injectable, so all
tests remain offline.
"""

from __future__ import annotations

import html
import json
import re
import socket
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timezone
from html.parser import HTMLParser
from typing import Any, Protocol

from workspace_core import UserFacingError

from .models import clean_text


GREENHOUSE_HOST = "boards-api.greenhouse.io"
GREENHOUSE_TIMEOUT_SECONDS = 8
GREENHOUSE_MAX_RESPONSE_BYTES = 4 * 1024 * 1024
GREENHOUSE_MAX_JOBS = 150
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
        self._opener = urllib.request.build_opener(_NoRedirect())

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


def _location_parts(value: Any) -> tuple[str, str]:
    location = clean_text(value, limit=300)
    if not location:
        return "", ""
    pieces = [piece.strip() for piece in re.split(r"\s*[,|/]\s*", location) if piece.strip()]
    if len(pieces) >= 2:
        return clean_text(pieces[0], limit=160), clean_text(pieces[-1], limit=120)
    return clean_text(location, limit=160), ""


class GreenhouseJobBoardConnector:
    """Read published openings from one known board, with one capped retry."""

    def __init__(self, transport: GreenhouseTransport | None = None) -> None:
        self.transport = transport or UrllibGreenhouseTransport()

    def discover(self, board: GreenhouseBoard) -> DiscoveryPayload:
        error: PublicSourceError | None = None
        for attempt in range(2):
            try:
                payload = self.transport.get_json(board.endpoint, GREENHOUSE_TIMEOUT_SECONDS)
                return self._normalise(board, payload)
            except PublicSourceError as caught:
                error = caught
                if not caught.retryable or attempt:
                    raise
                # One small retry accommodates temporary 429/503/network
                # failures without turning a refresh button into a loop.
                time.sleep(0.35)
        assert error is not None
        raise error

    @staticmethod
    def _normalise(board: GreenhouseBoard, payload: Any) -> DiscoveryPayload:
        if not isinstance(payload, dict) or not isinstance(payload.get("jobs"), list):
            raise PublicSourceError("Greenhouse a renvoyé un format d’offres inattendu.", code="invalid_payload")
        raw_jobs = payload["jobs"]
        jobs: list[dict[str, Any]] = []
        for raw in raw_jobs[:GREENHOUSE_MAX_JOBS]:
            if not isinstance(raw, dict):
                continue
            job_id = clean_text(raw.get("id"), limit=240)
            title = clean_text(raw.get("title"), limit=300)
            official_url = clean_text(raw.get("absolute_url"), limit=2_000)
            if not job_id or not title or not official_url:
                continue
            location = raw.get("location") if isinstance(raw.get("location"), dict) else {}
            city, country = _location_parts(location.get("name"))
            jobs.append(
                {
                    "company": board.company,
                    "title": title,
                    "source_name": "greenhouse",
                    "source_id": job_id,
                    "official_url": official_url,
                    "city": city,
                    "country": country,
                    # ``updated_at`` is source maintenance metadata, not a
                    # posting or internship date.  We deliberately leave the
                    # calendar unknown unless the ATS exposes it structurally.
                    "posted_date": "",
                    "deadline_date": "",
                    "start_date": "",
                    "end_date": "",
                    "duration_months": None,
                    "source_status": "open",
                    "employment_type": "",
                    "role_level": "",
                    "requirements": "",
                    "languages_required": "",
                    "eligibility_requirement": "",
                    "description_original": source_html_to_text(raw.get("content")),
                }
            )
        return DiscoveryPayload(
            jobs=tuple(jobs),
            verified_at=datetime.now(timezone.utc).isoformat(timespec="microseconds"),
            truncated=len(raw_jobs) > GREENHOUSE_MAX_JOBS,
        )
