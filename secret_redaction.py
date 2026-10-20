"""Politique unique de redaction des secrets pour toute l'application.

Historique : ``task_queue.py`` et ``usage_ledger.py`` portaient chacun leur
propre copie de ``_SECRET_PATTERNS`` et les listes ont **divergé** (le préfixe
``AQ.`` des clés admin Google n'existait que côté ledger, les en-têtes
``bearer/authorization`` ne couvraient pas exactement le même périmètre).
Un module partagé + un test croisé figent désormais l'union des deux listes :
ajouter un motif ici protège partout.
"""

from __future__ import annotations

import re
from typing import Any

SENSITIVE_KEY_PARTS = frozenset(
    {
        "apikey",
        "authorization",
        "credential",
        "cookie",
        "password",
        "passphrase",
        "privatekey",
        "secret",
        "sessiontoken",
        "token",
    }
)

SECRET_PATTERNS = (
    # Clés de style Gemini, sans dépendre du fournisseur actif.
    re.compile(r"\bAIza[0-9A-Za-z_-]{20,}\b"),
    # Clés admin de projet Google (préfixe AQ.) — partagé depuis usage_ledger.
    re.compile(r"\bAQ\.[0-9A-Za-z_-]{20,}"),
    # OpenRouter : préfixe à tirets, non couvert par la règle générique
    # à soulignés ci-dessous.
    re.compile(r"\bsk-or-v1-[0-9A-Za-z_-]{24,}\b", re.IGNORECASE),
    # Préfixes de clés d'API usuelles ; la longueur évite de masquer la prose.
    re.compile(r"\b(?:sk|rk|pk)_[A-Za-z0-9_-]{16,}\b", re.IGNORECASE),
    # En-têtes et fragments clé=valeur qu'entraînent les erreurs réseau.
    re.compile(
        r"\b(?:authorization|bearer|api[ _-]?key|token|password|secret)\s*"
        r"(?:[:=]\s*|\s+)(?:Bearer\s+)?[A-Za-z0-9_./+=-]{8,}",
        re.IGNORECASE,
    ),
)

DEFAULT_REPLACEMENT = "[secret redacted]"


def normalise_key(key: str) -> str:
    return re.sub(r"[^a-z0-9]", "", key.lower())


def is_sensitive_key(key: str) -> bool:
    normalised = normalise_key(key)
    return any(part in normalised for part in SENSITIVE_KEY_PARTS)


def redact_text(
    value: object,
    *,
    limit: int | None = None,
    replacement: str = DEFAULT_REPLACEMENT,
    squish_whitespace: bool = False,
) -> str:
    """Masquer les secrets plausibles puis borner le texte sans garder de traceback."""

    text = str(value)
    for pattern in SECRET_PATTERNS:
        text = pattern.sub(replacement, text)
    if squish_whitespace:
        text = " ".join(text.split())
    if limit is not None and len(text) > limit:
        return text[: max(0, limit - 1)] + "…"
    return text


def redact_payload(value: Any) -> Any:
    """Redaction en profondeur d'un payload d'outil (dictionnaires, listes)."""
    if isinstance(value, str):
        return redact_text(value)
    if isinstance(value, dict):
        cleaned: dict[Any, Any] = {}
        for key, item in value.items():
            if isinstance(key, str) and is_sensitive_key(key):
                cleaned[redact_text(key)] = DEFAULT_REPLACEMENT
            else:
                safe_key = redact_text(key) if isinstance(key, str) else key
                cleaned[safe_key] = redact_payload(item)
        return cleaned
    if isinstance(value, list):
        return [redact_payload(item) for item in value]
    if isinstance(value, tuple):
        return tuple(redact_payload(item) for item in value)
    return value
