"""Tests de liaison : toute modification invalide l'accord.

Exigence centrale du lot : un accord couvre **exactement** une transmission,
définie par quatre champs — fournisseur, modèle, objectif, contenu sérialisé.
Modifier n'importe lequel de ces champs produit un refus
``envelope_mismatch`` qui nomme le champ divergent, sans jamais révéler le
contenu.

Est également vérifié ce qui, légitimement, ne doit **pas** invalider
l'accord : l'ordre des clés d'une structure JSON, la normalization du
fournisseur et de l'objectif, et une relance à froid du garde-fou.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from consent_guard import (
    CODE_ENVELOPE_MISMATCH,
    ConsentEnvelope,
    ConsentGuard,
    EnvelopeMismatchError,
    TransmissionRequest,
    payload_digest,
)
from consent_guard.errors import EnvelopeError

MARKER = "MARQUEUR-SYNTHETIQUE-7B21"
PROVIDER = "gemini"
MODEL = "gemini-3.8-flash"
PURPOSE = "exam_revision"
TARGET = {"marker": MARKER, "items": [{"id": "a", "value": 1}, {"id": "b", "value": 2}]}


class Clock:
    """Horloge injectable, pour rendre l'expiration déterministe."""

    def __init__(self, start: datetime) -> None:
        self.now = start

    def __call__(self) -> datetime:
        return self.now

    def advance(self, seconds: int) -> None:
        self.now = self.now + timedelta(seconds=seconds)


@pytest.fixture()
def clock() -> Clock:
    return Clock(datetime(2026, 10, 14, 9, 0, 0, tzinfo=timezone.utc))


@pytest.fixture()
def guard(tmp_path, clock: Clock) -> ConsentGuard:
    instance = ConsentGuard(tmp_path, clock=clock)
    yield instance
    instance.close()


def _grant(guard: ConsentGuard, **overrides: object) -> ConsentEnvelope:
    payload: object = dict(TARGET)
    base: dict[str, object] = {
        "provider": PROVIDER,
        "model": MODEL,
        "purpose": PURPOSE,
        "payload": payload,
    }
    base.update(overrides)
    return guard.grant(**base)  # type: ignore[arg-type]


def _mutant(**overrides: object) -> TransmissionRequest:
    payload: object = dict(TARGET)
    base: dict[str, object] = {
        "provider": PROVIDER,
        "model": MODEL,
        "purpose": PURPOSE,
        "payload": payload,
    }
    base.update(overrides)
    return TransmissionRequest(**base)  # type: ignore[arg-type]


# --- Champs de la cible ----------------------------------------------------


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("provider", "openrouter"),
        ("provider", "ollama_local"),
        ("model", "gemini-3.6-flash"),
        ("model", "gemini-3.8-flash-lite"),
        ("model", "vendor/other-model"),
        ("purpose", "job_application"),
        ("purpose", "generic"),
    ],
)
def test_changing_one_target_field_invalidates_the_agreement(
    guard: ConsentGuard, field: str, value: str
) -> None:
    grant = _grant(guard)
    request = _mutant(**{field: value})
    decision = guard.check(grant.consent_id, request=request)
    assert not decision.allowed
    assert decision.code == CODE_ENVELOPE_MISMATCH
    assert decision.fields == (field,)


def test_changing_model_and_content_at_once_names_both_fields(guard: ConsentGuard) -> None:
    grant = _grant(guard)
    request = _mutant(model="gemini-3.6-flash", payload={"marker": MARKER, "items": []})
    decision = guard.check(grant.consent_id, request=request)
    assert set(decision.fields) == {"model", "payload"}


@pytest.mark.parametrize(
    "mutate",
    [
        lambda data: data.update({"items": [{"id": "a", "value": 1}]}),
        lambda data: data.update({"items": [{"id": "a", "value": 1}, {"id": "b", "value": 3}]}),
        lambda data: data.update({"extra": "champ ajouté"}),
        lambda data: data.pop("marker"),
        lambda data: data.update({"marker": MARKER + " "}),
        lambda data: data.update({"marker": MARKER + "x"}),
        lambda data: data.update({"items": "plus une liste"}),
    ],
)
def test_any_content_change_invalidates_the_agreement(guard: ConsentGuard, mutate) -> None:
    grant = _grant(guard)
    altered = {"marker": MARKER, "items": [{"id": "a", "value": 1}, {"id": "b", "value": 2}]}
    mutate(altered)
    decision = guard.check(grant.consent_id, request=_mutant(payload=altered))
    assert not decision.allowed
    assert decision.code == CODE_ENVELOPE_MISMATCH
    assert decision.fields == ("payload",)
    assert decision.fallback == "local_engine"


def test_one_extra_space_in_the_text_invalidates_it(guard: ConsentGuard) -> None:
    grant = guard.grant(
        provider=PROVIDER, model=MODEL, purpose=PURPOSE, payload="Contexte synthétique à transmettre."
    )
    request = TransmissionRequest(
        provider=PROVIDER, model=MODEL, purpose=PURPOSE, payload="Contexte synthétique à transmettre. "
    )
    decision = guard.check(grant.consent_id, request=request)
    assert decision.code == CODE_ENVELOPE_MISMATCH
    assert decision.fields == ("payload",)


def test_truncated_content_invalidates_it(guard: ConsentGuard) -> None:
    grant = guard.grant(provider=PROVIDER, model=MODEL, purpose=PURPOSE, payload="Contexte synthétique.")
    request = TransmissionRequest(
        provider=PROVIDER, model=MODEL, purpose=PURPOSE, payload="Contexte synthétique"
    )
    assert guard.check(grant.consent_id, request=request).fields == ("payload",)


def test_bytes_content_is_bound_too(guard: ConsentGuard) -> None:
    grant = guard.grant(provider=PROVIDER, model=MODEL, purpose=PURPOSE, payload=b"octets synthetiques")
    request = TransmissionRequest(
        provider=PROVIDER, model=MODEL, purpose=PURPOSE, payload=b"octets synthetiqueS"
    )
    assert guard.check(grant.consent_id, request=request).fields == ("payload",)


def test_empty_content_has_no_agreement_at_all(guard: ConsentGuard) -> None:
    with pytest.raises(EnvelopeError) as caught:
        guard.grant(provider=PROVIDER, model=MODEL, purpose=PURPOSE, payload="   ")
    assert caught.value.code == "payload_empty"


# --- Ce qui ne doit pas invalider -----------------------------------------


def test_key_order_does_not_invalidate_the_agreement(guard: ConsentGuard) -> None:
    """L'ordre des clés d'un objet JSON n'est pas du contenu ; celui d'une liste si."""

    grant = _grant(guard)
    reordered = {
        "items": [{"value": 1, "id": "a"}, {"value": 2, "id": "b"}],
        "marker": MARKER,
    }
    decision = guard.check(grant.consent_id, request=_mutant(payload=reordered))
    assert decision.allowed


def test_item_order_inside_a_list_is_content(guard: ConsentGuard) -> None:
    grant = _grant(guard)
    swapped = {"marker": MARKER, "items": [{"id": "b", "value": 2}, {"id": "a", "value": 1}]}
    decision = guard.check(grant.consent_id, request=_mutant(payload=swapped))
    assert decision.code == CODE_ENVELOPE_MISMATCH
    assert decision.fields == ("payload",)


def test_provider_and_purpose_are_normalised_before_comparison(guard: ConsentGuard) -> None:
    grant = _grant(guard)
    request = TransmissionRequest(
        provider="  GEMINI ", model=MODEL, purpose=" Exam_Revision ", payload=dict(TARGET)
    )
    assert guard.check(grant.consent_id, request=request).allowed


def test_a_cold_restart_keeps_the_same_binding(tmp_path) -> None:
    first = ConsentGuard(tmp_path)
    grant = first.grant(provider=PROVIDER, model=MODEL, purpose=PURPOSE, payload=dict(TARGET))
    first.close()
    second = ConsentGuard(tmp_path)
    assert second.check(grant.consent_id, request=_mutant()).allowed
    assert second.check(grant.consent_id, request=_mutant(model=MODEL + "-pro")).fields == ("model",)
    second.close()


# --- Levée et messages -----------------------------------------------------


def test_consume_raises_a_mismatch_refusal_without_consuming(guard: ConsentGuard) -> None:
    grant = _grant(guard)
    with pytest.raises(EnvelopeMismatchError) as caught:
        guard.consume(
            grant.consent_id,
            provider=PROVIDER,
            model="gemini-3.6-flash",
            purpose=PURPOSE,
            payload=dict(TARGET),
        )
    assert caught.value.code == CODE_ENVELOPE_MISMATCH
    assert caught.value.fields == ("model",)
    assert guard.get(grant.consent_id).uses_consumed == 0


def test_refusal_message_mentions_no_content(guard: ConsentGuard) -> None:
    grant = _grant(guard)
    request = _mutant(payload={"marker": "autre", "items": []})
    decision = guard.check(grant.consent_id, request=request)
    assert "autre" not in decision.message
    assert MARKER not in decision.message
    assert PROVIDER not in decision.message
    assert MODEL not in decision.message


def test_digest_of_the_agreement_is_the_digest_of_the_payload(guard: ConsentGuard) -> None:
    grant = _grant(guard)
    assert grant.payload_digest == payload_digest(dict(TARGET))
    assert grant.payload_bytes > 0


def test_mismatch_is_reported_before_exhaustion(guard: ConsentGuard) -> None:
    """Un accord qui ne couvre pas la demande ne la couvre pas, usage ou pas."""

    grant = _grant(guard)
    guard.consume(
        grant.consent_id,
        provider=PROVIDER,
        model=MODEL,
        purpose=PURPOSE,
        payload=dict(TARGET),
    )
    decision = guard.check(
        grant.consent_id,
        provider=PROVIDER,
        model=MODEL,
        purpose=PURPOSE,
        payload={"marker": "tout autre chose"},
    )
    assert decision.code == CODE_ENVELOPE_MISMATCH
    assert decision.fields == ("payload",)
