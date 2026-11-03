"""SPEC-005 — cache local du cockpit quotidien (TTL, persistance, invalidation).

Le cockpit est recalculé à partir de la base Career locale. Le cache évite de
refaire ce calcul à chaque rafraîchissement de page, tout en gardant un
refresh manuel explicite.

Règles :

* le cache est **local** : un fichier JSON dans ``career_data/``, jamais
  envoyé sur le réseau ;
* une entrée expirée est ignorée, jamais servie ;
* un fichier illisible ou corrompu est traité comme un cache vide : le
  cockpit doit toujours rester disponible ;
* l'écriture est atomique (fichier temporaire + remplacement) et le fichier
  reste en permissions privées (0600) ;
* le TTL est configurable (4 heures par défaut) sans toucher au code.
"""

from __future__ import annotations

import json
import os
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Mapping

DEFAULT_TTL_SECONDS = 4 * 60 * 60
"""TTL par défaut : quatre heures."""

TTL_ENV_VAR = "CAREER_DAILY_DIGEST_TTL_SECONDS"
"""Variable d'environnement qui ajuste le TTL sans modification du code."""

MIN_TTL_SECONDS = 60
MAX_TTL_SECONDS = 7 * 24 * 60 * 60
MAX_CACHE_BYTES = 2 * 1024 * 1024
MAX_ENTRIES = 20
CACHE_VERSION = 1


def default_ttl_seconds() -> int:
    """TTL configuré par l'environnement, borné, sinon la valeur par défaut."""

    raw = os.environ.get(TTL_ENV_VAR, "")
    try:
        value = int(str(raw).strip())
    except (TypeError, ValueError):
        return DEFAULT_TTL_SECONDS
    if value < MIN_TTL_SECONDS:
        return DEFAULT_TTL_SECONDS
    return min(value, MAX_TTL_SECONDS)


class DailyDigestStore:
    """Cache fichier du cockpit quotidien, par identifiant local."""

    def __init__(self, path: Path, *, default_ttl_seconds: int = DEFAULT_TTL_SECONDS) -> None:
        self.path = Path(path)
        self.default_ttl_seconds = max(MIN_TTL_SECONDS, int(default_ttl_seconds or DEFAULT_TTL_SECONDS))

    # -- lecture -----------------------------------------------------------
    def read(self, user_id: str, *, now: datetime | None = None) -> dict[str, Any] | None:
        """Renvoie l'entrée encore valide, sinon ``None``.

        Une entrée expirée est supprimée au passage : elle ne doit jamais être
        servie, même si le fichier n'a pas été nettoyé depuis longtemps.
        """

        moment = _utc(now)
        entries = self._load()
        key = _key(user_id)
        entry = entries.get(key)
        if not isinstance(entry, Mapping):
            return None
        expires_at = _parse_iso(entry.get("expires_at"))
        if expires_at is None or expires_at <= moment:
            entries.pop(key, None)
            self._save(entries)
            return None
        payload = entry.get("payload")
        if not isinstance(payload, Mapping):
            return None
        return {
            "payload": dict(payload),
            "generated_at": _text(entry.get("generated_at")),
            "expires_at": _text(entry.get("expires_at")),
            "ttl_seconds": int(entry.get("ttl_seconds") or self.default_ttl_seconds),
        }

    # -- écriture ----------------------------------------------------------
    def write(
        self,
        user_id: str,
        payload: Mapping[str, Any],
        *,
        now: datetime | None = None,
        ttl_seconds: int | None = None,
    ) -> dict[str, Any]:
        """Enregistre le digest et renvoie ses métadonnées de cache."""

        moment = _utc(now)
        ttl = self._resolve_ttl(ttl_seconds)
        expires_at = moment + timedelta(seconds=ttl)
        entries = self._load()
        entries[_key(user_id)] = {
            "payload": dict(payload),
            "generated_at": _iso_z(moment),
            "expires_at": _iso_z(expires_at),
            "ttl_seconds": ttl,
        }
        self._save(entries)
        return {
            "generated_at": _iso_z(moment),
            "expires_at": _iso_z(expires_at),
            "ttl_seconds": ttl,
        }

    def invalidate(self, user_id: str) -> bool:
        """Supprime l'entrée d'un utilisateur ; renvoie ``True`` s'il y en avait une."""

        entries = self._load()
        key = _key(user_id)
        removed = entries.pop(key, None) is not None
        if removed:
            self._save(entries)
        return removed

    def clear(self) -> None:
        """Vide entièrement le cache local du cockpit."""

        self._save({})

    # -- interne -----------------------------------------------------------
    def _resolve_ttl(self, ttl_seconds: int | None) -> int:
        if ttl_seconds is None:
            return self.default_ttl_seconds
        try:
            value = int(ttl_seconds)
        except (TypeError, ValueError):
            return self.default_ttl_seconds
        if value < MIN_TTL_SECONDS:
            return self.default_ttl_seconds
        return min(value, MAX_TTL_SECONDS)

    def _load(self) -> dict[str, dict[str, Any]]:
        try:
            if not self.path.is_file():
                return {}
            if self.path.stat().st_size > MAX_CACHE_BYTES:
                return {}
            raw = self.path.read_text(encoding="utf-8")
        except (OSError, ValueError):
            return {}
        try:
            document = json.loads(raw)
        except (TypeError, ValueError):
            return {}
        if not isinstance(document, Mapping):
            return {}
        entries = document.get("entries")
        if not isinstance(entries, Mapping):
            return {}
        return {
            str(key): dict(value)
            for key, value in entries.items()
            if isinstance(value, Mapping)
        }

    def _save(self, entries: Mapping[str, Mapping[str, Any]]) -> None:
        document = {
            "version": CACHE_VERSION,
            "entries": dict(list(entries.items())[:MAX_ENTRIES]),
        }
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with tempfile.NamedTemporaryFile(
                "w",
                encoding="utf-8",
                dir=str(self.path.parent),
                prefix=self.path.name,
                suffix=".tmp",
                delete=False,
            ) as handle:
                temporary = Path(handle.name)
                json.dump(document, handle, ensure_ascii=False, sort_keys=True)
            try:
                os.chmod(temporary, 0o600)
            except OSError:
                pass
            os.replace(temporary, self.path)
        except OSError:
            # Le cache est un confort : son échec ne doit jamais casser le cockpit.
            try:
                temporary.unlink(missing_ok=True)
            except (OSError, UnboundLocalError, NameError):
                pass


def _key(user_id: str) -> str:
    text = str(user_id or "").strip()
    return text or "local"


def _utc(moment: datetime | None) -> datetime:
    if moment is None:
        return datetime.now(timezone.utc)
    if moment.tzinfo is None:
        return moment.replace(tzinfo=timezone.utc)
    return moment.astimezone(timezone.utc)


def _iso_z(moment: datetime) -> str:
    return moment.astimezone(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _parse_iso(value: Any) -> datetime | None:
    text = _text(value)
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _text(value: Any) -> str:
    return str(value or "").strip()
