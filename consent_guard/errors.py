"""Erreurs sûres et explicites du garde-fou de consentement.

Les messages sont destinés à l'utilisateur : ils ne contiennent jamais
d'extrait de contenu personnel, de chemin absolu, de clé secrète ni de détail
d'implémentation.  Chaque refus porte un **code stable** et lisible par une
machine, plus l'action de repli recommandée.

Deux familles d'erreurs seulement :

* :class:`ConsentGuardError` — l'enveloppe ou la demande est mal formée
  (erreur de programmation ou de contrat) ;

* :class:`ConsentRefusal` — la transmission est refusée, sans aucun appel
  réseau, avec un code stable et un repli documenté.
"""

from __future__ import annotations

from typing import Any

#: Code renvoyé lorsque la transmission est autorisée.
CODE_ALLOWED = "allowed"

#: Codes de refus stables, dans l'ordre où ils sont évalués.
CODE_UNKNOWN_CONSENT = "consent_unknown"
CODE_EXPIRED_CONSENT = "consent_expired"
CODE_CONSUMED_CONSENT = "consent_exhausted"
CODE_REVOKED_CONSENT = "consent_revoked"
CODE_ENVELOPE_MISMATCH = "envelope_mismatch"
CODE_INVALID_REQUEST = "invalid_request"

#: Sous-codes de ``invalid_request`` : la demande elle-même est mal formée.
CODE_PAYLOAD_EMPTY = "payload_empty"
CODE_PAYLOAD_TOO_LARGE = "payload_too_large"
CODE_PAYLOAD_TYPE = "payload_type"
CODE_PAYLOAD_UNSERIALISABLE = "payload_unserialisable"

#: Famille complète des demandes invalides, code racine compris.
INVALID_REQUEST_CODES: frozenset[str] = frozenset(
    {
        CODE_INVALID_REQUEST,
        CODE_PAYLOAD_EMPTY,
        CODE_PAYLOAD_TOO_LARGE,
        CODE_PAYLOAD_TYPE,
        CODE_PAYLOAD_UNSERIALISABLE,
    }
)

#: Tous les codes de refus reconnus par le contrat.
REFUSAL_CODES: frozenset[str] = frozenset(
    {
        CODE_UNKNOWN_CONSENT,
        CODE_EXPIRED_CONSENT,
        CODE_CONSUMED_CONSENT,
        CODE_REVOKED_CONSENT,
        CODE_ENVELOPE_MISMATCH,
    }
    | set(INVALID_REQUEST_CODES)
)

#: Repli recommandé quand rien n'est autorisé : rester en local.
FALLBACK_LOCAL = "local_engine"

#: Aucun repli nécessaire : la transmission peut partir.
FALLBACK_NONE = "none"


class ConsentGuardError(ValueError):
    """Erreur de base, sûre à afficher, sans donnée personnelle."""


class EnvelopeError(ConsentGuardError):
    """L'enveloppe ou la demande de transmission ne respecte pas le contrat."""

    def __init__(self, message: str, *, code: str = CODE_INVALID_REQUEST, field: str = "") -> None:
        super().__init__(message)
        self.code = code
        self.field = field


class StoreError(ConsentGuardError):
    """La persistance locale a rencontré un problème opérationnel."""


class ConsentRefusal(ConsentGuardError):
    """Transmission refusée avant tout contact avec un fournisseur.

    ``code`` est stable et documenté, ``fields`` liste les champs de l'accord
    qui ne correspondent plus, et ``fallback`` indique ce que l'appelant doit
    faire à la place.  Aucune de ces informations ne révèle le contenu refusé.
    """

    #: Code stable du refus, redéfini par chaque sous-classe.
    code: str = CODE_INVALID_REQUEST

    def __init__(
        self,
        message: str,
        *,
        code: str | None = None,
        fields: tuple[str, ...] = (),
        fallback: str = FALLBACK_LOCAL,
    ) -> None:
        super().__init__(message)
        if code is not None:
            self.code = code
        self.fields = tuple(fields)
        self.fallback = fallback

    def as_dict(self) -> dict[str, Any]:
        """Vue sûre du refus : codes et champs, jamais le contenu."""

        return {
            "code": self.code,
            "message": str(self),
            "fields": list(self.fields),
            "fallback": self.fallback,
        }


class InvalidRequestError(ConsentRefusal):
    """La demande de transmission est invalide (fournisseur, modèle, objectif)."""

    code = CODE_INVALID_REQUEST


class UnknownConsentError(ConsentRefusal):
    """L'identifiant d'accord ne correspond à aucun consentement connu."""

    code = CODE_UNKNOWN_CONSENT


class ExpiredConsentError(ConsentRefusal):
    """L'accord a expiré : il faut en redemander un, il n'est pas réanimé."""

    code = CODE_EXPIRED_CONSENT


class ConsumedConsentError(ConsentRefusal):
    """L'accord est à usage unique et a déjà été consommé (rejeu refusé)."""

    code = CODE_CONSUMED_CONSENT


class RevokedConsentError(ConsentRefusal):
    """L'accord a été révoqué explicitement avant son expiration."""

    code = CODE_REVOKED_CONSENT


class EnvelopeMismatchError(ConsentRefusal):
    """Un champ de l'accord ne correspond plus à la demande.

    ``fields`` porte le nom des champs divergents : toute modification du
    contenu sérialisé, du fournisseur, du modèle ou de l'objectif invalide
    l'accord.
    """

    code = CODE_ENVELOPE_MISMATCH


__all__ = [
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
    "CODE_ALLOWED",
    "CODE_UNKNOWN_CONSENT",
    "CODE_EXPIRED_CONSENT",
    "CODE_CONSUMED_CONSENT",
    "CODE_REVOKED_CONSENT",
    "CODE_ENVELOPE_MISMATCH",
    "CODE_INVALID_REQUEST",
    "CODE_PAYLOAD_EMPTY",
    "CODE_PAYLOAD_TOO_LARGE",
    "CODE_PAYLOAD_TYPE",
    "CODE_PAYLOAD_UNSERIALISABLE",
    "INVALID_REQUEST_CODES",
    "REFUSAL_CODES",
    "FALLBACK_LOCAL",
    "FALLBACK_NONE",
]
