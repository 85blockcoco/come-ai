"""Smoke test recorder for HTTP endpoints (N100-J07).

A tiny deterministic client-contract module: given canned HTTP responses it
validates status/body invariants per endpoint.  Real requests (if used) are
always against localhost, bounded, read-only (GET).
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Callable, Mapping

OK_CODES = (200, 204)
EXPECTED = {
    "GET /": OK_CODES,
    "GET /api/health": OK_CODES,
    "GET /career": OK_CODES + (404,),
    "GET /api/career/offers": OK_CODES + (404,),
    "GET /static/app.js": OK_CODES + (404,),
}


@dataclass
class SmokeResult:
    endpoint: str
    ok: bool
    status: int | None = None
    error: str | None = None
    payload_keys: list[str] = field(default_factory=list)


def check_endpoint(endpoint: str, response: Mapping[str, Any]) -> SmokeResult:
    """Better no data than bad data."""
    allowed = EXPECTED.get(endpoint)
    if allowed is None:
        return SmokeResult(endpoint=endpoint, ok=False, error="endpoint inconnu (pas dans le contrat, refusé)")
    status = response.get("status")
    if status not in allowed and status is not None:
        return SmokeResult(endpoint=endpoint, ok=False, status=status, error=f"status {status} inattendu (attendus {allowed})")
    ok = True
    try:
        body = response.get("body")
        keys = list(body.keys()) if isinstance(body, Mapping) else []
    except (AttributeError, TypeError):
        ok, keys = False, []
    return SmokeResult(endpoint=endpoint, ok=ok, status=status, payload_keys=keys)


def run_smoke(client: Callable[[str], Mapping[str, Any]], endpoints: list[str] | tuple[str, ...] | None = None) -> list[SmokeResult]:
    eps = list(endpoints) if endpoints else list(EXPECTED)
    return [check_endpoint(ep, client(ep)) for ep in eps]


def to_dict(r: SmokeResult) -> dict[str, Any]:
    return asdict(r)
