"""Tests d'expiration d'un accord.

Exigences vérifiées :

* un accord émis avec une durée de validité n'est utilisable que pendant
  celle-ci ;

* la frontière est inclusive : à l'instant d'expiration exact, l'accord est
  déjà expiré ;

* un accord expiré n'est jamais réanimé : il faut un nouvel accord ;

* la durée de validité est bornée par un plafond, et ne peut pas être nulle ;

* ``check`` et ``consume`` disent la même chose, sans appel réseau.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from consent_guard import (
    CODE_EXPIRED_CONSENT,
    ConsentGuard,
    ExpiredConsentError,
    TransmissionRequest,
)
from consent_guard.envelope import MAX_TTL_SECONDS, resolve_expiry
from consent_guard.errors import EnvelopeError

MARKER = "MARQUEUR-SYNTHETIQUE-5D14"
PROVIDER = "gemini"
MODEL = "gemini-3.8-flash"
PURPOSE = "exam_revision"
PAYLOAD = {"marker": MARKER, "items": ["a"]}
START = datetime(2026, 10, 14, 9, 0, 0, tzinfo=timezone.utc)


class Clock:
    """Horloge injectable et avance manuellement."""

    def __init__(self, start: datetime) -> None:
        self.now = start

    def __call__(self) -> datetime:
        return self.now

    def advance(self, seconds: int) -> None:
        self.now = self.now + timedelta(seconds=seconds)


@pytest.fixture()
def clock() -> Clock:
    return Clock(START)


@pytest.fixture()
def guard(tmp_path, clock: Clock) -> ConsentGuard:
    instance = ConsentGuard(tmp_path, clock=clock)
    yield instance
    instance.close()


def _grant(guard: ConsentGuard, **overrides: object) -> object:
    return guard.grant(provider=PROVIDER, model=MODEL, purpose=PURPOSE, payload=dict(PAYLOAD), **overrides)  # type: ignore[arg-type]


def _request(**overrides: object) -> TransmissionRequest:
    return TransmissionRequest(
        provider=PROVIDER, model=MODEL, purpose=PURPOSE, payload=dict(PAYLOAD), **overrides  # type: ignore[arg-type]
    )


def test_an_agreement_is_usable_before_its_expiry(guard: ConsentGuard, clock: Clock) -> None:
    grant = _grant(guard, ttl_seconds=600)
    clock.advance(599)
    decision = guard.check(grant.consent_id, request=_request())
    assert decision.allowed
    assert guard.consume(grant.consent_id, request=_request()).consent_id == grant.consent_id


def test_an_agreement_expires_at_the_exact_boundary(guard: ConsentGuard, clock: Clock) -> None:
    grant = _grant(guard, ttl_seconds=600)
    clock.advance(600)
    decision = guard.check(grant.consent_id, request=_request())
    assert not decision.allowed
    assert decision.code == CODE_EXPIRED_CONSENT
    assert decision.fallback == "local_engine"


def test_consume_after_expiry_raises(guard: ConsentGuard, clock: Clock) -> None:
    grant = _grant(guard, ttl_seconds=60)
    clock.advance(61)
    with pytest.raises(ExpiredConsentError) as caught:
        guard.consume(grant.consent_id, request=_request())
    assert caught.value.code == CODE_EXPIRED_CONSENT
    assert caught.value.fallback == "local_engine"
    assert guard.get(grant.consent_id).uses_consumed == 0


def test_an_expired_agreement_is_not_resurrected(guard: ConsentGuard, clock: Clock) -> None:
    """L'expiration ne se répare pas toute seule et ne consomme rien."""

    grant = _grant(guard, ttl_seconds=60)
    clock.advance(120)
    with pytest.raises(ExpiredConsentError):
        guard.consume(grant.consent_id, request=_request())
    clock.advance(600)
    with pytest.raises(ExpiredConsentError):
        guard.consume(grant.consent_id, request=_request())
    stored = guard.get(grant.consent_id)
    assert stored.uses_consumed == 0
    assert stored.state == "granted"
    assert guard.store.mark_expired(now=clock.now) == 1
    assert guard.get(grant.consent_id).state == "revoked"


def test_a_fresh_agreement_is_needed_after_expiry(guard: ConsentGuard, clock: Clock) -> None:
    expired = _grant(guard, ttl_seconds=60)
    clock.advance(120)
    assert guard.check(expired.consent_id, request=_request()).code == CODE_EXPIRED_CONSENT
    fresh = _grant(guard, ttl_seconds=600)
    assert guard.check(fresh.consent_id, request=_request()).allowed


def test_expiry_is_evaluated_against_the_injected_clock(guard: ConsentGuard, clock: Clock) -> None:
    grant = _grant(guard, ttl_seconds=60)
    assert guard.check(grant.consent_id, request=_request(), now=START + timedelta(seconds=59)).allowed
    assert guard.check(grant.consent_id, request=_request(), now=START + timedelta(seconds=61)).code == (
        CODE_EXPIRED_CONSENT
    )


def test_expiry_is_independent_of_the_default_ttl(guard: ConsentGuard) -> None:
    grant = guard.grant(
        provider=PROVIDER,
        model=MODEL,
        purpose=PURPOSE,
        payload=dict(PAYLOAD),
        expires_at="2026-10-14T09:00:30Z",
    )
    assert guard.check(
        grant.consent_id, request=_request(), now=datetime(2026, 10, 14, 9, 0, 29, tzinfo=timezone.utc)
    ).allowed
    assert guard.check(
        grant.consent_id, request=_request(), now=datetime(2026, 10, 14, 9, 0, 31, tzinfo=timezone.utc)
    ).code == CODE_EXPIRED_CONSENT


def test_the_ttl_ceiling_is_enforced(guard: ConsentGuard) -> None:
    with pytest.raises(EnvelopeError):
        _grant(guard, ttl_seconds=MAX_TTL_SECONDS + 1)
    assert _grant(guard, ttl_seconds=MAX_TTL_SECONDS).expires_at == "2026-10-15T09:00:00Z"


def test_mark_expired_revokes_only_granted_agreements(guard: ConsentGuard, clock: Clock) -> None:
    spent = _grant(guard, ttl_seconds=60)
    guard.consume(spent.consent_id, request=_request())
    pending = _grant(guard, ttl_seconds=60)
    clock.advance(120)
    assert guard.store.mark_expired(now=clock.now) == 1
    assert guard.get(spent.consent_id).state == "used"
    assert guard.get(pending.consent_id).state == "revoked"


def test_resolve_expiry_accepts_a_far_but_bounded_future() -> None:
    assert resolve_expiry(ttl_seconds=MAX_TTL_SECONDS, now=START) == "2026-10-15T09:00:00Z"


def test_expired_refusals_are_journalised_without_content(guard: ConsentGuard, clock: Clock) -> None:
    grant = _grant(guard, ttl_seconds=60)
    clock.advance(120)
    guard.check(grant.consent_id, request=_request())
    entries = guard.journal()
    assert entries[-1].code == CODE_EXPIRED_CONSENT
    assert entries[-1].consent_id == grant.consent_id
    assert MARKER not in repr(entries)
    assert guard.db_path.read_bytes().find(MARKER.encode("utf-8")) == -1
