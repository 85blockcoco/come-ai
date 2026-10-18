"""Garde-fou de consentement cloud pour Côme AI.

Package autonome, local et intégrable.  Il autorise **une seule** transmission
de donnée personnelle, liée à quatre champs : le fournisseur, le modèle,
l'objectif et l'empreinte du contenu sérialisé exact.  Toute modification du
contenu ou du modèle invalide l'accord.  L'accord expire, se consomme une fois
et se révoque.

Ce paquet ne fait aucun appel réseau, ne lit aucun fichier de configuration,
ne détient aucune clé de fournisseur et ne connaît aucun transport.  Il
décide et trace ; l'intégrateur appelle son transport après consommation.

Exemple minimal ::

    from consent_guard import ConsentGuard

    guard = ConsentGuard("/dossier/local/prive")
    grant = guard.grant(
        provider="gemini",
        model="gemini-3.8-flash",
        purpose="exam_revision",
        payload="Contexte synthétique à transmettre.",
    )
    receipt = guard.consume(
        grant.consent_id,
        provider="gemini",
        model="gemini-3.8-flash",
        purpose="exam_revision",
        payload="Contexte synthétique à transmettre.",
    )
    # receipt prouve la consommation ; l'intégrateur transmet ici, une fois.

Codes de refus stables : ``consent_unknown``, ``consent_revoked``,
``consent_expired``, ``consent_exhausted``, ``envelope_mismatch``,
``invalid_request``.  Chaque refus propose le repli ``local_engine``.
"""

from __future__ import annotations

from .envelope import (
    CONTRACT_ID,
    DEFAULT_TTL_SECONDS,
    LOCAL_PROVIDERS,
    MAX_PAYLOAD_BYTES,
    MAX_TTL_SECONDS,
    PURPOSES,
    SCHEMA_ID,
    SINGLE_USE,
    ConsentDecision,
    ConsentEnvelope,
    ConsentRequest,
    TransmissionReceipt,
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
from .errors import (
    CODE_ALLOWED,
    CODE_CONSUMED_CONSENT,
    CODE_ENVELOPE_MISMATCH,
    CODE_EXPIRED_CONSENT,
    CODE_INVALID_REQUEST,
    CODE_REVOKED_CONSENT,
    CODE_UNKNOWN_CONSENT,
    ConsentGuardError,
    ConsentRefusal,
    ConsumedConsentError,
    EnvelopeError,
    EnvelopeMismatchError,
    ExpiredConsentError,
    FALLBACK_LOCAL,
    FALLBACK_NONE,
    InvalidRequestError,
    REFUSAL_CODES,
    RevokedConsentError,
    StoreError,
    UnknownConsentError,
)
from .guard import CloudTransport, ConsentGuard, fallback_notice, transmit
from .store import (
    DEFAULT_DB_NAME,
    STATE_GRANTED,
    STATE_REVOKED,
    STATE_USED,
    STORE_SCHEMA_VERSION,
    ConsentStore,
    RefusalRecord,
)

__version__ = "1.0.0"

__all__ = [
    "__version__",
    # Contrat
    "CONTRACT_ID",
    "SCHEMA_ID",
    "SINGLE_USE",
    "PURPOSES",
    "LOCAL_PROVIDERS",
    "DEFAULT_TTL_SECONDS",
    "MAX_TTL_SECONDS",
    "MAX_PAYLOAD_BYTES",
    "DEFAULT_DB_NAME",
    "STORE_SCHEMA_VERSION",
    "STATE_GRANTED",
    "STATE_USED",
    "STATE_REVOKED",
    # Objets
    "ConsentEnvelope",
    "ConsentDecision",
    "ConsentRequest",
    "TransmissionReceipt",
    "TransmissionRequest",
    "ConsentGuard",
    "ConsentStore",
    "RefusalRecord",
    "CloudTransport",
    # Fonctions
    "transmit",
    "fallback_notice",
    "canonical_payload",
    "payload_bytes",
    "payload_digest",
    "is_local_provider",
    "new_consent_id",
    "normalise_model",
    "normalise_provider",
    "normalise_purpose",
    "resolve_expiry",
    # Codes et erreurs
    "CODE_ALLOWED",
    "CODE_UNKNOWN_CONSENT",
    "CODE_REVOKED_CONSENT",
    "CODE_EXPIRED_CONSENT",
    "CODE_CONSUMED_CONSENT",
    "CODE_ENVELOPE_MISMATCH",
    "CODE_INVALID_REQUEST",
    "REFUSAL_CODES",
    "FALLBACK_LOCAL",
    "FALLBACK_NONE",
    "ConsentGuardError",
    "EnvelopeError",
    "StoreError",
    "ConsentRefusal",
    "InvalidRequestError",
    "UnknownConsentError",
    "ExpiredConsentError",
    "ConsumedConsentError",
    "RevokedConsentError",
    "EnvelopeMismatchError",
]
