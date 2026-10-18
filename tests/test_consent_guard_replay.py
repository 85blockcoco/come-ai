"""Tests de consommation unique et de rejeu.

Exigences vérifiées :

* un accord autorise **une** transmission, jamais deux ;

* le rejeu est refusé, que ce soit via ``check`` ou ``consume`` ;

* la consommation est atomique : deux threads concurrents sur le même accord
  ne peuvent pas réussir tous les deux ;

* l'expéditeur de l'intégrateur n'est jamais appelé deux fois ;

* le reçu de consommation prouve l'usage sans révéler le contenu.
"""

from __future__ import annotations

import threading
from datetime import datetime, timezone
from typing import Any

import pytest

from consent_guard import (
    CODE_CONSUMED_CONSENT,
    ConsentEnvelope,
    ConsentGuard,
    ConsumedConsentError,
    TransmissionReceipt,
    transmit,
)
from consent_guard.guard import CloudTransport

MARKER = "MARQUEUR-SYNTHETIQUE-1E77"
PROVIDER = "gemini"
MODEL = "gemini-3.8-flash"
PURPOSE = "exam_revision"
PAYLOAD = {"marker": MARKER, "items": ["a", "b"]}
FIXED_NOW = datetime(2026, 10, 14, 9, 0, 0, tzinfo=timezone.utc)


class SpyTransport:
    """Transport fictif : il compte les appels et n'en fait aucun."""

    name = "spy"

    def __init__(self) -> None:
        self.calls: list[int] = []

    def send(self, payload: bytes, receipt: TransmissionReceipt) -> dict[str, Any]:
        self.calls.append(len(payload))
        return {"answer": "réponse fictive", "bytes": len(payload), "receipt": receipt.consent_id}


def test_transport_protocol_is_satisfied_by_a_simple_object() -> None:
    assert isinstance(SpyTransport(), CloudTransport)


@pytest.fixture()
def guard(tmp_path) -> ConsentGuard:
    instance = ConsentGuard(tmp_path, clock=lambda: FIXED_NOW)
    yield instance
    instance.close()


@pytest.fixture()
def transport() -> SpyTransport:
    return SpyTransport()


def _grant(guard: ConsentGuard, **overrides: object) -> ConsentEnvelope:
    return guard.grant(provider=PROVIDER, model=MODEL, purpose=PURPOSE, payload=dict(PAYLOAD), **overrides)  # type: ignore[arg-type]


# --- Usage unique ----------------------------------------------------------


def test_the_first_transmission_is_allowed(guard: ConsentGuard, transport: SpyTransport) -> None:
    grant = _grant(guard)
    response = transmit(
        guard,
        grant.consent_id,
        provider=PROVIDER,
        model=MODEL,
        purpose=PURPOSE,
        payload=dict(PAYLOAD),
        sender=transport,
    )
    assert response["bytes"] > 0
    assert transport.calls == [response["bytes"]]


def test_the_replay_is_refused(guard: ConsentGuard, transport: SpyTransport) -> None:
    grant = _grant(guard)
    transmit(
        guard,
        grant.consent_id,
        provider=PROVIDER,
        model=MODEL,
        purpose=PURPOSE,
        payload=dict(PAYLOAD),
        sender=transport,
    )
    decision = guard.check(
        grant.consent_id, provider=PROVIDER, model=MODEL, purpose=PURPOSE, payload=dict(PAYLOAD)
    )
    assert decision.code == CODE_CONSUMED_CONSENT
    with pytest.raises(ConsumedConsentError) as caught:
        transmit(
            guard,
            grant.consent_id,
            provider=PROVIDER,
            model=MODEL,
            purpose=PURPOSE,
            payload=dict(PAYLOAD),
            sender=transport,
        )
    assert caught.value.code == CODE_CONSUMED_CONSENT
    assert transport.calls and len(transport.calls) == 1


def test_a_replay_with_the_very_same_bytes_is_refused(guard: ConsentGuard) -> None:
    grant = _grant(guard)
    first = guard.consume(
        grant.consent_id, provider=PROVIDER, model=MODEL, purpose=PURPOSE, payload=dict(PAYLOAD)
    )
    with pytest.raises(ConsumedConsentError):
        guard.consume(
            grant.consent_id, provider=PROVIDER, model=MODEL, purpose=PURPOSE, payload=dict(PAYLOAD)
        )
    assert first.consent_id == grant.consent_id
    assert guard.get(grant.consent_id).uses_consumed == 1


def test_a_used_agreement_is_not_listed_as_active(guard: ConsentGuard) -> None:
    grant = _grant(guard)
    guard.consume(grant.consent_id, provider=PROVIDER, model=MODEL, purpose=PURPOSE, payload=dict(PAYLOAD))
    assert guard.active() == ()


# --- Atomicité -------------------------------------------------------------


def test_concurrent_consumption_allows_exactly_one(guard: ConsentGuard) -> None:
    grant = _grant(guard)
    outcomes: list[bool] = []
    errors: list[Exception] = []
    lock = threading.Lock()
    start = threading.Barrier(8)

    def worker() -> None:
        start.wait()
        try:
            guard.consume(
                grant.consent_id, provider=PROVIDER, model=MODEL, purpose=PURPOSE, payload=dict(PAYLOAD)
            )
            outcome = True
        except ConsumedConsentError as error:
            outcome = False
            with lock:
                errors.append(error)
        except Exception as error:  # pragma: no cover - garde-fou de test
            with lock:
                errors.append(error)
            outcome = False
        with lock:
            outcomes.append(outcome)

    threads = [threading.Thread(target=worker) for _ in range(8)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert outcomes.count(True) == 1
    assert len(errors) == 7
    assert all(isinstance(error, ConsumedConsentError) for error in errors)
    assert guard.get(grant.consent_id).uses_consumed == 1


def test_concurrent_transmissions_call_the_sender_once(guard: ConsentGuard, transport: SpyTransport) -> None:
    grant = _grant(guard)
    start = threading.Barrier(6)
    statuses: list[str] = []
    refusals: list[Exception] = []
    lock = threading.Lock()

    def worker() -> None:
        start.wait()
        try:
            transmit(
                guard,
                grant.consent_id,
                provider=PROVIDER,
                model=MODEL,
                purpose=PURPOSE,
                payload=dict(PAYLOAD),
                sender=transport,
            )
            status = "transmitted"
        except Exception as error:  # noqa: BLE001 - on compte les refus, quoi qu'ils soient
            status = "refused"
            with lock:
                refusals.append(error)
        with lock:
            statuses.append(status)

    threads = [threading.Thread(target=worker) for _ in range(6)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert statuses.count("transmitted") == 1
    assert len(transport.calls) == 1
    assert len(refusals) == 5
    assert guard.get(grant.consent_id).uses_consumed == 1


# --- Reçu ------------------------------------------------------------------


def test_the_receipt_carries_no_content(guard: ConsentGuard) -> None:
    grant = _grant(guard)
    receipt = guard.consume(
        grant.consent_id, provider=PROVIDER, model=MODEL, purpose=PURPOSE, payload=dict(PAYLOAD)
    )
    payload = receipt.as_dict()
    assert payload["payload_digest"] == grant.payload_digest
    assert MARKER not in repr(payload)
    assert receipt.payload_digest != ""
    assert receipt.payload_bytes > 0


def test_each_receipt_has_a_distinct_identifier(guard: ConsentGuard) -> None:
    first = _grant(guard)
    second = _grant(guard)
    one = guard.consume(first.consent_id, provider=PROVIDER, model=MODEL, purpose=PURPOSE, payload=dict(PAYLOAD))
    two = guard.consume(second.consent_id, provider=PROVIDER, model=MODEL, purpose=PURPOSE, payload=dict(PAYLOAD))
    assert one.transmission_id != two.transmission_id
    assert one.payload_digest == two.payload_digest
