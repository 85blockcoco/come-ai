"""Garde-fou de transmission : un accord, une transmission, aucun appel réseau.

Le garde-fou ne parle jamais à un fournisseur.  Il décide, et il trace :

1. :meth:`ConsentGuard.grant` enregistre un accord **avant** tout envoi, lié au
   fournisseur, au modèle, à l'objectif et à l'empreinte du contenu sérialisé
   exact ;

2. :meth:`ConsentGuard.check` répond sans lever d'exception : la transmission
   est-elle autorisée, et sinon pourquoi (code stable) et avec quel repli ;

3. :meth:`ConsentGuard.consume` consomme l'accord de façon atomique et rend un
   reçu. Usage unique : une deuxième consommation est refusée avec
   ``consent_exhausted`` ;

4. :func:`transmit` appelle l'expéditeur fourni par l'intégrateur **seulement
   après** une consommation réussie, jamais avant.

L'ordre d'évaluation des refus est fixe et documenté :
``consent_unknown`` → ``consent_revoked`` → ``envelope_mismatch`` →
``consent_expired`` → ``consent_exhausted``.  La correspondance est examinée
avant l'état : un accord qui ne couvre pas la demande ne la couvre pas, quel
que soit son âge.  Aucun de ces refus n'ouvre de connexion, ne lit de clé
secrète ni ne consulte de catalogue de modèles.

Exemple minimal ::

    from consent_guard import ConsentGuard

    guard = ConsentGuard("/dossier/local/prive")
    grant = guard.grant(
        provider="gemini", model="gemini-3.8-flash", purpose="exam_revision",
        payload="Contexte synthétique à transmettre.",
    )
    decision = guard.check(grant.consent_id, provider="gemini",
                           model="gemini-3.8-flash", purpose="exam_revision",
                           payload="Contexte synthétique à transmettre.")
    if decision.allowed:
        receipt = guard.consume(grant.consent_id, provider="gemini", ...)
        # Ici, et ici seulement, l'intégrateur appelle son transport.
"""

from __future__ import annotations

import secrets
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Protocol, runtime_checkable

from .envelope import (
    DEFAULT_TTL_SECONDS,
    SINGLE_USE,
    ConsentDecision,
    ConsentEnvelope,
    TransmissionReceipt,
    TransmissionRequest,
    format_instant,
    is_local_provider,
    new_consent_id,
    payload_digest,
    resolve_expiry,
)
from .errors import (
    CODE_ALLOWED,
    CODE_CONSUMED_CONSENT,
    CODE_ENVELOPE_MISMATCH,
    CODE_EXPIRED_CONSENT,
    CODE_INVALID_REQUEST,
    CODE_PAYLOAD_EMPTY,
    CODE_PAYLOAD_TOO_LARGE,
    CODE_PAYLOAD_TYPE,
    CODE_PAYLOAD_UNSERIALISABLE,
    CODE_REVOKED_CONSENT,
    CODE_UNKNOWN_CONSENT,
    ConsentRefusal,
    ConsumedConsentError,
    EnvelopeError,
    EnvelopeMismatchError,
    ExpiredConsentError,
    FALLBACK_LOCAL,
    FALLBACK_NONE,
    InvalidRequestError,
    RevokedConsentError,
    StoreError,
    UnknownConsentError,
)
from .store import STATE_GRANTED, STATE_REVOKED, ConsentStore, RefusalRecord

#: Messages de refus, sûrs : aucun extrait de contenu, aucun chemin.
_MESSAGES = {
    CODE_UNKNOWN_CONSENT: "Aucun accord de consentement ne correspond à cet identifiant.",
    CODE_REVOKED_CONSENT: "L'accord de consentement a été révoqué avant son expiration.",
    CODE_EXPIRED_CONSENT: "L'accord de consentement a expiré : une nouvelle demande est nécessaire.",
    CODE_CONSUMED_CONSENT: "L'accord de consentement est à usage unique et a déjà été consommé.",
    CODE_ENVELOPE_MISMATCH: "L'accord ne couvre pas cette transmission : {details}.",
    CODE_INVALID_REQUEST: "La demande de transmission est invalide : {details}.",
    CODE_PAYLOAD_EMPTY: "Le contenu à transmettre est vide : il n'y a rien à autoriser.",
    CODE_PAYLOAD_TOO_LARGE: "Le contenu dépasse la taille maximale autorisée : divise la transmission.",
    CODE_PAYLOAD_TYPE: "Le contenu doit être du texte, des octets ou une structure JSON.",
    CODE_PAYLOAD_UNSERIALISABLE: "Le contenu à transmettre n'est pas sérialisable en JSON.",
}

_REFUSAL_ERRORS: dict[str, type[ConsentRefusal]] = {
    CODE_UNKNOWN_CONSENT: UnknownConsentError,
    CODE_REVOKED_CONSENT: RevokedConsentError,
    CODE_EXPIRED_CONSENT: ExpiredConsentError,
    CODE_CONSUMED_CONSENT: ConsumedConsentError,
    CODE_ENVELOPE_MISMATCH: EnvelopeMismatchError,
    CODE_PAYLOAD_EMPTY: InvalidRequestError,
    CODE_PAYLOAD_TOO_LARGE: InvalidRequestError,
    CODE_PAYLOAD_TYPE: InvalidRequestError,
    CODE_PAYLOAD_UNSERIALISABLE: InvalidRequestError,
    CODE_INVALID_REQUEST: InvalidRequestError,
}


def _refusal_for(
    code: str,
    *,
    fields: tuple[str, ...] = (),
    details: str = "",
    message: str = "",
) -> ConsentRefusal:
    """Construit l'erreur de refus correspondant à un code stable."""

    if message:
        text = message
    else:
        text = _MESSAGES.get(code, _MESSAGES[CODE_INVALID_REQUEST]).format(details=details or code)
    return _REFUSAL_ERRORS[code](text, code=code, fields=fields)


@runtime_checkable
class CloudTransport(Protocol):
    """Expéditeur fourni par l'intégrateur, appelé après consommation.

    Le garde-fou ne fournit aucune implémentation : aucun transport réel,
    fictif ou de test ne vit dans ce paquet.  ``send`` reçoit les octets exacts
    qui ont été autorisés et le reçu de consommation.
    """

    def send(self, payload: bytes, receipt: TransmissionReceipt) -> Any:
        """Transmet les octets autorisés et renvoie la réponse du fournisseur."""


def fallback_notice(decision: ConsentDecision) -> str:
    """Phrase affichable lorsqu'une transmission est refusée.

    Elle ne contient que le code de refus et le repli : ni contenu personnel,
    ni identifiant de modèle, ni chemin.
    """

    return (
        "Aucune donnée personnelle n'a quitté cet appareil. "
        f"Motif du refus : {decision.code}. Repli : {decision.fallback}."
    )


class ConsentGuard:
    """Décideur local de transmission, persistant et sans accès réseau."""

    def __init__(
        self,
        base_dir: Path | str,
        *,
        db_name: str = "consent_guard.sqlite3",
        clock: Callable[[], datetime] | None = None,
        default_ttl_seconds: int = DEFAULT_TTL_SECONDS,
    ) -> None:
        self._store = ConsentStore(base_dir, db_name=db_name)
        self._clock = clock or (lambda: datetime.now(timezone.utc))
        self.default_ttl_seconds = int(default_ttl_seconds)

    # --- utilitaires ------------------------------------------------------

    @property
    def store(self) -> ConsentStore:
        return self._store

    @property
    def db_path(self) -> Path:
        return self._store.db_path

    def _now(self) -> datetime:
        return self._clock()

    def build_request(
        self,
        *,
        provider: str,
        model: str,
        purpose: str,
        payload: Any,
    ) -> TransmissionRequest:
        """Construit et valide une demande de transmission."""

        return TransmissionRequest(provider=provider, model=model, purpose=purpose, payload=payload)

    # --- accord ------------------------------------------------------------

    def grant(
        self,
        payload: Any = None,
        *,
        provider: str = "",
        model: str = "",
        purpose: str = "",
        request: TransmissionRequest | None = None,
        actor: str = "",
        note: str = "",
        ttl_seconds: int | None = None,
        expires_at: str | None = None,
        consent_id: str | None = None,
    ) -> ConsentEnvelope:
        """Enregistre un accord pour **une** transmission, ou lève une erreur.

        Le contenu n'est pas conservé : seule son empreinte entre dans
        l'enveloppe.  ``uses_allowed`` vaut toujours :data:`SINGLE_USE`.
        """

        if request is None:
            request = self.build_request(provider=provider, model=model, purpose=purpose, payload=payload)
        now = self._now()
        envelope = ConsentEnvelope(
            consent_id=consent_id or new_consent_id(secrets.token_hex(16)),
            provider=request.provider,
            model=request.model,
            purpose=request.purpose,
            payload_digest=request.digest,
            payload_bytes=request.size,
            issued_at=format_instant(now),
            expires_at=resolve_expiry(
                ttl_seconds=ttl_seconds if ttl_seconds is not None else self.default_ttl_seconds,
                expires_at=expires_at,
                now=now,
            ),
            state=STATE_GRANTED,
            uses_allowed=SINGLE_USE,
            uses_consumed=0,
            actor=actor,
            note=note[:200],
        )
        self._store.insert(envelope)
        return envelope

    def get(self, consent_id: str) -> ConsentEnvelope | None:
        """Relit un accord, ou ``None`` s'il est inconnu."""

        return self._store.get(consent_id)

    def revoke(self, consent_id: str, *, actor: str = "", note: str = "") -> ConsentEnvelope:
        """Révoque un accord avant son expiration.

        Un accord déjà consommé ou déjà révoqué ne se révoque pas une seconde
        fois : il est clos.  La révocation est définitive, il faut un nouvel
        accord pour transmettre à nouveau.
        """

        envelope = self._store.get(consent_id)
        if envelope is None:
            raise UnknownConsentError(_MESSAGES[CODE_UNKNOWN_CONSENT])
        if envelope.state != STATE_GRANTED:
            raise StoreError("Cet accord n'est plus en attente : il est clos ou déjà révoqué.")
        self._store.mark_revoked(consent_id)
        revoked = self._store.get(consent_id)
        if revoked is None:  # pragma: no cover - la ligne vient d'être relue
            raise StoreError("L'accord révoqué est introuvable après révocation.")
        del actor, note
        return revoked

    def active(self, *, now: datetime | None = None) -> tuple[ConsentEnvelope, ...]:
        """Accords encore utilisables : émis, non révoqués, non expirés."""

        moment = now or self._now()
        return tuple(
            envelope
            for envelope in self._store.list_consents(state=STATE_GRANTED)
            if not envelope.is_expired(moment) and not envelope.is_consumed()
        )

    # --- décision ----------------------------------------------------------

    def check(
        self,
        consent_id: str,
        *,
        provider: str = "",
        model: str = "",
        purpose: str = "",
        payload: Any = None,
        request: TransmissionRequest | None = None,
        now: datetime | None = None,
    ) -> ConsentDecision:
        """Répond sans lever d'exception : autoriser, ou refuser avec un code.

        C'est le point d'entrée à utiliser pour un repli local : l'appelant
        décide quoi faire quand ``allowed`` est faux.
        """

        moment = now or self._now()
        try:
            prepared = request or self.build_request(
                provider=provider, model=model, purpose=purpose, payload=payload
            )
        except EnvelopeError as error:
            return ConsentDecision(
                allowed=False,
                code=error.code or CODE_INVALID_REQUEST,
                message=str(error),
                fallback=FALLBACK_LOCAL,
                consent_id=consent_id,
                fields=(error.field,) if error.field else (),
            )
        envelope = self._store.get(consent_id)
        if envelope is None:
            return self._decision(CODE_UNKNOWN_CONSENT, consent_id)
        return self._evaluate(envelope, prepared, moment, consent_id)

    def _evaluate(
        self, envelope: ConsentEnvelope, request: TransmissionRequest, now: datetime, consent_id: str
    ) -> ConsentDecision:
        if envelope.state == STATE_REVOKED:
            return self._decision(CODE_REVOKED_CONSENT, consent_id)
        fields = envelope.matches(request)
        if fields:
            details = ", ".join(fields)
            return self._decision(CODE_ENVELOPE_MISMATCH, consent_id, fields=fields, details=details)
        if envelope.is_expired(now):
            return self._decision(CODE_EXPIRED_CONSENT, consent_id)
        if envelope.is_consumed():
            return self._decision(CODE_CONSUMED_CONSENT, consent_id)
        return ConsentDecision(
            allowed=True,
            code=CODE_ALLOWED,
            message="L'accord couvre exactement cette transmission.",
            fallback=FALLBACK_NONE,
            consent_id=consent_id,
        )

    def _decision(
        self,
        code: str,
        consent_id: str,
        *,
        fields: tuple[str, ...] = (),
        details: str = "",
    ) -> ConsentDecision:
        message = _MESSAGES[code].format(details=details or code)
        self._store.record_refusal(format_instant(self._now()), code, consent_id, fields)
        return ConsentDecision(
            allowed=False,
            code=code,
            message=message,
            fallback=FALLBACK_LOCAL,
            consent_id=consent_id,
            fields=fields,
        )

    # --- consommation ------------------------------------------------------

    def consume(
        self,
        consent_id: str,
        *,
        provider: str = "",
        model: str = "",
        purpose: str = "",
        payload: Any = None,
        request: TransmissionRequest | None = None,
    ) -> TransmissionReceipt:
        """Consomme l'accord et rend le reçu, ou lève un :class:`ConsentRefusal`.

        La consommation est atomique : deux appels concurrents sur le même
        accord ne peuvent pas réussir tous les deux.
        """

        moment = self._now()
        try:
            prepared = request or self.build_request(
                provider=provider, model=model, purpose=purpose, payload=payload
            )
        except EnvelopeError as error:
            code = error.code if error.code in _REFUSAL_ERRORS else CODE_INVALID_REQUEST
            fields = (error.field,) if error.field else ()
            self._store.record_refusal(format_instant(moment), code, consent_id, fields)
            raise _refusal_for(code, fields=fields, message=str(error)) from error
        envelope = self._store.get(consent_id)
        if envelope is None:
            raise self._raise(CODE_UNKNOWN_CONSENT, consent_id, moment)
        if envelope.state == STATE_REVOKED:
            raise self._raise(CODE_REVOKED_CONSENT, consent_id, moment)
        fields = envelope.matches(prepared)
        if fields:
            raise self._raise(CODE_ENVELOPE_MISMATCH, consent_id, moment, fields=fields, details=", ".join(fields))
        if envelope.is_expired(moment):
            raise self._raise(CODE_EXPIRED_CONSENT, consent_id, moment)
        if envelope.is_consumed():
            raise self._raise(CODE_CONSUMED_CONSENT, consent_id, moment)
        if not self._store.mark_consumed(consent_id, at=format_instant(moment)):
            raise self._raise(CODE_CONSUMED_CONSENT, consent_id, moment)
        return TransmissionReceipt(
            transmission_id=f"trm_{secrets.token_hex(12)}",
            consent_id=consent_id,
            provider=envelope.provider,
            model=envelope.model,
            purpose=envelope.purpose,
            payload_digest=envelope.payload_digest,
            payload_bytes=envelope.payload_bytes,
            consumed_at=format_instant(moment),
        )

    def _raise(
        self,
        code: str,
        consent_id: str,
        moment: datetime,
        *,
        fields: tuple[str, ...] = (),
        details: str = "",
    ) -> ConsentRefusal:
        self._store.record_refusal(format_instant(moment), code, consent_id, fields)
        return _refusal_for(code, fields=fields, details=details)

    # --- diagnostic --------------------------------------------------------

    def journal(self, *, limit: int = 200) -> tuple[RefusalRecord, ...]:
        """Journal des refus : codes, champs et horodatages, rien d'autre."""

        return self._store.journal(limit=limit)

    def stats(self) -> dict[str, Any]:
        return self._store.stats()

    def forget_everything(self) -> bool:
        """Efface tous les accords et tout le journal local."""

        return self._store.forget_everything()

    def close(self) -> None:
        self._store.close()

    def __enter__(self) -> "ConsentGuard":
        return self

    def __exit__(self, *_exc: object) -> None:
        self.close()


def transmit(
    guard: ConsentGuard,
    consent_id: str,
    *,
    provider: str,
    model: str,
    purpose: str,
    payload: Any,
    sender: CloudTransport,
) -> Any:
    """Vérifie, consomme, puis transmet une seule fois via ``sender``.

    L'ordre est la garantie du lot : ``sender.send`` n'est jamais appelé si
    l'accord manque, a expiré, est déjà consommé, a été révoqué ou ne couvre
    pas exactement cette cible.  L'expéditeur est fourni par l'intégrateur :
    ce paquet ne contient aucun transport, fictif ou réel.
    """

    request = guard.build_request(provider=provider, model=model, purpose=purpose, payload=payload)
    decision = guard.check(consent_id, request=request)
    if not decision.allowed:
        raise _refusal_for(decision.code, fields=decision.fields, message=decision.message)
    receipt = guard.consume(consent_id, request=request)
    return sender.send(request.serialised(), receipt)


__all__ = [
    "CloudTransport",
    "ConsentGuard",
    "ConsentRequest",
    "TransmissionRequest",
    "fallback_notice",
    "is_local_provider",
    "payload_digest",
    "transmit",
]

#: Alias de confort pour l'intégration.
ConsentRequest = TransmissionRequest
