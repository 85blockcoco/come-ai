"""Tests du cycle de vie d'un accord : octroi, consommation, révocation.

Exigences vérifiées :

* un accord est octroyé pour une seule transmission, jamais plus ;
* le contenu n'entre jamais dans la base locale : empreinte et taille seule ;
* la base et ses journaux restent privés (``0600``, dossier ``0700``) ;
* la révocation est explicite, tracée et définitive ;
* un accord consommé ne peut plus être révoqué ni réutilisé ;
* la persistance survit à une relance à froid du garde-fou ;
* l'effacement complet supprime accords et journal.
"""

from __future__ import annotations

import os
from datetime import datetime, timezone

import pytest

from consent_guard import (
    STATE_GRANTED,
    STATE_REVOKED,
    STATE_USED,
    ConsentEnvelope,
    ConsentGuard,
    ConsentStore,
)
from consent_guard.errors import ConsentRefusal, StoreError, UnknownConsentError

MARKER = "MARQUEUR-SYNTHETIQUE-3C88"
PROVIDER = "gemini"
MODEL = "gemini-3.8-flash"
PURPOSE = "exam_revision"
PAYLOAD = {"marker": MARKER, "items": ["a", "b"]}
FIXED_NOW = datetime(2026, 10, 14, 9, 0, 0, tzinfo=timezone.utc)


@pytest.fixture()
def guard(tmp_path) -> ConsentGuard:
    instance = ConsentGuard(tmp_path, clock=lambda: FIXED_NOW)
    yield instance
    instance.close()


def _grant(guard: ConsentGuard, **overrides: object) -> ConsentEnvelope:
    return guard.grant(
        provider=PROVIDER, model=MODEL, purpose=PURPOSE, payload=dict(PAYLOAD), **overrides  # type: ignore[arg-type]
    )


# --- Octroi ----------------------------------------------------------------


def test_grant_creates_a_single_use_agreement(guard: ConsentGuard) -> None:
    grant = guard.grant(provider=PROVIDER, model=MODEL, purpose=PURPOSE, payload=dict(PAYLOAD))
    assert grant.state == STATE_GRANTED
    assert grant.uses_allowed == 1
    assert grant.uses_consumed == 0
    assert grant.expires_at == "2026-10-14T09:15:00Z"
    assert grant.consent_id.startswith("cgt_")


def test_grant_accepts_an_explicit_consent_id(guard: ConsentGuard) -> None:
    identifier = "cgt_" + "b" * 32
    grant = guard.grant(
        provider=PROVIDER, model=MODEL, purpose=PURPOSE, payload=dict(PAYLOAD), consent_id=identifier
    )
    assert grant.consent_id == identifier
    assert guard.get(identifier) == grant


def test_grant_refuses_a_duplicated_identifier(guard: ConsentGuard) -> None:
    identifier = "cgt_" + "c" * 32
    guard.grant(
        provider=PROVIDER, model=MODEL, purpose=PURPOSE, payload=dict(PAYLOAD), consent_id=identifier
    )
    with pytest.raises(StoreError):
        guard.grant(
            provider=PROVIDER, model=MODEL, purpose=PURPOSE, payload=dict(PAYLOAD), consent_id=identifier
        )


def test_grant_refuses_an_invalid_request_without_writing(guard: ConsentGuard) -> None:
    with pytest.raises(ValueError):
        guard.grant(provider="", model=MODEL, purpose=PURPOSE, payload=dict(PAYLOAD))
    with pytest.raises(ValueError):
        guard.grant(provider=PROVIDER, model="", purpose=PURPOSE, payload=dict(PAYLOAD))
    with pytest.raises(ValueError):
        guard.grant(provider=PROVIDER, model=MODEL, purpose="inconnu", payload=dict(PAYLOAD))
    assert guard.stats()["consents"] == {}


def test_grant_bounds_the_validity_period(guard: ConsentGuard) -> None:
    with pytest.raises(ValueError):
        guard.grant(provider=PROVIDER, model=MODEL, purpose=PURPOSE, payload=dict(PAYLOAD), ttl_seconds=0)
    with pytest.raises(ValueError):
        guard.grant(provider=PROVIDER, model=MODEL, purpose=PURPOSE, payload=dict(PAYLOAD), ttl_seconds=90_000)


def test_grant_truncates_the_free_note(guard: ConsentGuard) -> None:
    grant = guard.grant(
        provider=PROVIDER, model=MODEL, purpose=PURPOSE, payload=dict(PAYLOAD), note="n" * 500
    )
    assert len(grant.note) == 200


# --- Consommation ----------------------------------------------------------


def test_consume_returns_a_receipt_without_the_content(guard: ConsentGuard) -> None:
    grant = _grant(guard)
    receipt = guard.consume(
        grant.consent_id, provider=PROVIDER, model=MODEL, purpose=PURPOSE, payload=dict(PAYLOAD)
    )
    assert receipt.consent_id == grant.consent_id
    assert receipt.provider == PROVIDER
    assert receipt.model == MODEL
    assert receipt.purpose == PURPOSE
    assert receipt.payload_digest == grant.payload_digest
    assert receipt.payload_bytes == grant.payload_bytes
    assert receipt.consumed_at == "2026-10-14T09:00:00Z"
    assert receipt.transmission_id.startswith("trm_")
    assert MARKER not in repr(receipt)
    assert MARKER not in repr(receipt.as_dict())


def test_consume_marks_the_agreement_as_used(guard: ConsentGuard) -> None:
    grant = _grant(guard)
    guard.consume(grant.consent_id, provider=PROVIDER, model=MODEL, purpose=PURPOSE, payload=dict(PAYLOAD))
    refreshed = guard.get(grant.consent_id)
    assert refreshed.state == STATE_USED
    assert refreshed.uses_consumed == 1
    assert refreshed.consumed_at == "2026-10-14T09:00:00Z"


def test_consume_on_an_unknown_identifier_raises(guard: ConsentGuard) -> None:
    with pytest.raises(UnknownConsentError) as caught:
        guard.consume("cgt_" + "d" * 32, provider=PROVIDER, model=MODEL, purpose=PURPOSE, payload=dict(PAYLOAD))
    assert caught.value.code == "consent_unknown"


def test_consume_never_leaves_a_half_consumed_agreement(guard: ConsentGuard) -> None:
    grant = _grant(guard)
    with pytest.raises(ConsentRefusal):
        guard.consume(grant.consent_id, provider="openrouter", model=MODEL, purpose=PURPOSE, payload=dict(PAYLOAD))
    assert guard.get(grant.consent_id).uses_consumed == 0
    assert guard.get(grant.consent_id).state == STATE_GRANTED


# --- Révocation ------------------------------------------------------------


def test_revoke_blocks_a_granted_agreement(guard: ConsentGuard) -> None:
    grant = _grant(guard)
    revoked = guard.revoke(grant.consent_id, actor="come")
    assert revoked.state == STATE_REVOKED
    decision = guard.check(grant.consent_id, provider=PROVIDER, model=MODEL, purpose=PURPOSE, payload=dict(PAYLOAD))
    assert decision.code == "consent_revoked"


def test_revoke_of_an_unknown_agreement_raises(guard: ConsentGuard) -> None:
    with pytest.raises(UnknownConsentError):
        guard.revoke("cgt_" + "e" * 32)


def test_a_consumed_agreement_cannot_be_revoked(guard: ConsentGuard) -> None:
    grant = _grant(guard)
    guard.consume(grant.consent_id, provider=PROVIDER, model=MODEL, purpose=PURPOSE, payload=dict(PAYLOAD))
    with pytest.raises(StoreError):
        guard.revoke(grant.consent_id)


def test_a_revoked_agreement_cannot_be_revoked_twice(guard: ConsentGuard) -> None:
    grant = _grant(guard)
    guard.revoke(grant.consent_id)
    with pytest.raises(StoreError):
        guard.revoke(grant.consent_id)


# --- Listing ---------------------------------------------------------------


def test_active_lists_only_usable_agreements(tmp_path) -> None:
    moments = [datetime(2026, 10, 14, 9, 0, 0, tzinfo=timezone.utc)]
    guard = ConsentGuard(tmp_path, clock=lambda: moments[0])
    usable = _grant(guard, ttl_seconds=86_400)
    revoked = _grant(guard)
    consumed = _grant(guard)
    expired = _grant(guard)
    guard.revoke(revoked.consent_id)
    guard.consume(
        consumed.consent_id, provider=PROVIDER, model=MODEL, purpose=PURPOSE, payload=dict(PAYLOAD)
    )
    moments[0] = datetime(2026, 10, 14, 12, 0, 0, tzinfo=timezone.utc)
    active = {item.consent_id for item in guard.active()}
    assert active == {usable.consent_id}
    assert guard.active() == (usable,)
    assert guard.get(expired.consent_id).is_expired()
    assert not guard.get(usable.consent_id).is_expired(moments[0])
    guard.close()


def test_list_consents_orders_by_issue_then_identifier(tmp_path) -> None:
    moments = [datetime(2026, 10, 14, 9, 0, 0, tzinfo=timezone.utc)]
    guard = ConsentGuard(tmp_path, clock=lambda: moments[0])
    first = _grant(guard)
    moments[0] = datetime(2026, 10, 14, 9, 5, 0, tzinfo=timezone.utc)
    second = _grant(guard)
    listed = guard.store.list_consents()
    assert [item.consent_id for item in listed] == [second.consent_id, first.consent_id]
    assert listed == guard.store.list_consents()
    guard.close()


# --- Persistance et vie privée --------------------------------------------


def test_the_content_is_never_written_to_disk(tmp_path) -> None:
    guard = ConsentGuard(tmp_path, clock=lambda: FIXED_NOW)
    grant = _grant(guard)
    guard.consume(grant.consent_id, provider=PROVIDER, model=MODEL, purpose=PURPOSE, payload=dict(PAYLOAD))
    guard.revoke(_grant(guard).consent_id)
    for suffix in ("", "-wal", "-shm"):
        candidate = tmp_path / f"consent_guard.sqlite3{suffix}"
        if candidate.exists():
            assert MARKER.encode("utf-8") not in candidate.read_bytes()
    guard.close()


def test_the_database_and_journals_stay_private(tmp_path) -> None:
    store = ConsentStore(tmp_path)
    store.insert(
        ConsentEnvelope(
            consent_id="cgt_" + "f" * 32,
            provider=PROVIDER,
            model=MODEL,
            purpose=PURPOSE,
            payload_digest="0" * 64,
            payload_bytes=12,
            issued_at="2026-10-14T09:00:00Z",
            expires_at="2026-10-14T09:15:00Z",
        )
    )
    store.close()
    assert os.stat(tmp_path).st_mode & 0o777 == 0o700
    for suffix in ("", "-wal", "-shm"):
        candidate = tmp_path / f"consent_guard.sqlite3{suffix}"
        if candidate.exists():
            assert os.stat(candidate).st_mode & 0o777 == 0o600


def test_no_absolute_path_is_stored(tmp_path) -> None:
    guard = ConsentGuard(tmp_path, clock=lambda: FIXED_NOW)
    grant = _grant(guard, actor="come", note="note de test")
    serialised = repr(grant.as_dict())
    assert str(tmp_path) not in serialised
    assert "/Users/" not in serialised
    guard.close()


def test_a_cold_restart_reloads_the_agreements(tmp_path) -> None:
    first = ConsentGuard(tmp_path, clock=lambda: FIXED_NOW)
    grant = _grant(first)
    first.close()
    second = ConsentGuard(tmp_path, clock=lambda: FIXED_NOW)
    reloaded = second.get(grant.consent_id)
    assert reloaded is not None
    assert reloaded.payload_digest == grant.payload_digest
    assert second.check(grant.consent_id, provider=PROVIDER, model=MODEL, purpose=PURPOSE, payload=dict(PAYLOAD)).allowed
    second.close()


def test_forget_everything_clears_agreements_and_journal(guard: ConsentGuard) -> None:
    grant = _grant(guard)
    guard.check("cgt_" + "0" * 32, provider=PROVIDER, model=MODEL, purpose=PURPOSE, payload=dict(PAYLOAD))
    assert guard.stats()["refusals"] >= 1
    assert guard.forget_everything()
    assert guard.stats() == {"consents": {}, "refusals": 0, "db_name": "consent_guard.sqlite3", "schema_version": 1}
    assert guard.get(grant.consent_id) is None
    assert guard.journal() == ()


def test_stats_report_the_states(guard: ConsentGuard) -> None:
    grant = _grant(guard)
    guard.revoke(_grant(guard).consent_id)
    guard.consume(grant.consent_id, provider=PROVIDER, model=MODEL, purpose=PURPOSE, payload=dict(PAYLOAD))
    assert guard.stats()["consents"] == {STATE_USED: 1, STATE_REVOKED: 1}
