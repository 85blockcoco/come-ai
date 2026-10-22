"""Local persistence for the evidence freshness layer — private and offline.

The freshness layer is transverse: it does not own the proofs themselves,
it only tracks how old they are.  It therefore keeps its own small,
self-describing state file inside the private Career directory instead of
adding a table to the main Career schema.

The state file is written atomically (temporary file + ``os.replace``) so an
interrupted write never leaves a half-written state behind, and it is only
readable by the person who owns the machine.
"""

from __future__ import annotations

import json
import os
import threading
import uuid
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Iterable

from .evidence_freshness import (
    CHECK_METHODS,
    CHECK_RESULTS,
    COVERAGE_COVERED,
    COVERAGE_TO_REVERIFY,
    FRESHNESS_POLICIES,
    FREQUENCY_INTERVAL_DAYS,
    MAX_AUTO_ACTIONS,
    SourceCheck,
    check_frequency,
    instant_to_text,
    is_check_due,
    normalize_policy,
    parse_instant,
    utc_now,
)
from .models import clean_text


STATE_FILENAME = "evidence_freshness.json"
SCHEMA_VERSION = 1
DIRECTORY_NAME = "evidence_freshness"

#: A state file never grows without bound: the oldest snapshots and the
#: oldest checks of a proof are dropped first.
MAX_SNAPSHOTS = 400
MAX_CHECKS_PER_EVIDENCE = 50


def _empty_state() -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "policies": {},
        "evidence": {},
        "alerts": {},
        "snapshots": [],
    }


def _bounded(value: Any, limit: int) -> str:
    return clean_text(value, limit=limit)


def _as_dict(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, dict) else {}


def _as_list(value: Any) -> list[Any]:
    return list(value) if isinstance(value, list) else []


class EvidenceFreshnessStore:
    """File-backed store of the freshness state of a candidate's proofs."""

    def __init__(self, career_data_dir: Path):
        self.directory = career_data_dir / DIRECTORY_NAME
        self.path = self.directory / STATE_FILENAME
        self._lock = threading.RLock()

    # -- persistence ------------------------------------------------------

    def _ensure_directory(self) -> None:
        self.directory.mkdir(parents=True, exist_ok=True)
        try:
            os.chmod(self.directory, 0o700)
        except OSError:
            pass

    def _load(self) -> dict[str, Any]:
        if not self.path.exists():
            return _empty_state()
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return _empty_state()
        if not isinstance(raw, dict):
            return _empty_state()
        state = _empty_state()
        policies = _as_dict(raw.get("policies"))
        evidence = _as_dict(raw.get("evidence"))
        alerts = _as_dict(raw.get("alerts"))
        snapshots = [item for item in _as_list(raw.get("snapshots")) if isinstance(item, dict)]
        state["policies"] = {key: _as_dict(value) for key, value in policies.items()}
        state["evidence"] = {key: _as_dict(value) for key, value in evidence.items()}
        state["alerts"] = {key: _as_dict(value) for key, value in alerts.items()}
        state["snapshots"] = snapshots[-MAX_SNAPSHOTS:]
        return state

    def _save(self, state: dict[str, Any]) -> None:
        self._ensure_directory()
        payload = json.dumps(state, ensure_ascii=False, indent=2, sort_keys=True)
        temporary = self.path.with_suffix(".tmp")
        try:
            temporary.write_text(payload, encoding="utf-8")
            try:
                os.chmod(temporary, 0o600)
            except OSError:
                pass
            os.replace(temporary, self.path)
        except OSError as error:
            temporary.unlink(missing_ok=True)
            raise OSError("Le suivi de la fraîcheur des preuves n’a pas pu être enregistré.") from error

    # -- policies ---------------------------------------------------------

    def policies(self) -> dict[str, Any]:
        """Return the person-made policy overrides."""
        with self._lock:
            return dict(self._load()["policies"])

    def set_policy(self, evidence_type: str, policy: dict[str, Any]) -> dict[str, Any]:
        """Store the policy of one evidence type."""
        normalized = normalize_policy(policy)
        with self._lock:
            state = self._load()
            state["policies"][evidence_type] = normalized
            self._save(state)
        return normalized

    def reset_policy(self, evidence_type: str) -> bool:
        """Drop the override of one evidence type; ``True`` when it existed."""
        with self._lock:
            state = self._load()
            existed = evidence_type in state["policies"]
            state["policies"].pop(evidence_type, None)
            self._save(state)
        return existed

    def effective_policies(self) -> dict[str, Any]:
        """Return the shipped policies merged with the person-made overrides."""
        policies = {key: dict(value) for key, value in FRESHNESS_POLICIES.items()}
        for key, value in self.policies().items():
            policies[key] = value
        return policies

    # -- evidence ---------------------------------------------------------

    def list_evidence(self) -> list[dict[str, Any]]:
        """Return every tracked proof, oldest first."""
        with self._lock:
            evidence = self._load()["evidence"]
            records = [_as_dict(value) for value in evidence.values()]
        records.sort(key=lambda record: (str(record.get("created_at") or ""), str(record.get("id") or "")))
        return records

    def get_evidence(self, evidence_id: str) -> dict[str, Any] | None:
        """Return one proof, or ``None`` when it is unknown."""
        with self._lock:
            record = self._load()["evidence"].get(evidence_id)
        return _as_dict(record) if isinstance(record, dict) else None

    def save_evidence(self, record: dict[str, Any]) -> dict[str, Any]:
        """Create or replace one proof."""
        payload = _as_dict(record)
        history = [item for item in _as_list(payload.get("auto_actions")) if isinstance(item, dict)]
        if history:
            payload["auto_actions"] = history[-MAX_AUTO_ACTIONS:]
        with self._lock:
            state = self._load()
            state["evidence"][str(payload.get("id"))] = payload
            self._save(state)
        return dict(payload)

    def delete_evidence(self, evidence_id: str) -> bool:
        """Remove one proof and the alerts it raised."""
        with self._lock:
            state = self._load()
            existed = evidence_id in state["evidence"]
            state["evidence"].pop(evidence_id, None)
            for alert_id, alert in list(state["alerts"].items()):
                if isinstance(alert, dict) and alert.get("evidence_id") == evidence_id:
                    state["alerts"].pop(alert_id, None)
            self._save(state)
        return existed

    # -- source checks ----------------------------------------------------

    def record_check(self, evidence_id: str, check: SourceCheck) -> dict[str, Any]:
        """Append an external verification to a proof.

        The consequence of the check depends on its outcome: an unchanged
        source refreshes the proof, a changed source asks for a new
        verification, a removed source is treated as a revocation.
        """
        now = utc_now()
        with self._lock:
            state = self._load()
            record = _as_dict(state["evidence"].get(evidence_id))
            if not record:
                raise KeyError(evidence_id)
            checks = [item for item in _as_list(record.get("source_checks")) if isinstance(item, dict)]
            checks.append(
                {
                    "check_id": check.check_id,
                    "checked_at": check.checked_at,
                    "source_url": check.source_url,
                    "method": check.method,
                    "result": check.result,
                    "details": dict(check.details),
                }
            )
            record["source_checks"] = checks[-MAX_CHECKS_PER_EVIDENCE:]
            if check.result == "unchanged":
                record["last_verified_at"] = instant_to_text(now)
                if record.get("coverage_status") == COVERAGE_TO_REVERIFY:
                    record["coverage_status"] = COVERAGE_COVERED
            elif check.result == "updated":
                record["coverage_status"] = COVERAGE_TO_REVERIFY
            elif check.result == "removed":
                # The source no longer exists: the proof is treated as
                # expired at the instant of the check, never as still valid.
                record["coverage_status"] = COVERAGE_TO_REVERIFY
                record["expires_at"] = instant_to_text(now)
            record["updated_at"] = instant_to_text(now)
            state["evidence"][evidence_id] = record
            self._save(state)
        return record

    def checks_of(self, evidence_id: str) -> list[dict[str, Any]]:
        """Return the verifications already performed on a proof."""
        record = self.get_evidence(evidence_id)
        if not record:
            return []
        return [item for item in _as_list(record.get("source_checks")) if isinstance(item, dict)]

    # -- alerts -----------------------------------------------------------

    def list_alerts(self, *, active_only: bool = True) -> list[dict[str, Any]]:
        """Return the raised alerts, most severe first."""
        with self._lock:
            alerts = [_as_dict(value) for value in self._load()["alerts"].values()]
        if active_only:
            alerts = [alert for alert in alerts if not alert.get("acknowledged")]
        alerts.sort(key=lambda alert: (str(alert.get("created_at") or ""), str(alert.get("evidence_id") or "")))
        alerts.reverse()
        return alerts

    def has_alert(self, evidence_id: str, code: str) -> bool:
        """Return whether an alert of this kind is already open."""
        with self._lock:
            for alert in self._load()["alerts"].values():
                if not isinstance(alert, dict) or alert.get("acknowledged"):
                    continue
                if alert.get("evidence_id") == evidence_id and alert.get("code") == code:
                    return True
        return False

    def add_alert(self, alert: dict[str, Any]) -> dict[str, Any]:
        """Store an alert, ignoring a duplicate still open on the same proof."""
        payload = _as_dict(alert)
        evidence_id = str(payload.get("evidence_id") or "")
        code = str(payload.get("code") or "")
        if not evidence_id or not code:
            raise ValueError("An alert needs an evidence identifier and a code.")
        with self._lock:
            state = self._load()
            for existing in state["alerts"].values():
                if not isinstance(existing, dict) or existing.get("acknowledged"):
                    continue
                if existing.get("evidence_id") == evidence_id and existing.get("code") == code:
                    return dict(existing)
            alert_id = str(payload.get("alert_id") or f"alert_{uuid.uuid4().hex[:12]}")
            stored = {**payload, "alert_id": alert_id}
            state["alerts"][alert_id] = stored
            self._save(state)
        return stored

    def acknowledge_alert(self, alert_id: str) -> dict[str, Any] | None:
        """Acknowledge one alert; ``None`` when it is unknown."""
        now = instant_to_text(utc_now())
        with self._lock:
            state = self._load()
            alert = state["alerts"].get(alert_id)
            if not isinstance(alert, dict):
                return None
            updated = {**alert, "acknowledged": True, "acknowledged_at": now}
            state["alerts"][alert_id] = updated
            self._save(state)
        return updated

    # -- history ----------------------------------------------------------

    def record_snapshot(self, snapshot: dict[str, Any]) -> dict[str, Any]:
        """Store one point of the freshness history."""
        with self._lock:
            state = self._load()
            entry = {**snapshot, "at": str(snapshot.get("at") or instant_to_text(utc_now()))}
            state["snapshots"].append(entry)
            state["snapshots"] = state["snapshots"][-MAX_SNAPSHOTS:]
            self._save(state)
        return entry

    def snapshots(self, *, window_days: int | None = None) -> list[dict[str, Any]]:
        """Return the freshness history, oldest first."""
        with self._lock:
            snapshots = [dict(item) for item in self._load()["snapshots"]]
        if window_days is None:
            return snapshots
        limit = utc_now() - timedelta(days=max(0, int(window_days)))
        kept = [item for item in snapshots if (parse_instant(item.get("at")) or limit) >= limit]
        return kept

    # -- scheduling -------------------------------------------------------

    def due_checks(self, freshnesses: Iterable[Any], *, now: datetime | None = None) -> list[dict[str, Any]]:
        """Return the proofs whose scheduled verification is due.

        The cadence comes from the policy of the proof: a proof inside its
        warning window is re-checked every day, a certification every week,
        a technical skill every month, an experience every quarter.
        """
        reference = now or utc_now()
        due: list[dict[str, Any]] = []
        for freshness in freshnesses:
            record = self.get_evidence(freshness.evidence_id)
            if not record:
                continue
            frequency = check_frequency(record, freshness, now=reference)
            last_checked = ""
            checks = [item for item in _as_list(record.get("source_checks")) if isinstance(item, dict)]
            if checks:
                last_checked = str(checks[-1].get("checked_at") or "")
            if not is_check_due(last_checked, frequency, now=reference):
                continue
            due.append(
                {
                    "evidence_id": freshness.evidence_id,
                    "frequency": frequency,
                    "interval_days": FREQUENCY_INTERVAL_DAYS.get(frequency, 90),
                    "last_checked_at": last_checked,
                    "status": freshness.status,
                }
            )
        due.sort(key=lambda item: (item["interval_days"], item["evidence_id"]))
        return due

    # -- lifecycle --------------------------------------------------------

    def reset(self) -> None:
        """Remove the whole freshness state, including its history."""
        with self._lock:
            self.path.unlink(missing_ok=True)
            temporary = self.path.with_suffix(".tmp")
            temporary.unlink(missing_ok=True)


def normalize_check(
    *,
    method: str,
    result: str,
    source_url: str = "",
    details: dict[str, Any] | None = None,
    check_id: str = "",
    checked_at: str = "",
) -> SourceCheck:
    """Validate the outcome of an external verification."""
    clean_method = _bounded(method, 20).lower()
    if clean_method not in CHECK_METHODS:
        raise ValueError(f"Méthode de vérification non prise en charge : {clean_method or '—'}")
    clean_result = _bounded(result, 20).lower()
    if clean_result not in CHECK_RESULTS:
        raise ValueError(f"Résultat de vérification non pris en charge : {clean_result or '—'}")
    return SourceCheck(
        check_id=_bounded(check_id, 80) or f"check_{uuid.uuid4().hex[:12]}",
        checked_at=_bounded(checked_at, 40) or instant_to_text(utc_now()),
        source_url=_bounded(source_url, 2_000) or None,
        method=clean_method,  # type: ignore[arg-type]
        result=clean_result,  # type: ignore[arg-type]
        details=_as_dict(details),
    )


def empty_snapshot(counts: dict[str, Any], *, total: int) -> dict[str, Any]:
    """Build one point of the freshness history."""
    ratio = (float(counts.get("fresh", 0)) / total) if total else 0.0
    return {
        "at": instant_to_text(utc_now()),
        "counts": {key: int(value) for key, value in counts.items()},
        "total": int(total),
        "fresh_ratio": round(ratio, 4),
    }
