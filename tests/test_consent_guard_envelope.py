"""Tests de l'enveloppe de consentement : sérialisation, empreinte, champs.

Exigences vérifiées :

* le contenu est sérialisé de façon canonique et déterministe ;
* l'empreinte change dès qu'un octet du contenu change ;
* l'ordre des clés d'une structure JSON ne change pas l'empreinte ;
* le contenu n'apparaît jamais dans ``repr()`` ni dans ``as_dict()`` ;
* chaque champ de l'accord est validé et refusé sans bruit ;
* l'expiration est bornée et ne peut pas être déjà dépassée.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

import pytest

from consent_guard.envelope import (
    MAX_TTL_SECONDS,
    PURPOSES,
    SINGLE_USE,
    ConsentEnvelope,
    TransmissionRequest,
    canonical_payload,
    is_local_provider,
    new_consent_id,
    normalise_model,
    normalise_provider,
    normalise_purpose,
    payload_bytes,
    payload_digest,
    resolve_expiry,
)
from consent_guard.errors import EnvelopeError

#: Marqueur synthétique utilisé pour prouver qu'aucun contenu ne fuit.
MARKER = "MARQUEUR-SYNTHETIQUE-9F4C"

NOW = datetime(2026, 10, 14, 9, 0, 0, tzinfo=timezone.utc)


# --- Sérialisation canonique ----------------------------------------------


def test_text_payload_is_serialised_to_exact_utf8_bytes() -> None:
    raw = canonical_payload("accents : é è ç — synthétique")
    assert raw == "accents : é è ç — synthétique".encode("utf-8")


def test_bytes_payload_is_used_verbatim() -> None:
    raw = b"\x00\x01contenu synth\xc3\xa9tique"
    assert canonical_payload(raw) == raw
    assert payload_bytes(raw) == len(raw)


def test_json_payload_is_independent_of_key_order() -> None:
    first = {"b": 1, "a": {"z": True, "y": [1, 2]}}
    second = {"a": {"y": [1, 2], "z": True}, "b": 1}
    assert canonical_payload(first) == canonical_payload(second)
    assert payload_digest(first) == payload_digest(second)


def test_json_payload_is_compact_and_sorted() -> None:
    raw = canonical_payload({"b": 1, "a": 2}).decode("utf-8")
    assert raw == '{"a":2,"b":1}'


def test_list_payload_is_serialised() -> None:
    assert canonical_payload([1, "deux", None]) == b'[1,"deux",null]'


@pytest.mark.parametrize("empty", ["", "   \n\t ", b"", bytearray()])
def test_empty_payload_is_refused(empty: object) -> None:
    with pytest.raises(EnvelopeError) as caught:
        canonical_payload(empty)
    assert caught.value.code == "payload_empty"


def test_oversized_payload_is_refused(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("consent_guard.envelope.MAX_PAYLOAD_BYTES", 16)
    with pytest.raises(EnvelopeError) as caught:
        canonical_payload("x" * 17)
    assert caught.value.code == "payload_too_large"


def test_unserialisable_payload_is_refused() -> None:
    with pytest.raises(EnvelopeError) as caught:
        canonical_payload({"objet": object()})
    assert caught.value.code == "payload_unserialisable"


def test_scalar_payload_is_refused() -> None:
    for value in (42, 3.5, True, None):
        with pytest.raises(EnvelopeError) as caught:
            canonical_payload(value)
        assert caught.value.code == "payload_type"


def test_error_message_never_contains_the_payload() -> None:
    with pytest.raises(EnvelopeError) as caught:
        canonical_payload({"objet": object(), "marker": MARKER})
    assert MARKER not in str(caught.value)


# --- Empreinte -------------------------------------------------------------


def test_digest_changes_on_a_single_character() -> None:
    first = payload_digest("Contexte synthétique à transmettre.")
    second = payload_digest("Contexte synthétique à transmettre,")
    assert first != second


def test_digest_changes_on_added_or_removed_item() -> None:
    base = {"items": [{"id": "a"}, {"id": "b"}], "marker": MARKER}
    added = {"items": [{"id": "a"}, {"id": "b"}, {"id": "c"}], "marker": MARKER}
    removed = {"items": [{"id": "a"}], "marker": MARKER}
    assert payload_digest(base) != payload_digest(added)
    assert payload_digest(base) != payload_digest(removed)


def test_digest_changes_on_a_number_change() -> None:
    assert payload_digest({"n": 1}) != payload_digest({"n": 1.0}) != payload_digest({"n": 2})


def test_digest_is_stable_and_sha256_shaped() -> None:
    first = payload_digest("stable")
    assert first == payload_digest("stable")
    assert len(first) == 64
    int(first, 16)


def test_text_and_bytes_payloads_agree_on_the_same_octets() -> None:
    assert payload_digest("texte") == payload_digest(b"texte")


# --- Champs de l'accord ----------------------------------------------------


def test_request_repr_hides_the_payload() -> None:
    request = TransmissionRequest(provider="Gemini", model="gemini-3.8-flash", purpose="generic", payload=MARKER)
    assert MARKER not in repr(request)
    assert "payload" not in repr(request)
    assert request.digest in repr(request)


def test_request_as_dict_hides_the_payload() -> None:
    request = TransmissionRequest(provider="gemini", model="m-1", purpose="generic", payload=MARKER)
    summary = request.as_dict()
    assert summary == {
        "provider": "gemini",
        "model": "m-1",
        "purpose": "generic",
        "payload_digest": payload_digest(MARKER),
        "payload_bytes": payload_bytes(MARKER),
    }
    assert MARKER not in json.dumps(summary, ensure_ascii=False)


def test_request_equality_compares_digests_not_content() -> None:
    first = TransmissionRequest(provider="gemini", model="m-1", purpose="generic", payload="même empreinte")
    second = TransmissionRequest(provider="gemini", model="m-1", purpose="generic", payload="même empreinte")
    assert first == second


def test_request_normalises_provider_and_purpose() -> None:
    request = TransmissionRequest(provider="  Gemini ", model=" m-1 ", purpose=" Generic ", payload="x")
    assert request.provider == "gemini"
    assert request.purpose == "generic"
    assert request.model == "m-1"


@pytest.mark.parametrize(
    "value",
    ["", "  ", "gémini", "gem ini", "gemini!", "x" * 65, "é", "..", None, 7, ["gemini"]],
)
def test_invalid_providers_are_refused(value: object) -> None:
    with pytest.raises(EnvelopeError) as caught:
        normalise_provider(value)
    assert caught.value.field == "provider"


@pytest.mark.parametrize(
    "value",
    ["", " ", "-modele", "modèle", "model with space", "x" * 193, None, 12, {"a": 1}],
)
def test_invalid_models_are_refused(value: object) -> None:
    with pytest.raises(EnvelopeError) as caught:
        normalise_model(value)
    assert caught.value.field == "model"


def test_valid_model_identifiers_are_accepted() -> None:
    for value in ("gemini-3.8-flash", "qwen3.5:2b-q4_K_M", "vendor/paid-model:free", "a.b/c_d-e"):
        assert normalise_model(value) == value


def test_unknown_purpose_is_refused_with_allowed_values() -> None:
    with pytest.raises(EnvelopeError) as caught:
        normalise_purpose("espionnage")
    assert caught.value.field == "purpose"
    assert "generic" in str(caught.value)


def test_every_declared_purpose_is_accepted() -> None:
    for purpose in PURPOSES:
        assert normalise_purpose(purpose.upper()) == purpose


def test_local_providers_are_recognised() -> None:
    assert is_local_provider("ollama_local")
    assert is_local_provider("LOCAL")
    assert not is_local_provider("gemini")


def test_consent_id_is_prefixed_and_unique() -> None:
    identifiers = {new_consent_id(f"graine-{index}") for index in range(50)}
    assert len(identifiers) == 50
    assert all(item.startswith("cgt_") and len(item) == 36 for item in identifiers)


# --- Expiration ------------------------------------------------------------


def test_default_ttl_is_applied() -> None:
    expires = resolve_expiry(now=NOW)
    assert expires == "2026-10-14T09:15:00Z"


def test_ttl_ceiling_is_enforced() -> None:
    with pytest.raises(EnvelopeError) as caught:
        resolve_expiry(ttl_seconds=MAX_TTL_SECONDS + 1, now=NOW)
    assert caught.value.field == "ttl_seconds"


def test_zero_or_negative_ttl_is_refused() -> None:
    for ttl in (0, -1):
        with pytest.raises(EnvelopeError) as caught:
            resolve_expiry(ttl_seconds=ttl, now=NOW)
        assert caught.value.field == "ttl_seconds"


def test_explicit_expiry_is_accepted() -> None:
    assert resolve_expiry(expires_at="2026-10-14T10:00:00Z", now=NOW) == "2026-10-14T10:00:00Z"


def test_already_past_expiry_is_refused() -> None:
    with pytest.raises(EnvelopeError) as caught:
        resolve_expiry(expires_at="2026-10-14T08:59:59Z", now=NOW)
    assert caught.value.field == "expires_at"


# --- Enveloppe -------------------------------------------------------------


def _envelope(**overrides: object) -> ConsentEnvelope:
    payload = {"marker": MARKER, "items": [1, 2, 3]}
    base: dict[str, object] = {
        "consent_id": "cgt_" + "a" * 32,
        "provider": "gemini",
        "model": "gemini-3.8-flash",
        "purpose": "exam_revision",
        "payload_digest": payload_digest(payload),
        "payload_bytes": payload_bytes(payload),
        "issued_at": "2026-10-14T09:00:00Z",
        "expires_at": "2026-10-14T09:15:00Z",
    }
    base.update(overrides)
    return ConsentEnvelope(**base)  # type: ignore[arg-type]


def _request(**overrides: object) -> TransmissionRequest:
    payload: dict[str, object] = {"marker": MARKER, "items": [1, 2, 3]}
    base: dict[str, object] = {
        "provider": "gemini",
        "model": "gemini-3.8-flash",
        "purpose": "exam_revision",
        "payload": payload,
    }
    base.update(overrides)
    return TransmissionRequest(**base)  # type: ignore[arg-type]


def test_matching_request_has_no_divergent_field() -> None:
    assert _envelope().matches(_request()) == ()


def test_envelope_expiry_boundary_is_inclusive() -> None:
    envelope = _envelope()
    assert not envelope.is_expired(datetime(2026, 10, 14, 9, 14, 59, tzinfo=timezone.utc))
    assert envelope.is_expired(datetime(2026, 10, 14, 9, 15, 0, tzinfo=timezone.utc))
    assert envelope.is_expired(datetime(2026, 10, 14, 9, 15, 1, tzinfo=timezone.utc))


def test_envelope_consumption_flag() -> None:
    fresh = _envelope()
    assert not fresh.is_consumed()
    consumed = _envelope(uses_consumed=1, state="used", consumed_at="2026-10-14T09:01:00Z")
    assert consumed.is_consumed()


def test_envelope_as_dict_carries_no_payload() -> None:
    summary = _envelope().as_dict()
    assert summary["payload_digest"] == payload_digest({"marker": MARKER, "items": [1, 2, 3]})
    assert MARKER not in json.dumps(summary, ensure_ascii=False)


def test_binding_digest_binds_all_four_fields() -> None:
    reference = _envelope().binding_digest
    assert reference == _envelope().binding_digest
    assert reference != _envelope(model="gemini-3.6-flash").binding_digest
    assert reference != _envelope(provider="openrouter").binding_digest
    assert reference != _envelope(purpose="generic").binding_digest
    assert reference != _envelope(payload_digest="0" * 64).binding_digest
    assert reference != _envelope(payload_bytes=999).binding_digest


def test_single_use_constant_is_one() -> None:
    assert SINGLE_USE == 1


def test_expiry_helpers_round_trip() -> None:
    moment = datetime(2026, 1, 2, 3, 4, 5, tzinfo=timezone.utc)
    assert resolve_expiry(ttl_seconds=60, now=moment) == "2026-01-02T03:05:05Z"
    assert moment + timedelta(seconds=60) == datetime(2026, 1, 2, 3, 5, 5, tzinfo=timezone.utc)
