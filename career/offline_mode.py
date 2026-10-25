"""Offline reads with an expiring local cache (SPEC-032).

The Career space must remain usable without a network: the last local copy of
an offer list, an application checklist or a dossier can be served while the
train Wi-Fi is down.  This module is deliberately independent from the
Career SQLite schema (``SCHEMA_VERSION`` is untouched): the cache is a bounded
JSON file inside the private ``career_data`` directory, readable only by the
local user account.

Design rules:

* A cache entry never pretends to be fresh.  ``serve_or_cache`` reports
  ``network``, ``cache`` (still within ``max_age_hours``) or ``stale`` (older
  than the policy) and lists the fields a person must re-check.
* Any unreadable, truncated or tampered cache file is ignored rather than
  crashing the application; invalid entries are dropped individually.
* Keys are validated against a closed alphabet, so a key can never escape the
  cache directory or inject a path.
* Nothing here performs a network call: callers pass the reader explicitly.
"""

from __future__ import annotations

import json
import os
import re
import tempfile
import threading
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Literal, Mapping

CACHE_FILE_NAME = "offline_cache.json"
CACHE_SCHEMA_VERSION = 1
DEFAULT_MAX_AGE_HOURS = 24
MAX_MAX_AGE_HOURS = 24 * 365
MAX_CACHE_ENTRIES = 80
MAX_PAYLOAD_BYTES = 256 * 1024
MAX_CACHE_FILE_BYTES = 8 * 1024 * 1024

#: Freshness policy (hours) per read kind.  A "job list" is cheaper to refresh
#: than a checklist a person spent time filling in, so the defaults differ.
FRESHNESS_POLICY_HOURS: dict[str, int] = {
    "jobs": 6,
    "offers": 6,
    "dashboard": 6,
    "applications": 12,
    "dossiers": 12,
    "profile": 24,
    "checklists": 72,
    "default": DEFAULT_MAX_AGE_HOURS,
}

MAX_AGE_ENV = "CAREER_OFFLINE_MAX_AGE_HOURS"

_KEY_PATTERN = re.compile(r"^[a-z0-9][a-z0-9._:-]{0,119}$")
_KIND_PATTERN = re.compile(r"^[a-z0-9][a-z0-9_-]{0,39}$")

OfflineSource = Literal["network", "cache", "stale"]


class OfflineCacheError(ValueError):
    """A cache request or a cached document is not usable."""


class OfflineDataUnavailable(OfflineCacheError):
    """Neither the network reader nor a cache entry can answer the read."""


@dataclass(frozen=True)
class CacheEntry:
    key: str
    payload: dict[str, Any]
    fetched_at: str  # ISO-8601, stored with an explicit UTC offset
    max_age_hours: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "key": self.key,
            "payload": self.payload,
            "fetched_at": self.fetched_at,
            "max_age_hours": self.max_age_hours,
        }

    @classmethod
    def from_dict(cls, raw: Any) -> "CacheEntry":
        """Parse one stored entry, rejecting anything surprising."""
        if not isinstance(raw, dict):
            raise OfflineCacheError("Entrée de cache invalide.")
        key = raw.get("key")
        payload = raw.get("payload")
        fetched_at = raw.get("fetched_at")
        max_age_hours = raw.get("max_age_hours")
        if not isinstance(key, str) or not _KEY_PATTERN.fullmatch(key):
            raise OfflineCacheError("Clé de cache invalide.")
        if not isinstance(payload, dict) or not payload:
            raise OfflineCacheError("Contenu de cache invalide.")
        if not isinstance(fetched_at, str):
            raise OfflineCacheError("Horodatage de cache invalide.")
        parse_timestamp(fetched_at)
        if type(max_age_hours) is not int or not 1 <= max_age_hours <= MAX_MAX_AGE_HOURS:
            raise OfflineCacheError("Durée de fraîcheur invalide.")
        return cls(
            key=key,
            payload=payload,
            fetched_at=fetched_at,
            max_age_hours=max_age_hours,
        )


@dataclass(frozen=True)
class OfflineDecision:
    source: OfflineSource
    age_hours: float | None
    degraded_fields: list[str]


@dataclass(frozen=True)
class OfflineRead:
    payload: dict[str, Any]
    decision: OfflineDecision


def normalize_key(key: Any) -> str:
    """Return a safe cache key or raise a non-echoing error."""
    if not isinstance(key, str) or not _KEY_PATTERN.fullmatch(key):
        raise OfflineCacheError(
            "Clé de cache invalide : minuscules, chiffres et « . _ : - » uniquement, 120 caractères maximum."
        )
    return key


def normalize_kind(kind: Any) -> str:
    if not isinstance(kind, str) or not _KIND_PATTERN.fullmatch(kind):
        raise OfflineCacheError(
            "Type de lecture hors-ligne invalide : minuscules, chiffres et « _ - » uniquement."
        )
    return kind


def parse_timestamp(value: str) -> datetime:
    """Parse an ISO timestamp; naive values are treated as UTC."""
    if not isinstance(value, str):
        raise OfflineCacheError("Horodatage de cache invalide.")
    text = value.strip()
    if not text or len(text) > 64:
        raise OfflineCacheError("Horodatage de cache invalide.")
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError as error:
        raise OfflineCacheError("Horodatage de cache invalide.") from error
    return _as_utc(parsed)


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def freshness_policy(
    kind: str = "default",
    *,
    overrides: Mapping[str, int] | None = None,
    environ: Mapping[str, str] | None = None,
) -> int:
    """Return the freshness window (hours) for one read kind.

    ``overrides`` is a programmatic policy (invalid values raise, they are a
    developer error).  ``CAREER_OFFLINE_MAX_AGE_HOURS`` only replaces the
    default window; a malformed environment value is ignored so a bad export
    in a shell profile cannot make the local app unusable.
    """
    normalized = str(kind or "default").strip().lower() or "default"
    if overrides and normalized in overrides:
        return _validated_hours(overrides[normalized])
    if normalized in FRESHNESS_POLICY_HOURS:
        return FRESHNESS_POLICY_HOURS[normalized]
    env = os.environ if environ is None else environ
    raw = str(env.get(MAX_AGE_ENV, "")).strip()
    if raw:
        try:
            return _validated_hours(int(raw, 10))
        except (OfflineCacheError, ValueError):
            pass
    return DEFAULT_MAX_AGE_HOURS


def _validated_hours(value: Any) -> int:
    if type(value) is not int or not 1 <= value <= MAX_MAX_AGE_HOURS:
        raise OfflineCacheError(
            f"Durée de fraîcheur invalide : entier de 1 à {MAX_MAX_AGE_HOURS} heures attendu."
        )
    return value


def entry_age_hours(entry: CacheEntry, *, now: datetime | None = None) -> float:
    """Age of an entry in hours; negative ages (clock skew) are clamped to 0."""
    current = _as_utc(now) if now is not None else datetime.now(timezone.utc)
    fetched = parse_timestamp(entry.fetched_at)
    seconds = (current - fetched).total_seconds()
    return round(max(0.0, seconds) / 3600.0, 3)


def decision_for_entry(
    entry: CacheEntry, *, now: datetime | None = None
) -> OfflineDecision:
    age = entry_age_hours(entry, now=now)
    if age <= entry.max_age_hours:
        return OfflineDecision(source="cache", age_hours=age, degraded_fields=[])
    return OfflineDecision(
        source="stale",
        age_hours=age,
        degraded_fields=sorted(str(field) for field in entry.payload),
    )


def offline_banner(decision: OfflineDecision) -> dict[str, Any]:
    """The small status strip the interface shows in offline mode."""
    age = decision.age_hours
    if decision.source == "network":
        return {
            "offline": False,
            "level": "online",
            "source": decision.source,
            "age_hours": age,
            "degraded_fields": list(decision.degraded_fields),
            "message": "Données actualisées à l'instant.",
        }
    hours = f"{age:.1f} h" if age is not None else "âge inconnu"
    if decision.source == "cache":
        return {
            "offline": True,
            "level": "cached",
            "source": decision.source,
            "age_hours": age,
            "degraded_fields": [],
            "message": f"Mode hors-ligne — copie locale vieille de {hours}.",
        }
    count = len(decision.degraded_fields)
    return {
        "offline": True,
        "level": "stale",
        "source": decision.source,
        "age_hours": age,
        "degraded_fields": list(decision.degraded_fields),
        "message": (
            f"Mode hors-ligne — copie locale vieille de {hours} ; "
            f"{count} champ(s) à revérifier avant toute décision."
        ),
    }


def serve_or_cache(
    cache_key: str,
    *,
    cache: "OfflineCache",
    reader: Callable[[], dict[str, Any]] | None = None,
    network_ok: bool = True,
    kind: str = "default",
    max_age_hours: int | None = None,
    now: datetime | None = None,
) -> OfflineRead:
    """Serve a fresh read, a cached copy, or an explicitly stale copy.

    ``reader`` is only invoked when ``network_ok`` is true.  A failing reader
    (timeout, connector error, …) transparently falls back to the cache.  If
    no copy exists, :class:`OfflineDataUnavailable` is raised so the caller can
    show an honest empty state instead of invented data.
    """
    key = normalize_key(cache_key)
    kind = normalize_kind(kind)
    if max_age_hours is not None:
        max_age_hours = _validated_hours(max_age_hours)

    if network_ok and reader is not None:
        try:
            payload = reader()
        except Exception:
            payload = None
        if payload is not None:
            if not isinstance(payload, dict):
                raise OfflineCacheError("La lecture réseau doit produire un objet JSON.")
            try:
                cache.put(
                    key,
                    payload,
                    kind=kind,
                    max_age_hours=max_age_hours,
                    fetched_at=(_as_utc(now) if now is not None else None),
                )
            except (OfflineCacheError, OSError):
                # Serving fresh data matters more than persisting a copy.
                pass
            return OfflineRead(
                payload=payload,
                decision=OfflineDecision(source="network", age_hours=0.0, degraded_fields=[]),
            )

    entry = cache.get(key)
    if entry is None:
        raise OfflineDataUnavailable(
            f"Aucune copie locale pour « {key} » : reconnecte-toi une fois pour l'enregistrer."
        )
    return OfflineRead(payload=entry.payload, decision=decision_for_entry(entry, now=now))


class OfflineCache:
    """Bounded JSON cache stored in a private local directory."""

    def __init__(
        self,
        directory: Path | str,
        *,
        clock: Callable[[], datetime] | None = None,
        max_entries: int = MAX_CACHE_ENTRIES,
        environ: Mapping[str, str] | None = None,
    ) -> None:
        if type(max_entries) is not int or not 1 <= max_entries <= 1_000:
            raise OfflineCacheError("Nombre maximal d'entrées de cache invalide.")
        self.directory = Path(directory)
        self.path = self.directory / CACHE_FILE_NAME
        self.max_entries = max_entries
        self._clock = clock or (lambda: datetime.now(timezone.utc))
        self._environ = environ
        self._lock = threading.RLock()
        self._dropped = 0
        self._corrupted = False

    # -- internal storage -------------------------------------------------
    def _now(self, now: datetime | None = None) -> datetime:
        return _as_utc(now) if now is not None else _as_utc(self._clock())

    def _read_store(self) -> dict[str, CacheEntry]:
        with self._lock:
            try:
                if self.path.stat().st_size > MAX_CACHE_FILE_BYTES:
                    self._corrupted = True
                    self._dropped = 0
                    return {}
                raw_text = self.path.read_text(encoding="utf-8")
            except FileNotFoundError:
                self._corrupted = False
                self._dropped = 0
                return {}
            except OSError:
                self._corrupted = True
                self._dropped = 0
                return {}
            try:
                data = json.loads(raw_text)
            except (TypeError, ValueError):
                self._corrupted = True
                self._dropped = 0
                return {}
            if (
                not isinstance(data, dict)
                or data.get("schema_version") != CACHE_SCHEMA_VERSION
                or not isinstance(data.get("entries"), dict)
            ):
                self._corrupted = True
                self._dropped = 0
                return {}
            entries: dict[str, CacheEntry] = {}
            dropped = 0
            for raw_key, raw_entry in data["entries"].items():
                try:
                    entry = CacheEntry.from_dict(raw_entry)
                    if entry.key != raw_key:
                        raise OfflineCacheError("Entrée de cache déplacée.")
                except OfflineCacheError:
                    dropped += 1
                    continue
                entries[entry.key] = entry
            self._corrupted = False
            self._dropped = dropped
            return entries

    def _serialize(self, entries: dict[str, CacheEntry]) -> str:
        ordered = sorted(
            entries.values(),
            key=lambda entry: (parse_timestamp(entry.fetched_at), entry.key),
        )
        keep = ordered[-self.max_entries:]
        document = {
            "schema_version": CACHE_SCHEMA_VERSION,
            "entries": {entry.key: entry.to_dict() for entry in keep},
        }
        text = json.dumps(document, ensure_ascii=False, sort_keys=True)
        while len(text.encode("utf-8")) > MAX_CACHE_FILE_BYTES and len(keep) > 1:
            keep = keep[1:]
            document["entries"] = {entry.key: entry.to_dict() for entry in keep}
            text = json.dumps(document, ensure_ascii=False, sort_keys=True)
        return text

    def _write_store(self, entries: dict[str, CacheEntry]) -> None:
        with self._lock:
            self._ensure_directory()
            text = self._serialize(entries)
            descriptor, temporary = tempfile.mkstemp(
                prefix=".offline-cache-", suffix=".tmp", dir=self.directory
            )
            try:
                os.chmod(temporary, 0o600)
                with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
                    handle.write(text)
                os.replace(temporary, self.path)
            finally:
                try:
                    os.unlink(temporary)
                except FileNotFoundError:
                    pass

    def _ensure_directory(self) -> None:
        self.directory.mkdir(parents=True, exist_ok=True)
        try:
            os.chmod(self.directory, 0o700)
        except OSError:
            pass

    # -- public API -------------------------------------------------------
    def put(
        self,
        key: str,
        payload: dict[str, Any],
        *,
        kind: str = "default",
        max_age_hours: int | None = None,
        fetched_at: datetime | str | None = None,
    ) -> CacheEntry:
        """Store one local copy; ``max_age_hours`` defaults to the policy."""
        normalized_key = normalize_key(key)
        normalized_kind = normalize_kind(kind)
        if max_age_hours is None:
            max_age_hours = freshness_policy(normalized_kind, environ=self._environ)
        hours = _validated_hours(max_age_hours)
        clean_payload = _validated_payload(payload)
        if fetched_at is None:
            fetched = self._now()
        elif isinstance(fetched_at, datetime):
            fetched = _as_utc(fetched_at)
        else:
            fetched = parse_timestamp(fetched_at)
        entry = CacheEntry(
            key=normalized_key,
            payload=clean_payload,
            fetched_at=fetched.isoformat(),
            max_age_hours=hours,
        )
        with self._lock:
            entries = self._read_store()
            entries[normalized_key] = entry
            self._write_store(entries)
        return entry

    def get(self, key: str) -> CacheEntry | None:
        normalized_key = normalize_key(key)
        with self._lock:
            return self._read_store().get(normalized_key)

    def delete(self, key: str) -> bool:
        normalized_key = normalize_key(key)
        with self._lock:
            entries = self._read_store()
            if normalized_key not in entries:
                return False
            del entries[normalized_key]
            self._write_store(entries)
            return True

    def clear(self) -> int:
        with self._lock:
            entries = self._read_store()
            count = len(entries)
            try:
                self.path.unlink()
            except FileNotFoundError:
                pass
            except OSError as error:
                raise OfflineCacheError(
                    "Le cache hors-ligne local n'a pas pu être effacé."
                ) from error
            self._dropped = 0
            self._corrupted = False
            return count

    def summaries(self, *, now: datetime | None = None) -> list[dict[str, Any]]:
        """Cache inventory without exposing the cached payloads themselves."""
        with self._lock:
            entries = self._read_store()
        current = self._now(now)
        result = []
        for entry in sorted(entries.values(), key=lambda item: item.key):
            age = entry_age_hours(entry, now=current)
            result.append(
                {
                    "key": entry.key,
                    "fetched_at": entry.fetched_at,
                    "max_age_hours": entry.max_age_hours,
                    "age_hours": age,
                    "stale": age > entry.max_age_hours,
                    "field_count": len(entry.payload),
                }
            )
        return result

    def status(self, *, now: datetime | None = None) -> dict[str, Any]:
        with self._lock:
            entries = self._read_store()
            corrupted = self._corrupted
            dropped = self._dropped
        current = self._now(now)
        stale = sum(
            1
            for entry in entries.values()
            if entry_age_hours(entry, now=current) > entry.max_age_hours
        )
        return {
            "schema_version": CACHE_SCHEMA_VERSION,
            "storage": "local_user_dir",
            "cache_file": CACHE_FILE_NAME,
            "entry_count": len(entries),
            "stale_count": stale,
            "dropped_entries": dropped,
            "corrupted": corrupted,
            "max_entries": self.max_entries,
            "policy_hours": dict(FRESHNESS_POLICY_HOURS),
        }


def _validated_payload(payload: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(payload, dict) or not payload:
        raise OfflineCacheError("Le contenu mis en cache doit être un objet JSON non vide.")
    try:
        encoded = json.dumps(
            payload, ensure_ascii=False, allow_nan=False
        ).encode("utf-8")
    except (TypeError, ValueError) as error:
        raise OfflineCacheError(
            "Le contenu mis en cache doit être sérialisable en JSON."
        ) from error
    if len(encoded) > MAX_PAYLOAD_BYTES:
        raise OfflineCacheError(
            f"Contenu hors-ligne trop volumineux ({MAX_PAYLOAD_BYTES // 1024} Ko maximum)."
        )
    return payload


__all__ = [
    "CACHE_FILE_NAME",
    "CACHE_SCHEMA_VERSION",
    "CacheEntry",
    "DEFAULT_MAX_AGE_HOURS",
    "FRESHNESS_POLICY_HOURS",
    "MAX_AGE_ENV",
    "MAX_CACHE_ENTRIES",
    "MAX_MAX_AGE_HOURS",
    "MAX_PAYLOAD_BYTES",
    "OfflineCache",
    "OfflineCacheError",
    "OfflineDataUnavailable",
    "OfflineDecision",
    "OfflineRead",
    "decision_for_entry",
    "entry_age_hours",
    "freshness_policy",
    "normalize_key",
    "normalize_kind",
    "offline_banner",
    "parse_timestamp",
    "serve_or_cache",
]
