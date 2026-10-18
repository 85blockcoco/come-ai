"""Enveloppe de consentement : un accord unique, lié, daté et non réutilisable.

Une transmission de donnée personnelle vers un fournisseur cloud n'est
possible que si un **accord préalable** existe et que la demande lui
correspond exactement.  L'accord porte sur quatre champs seulement :

* le fournisseur (``provider``) ;

* le modèle (``model``) ;

* l'objectif (``purpose``) ;

* l'empreinte du contenu sérialisé exact (``payload_digest``).

Le contenu lui-même n'est **jamais** stocké, journalisé ni renvoyé par une
erreur : seule son empreinte SHA-256 circule.  Modifier un seul caractère du
contenu, changer de modèle, de fournisseur ou d'objectif produit une empreinte
ou une cible différente, donc un refus ``envelope_mismatch``.

Sérialisation canonique du contenu :

* ``str`` → octets UTF-8 exacts de la chaîne ;

* ``bytes`` → octets exacts ;

* structure JSON (tableau associatif ou liste) → JSON canonique
  (``sort_keys=True``, séparateurs compacts, ``ensure_ascii=False``) encodé en
  UTF-8.  L'ordre des clés ne change donc pas l'empreinte, mais toute valeur
  ajoutée, retirée ou modifiée la change.

La durée de vie, la consommation unique et le refus sans appel réseau sont
définis ici : :data:`SINGLE_USE` vaut toujours 1, il n'existe pas de réglage
pour l'autoriser à plusieurs usages.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Mapping

from .errors import (
    CODE_PAYLOAD_EMPTY,
    CODE_PAYLOAD_TOO_LARGE,
    CODE_PAYLOAD_TYPE,
    CODE_PAYLOAD_UNSERIALISABLE,
    EnvelopeError,
)

#: Contrat de l'enveloppe.  Toute rupture majeure incrémente la version.
CONTRACT_ID = "come-consent-guard-envelope/1"
SCHEMA_ID = "come-consent-guard-envelope/1"

#: Nombre d'autorisations d'usage par accord.  Toujours 1, par construction.
SINGLE_USE = 1

#: Objectifs reconnus.  Un objectif inconnu est refusé, jamais deviné.
PURPOSES: tuple[str, ...] = (
    "profile_context",
    "job_application",
    "exam_revision",
    "technical_project",
    "personal_decision",
    "data_analysis",
    "generic",
)

#: Fournisseurs strictement locaux : ils n'ont jamais besoin d'accord cloud.
LOCAL_PROVIDERS: tuple[str, ...] = ("ollama_local", "ollama", "local")

#: Durée de vie par défaut d'un accord, et plafond absolu.
DEFAULT_TTL_SECONDS = 900
MAX_TTL_SECONDS = 86_400

#: Taille maximale du contenu sérialisé accepté (256 Kio).
MAX_PAYLOAD_BYTES = 262_144

_MODEL_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/-]{0,191}$")
_PROVIDER_PATTERN = re.compile(r"^[a-z0-9][a-z0-9._-]{0,63}$")
_PURPOSE_PATTERN = re.compile(r"^[a-z][a-z0-9_]{2,63}$")
_CONSENT_ID_PATTERN = re.compile(r"^cgt_[0-9a-f]{32,64}$")

# --- Sérialisation et empreinte --------------------------------------------


def _stable_json(payload: Any) -> str:
    return json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def canonical_payload(payload: Any) -> bytes:
    """Sérialise le contenu en octets, de façon canonique et déterministe.

    Lève :class:`EnvelopeError` si le contenu est vide, trop gros ou d'un type
    non sérialisable.  Le message d'erreur ne contient jamais le contenu.
    """

    if isinstance(payload, bytes):
        raw = payload
    elif isinstance(payload, bytearray):
        raw = bytes(payload)
    elif isinstance(payload, str):
        if not payload.strip():
            raise EnvelopeError(
                "Le contenu à transmettre est vide : il n'y a rien à autoriser.",
                code=CODE_PAYLOAD_EMPTY,
                field="payload",
            )
        raw = payload.encode("utf-8")
    elif isinstance(payload, (Mapping, list, tuple)):
        try:
            raw = _stable_json(_plain(payload)).encode("utf-8")
        except (TypeError, ValueError) as error:
            raise EnvelopeError(
                "Le contenu à transmettre n'est pas sérialisable en JSON.",
                code=CODE_PAYLOAD_UNSERIALISABLE,
                field="payload",
            ) from error
    else:
        raise EnvelopeError(
            "Le contenu à transmettre doit être du texte, des octets ou une structure JSON.",
            code=CODE_PAYLOAD_TYPE,
            field="payload",
        )
    if not raw:
        raise EnvelopeError(
            "Le contenu à transmettre est vide : il n'y a rien à autoriser.",
            code=CODE_PAYLOAD_EMPTY,
            field="payload",
        )
    if len(raw) > MAX_PAYLOAD_BYTES:
        raise EnvelopeError(
            f"Le contenu dépasse {MAX_PAYLOAD_BYTES} octets : divise la transmission.",
            code=CODE_PAYLOAD_TOO_LARGE,
            field="payload",
        )
    return raw


def payload_digest(payload: Any) -> str:
    """Empreinte SHA-256 hexadécimale du contenu sérialisé exact."""

    return hashlib.sha256(canonical_payload(payload)).hexdigest()


def payload_bytes(payload: Any) -> int:
    """Taille en octets du contenu sérialisé exact."""

    return len(canonical_payload(payload))


def _plain(value: Any) -> Any:
    """Convertit une structure en types JSON natifs, sans exécuter de code."""

    if isinstance(value, Mapping):
        return {str(key): _plain(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_plain(item) for item in value]
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    raise EnvelopeError(
        "Le contenu à transmettre contient une valeur non sérialisable.",
        code="payload_unserialisable",
        field="payload",
    )


# --- Normalisation des champs de l'accord ----------------------------------


def normalise_provider(value: Any) -> str:
    """Normalise et valide le fournisseur demandé."""

    if not isinstance(value, str):
        raise EnvelopeError("Le fournisseur doit être une chaîne.", field="provider")
    text = value.strip().casefold()
    if not _PROVIDER_PATTERN.fullmatch(text):
        raise EnvelopeError(
            "Le fournisseur demandé est invalide : lettres, chiffres, point, tiret ou souligné.",
            field="provider",
        )
    return text


def normalise_model(value: Any) -> str:
    """Normalise et valide le modèle demandé.

    Le modèle fait partie de l'accord : « gemini-3.8-flash » et
    « gemini-3.6-flash » sont deux cibles distinctes.
    """

    if not isinstance(value, str):
        raise EnvelopeError("Le modèle doit être une chaîne.", field="model")
    text = value.strip()
    if not _MODEL_PATTERN.fullmatch(text):
        raise EnvelopeError(
            "Le modèle demandé est invalide : au plus 192 caractères autorisés.",
            field="model",
        )
    return text


def normalise_purpose(value: Any) -> str:
    """Normalise et valide l'objectif, dans la liste fermée :data:`PURPOSES`."""

    if not isinstance(value, str):
        raise EnvelopeError("L'objectif doit être une chaîne.", field="purpose")
    text = value.strip().casefold()
    if not _PURPOSE_PATTERN.fullmatch(text) or text not in PURPOSES:
        raise EnvelopeError(
            f"L'objectif demandé est inconnu. Valeurs autorisées : {', '.join(PURPOSES)}.",
            field="purpose",
        )
    return text


def is_local_provider(provider: str) -> bool:
    """Vrai si le fournisseur ne fait jamais sortir la donnée de la machine."""

    return provider.strip().casefold() in LOCAL_PROVIDERS


# --- Objets du contrat ------------------------------------------------------


@dataclass(frozen=True)
class TransmissionRequest:
    """Ce que l'appelant demande à envoyer, avec le contenu encore en main.

    Le champ ``payload`` est exclu de ``repr()`` et de la comparaison : une
    trace d'appel ou un message d'assertion ne peuvent pas le révéler, et deux
    demandes sont comparées par empreinte, jamais par contenu.
    """

    provider: str
    model: str
    purpose: str
    payload: Any = field(default=None, repr=False, compare=False)
    digest: str = ""
    size: int = 0

    def __post_init__(self) -> None:
        object.__setattr__(self, "provider", normalise_provider(self.provider))
        object.__setattr__(self, "model", normalise_model(self.model))
        object.__setattr__(self, "purpose", normalise_purpose(self.purpose))
        if not self.digest:
            object.__setattr__(self, "digest", payload_digest(self.payload))
            object.__setattr__(self, "size", payload_bytes(self.payload))
        elif not self.size:
            object.__setattr__(self, "size", len(canonical_payload(self.payload)))

    @property
    def payload_digest(self) -> str:
        return self.digest

    @property
    def payload_bytes(self) -> int:
        return self.size

    def serialised(self) -> bytes:
        """Octets exacts qui partiraient vers le fournisseur."""

        return canonical_payload(self.payload)

    def as_dict(self) -> dict[str, Any]:
        """Vue sûre : métadonnées et empreinte, jamais le contenu."""

        return {
            "provider": self.provider,
            "model": self.model,
            "purpose": self.purpose,
            "payload_digest": self.digest,
            "payload_bytes": self.size,
        }


@dataclass(frozen=True)
class ConsentEnvelope:
    """L'accord mémorisé : cible liée, usage unique, date d'expiration.

    L'enveloppe ne contient aucun contenu personnel, seulement son empreinte.
    """

    consent_id: str
    provider: str
    model: str
    purpose: str
    payload_digest: str
    payload_bytes: int
    issued_at: str
    expires_at: str
    state: str = "granted"
    uses_allowed: int = SINGLE_USE
    uses_consumed: int = 0
    consumed_at: str = ""
    actor: str = ""
    note: str = ""

    @property
    def binding_digest(self) -> str:
        """Empreinte de la cible liée : fournisseur, modèle, objectif, contenu."""

        blob = _stable_json(
            {
                "contract": CONTRACT_ID,
                "provider": self.provider,
                "model": self.model,
                "purpose": self.purpose,
                "payload_digest": self.payload_digest,
                "payload_bytes": self.payload_bytes,
            }
        )
        return hashlib.sha256(blob.encode("utf-8")).hexdigest()

    def is_expired(self, now: datetime | None = None) -> bool:
        """Vrai si l'instant courant dépasse l'expiration de l'accord."""

        moment = now or datetime.now(timezone.utc)
        return _parse_instant(self.expires_at) <= moment

    def is_consumed(self) -> bool:
        return self.uses_consumed >= self.uses_allowed

    def matches(self, request: TransmissionRequest) -> tuple[str, ...]:
        """Champs de l'accord qui ne correspondent plus à la demande.

        Une liste vide signifie que la demande correspond exactement à l'accord.
        """

        divergent: list[str] = []
        if self.provider != request.provider:
            divergent.append("provider")
        if self.model != request.model:
            divergent.append("model")
        if self.purpose != request.purpose:
            divergent.append("purpose")
        if not hmac.compare_digest(self.payload_digest, request.digest):
            divergent.append("payload")
        elif self.payload_bytes != request.size:
            divergent.append("payload")
        return tuple(divergent)

    def as_dict(self) -> dict[str, Any]:
        """Vue sûre, persistable et journalisable de l'accord."""

        return {
            "consent_id": self.consent_id,
            "provider": self.provider,
            "model": self.model,
            "purpose": self.purpose,
            "payload_digest": self.payload_digest,
            "payload_bytes": self.payload_bytes,
            "issued_at": self.issued_at,
            "expires_at": self.expires_at,
            "state": self.state,
            "uses_allowed": self.uses_allowed,
            "uses_consumed": self.uses_consumed,
            "consumed_at": self.consumed_at,
            "actor": self.actor,
            "note": self.note,
        }


@dataclass(frozen=True)
class ConsentDecision:
    """Réponse non levante du garde-fou : faut-il autoriser la transmission ?"""

    allowed: bool
    code: str
    message: str
    fallback: str
    consent_id: str = ""
    fields: tuple[str, ...] = ()

    def as_dict(self) -> dict[str, Any]:
        return {
            "allowed": self.allowed,
            "code": self.code,
            "message": self.message,
            "fallback": self.fallback,
            "consent_id": self.consent_id,
            "fields": list(self.fields),
        }


@dataclass(frozen=True)
class TransmissionReceipt:
    """Preuve qu'une transmission vient d'être autorisée, une seule fois.

    Le reçu prouve la consommation : il ne contient ni le contenu, ni la clé
    d'un fournisseur, seulement l'empreinte qui a été autorisée.
    """

    transmission_id: str
    consent_id: str
    provider: str
    model: str
    purpose: str
    payload_digest: str
    payload_bytes: int
    consumed_at: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "transmission_id": self.transmission_id,
            "consent_id": self.consent_id,
            "provider": self.provider,
            "model": self.model,
            "purpose": self.purpose,
            "payload_digest": self.payload_digest,
            "payload_bytes": self.payload_bytes,
            "consumed_at": self.consumed_at,
        }


# --- Instants ---------------------------------------------------------------

_TIME_FORMAT = "%Y-%m-%dT%H:%M:%SZ"


def format_instant(moment: datetime) -> str:
    """Formate un instant en UTC lisible et triable."""

    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    return moment.astimezone(timezone.utc).strftime(_TIME_FORMAT)


def _parse_instant(value: str) -> datetime:
    try:
        return datetime.strptime(value, _TIME_FORMAT).replace(tzinfo=timezone.utc)
    except (TypeError, ValueError) as error:
        raise EnvelopeError("L'instant de l'accord est illisible.", field="expires_at") from error


def resolve_expiry(
    *, ttl_seconds: int | None = None, expires_at: str | None = None, now: datetime | None = None
) -> str:
    """Calcule l'instant d'expiration d'un accord, borné par :data:`MAX_TTL_SECONDS`."""

    moment = now or datetime.now(timezone.utc)
    if expires_at:
        limit = _parse_instant(expires_at)
        if limit <= moment:
            raise EnvelopeError(
                "L'expiration demandée est déjà dépassée : aucun accord ne serait utilisable.",
                field="expires_at",
            )
        return format_instant(limit)
    ttl = DEFAULT_TTL_SECONDS if ttl_seconds is None else int(ttl_seconds)
    if ttl <= 0:
        raise EnvelopeError("La durée de validité doit être positive.", field="ttl_seconds")
    if ttl > MAX_TTL_SECONDS:
        raise EnvelopeError(
            f"La durée de validité dépasse le plafond de {MAX_TTL_SECONDS} secondes.",
            field="ttl_seconds",
        )
    return format_instant(moment + timedelta(seconds=ttl))


def new_consent_id(seed: str = "") -> str:
    """Identifiant d'accord stable, dérivé d'une graine aléatoire ou fournie."""

    source = seed or f"{datetime.now(timezone.utc).isoformat()}-{id(object())}"
    digest = hashlib.sha256(source.encode("utf-8")).hexdigest()
    return f"cgt_{digest[:32]}"


#: Alias de confort : « demande de consentement » et « demande de transmission »
#: désignent le même objet dans le contrat d'intégration.
ConsentRequest = TransmissionRequest


__all__ = [
    "CONTRACT_ID",
    "SCHEMA_ID",
    "SINGLE_USE",
    "PURPOSES",
    "LOCAL_PROVIDERS",
    "DEFAULT_TTL_SECONDS",
    "MAX_TTL_SECONDS",
    "MAX_PAYLOAD_BYTES",
    "ConsentEnvelope",
    "ConsentDecision",
    "ConsentRequest",
    "TransmissionReceipt",
    "TransmissionRequest",
    "canonical_payload",
    "format_instant",
    "is_local_provider",
    "new_consent_id",
    "normalise_model",
    "normalise_provider",
    "normalise_purpose",
    "payload_bytes",
    "payload_digest",
    "resolve_expiry",
]
