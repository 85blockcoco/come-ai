"""Local persistence for the evidence freshness module (SPEC-012).

The store keeps every proof, every policy override, every verification and
every alert in one private JSON file, inside the private Career data
directory.  It never reaches the network and never calls a model.

GUARANTEES
----------
* **Atomic writes** — the state is written to a temporary file in the same
  directory, flushed, then renamed over the target: an interrupted write can
  never truncate the store.
* **Private permissions** — the directory is ``0700`` and the file ``0600``:
  proofs describe a person's career and stay inside the private workspace.
* **Bounded history** — the event log keeps the last 500 events, the newest
  last, so the file cannot grow without limit.
* **Schema versioning** — a state written by a newer version is refused
  instead of being silently reinterpreted.
* **Explicit clock** — every method accepts an optional ``now``; the store
  falls back to the system clock only when the caller says nothing.
"""

from __future__ import annotations

import json
import os
import threading
import uuid
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

from .evidence_freshness import (
    CHECK_METHODS,
    CHECK_RESULTS,
    FRESHNESS_POLICIES,
    EvidenceFreshness,
    FreshnessAlert,
    FreshnessPolicy,
    ScheduledCheck,
    SourceCheck,
    alert_from_dict,
    apply_source_check,
    archive_evidence,
    as_datetime,
    build_alerts,
    build_evidence,
    compute_warning,
    effective_dates,
    evidence_from_dict,
    extend_expiry,
    format_timestamp,
    make_check_id,
    parse_timestamp,
    plan_checks,
    policy_for,
    reactivate_evidence,
    refresh_evidence,
    validate_policy_values,
)

STATE_FILENAME = "evidence_freshness.json"
SCHEMA_VERSION = 1
MAX_HISTORY = 500


class FreshnessStoreError(RuntimeError):
    """Raised when the local store cannot be read or written."""


class FreshnessStore:
    """Persistence layer for :mod:`career.evidence_freshness`."""

    def __init__(self, base_dir: Path, *, filename: str = STATE_FILENAME) -> None:
        self.base_dir = Path(base_dir).expanduser()
        self.path = self.base_dir / filename
        self._lock = threading.RLock()

    # ── storage ──────────────────────────────────────────────────────────

    def _ensure_dir(self) -> None:
        try:
            self.base_dir.mkdir(parents=True, exist_ok=True)
            os.chmod(self.base_dir, 0o700)
        except OSError as error:  # pragma: no cover - depends on the filesystem
            raise FreshnessStoreError("Le dossier local de fraîcheur est inaccessible.") from error

    def _empty_state(self) -> dict[str, Any]:
        return {
            "schema_version": SCHEMA_VERSION,
            "updated_at": None,
            "evidence": {},
            "policies": {},
            "alerts": {},
            "history": [],
        }

    def read_state(self) -> dict[str, Any]:
        """Read the raw state; a missing file yields an empty state."""
        with self._lock:
            if not self.path.exists():
                return self._empty_state()
            try:
                raw = json.loads(self.path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError) as error:
                raise FreshnessStoreError("Le fichier local de fraîcheur est illisible.") from error
            if not isinstance(raw, dict):
                raise FreshnessStoreError("Le fichier local de fraîcheur est illisible.")
            version = int(raw.get("schema_version", 0) or 0)
            if version > SCHEMA_VERSION:
                raise FreshnessStoreError(
                    "Le fichier local de fraîcheur a été créé par une version plus récente."
                )
            state = self._empty_state()
            state["evidence"] = dict(raw.get("evidence") or {})
            state["policies"] = dict(raw.get("policies") or {})
            state["alerts"] = dict(raw.get("alerts") or {})
            history = raw.get("history")
            state["history"] = list(history) if isinstance(history, list) else []
            state["updated_at"] = raw.get("updated_at")
            return state

    def write_state(self, state: Mapping[str, Any]) -> None:
        """Write the state atomically with private permissions."""
        with self._lock:
            self._ensure_dir()
            payload = {
                "schema_version": SCHEMA_VERSION,
                "updated_at": state.get("updated_at"),
                "evidence": dict(state.get("evidence") or {}),
                "policies": dict(state.get("policies") or {}),
                "alerts": dict(state.get("alerts") or {}),
                "history": list(state.get("history") or []),
            }
            temporary = self.path.with_suffix(f"{self.path.suffix}.tmp")
            try:
                with temporary.open("w", encoding="utf-8") as destination:
                    json.dump(payload, destination, ensure_ascii=False, indent=2, sort_keys=True)
                    destination.flush()
                    os.fsync(destination.fileno())
                os.chmod(temporary, 0o600)
                os.replace(temporary, self.path)
            except OSError as error:
                temporary.unlink(missing_ok=True)
                raise FreshnessStoreError("Le fichier local de fraîcheur n'a pas pu être écrit.") from error

    # ── helpers ─────────────────────────────────────────────────────────

    @staticmethod
    def _now(now: datetime | None) -> datetime:
        if now is None:
            return datetime.now(timezone.utc)
        if now.tzinfo is None:
            return now.replace(tzinfo=timezone.utc)
        return now.astimezone(timezone.utc)

    @staticmethod
    def _append_history(state: dict[str, Any], event: str, **detail: Any) -> None:
        history = state.setdefault("history", [])
        history.append({"at": detail.pop("at", None), "event": event, **detail})
        if len(history) > MAX_HISTORY:
            del history[: len(history) - MAX_HISTORY]

    def _policy_overrides(self, state: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
        return {str(key): dict(value) for key, value in (state.get("policies") or {}).items() if isinstance(value, Mapping)}

    def policy_for_evidence(self, evidence: EvidenceFreshness, state: Mapping[str, Any] | None = None) -> FreshnessPolicy:
        """Effective policy of one proof (global override, then local one)."""
        payload = state if state is not None else self.read_state()
        return policy_for(
            evidence.evidence_type,
            self._policy_overrides(payload),
            evidence.policy_override,
        )

    # ── evidence ────────────────────────────────────────────────────────

    def register_evidence(
        self,
        *,
        evidence_type: str,
        title: str = "",
        mandatory: bool = False,
        source_url: str = "",
        notes: str = "",
        created_at: datetime | str | None = None,
        last_verified_at: datetime | str | None = None,
        expires_at: datetime | str | None = None,
        warning_at: datetime | str | None = None,
        evidence_id: str | None = None,
        policy_override: Mapping[str, Any] | None = None,
        now: datetime | None = None,
    ) -> EvidenceFreshness:
        """Register a new proof and compute its dates from the policy."""
        with self._lock:
            state = self.read_state()
            reference = self._now(now)
            created = as_datetime(created_at) or reference
            verified_at = as_datetime(last_verified_at)
            explicit_expiry = as_datetime(expires_at)
            explicit_warning = as_datetime(warning_at)
            kind = str(evidence_type or "").strip() or "unknown"
            policy = policy_for(kind, self._policy_overrides(state), policy_override)
            identifier = str(evidence_id or "").strip() or f"ev_{uuid.uuid4().hex[:12]}"
            if identifier in state["evidence"]:
                raise FreshnessStoreError("Cette preuve existe déjà.")
            record = build_evidence(
                evidence_id=identifier,
                evidence_type=kind,
                created_at=created,
                policy=policy,
                title=str(title or ""),
                mandatory=bool(mandatory),
                source_url=str(source_url or ""),
                last_verified_at=verified_at,
                expires_at=explicit_expiry,
                warning_at=explicit_warning,
                notes=str(notes or ""),
                policy_override=policy_override,
                dates_pinned=explicit_expiry is not None,
            )
            state["evidence"][identifier] = record.to_dict()
            self._append_history(
                state,
                "register",
                at=format_timestamp(reference),
                evidence_id=identifier,
                detail=f"{kind} — {record.title or identifier}",
            )
            self._save(state)
            return record

    def list_evidence(
        self,
        *,
        status: str | None = None,
        evidence_type: str | None = None,
        now: datetime | None = None,
    ) -> list[EvidenceFreshness]:
        """Every known proof, with a status recomputed at ``now``."""
        with self._lock:
            state = self.read_state()
            reference = self._now(now)
            records: list[EvidenceFreshness] = []
            for payload in state["evidence"].values():
                evidence = evidence_from_dict(payload)
                policy = self.policy_for_evidence(evidence, state)
                refreshed, _ = refresh_evidence(evidence, reference, policy)
                records.append(refreshed)
            if status:
                wanted = {item.strip() for item in str(status).split(",") if item.strip()}
                records = [record for record in records if record.status in wanted]
            if evidence_type:
                wanted_type = str(evidence_type).strip()
                records = [record for record in records if record.evidence_type == wanted_type]
            records.sort(key=lambda record: (record.expires_at or "9999", record.evidence_id))
            return records

    def get_evidence(self, evidence_id: str, *, now: datetime | None = None) -> EvidenceFreshness | None:
        """One proof, or ``None`` when it is unknown."""
        with self._lock:
            state = self.read_state()
            payload = state["evidence"].get(str(evidence_id))
            if payload is None:
                return None
            evidence = evidence_from_dict(payload)
            policy = self.policy_for_evidence(evidence, state)
            refreshed, _ = refresh_evidence(evidence, self._now(now), policy)
            return refreshed

    def update_evidence(
        self,
        evidence_id: str,
        changes: Mapping[str, Any],
        *,
        now: datetime | None = None,
    ) -> EvidenceFreshness:
        """Apply a manual update (dates, title, mandatory flag, archive…)."""
        with self._lock:
            state = self.read_state()
            identifier = str(evidence_id)
            payload = state["evidence"].get(identifier)
            if payload is None:
                raise KeyError(identifier)
            reference = self._now(now)
            evidence = evidence_from_dict(payload)
            policy = self.policy_for_evidence(evidence, state)

            updated = evidence
            actions: list[str] = []
            if "title" in changes and changes["title"] is not None:
                updated = replace(updated, title=str(changes["title"]))
            if "notes" in changes and changes["notes"] is not None:
                updated = replace(updated, notes=str(changes["notes"]))
            if "mandatory" in changes and changes["mandatory"] is not None:
                updated = replace(updated, mandatory=bool(changes["mandatory"]))
            if "source_url" in changes and changes["source_url"] is not None:
                updated = replace(updated, source_url=str(changes["source_url"]))
            if "archived" in changes and changes["archived"] is not None:
                if changes["archived"]:
                    updated, actions = archive_evidence(updated, reference)
                else:
                    updated = replace(updated, archived=False, status="fresh")
            if "expires_at" in changes:
                new_expiry = parse_timestamp(changes["expires_at"]) if changes["expires_at"] else None
                new_warning = (
                    parse_timestamp(changes["warning_at"])
                    if changes.get("warning_at")
                    else compute_warning(policy, new_expiry)
                )
                updated = replace(
                    updated,
                    expires_at=format_timestamp(new_expiry),
                    warning_at=format_timestamp(new_warning),
                    dates_pinned=True,
                )
            elif "warning_at" in changes:
                new_warning = parse_timestamp(changes["warning_at"]) if changes["warning_at"] else None
                updated = replace(
                    updated,
                    warning_at=format_timestamp(new_warning),
                    dates_pinned=True,
                )
            if "extend_days" in changes and changes["extend_days"]:
                updated, actions = extend_expiry(updated, int(changes["extend_days"]), reference, policy)
            if changes.get("reactivate"):
                updated, actions = reactivate_evidence(updated, reference, policy)
            if "policy_override" in changes and changes["policy_override"] is not None:
                override = dict(changes["policy_override"])
                max_age, warning_days, auto_expire = validate_policy_values(
                    override.get("max_age_days", policy.max_age_days),
                    override.get("warning_days", policy.warning_days),
                    bool(override.get("auto_expire", policy.auto_expire)),
                )
                updated = replace(
                    updated,
                    policy_override={
                        "max_age_days": max_age,
                        "warning_days": warning_days,
                        "auto_expire": auto_expire,
                    },
                )
                policy = policy_for(updated.evidence_type, self._policy_overrides(state), updated.policy_override)

            if not updated.dates_pinned:
                expiry, warning = effective_dates(updated, policy)
                updated = replace(
                    updated,
                    expires_at=format_timestamp(expiry),
                    warning_at=format_timestamp(warning),
                )
            refreshed, refresh_actions = refresh_evidence(updated, reference, policy)
            state["evidence"][identifier] = refreshed.to_dict()
            self._append_history(
                state,
                "update",
                at=format_timestamp(reference),
                evidence_id=identifier,
                detail=",".join(actions + refresh_actions) or "champs modifiés",
            )
            self._save(state)
            return refreshed

    def delete_evidence(self, evidence_id: str, *, now: datetime | None = None) -> bool:
        """Delete one proof and its alerts."""
        with self._lock:
            state = self.read_state()
            identifier = str(evidence_id)
            if identifier not in state["evidence"]:
                return False
            del state["evidence"][identifier]
            for alert_id in [key for key, value in state["alerts"].items() if value.get("evidence_id") == identifier]:
                del state["alerts"][alert_id]
            self._append_history(
                state,
                "delete",
                at=format_timestamp(self._now(now)),
                evidence_id=identifier,
                detail="preuve supprimée",
            )
            self._save(state)
            return True

    # ── policies ────────────────────────────────────────────────────────

    def list_policies(self) -> dict[str, dict[str, Any]]:
        """Base policies merged with the global overrides."""
        with self._lock:
            state = self.read_state()
            overrides = self._policy_overrides(state)
            policies: dict[str, dict[str, Any]] = {}
            for evidence_type in sorted(set(FRESHNESS_POLICIES) | set(overrides)):
                policy = policy_for(evidence_type, overrides)
                policies[evidence_type] = {
                    "evidence_type": evidence_type,
                    "max_age_days": policy.max_age_days,
                    "warning_days": policy.warning_days,
                    "auto_expire": policy.auto_expire,
                    "overridden": evidence_type in overrides,
                }
            return policies

    def set_policy(
        self,
        evidence_type: str,
        *,
        max_age_days: int | None = None,
        warning_days: int | None = None,
        auto_expire: bool | None = None,
        reset: bool = False,
        now: datetime | None = None,
    ) -> FreshnessPolicy:
        """Override the policy of one evidence type for every proof."""
        with self._lock:
            state = self.read_state()
            kind = str(evidence_type or "").strip() or "unknown"
            reference = self._now(now)
            if reset:
                state["policies"].pop(kind, None)
                policy = policy_for(kind)
            else:
                base = policy_for(kind, self._policy_overrides(state))
                max_age, warning, auto = validate_policy_values(
                    base.max_age_days if max_age_days is None else int(max_age_days),
                    base.warning_days if warning_days is None else int(warning_days),
                    base.auto_expire if auto_expire is None else bool(auto_expire),
                )
                state["policies"][kind] = {
                    "max_age_days": max_age,
                    "warning_days": warning,
                    "auto_expire": auto,
                }
                policy = policy_for(kind, self._policy_overrides(state))
            # A policy change never overrides a pinned date.
            for identifier, payload in list(state["evidence"].items()):
                evidence = evidence_from_dict(payload)
                if evidence.evidence_type != kind or evidence.dates_pinned:
                    continue
                expiry, warning = effective_dates(evidence, policy)
                state["evidence"][identifier] = replace(
                    evidence,
                    expires_at=format_timestamp(expiry),
                    warning_at=format_timestamp(warning),
                ).to_dict()
            self._append_history(
                state,
                "policy",
                at=format_timestamp(reference),
                detail=kind,
            )
            self._save(state)
            return policy

    # ── source checks ───────────────────────────────────────────────────

    def record_source_check(
        self,
        evidence_id: str,
        *,
        method: str = "manual",
        result: str = "unchanged",
        source_url: str | None = None,
        details: Mapping[str, Any] | None = None,
        now: datetime | None = None,
    ) -> tuple[EvidenceFreshness, list[FreshnessAlert]]:
        """Record one verification and apply its consequences."""
        with self._lock:
            state = self.read_state()
            identifier = str(evidence_id)
            payload = state["evidence"].get(identifier)
            if payload is None:
                raise KeyError(identifier)
            reference = self._now(now)
            evidence = evidence_from_dict(payload)
            policy = self.policy_for_evidence(evidence, state)
            check_method = str(method or "manual").strip()
            if check_method not in CHECK_METHODS:
                check_method = "manual"
            check_result = str(result or "unchanged").strip()
            if check_result not in CHECK_RESULTS:
                check_result = "error"
            check = SourceCheck(
                check_id=make_check_id(identifier, reference, check_method, check_result),
                checked_at=format_timestamp(reference) or "",
                source_url=source_url if source_url else (evidence.source_url or None),
                method=check_method,  # type: ignore[arg-type]
                result=check_result,  # type: ignore[arg-type]
                details=dict(details or {}),
            )
            updated, actions = apply_source_check(evidence, check, reference, policy)
            state["evidence"][identifier] = updated.to_dict()
            self._append_history(
                state,
                "check",
                at=format_timestamp(reference),
                evidence_id=identifier,
                detail=f"{check_method}:{check_result}",
            )
            new_alerts = self._materialize_alerts(state, updated, reference)
            self._save(state)
            return updated, new_alerts

    # ── alerts ──────────────────────────────────────────────────────────

    def _materialize_alerts(
        self,
        state: dict[str, Any],
        evidence: EvidenceFreshness,
        now: datetime,
    ) -> list[FreshnessAlert]:
        created: list[FreshnessAlert] = []
        for alert in build_alerts(evidence, now):
            existing = state["alerts"].get(alert.alert_id)
            if existing is None:
                state["alerts"][alert.alert_id] = alert.to_dict()
                created.append(alert)
                self._append_history(
                    state,
                    "alert",
                    at=alert.created_at,
                    evidence_id=alert.evidence_id,
                    detail=f"{alert.level}:{alert.kind}",
                )
            # An alert already known keeps its acknowledgement: the user
            # already saw it, the refresh must not raise it again.
        return created

    def list_alerts(self, *, active_only: bool = True, now: datetime | None = None) -> list[FreshnessAlert]:
        """Alerts, most critical first."""
        with self._lock:
            state = self.read_state()
            alerts = [alert_from_dict(payload) for payload in state["alerts"].values()]
            if active_only:
                alerts = [alert for alert in alerts if not alert.acknowledged]
            order = {"critical": 0, "warning": 1, "info": 2}
            alerts.sort(key=lambda alert: (order.get(alert.level, 3), alert.created_at, alert.alert_id))
            return alerts

    def acknowledge_alert(self, alert_id: str, *, now: datetime | None = None) -> FreshnessAlert:
        """Acknowledge one alert so it stops being active."""
        with self._lock:
            state = self.read_state()
            identifier = str(alert_id)
            payload = state["alerts"].get(identifier)
            if payload is None:
                raise KeyError(identifier)
            reference = self._now(now)
            alert = alert_from_dict(payload)
            alert = replace(alert, acknowledged=True, acknowledged_at=format_timestamp(reference))
            state["alerts"][identifier] = alert.to_dict()
            self._append_history(
                state,
                "acknowledge",
                at=format_timestamp(reference),
                evidence_id=alert.evidence_id,
                detail=identifier,
            )
            self._save(state)
            return alert

    # ── monitoring ──────────────────────────────────────────────────────

    def refresh(self, *, now: datetime | None = None) -> dict[str, Any]:
        """Recompute every status, apply the automatic actions, raise alerts."""
        with self._lock:
            state = self.read_state()
            reference = self._now(now)
            actions: list[dict[str, str]] = []
            new_alerts: list[FreshnessAlert] = []
            for identifier, payload in list(state["evidence"].items()):
                evidence = evidence_from_dict(payload)
                policy = self.policy_for_evidence(evidence, state)
                refreshed, triggered = refresh_evidence(evidence, reference, policy)
                if refreshed.to_dict() != evidence.to_dict():
                    state["evidence"][identifier] = refreshed.to_dict()
                for action in triggered:
                    actions.append({"evidence_id": identifier, "action": action})
                new_alerts.extend(self._materialize_alerts(state, refreshed, reference))
            snapshot = self._record_snapshot(state, reference)
            self._save(state)
            return {
                "refreshed_at": format_timestamp(reference),
                "actions": actions,
                "new_alerts": new_alerts,
                "snapshot": snapshot,
            }

    def _record_snapshot(self, state: dict[str, Any], now: datetime) -> dict[str, Any]:
        counts = {"fresh": 0, "warning": 0, "expired": 0, "archived": 0}
        for payload in state["evidence"].values():
            evidence = evidence_from_dict(payload)
            policy = self.policy_for_evidence(evidence, state)
            refreshed, _ = refresh_evidence(evidence, now, policy)
            counts[refreshed.status] = counts.get(refreshed.status, 0) + 1
        snapshot = {
            "at": format_timestamp(now),
            "date": now.date().isoformat(),
            "total": sum(counts.values()),
            "counts": counts,
        }
        history = state.setdefault("history", [])
        for entry in reversed(history):
            if entry.get("event") == "snapshot" and entry.get("date") == snapshot["date"]:
                return dict(entry)
        history.append({"event": "snapshot", **snapshot})
        if len(history) > MAX_HISTORY:
            del history[: len(history) - MAX_HISTORY]
        return snapshot

    def plan(self, *, now: datetime | None = None) -> list[ScheduledCheck]:
        """The monitoring plan: which proof must be checked and when."""
        with self._lock:
            state = self.read_state()
            reference = self._now(now)
            evidences = []
            for payload in state["evidence"].values():
                evidence = evidence_from_dict(payload)
                policy = self.policy_for_evidence(evidence, state)
                refreshed, _ = refresh_evidence(evidence, reference, policy)
                evidences.append(refreshed)
            return plan_checks(evidences, reference)

    # ── history ─────────────────────────────────────────────────────────

    def history(self, *, limit: int = 100) -> list[dict[str, Any]]:
        """The most recent events, newest last."""
        with self._lock:
            state = self.read_state()
            events = list(state.get("history") or [])
            if limit <= 0:
                return []
            return events[-limit:]

    # ── internals ───────────────────────────────────────────────────────

    def _save(self, state: dict[str, Any]) -> None:
        state["updated_at"] = format_timestamp(datetime.now(timezone.utc))
        self.write_state(state)
