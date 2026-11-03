"""Local cache and change history of the offer quality assessments (SPEC-006).

The assessment itself is pure (``career.offer_quality``).  This module owns
the two things that need a storage:

* the **snapshot** of the last assessment of each offer, so that the next
  check can tell what changed;
* the **history** of the detected changes, so that the person can read when
  a deadline moved or when a requirement disappeared.

The store is a single JSON file kept beside the other private Career data.
It never contains a secret, it is written atomically and it is readable only
by the person who owns the workspace.  A corrupted or unreadable file never
crashes the workspace: it is treated as an empty history.

The optional ``probe_source_status`` helper performs the one bounded network
call of the module.  It is never called implicitly: the refresh endpoint
only uses it when the caller explicitly asks for a forced verification.
"""

from __future__ import annotations

import json
import os
import socket
import tempfile
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any, Mapping, Optional, Sequence

from .models import clean_text


#: The version of the file format.
STORE_SCHEMA_VERSION = 1
#: The number of offers kept in the store.
MAX_TRACKED_OFFERS = 500
#: The number of changes kept for one offer.
MAX_HISTORY_PER_OFFER = 100
#: The delay of the bounded HTTP probe, in seconds.
PROBE_TIMEOUT_SECONDS = 6
#: The maximum size of the answer read by the probe.
PROBE_MAX_BYTES = 4_096


def probe_source_status(url: str, *, timeout_seconds: int = PROBE_TIMEOUT_SECONDS) -> Optional[int]:
    """Return the HTTP status of a public offer page.

    The probe is bounded: one request, a short delay, and the body is never
    read beyond a few kilobytes.  A network failure returns ``None``: an
    unreachable source is *unknown*, never "the offer is gone".

    Only a ``http``/``https`` URL is ever requested, and no credential is
    ever sent.
    """

    target = clean_text(url, limit=2_000)
    parsed = urllib.parse.urlsplit(target) if target else None
    if parsed is None or parsed.scheme.lower() not in {"http", "https"} or not parsed.hostname:
        return None
    request = urllib.request.Request(
        target,
        method="HEAD",
        headers={"User-Agent": "ComeAI-Career/1.0 (local offer freshness check)", "Accept": "*/*"},
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout_seconds) as response:  # nosec B310 - http(s) only
            return int(response.status)
    except urllib.error.HTTPError as error:
        return int(error.code)
    except (urllib.error.URLError, TimeoutError, socket.timeout, OSError, ValueError):
        return None


class OfferQualityStore:
    """The snapshots and the change history of the assessed offers."""

    def __init__(self, path: Path):
        self.path = Path(path)
        self._data: dict[str, Any] = {"schema_version": STORE_SCHEMA_VERSION, "offers": {}}

    # -- reading ---------------------------------------------------------

    def load(self) -> dict[str, Any]:
        """Read the store from the disk; a damaged file is an empty store."""

        if not self.path.exists():
            self._data = {"schema_version": STORE_SCHEMA_VERSION, "offers": {}}
            return self._data
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError, json.JSONDecodeError):
            self._data = {"schema_version": STORE_SCHEMA_VERSION, "offers": {}}
            return self._data
        if not isinstance(raw, dict) or not isinstance(raw.get("offers"), dict):
            self._data = {"schema_version": STORE_SCHEMA_VERSION, "offers": {}}
            return self._data
        self._data = raw
        self._data.setdefault("schema_version", STORE_SCHEMA_VERSION)
        return self._data

    def _offers(self) -> dict[str, Any]:
        if "offers" not in self._data or not isinstance(self._data.get("offers"), dict):
            self._data["offers"] = {}
        return self._data["offers"]

    def snapshot(self, offer_id: str) -> Optional[dict[str, Any]]:
        """Return the last snapshot of an offer (``None`` when unknown)."""

        entry = self._offers().get(clean_text(offer_id, limit=120))
        if not isinstance(entry, dict):
            return None
        quality = entry.get("quality")
        return quality if isinstance(quality, dict) else None

    def facts(self, offer_id: str) -> Optional[dict[str, Any]]:
        """Return the watched facts of the last check of an offer."""

        entry = self._offers().get(clean_text(offer_id, limit=120))
        if not isinstance(entry, dict):
            return None
        facts = entry.get("facts")
        return facts if isinstance(facts, dict) else None

    def history(self, offer_id: str) -> list[dict[str, Any]]:
        """Return the changes detected for an offer, oldest first."""

        entry = self._offers().get(clean_text(offer_id, limit=120))
        if not isinstance(entry, dict):
            return []
        history = entry.get("history")
        if not isinstance(history, list):
            return []
        return [item for item in history if isinstance(item, dict)]

    def offer_ids(self) -> list[str]:
        """Return the identifiers of the tracked offers."""

        return sorted(self._offers())

    # -- writing ---------------------------------------------------------

    def record(
        self,
        offer_id: str,
        *,
        quality: Mapping[str, Any],
        facts: Mapping[str, Any],
        changes: Sequence[Mapping[str, Any]] = (),
        assessed_at: str = "",
    ) -> dict[str, Any]:
        """Store the snapshot of an offer and append the detected changes.

        The snapshot replaces the previous one, but the history keeps every
        change ever detected, oldest first.
        """

        identifier = clean_text(offer_id, limit=120)
        if not identifier:
            raise ValueError("offer_id is required")
        offers = self._offers()
        entry = offers.get(identifier)
        if not isinstance(entry, dict):
            entry = {"offer_id": identifier, "history": []}
            offers[identifier] = entry
        history = entry.get("history")
        if not isinstance(history, list):
            history = []
        for change in changes:
            if isinstance(change, Mapping):
                history.append(dict(change))
        entry["history"] = history[-MAX_HISTORY_PER_OFFER:]
        entry["quality"] = dict(quality)
        entry["facts"] = dict(facts)
        entry["assessed_at"] = clean_text(assessed_at, limit=40)
        self.prune()
        return entry

    def prune(self) -> None:
        """Drop the oldest offers when the store grows too much."""

        offers = self._offers()
        if len(offers) <= MAX_TRACKED_OFFERS:
            return
        ordered = sorted(
            offers.items(),
            key=lambda item: str(item[1].get("assessed_at", "")) if isinstance(item[1], dict) else "",
        )
        for identifier, _entry in ordered[: len(offers) - MAX_TRACKED_OFFERS]:
            offers.pop(identifier, None)

    def save(self, updated_at: str = "") -> Path:
        """Write the store on the disk, atomically."""

        self._data["schema_version"] = STORE_SCHEMA_VERSION
        self._data["updated_at"] = clean_text(updated_at, limit=40)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        try:
            os.chmod(self.path.parent, 0o700)
        except OSError:
            pass
        payload = json.dumps(self._data, ensure_ascii=False, indent=2, sort_keys=True)
        handle = tempfile.NamedTemporaryFile(
            "w",
            encoding="utf-8",
            dir=str(self.path.parent),
            prefix=self.path.name,
            suffix=".tmp",
            delete=False,
        )
        try:
            with handle:
                handle.write(payload)
            os.chmod(handle.name, 0o600)
            os.replace(handle.name, self.path)
        except OSError:
            try:
                os.unlink(handle.name)
            except OSError:
                pass
            raise
        return self.path
