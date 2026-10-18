"""Tests de refus hors ligne, de repli local et d'absence de fuite.

Exigences vérifiées :

* tout refus est décidé **avant** tout contact avec un fournisseur : aucun
  socket, aucune clé, aucun catalogue de modèles ;

* ``check`` ne lève jamais pour un refus : l'appelant peut choisir son repli ;

* le repli recommandé est toujours le moteur local déterministe ;

* le journal des refus et la base locale ne contiennent que des codes, des
  champs et des horodatages — jamais le contenu personnel ;

* le paquet n'émet aucun journal de log, et ne lit aucun fichier de
  configuration.
"""

from __future__ import annotations

import logging
import socket
from datetime import datetime, timezone

import pytest

from consent_guard import (
    FALLBACK_LOCAL,
    REFUSAL_CODES,
    ConsentGuard,
    ConsentGuardError,
    ConsentRefusal,
    TransmissionReceipt,
    fallback_notice,
    transmit,
)
from consent_guard.envelope import MAX_PAYLOAD_BYTES
from consent_guard.errors import INVALID_REQUEST_CODES

MARKER = "MARQUEUR-PERSONNEL-SYNTHETIQUE-4A90"
PROVIDER = "gemini"
MODEL = "gemini-3.8-flash"
PURPOSE = "exam_revision"
PAYLOAD = {"marker": MARKER, "items": ["élément synthétique un", "élément synthétique deux"]}
FIXED_NOW = datetime(2026, 10, 14, 9, 0, 0, tzinfo=timezone.utc)


class ExplodingTransport:
    """Transport interdit : s'il est appelé, le test échoue immédiatement."""

    name = "interdit"

    def send(self, payload: bytes, receipt: TransmissionReceipt) -> object:
        raise AssertionError("Aucun transport ne doit être appelé après un refus.")


class SpyTransport:
    """Transport fictif qui compte ses appels."""

    name = "spy"

    def __init__(self) -> None:
        self.calls = 0

    def send(self, payload: bytes, receipt: TransmissionReceipt) -> dict[str, object]:
        self.calls += 1
        return {"answer": "réponse fictive", "bytes": len(payload)}


@pytest.fixture()
def guard(tmp_path) -> ConsentGuard:
    instance = ConsentGuard(tmp_path, clock=lambda: FIXED_NOW)
    yield instance
    instance.close()


def _grant(guard: ConsentGuard, **overrides: object) -> object:
    return guard.grant(provider=PROVIDER, model=MODEL, purpose=PURPOSE, payload=dict(PAYLOAD), **overrides)  # type: ignore[arg-type]


# --- Refus sans appel réseau ------------------------------------------------


def test_no_socket_is_ever_opened(guard: ConsentGuard, monkeypatch: pytest.MonkeyPatch) -> None:
    def _forbidden(*args: object, **kwargs: object) -> None:
        raise AssertionError("Aucune connexion réseau n'est autorisée dans ce lot.")

    monkeypatch.setattr(socket, "socket", _forbidden)
    monkeypatch.setattr(socket, "create_connection", _forbidden)
    grant = _grant(guard)
    assert guard.check(
        grant.consent_id, provider=PROVIDER, model=MODEL, purpose=PURPOSE, payload=dict(PAYLOAD)
    ).allowed
    assert guard.consume(
        grant.consent_id, provider=PROVIDER, model=MODEL, purpose=PURPOSE, payload=dict(PAYLOAD)
    ).consent_id
    assert guard.revoke(_grant(guard).consent_id).state == "revoked"


def test_a_refused_transmission_never_calls_the_transport(guard: ConsentGuard) -> None:
    transport = ExplodingTransport()
    grant = _grant(guard)
    with pytest.raises(ConsentRefusal):
        transmit(
            guard,
            grant.consent_id,
            provider="openrouter",
            model=MODEL,
            purpose=PURPOSE,
            payload=dict(PAYLOAD),
            sender=transport,
        )
    with pytest.raises(ConsentRefusal):
        transmit(
            guard,
            "cgt_" + "9" * 32,
            provider=PROVIDER,
            model=MODEL,
            purpose=PURPOSE,
            payload=dict(PAYLOAD),
            sender=transport,
        )
    assert guard.get(grant.consent_id).uses_consumed == 0


def test_check_never_raises_for_a_refusal(guard: ConsentGuard) -> None:
    grant = _grant(guard)
    cases: list[dict[str, object]] = [
        {"provider": "openrouter", "model": MODEL, "purpose": PURPOSE, "payload": dict(PAYLOAD)},
        {"provider": PROVIDER, "model": "other-model", "purpose": PURPOSE, "payload": dict(PAYLOAD)},
        {"provider": PROVIDER, "model": MODEL, "purpose": "job_application", "payload": dict(PAYLOAD)},
        {"provider": PROVIDER, "model": MODEL, "purpose": PURPOSE, "payload": {"marker": "autre"}},
    ]
    for case in cases:
        decision = guard.check(grant.consent_id, **case)  # type: ignore[arg-type]
        assert not decision.allowed
        assert decision.code in REFUSAL_CODES
        assert decision.fallback == FALLBACK_LOCAL


def test_an_invalid_request_is_refused_before_any_lookup(guard: ConsentGuard) -> None:
    cases: list[dict[str, object]] = [
        {"provider": "!!!"},
        {"model": "modèle avec espaces"},
        {"purpose": "inconnu"},
        {"payload": ""},
        {"payload": b""},
        {"payload": {"objet": object()}},
        {"payload": 42},
    ]
    for case in cases:
        decision = guard.check("cgt_" + "8" * 32, **case)  # type: ignore[arg-type]
        assert not decision.allowed
        assert decision.code in INVALID_REQUEST_CODES
        assert decision.fallback == FALLBACK_LOCAL
    assert guard.stats()["consents"] == {}


def test_an_oversized_payload_is_refused(guard: ConsentGuard) -> None:
    decision = guard.check(
        "cgt_" + "7" * 32, provider=PROVIDER, model=MODEL, purpose=PURPOSE, payload="x" * (MAX_PAYLOAD_BYTES + 1)
    )
    assert decision.code == "payload_too_large"
    assert decision.code in INVALID_REQUEST_CODES
    with pytest.raises(ConsentGuardError) as caught:
        guard.grant(
            provider=PROVIDER, model=MODEL, purpose=PURPOSE, payload="x" * (MAX_PAYLOAD_BYTES + 1)
        )
    assert caught.value.code == "payload_too_large"


def test_consume_raises_a_refusal_family_for_an_invalid_request(guard: ConsentGuard) -> None:
    with pytest.raises(ConsentRefusal) as caught:
        guard.consume("cgt_" + "6" * 32, provider="!!", model=MODEL, purpose=PURPOSE, payload=dict(PAYLOAD))
    assert caught.value.code == "invalid_request"
    with pytest.raises(ConsentRefusal) as caught:
        guard.consume("cgt_" + "6" * 32, provider=PROVIDER, model=MODEL, purpose=PURPOSE, payload=b"")
    assert caught.value.code == "payload_empty"
    assert {entry.code for entry in guard.journal()} == {"invalid_request", "payload_empty"}


# --- Repli local -----------------------------------------------------------


def test_fallback_notice_is_safe_and_fixed(guard: ConsentGuard) -> None:
    decision = guard.check(
        "cgt_" + "5" * 32, provider=PROVIDER, model=MODEL, purpose=PURPOSE, payload=dict(PAYLOAD)
    )
    notice = fallback_notice(decision)
    assert notice == "Aucune donnée personnelle n'a quitté cet appareil. Motif du refus : consent_unknown. Repli : local_engine."
    assert MARKER not in notice
    assert MODEL not in notice
    assert "élément synthétique" not in notice


def test_an_allowed_decision_has_no_fallback(guard: ConsentGuard) -> None:
    grant = _grant(guard)
    decision = guard.check(
        grant.consent_id, provider=PROVIDER, model=MODEL, purpose=PURPOSE, payload=dict(PAYLOAD)
    )
    assert decision.allowed
    assert decision.fallback == "none"
    assert fallback_notice(decision).startswith("Aucune donnée personnelle")


def test_local_providers_need_no_cloud_agreement() -> None:
    from consent_guard import is_local_provider

    assert is_local_provider("ollama_local")
    assert is_local_provider("ollama")
    assert is_local_provider("local")
    assert not is_local_provider("gemini")
    assert not is_local_provider("openrouter")


def test_the_transport_is_only_called_after_a_success(guard: ConsentGuard) -> None:
    transport = SpyTransport()
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
    with pytest.raises(ConsentRefusal):
        transmit(
            guard,
            grant.consent_id,
            provider=PROVIDER,
            model=MODEL,
            purpose=PURPOSE,
            payload=dict(PAYLOAD),
            sender=transport,
        )
    assert transport.calls == 1


# --- Absence de contenu personnel dans les traces --------------------------


def test_the_package_emits_no_log_record(guard: ConsentGuard, caplog: pytest.LogCaptureFixture) -> None:
    grant = _grant(guard)
    with caplog.at_level(logging.DEBUG):
        guard.check(
            "cgt_" + "4" * 32, provider=PROVIDER, model=MODEL, purpose=PURPOSE, payload=dict(PAYLOAD)
        )
        guard.consume(
            grant.consent_id, provider=PROVIDER, model=MODEL, purpose=PURPOSE, payload=dict(PAYLOAD)
        )
        guard.revoke(_grant(guard).consent_id)
    assert [record for record in caplog.records if record.name.startswith("consent_guard")] == []


def test_the_database_holds_no_personal_content(guard: ConsentGuard) -> None:
    grant = _grant(guard)
    guard.consume(
        grant.consent_id, provider=PROVIDER, model=MODEL, purpose=PURPOSE, payload=dict(PAYLOAD)
    )
    guard.check("cgt_" + "3" * 32, provider=PROVIDER, model=MODEL, purpose=PURPOSE, payload=dict(PAYLOAD))
    for suffix in ("", "-wal", "-shm"):
        candidate = guard.db_path.with_name(guard.db_path.name + suffix)
        if candidate.exists():
            assert MARKER.encode("utf-8") not in candidate.read_bytes()
            assert "élément synthétique".encode("utf-8") not in candidate.read_bytes()


def test_the_journal_holds_codes_and_fields_only(guard: ConsentGuard) -> None:
    grant = _grant(guard)
    guard.check("cgt_" + "2" * 32, provider=PROVIDER, model=MODEL, purpose=PURPOSE, payload=dict(PAYLOAD))
    guard.check(grant.consent_id, provider="openrouter", model=MODEL, purpose=PURPOSE, payload=dict(PAYLOAD))
    journal = guard.journal()
    assert {entry.code for entry in journal} == {"consent_unknown", "envelope_mismatch"}
    assert all(entry.fields in ((), ("provider",), ("model",), ("purpose",), ("payload",)) for entry in journal)
    blob = repr([entry.as_dict() for entry in journal])
    assert MARKER not in blob
    assert "élément" not in blob


def test_no_representation_of_the_payload_leaks(guard: ConsentGuard) -> None:
    grant = _grant(guard, actor="come", note="accord de démonstration")
    decision = guard.check(
        grant.consent_id, provider=PROVIDER, model=MODEL, purpose=PURPOSE, payload={"marker": "autre"}
    )
    receipt = guard.consume(
        grant.consent_id, provider=PROVIDER, model=MODEL, purpose=PURPOSE, payload=dict(PAYLOAD)
    )
    for blob in (repr(grant), repr(grant.as_dict()), repr(decision), repr(receipt), repr(receipt.as_dict())):
        assert MARKER not in blob
        assert "élément synthétique" not in blob


def test_no_configuration_file_is_read(guard: ConsentGuard, monkeypatch: pytest.MonkeyPatch) -> None:
    opened: list[str] = []
    real_open = open

    def _tracked(file: object, *args: object, **kwargs: object) -> object:
        name = str(file)
        if any(token in name for token in (".env", "config", "settings", "secret", "credential")):
            opened.append(name)
        return real_open(file, *args, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr("builtins.open", _tracked)
    grant = _grant(guard)
    guard.consume(
        grant.consent_id, provider=PROVIDER, model=MODEL, purpose=PURPOSE, payload=dict(PAYLOAD)
    )
    assert opened == []


def test_the_environment_cannot_relax_the_guard(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    for name in (
        "CONSENT_GUARD_TTL",
        "CONSENT_GUARD_ALLOW_REUSE",
        "GEMINI_API_KEY",
        "OPENROUTER_API_KEY",
        "GOOGLE_API_KEY",
    ):
        monkeypatch.setenv(name, "1")
    guard = ConsentGuard(tmp_path, clock=lambda: FIXED_NOW)
    grant = _grant(guard)
    guard.consume(grant.consent_id, provider=PROVIDER, model=MODEL, purpose=PURPOSE, payload=dict(PAYLOAD))
    decision = guard.check(
        grant.consent_id, provider=PROVIDER, model=MODEL, purpose=PURPOSE, payload=dict(PAYLOAD)
    )
    assert decision.code == "consent_exhausted"
    guard.close()
