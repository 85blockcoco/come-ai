"""Freshness rules for candidate evidence — deterministic, local, offline.

An evidence item (a certification, a technical skill, an experience, a
language certificate...) stops being reliable over time: a certification
expires, a tool version moves on, a soft skill fades.  This module owns the
*rules* of that degradation:

* which policy applies to a type of evidence and how a person overrides it,
* when a proof enters its warning window and when it expires,
* which alert level is raised (info / warning / critical),
* which automatic action follows an expiry.

The module is deliberately pure: it never opens a file, never writes a file
and never performs a network request.  Persistence lives in
:mod:`career.evidence_freshness_store`, reporting in
:mod:`career.evidence_freshness_audit`.  The "now" reference is always
injected by the caller so a decision can be replayed and tested.

Two vocabularies coexist and must not be confused:

``status``
    The freshness truth of a proof: ``fresh``, ``warning``, ``expired`` or
    ``archived`` (explicitly set aside by the person).

``coverage_status``
    How the proof may still be used when matching an offer: ``covered``,
    ``warning``, ``archived`` or ``to_reverify``.  An expiry degrades the
    coverage, never the truth: an expired proof stays *expired* in the
    dashboard even when it was automatically archived.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import datetime, timedelta, timezone
from typing import Any, Iterable, Literal

from .models import clean_text
from workspace_core import UserFacingError


# --------------------------------------------------------------------------
# Vocabularies
# --------------------------------------------------------------------------

STATUS_FRESH = "fresh"
STATUS_WARNING = "warning"
STATUS_EXPIRED = "expired"
STATUS_ARCHIVED = "archived"

FreshnessStatus = Literal["fresh", "warning", "expired", "archived"]

ALERT_INFO = "info"
ALERT_WARNING = "warning"
ALERT_CRITICAL = "critical"

AlertLevel = Literal["info", "warning", "critical"]

#: Most severe first.  An alert list is always sorted with this order.
ALERT_LEVEL_ORDER: dict[str, int] = {ALERT_CRITICAL: 0, ALERT_WARNING: 1, ALERT_INFO: 2}

COVERAGE_COVERED = "covered"
COVERAGE_WARNING = "warning"
COVERAGE_ARCHIVED = "archived"
COVERAGE_TO_REVERIFY = "to_reverify"

COVERAGE_STATUSES = (
    COVERAGE_COVERED,
    COVERAGE_WARNING,
    COVERAGE_ARCHIVED,
    COVERAGE_TO_REVERIFY,
)

CHECK_METHODS = ("http", "api", "manual", "ocr", "api_partner")
CHECK_RESULTS = ("unchanged", "updated", "removed", "error")

#: A proof expiring in less than this many days raises a ``warning`` alert.
EXPIRING_SOON_DAYS = 7

#: Actions that change the stored proof.  The others only raise an alert.
STATE_ACTIONS = frozenset(
    {"downgrade_to_warning", "archive_optional", "mark_to_reverify", "expire_immediately"}
)

#: The history of the automatic actions never grows without bound.
MAX_AUTO_ACTIONS = 50

#: Default policy for an evidence type that is not listed below.  A proof of
#: an unknown type is never invented as expiring.
DEFAULT_POLICY: dict[str, Any] = {"max_age_days": None, "warning_days": None, "auto_expire": False}

#: Freshness policy per evidence type.
#:
#: ``max_age_days``    how long a proof stays valid after its last check.
#: ``warning_days``    how long before the expiry the person is warned.
#: ``auto_expire``     whether an expiry degrades the coverage automatically.
FRESHNESS_POLICIES: dict[str, dict[str, Any]] = {
    "certification": {"max_age_days": 365, "warning_days": 30, "auto_expire": True},
    "skill_technical": {"max_age_days": 730, "warning_days": 90, "auto_expire": False},
    "skill_soft": {"max_age_days": 1095, "warning_days": 180, "auto_expire": False},
    "experience": {"max_age_days": 1825, "warning_days": 365, "auto_expire": False},
    "education": {"max_age_days": None, "warning_days": None, "auto_expire": False},
    "language": {"max_age_days": 730, "warning_days": 90, "auto_expire": True},
    "tool": {"max_age_days": 730, "warning_days": 90, "auto_expire": False},
    "project": {"max_age_days": 1095, "warning_days": 180, "auto_expire": False},
}

#: Scheduled verification frequency per evidence type.  The daily rule is
#: not a type but a state: any proof already inside its warning window is
#: re-checked every day.
CHECK_FREQUENCIES: dict[str, str] = {
    "certification": "weekly",
    "language": "weekly",
    "skill_technical": "monthly",
    "tool": "monthly",
    "experience": "quarterly",
    "project": "quarterly",
    "education": "quarterly",
    "skill_soft": "quarterly",
}

#: Number of days between two scheduled verifications.
FREQUENCY_INTERVAL_DAYS: dict[str, int] = {
    "daily": 1,
    "weekly": 7,
    "monthly": 30,
    "quarterly": 90,
}


# --------------------------------------------------------------------------
# Time helpers
# --------------------------------------------------------------------------


def utc_now() -> datetime:
    """Return the current UTC reference used by every freshness decision."""
    return datetime.now(timezone.utc)


def instant_to_text(value: datetime) -> str:
    """Serialize an instant as a second-precision ISO-8601 UTC string."""
    return value.astimezone(timezone.utc).isoformat(timespec="seconds")


def parse_instant(value: Any) -> datetime | None:
    """Parse an ISO-8601 instant or a plain date; ``None`` when unusable.

    A malformed date never raises here: an unreadable timestamp is an
    unknown date, and an unknown date is never turned into a plausible one.
    """
    text = clean_text(value, limit=64)
    if not text:
        return None
    candidate = text[:-1] + "+00:00" if text.endswith("Z") else text
    try:
        parsed = datetime.fromisoformat(candidate)
    except ValueError:
        try:
            parsed = datetime.strptime(text, "%Y-%m-%d")
        except ValueError:
            return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _anchor_of(record: dict[str, Any]) -> datetime | None:
    """Return the instant the freshness countdown starts from.

    A proof is as old as its last successful verification; before any
    verification happened it is as old as its creation.
    """
    return parse_instant(record.get("last_verified_at")) or parse_instant(record.get("created_at"))


def days_between(later: datetime, earlier: datetime) -> int:
    """Return the whole number of days between two instants."""
    return int((later - earlier).total_seconds() // 86_400)


# --------------------------------------------------------------------------
# Data models
# --------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class SourceCheck:
    """One external verification of a proof.

    Attributes:
        check_id: Stable identifier of the check.
        checked_at: ISO-8601 instant of the check.
        source_url: Public location the check was made against, if any.
        method: How the check was performed (http, api, manual, ocr, api_partner).
        result: Outcome of the check (unchanged, updated, removed, error).
        details: Bounded extra context about the check.
    """

    check_id: str
    checked_at: str
    source_url: str | None
    method: Literal["http", "api", "manual", "ocr", "api_partner"]
    result: Literal["unchanged", "updated", "removed", "error"]
    details: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class EvidenceFreshness:
    """Freshness of a single proof.

    Attributes:
        evidence_id: Identifier of the proof.
        evidence_type: Type of the proof (certification, skill_technical, ...).
        created_at: ISO-8601 instant of the creation of the proof.
        last_verified_at: ISO-8601 instant of the last verification, if any.
        expires_at: ISO-8601 instant of the expiry, if the type expires.
        warning_at: ISO-8601 instant at which the warning window opens.
        status: Freshness truth (fresh, warning, expired, archived).
        source_checks: Verifications already performed on this proof.
        auto_actions: Automatic actions triggered for this proof.
    """

    evidence_id: str
    evidence_type: str
    created_at: str
    last_verified_at: str | None
    expires_at: str | None
    warning_at: str | None
    status: FreshnessStatus
    source_checks: list[SourceCheck]
    auto_actions: list[str]


# --------------------------------------------------------------------------
# Policies
# --------------------------------------------------------------------------


def evidence_types() -> list[str]:
    """Return the evidence types that ship with a default policy."""
    return sorted(FRESHNESS_POLICIES)


def normalize_policy(raw: Any) -> dict[str, Any]:
    """Validate and normalize a policy mapping.

    A policy is either "no expiry" (``max_age_days`` is ``None``) or a
    bounded number of days.  A warning window wider than the validity
    itself is rejected instead of being silently narrowed.
    """
    if not isinstance(raw, dict):
        raise UserFacingError("Une politique de fraîcheur doit être un objet.")
    policy: dict[str, Any] = dict(DEFAULT_POLICY)
    for key in ("max_age_days", "warning_days"):
        if key not in raw:
            continue
        value = raw.get(key)
        if value is None:
            policy[key] = None
            continue
        try:
            days = int(value)
        except (TypeError, ValueError) as error:
            raise UserFacingError(f"Le champ « {key} » doit être un nombre de jours.") from error
        if days < 0 or days > 20_000:
            raise UserFacingError(f"Le champ « {key} » doit être compris entre 0 et 20 000 jours.")
        policy[key] = days
    if "auto_expire" in raw and raw.get("auto_expire") is not None:
        policy["auto_expire"] = bool(raw.get("auto_expire"))
    max_age = policy.get("max_age_days")
    warning = policy.get("warning_days")
    if max_age is None:
        # A proof that never expires has no warning window either.
        policy["warning_days"] = None
    elif warning is not None and warning > max_age:
        raise UserFacingError("La fenêtre d’avertissement ne peut pas dépasser la durée de validité.")
    return policy


def policy_for(evidence_type: str, overrides: dict[str, Any] | None = None) -> dict[str, Any]:
    """Return the effective policy of an evidence type.

    ``overrides`` holds the person-made policies keyed by evidence type; a
    type without an override keeps the shipped default.
    """
    base = dict(FRESHNESS_POLICIES.get(evidence_type, DEFAULT_POLICY))
    if overrides and isinstance(overrides, dict):
        override = overrides.get(evidence_type)
        if isinstance(override, dict):
            base.update(normalize_policy(override))
    return base


def schedule_for(anchor: datetime | None, policy: dict[str, Any]) -> tuple[datetime | None, datetime | None]:
    """Return the (expiry, warning) instants implied by a policy."""
    max_age = policy.get("max_age_days")
    if anchor is None or max_age is None:
        return None, None
    expires_at = anchor + timedelta(days=int(max_age))
    warning_days = policy.get("warning_days")
    warning_at = expires_at - timedelta(days=int(warning_days)) if warning_days is not None else None
    return expires_at, warning_at


# --------------------------------------------------------------------------
# Evaluation
# --------------------------------------------------------------------------


def _coverage_of(record: dict[str, Any]) -> str:
    coverage = clean_text(record.get("coverage_status"), limit=40).lower()
    return coverage if coverage in COVERAGE_STATUSES else COVERAGE_COVERED


def _source_checks_of(record: dict[str, Any]) -> list[SourceCheck]:
    checks: list[SourceCheck] = []
    raw = record.get("source_checks")
    if not isinstance(raw, list):
        return checks
    for item in raw:
        if not isinstance(item, dict):
            continue
        method = clean_text(item.get("method"), limit=20).lower()
        result = clean_text(item.get("result"), limit=20).lower()
        if method not in CHECK_METHODS or result not in CHECK_RESULTS:
            continue
        details = item.get("details")
        checks.append(
            SourceCheck(
                check_id=clean_text(item.get("check_id"), limit=80),
                checked_at=clean_text(item.get("checked_at"), limit=40),
                source_url=clean_text(item.get("source_url"), limit=2_000) or None,
                method=method,
                result=result,
                details=dict(details) if isinstance(details, dict) else {},
            )
        )
    return checks


def evaluate_evidence(record: dict[str, Any], *, now: datetime | None = None) -> EvidenceFreshness:
    """Compute the freshness of one proof.

    The decision never invents a date: an unknown creation date yields an
    unknown expiry, and a proof without an expiry policy stays fresh.
    """
    reference = now or utc_now()
    evidence_type = clean_text(record.get("type"), limit=40)
    policy = policy_for(evidence_type, record.get("policy_overrides"))
    created = parse_instant(record.get("created_at"))
    last_verified = parse_instant(record.get("last_verified_at"))
    anchor = last_verified or created
    computed_expiry, computed_warning = schedule_for(anchor, policy)

    explicit_expiry = parse_instant(record.get("expires_at"))
    explicit_warning = parse_instant(record.get("warning_at"))
    expires_at = explicit_expiry or computed_expiry
    if explicit_warning is not None:
        warning_at = explicit_warning
    elif expires_at is not None and policy.get("warning_days") is not None:
        warning_at = expires_at - timedelta(days=int(policy["warning_days"]))
    else:
        warning_at = computed_warning

    # An archived proof is one the person explicitly set aside.  A proof that
    # was automatically archived after an expiry keeps the truth of its
    # status: it stays *expired* and only its coverage changed.
    archived = bool(record.get("archived"))
    if archived:
        status: FreshnessStatus = STATUS_ARCHIVED
    elif expires_at is None:
        status = STATUS_FRESH
    elif reference >= expires_at:
        status = STATUS_EXPIRED
    elif warning_at is not None and reference >= warning_at:
        status = STATUS_WARNING
    else:
        status = STATUS_FRESH

    return EvidenceFreshness(
        evidence_id=clean_text(record.get("id"), limit=80),
        evidence_type=evidence_type,
        created_at=instant_to_text(created) if created else "",
        last_verified_at=instant_to_text(last_verified) if last_verified else None,
        expires_at=instant_to_text(expires_at) if expires_at else None,
        warning_at=instant_to_text(warning_at) if warning_at else None,
        status=status,
        source_checks=_source_checks_of(record),
        auto_actions=[],
    )


def evaluate_all(records: Iterable[dict[str, Any]], *, now: datetime | None = None) -> list[EvidenceFreshness]:
    """Compute the freshness of every proof of a collection."""
    reference = now or utc_now()
    return [evaluate_evidence(record, now=reference) for record in records]


def days_to_expiry(freshness: EvidenceFreshness, *, now: datetime | None = None) -> int | None:
    """Return the whole number of days before the expiry (negative when past)."""
    reference = now or utc_now()
    expiry = parse_instant(freshness.expires_at)
    if expiry is None:
        return None
    return days_between(expiry, reference)


# --------------------------------------------------------------------------
# Automatic actions
# --------------------------------------------------------------------------


def planned_actions(record: dict[str, Any], freshness: EvidenceFreshness, *, now: datetime | None = None) -> list[str]:
    """Return the automatic actions triggered by the current freshness.

    The list is what the caller has to apply to the stored proof.  It is
    kept separate from the evaluation so a decision can be inspected
    before anything is written.
    """
    reference = now or utc_now()
    actions: list[str] = []
    policy = policy_for(freshness.evidence_type, record.get("policy_overrides"))
    coverage = _coverage_of(record)
    if freshness.status == STATUS_EXPIRED:
        actions.append("alert_critical")
        if policy.get("auto_expire") and coverage == COVERAGE_COVERED:
            actions.append("downgrade_to_warning" if record.get("mandatory") else "archive_optional")
    elif freshness.status == STATUS_WARNING:
        remaining = days_to_expiry(freshness, now=reference)
        if remaining is not None and remaining <= EXPIRING_SOON_DAYS:
            actions.append("alert_warning")
        else:
            actions.append("alert_info")
    return actions


def apply_actions(record: dict[str, Any], actions: Iterable[str], *, now: datetime | None = None) -> dict[str, Any]:
    """Return a copy of the proof with the automatic actions applied.

    The downgrade of an expired proof depends on its importance: a
    mandatory proof is downgraded to a warning so it stays visible, an
    optional one is archived so it stops being proposed.  Only the actions
    that change the proof are kept in its history; the alerts are stored
    once, in the alert list.
    """
    reference = now or utc_now()
    updated = dict(record)
    history = updated.get("auto_actions")
    history = list(history) if isinstance(history, list) else []
    before = updated.get("coverage_status")
    for action in actions:
        if action == "downgrade_to_warning":
            updated["coverage_status"] = COVERAGE_WARNING
        elif action == "archive_optional":
            updated["coverage_status"] = COVERAGE_ARCHIVED
        elif action == "mark_to_reverify":
            updated["coverage_status"] = COVERAGE_TO_REVERIFY
        elif action == "expire_immediately":
            updated["coverage_status"] = COVERAGE_WARNING
        if action in STATE_ACTIONS:
            history.append({"action": action, "at": instant_to_text(reference)})
    if updated.get("coverage_status") != before:
        updated["auto_actions"] = history[-MAX_AUTO_ACTIONS:]
        updated["updated_at"] = instant_to_text(reference)
    return updated


# --------------------------------------------------------------------------
# Alerts
# --------------------------------------------------------------------------


def _alert(
    *,
    evidence_id: str,
    evidence_type: str,
    label: str,
    level: str,
    code: str,
    message: str,
    created_at: datetime,
    expires_at: str | None = None,
) -> dict[str, Any]:
    return {
        "evidence_id": evidence_id,
        "evidence_type": evidence_type,
        "label": label,
        "level": level,
        "code": code,
        "message": message,
        "created_at": instant_to_text(created_at),
        "expires_at": expires_at,
        "acknowledged": False,
        "acknowledged_at": None,
    }


def build_alerts(
    records: Iterable[dict[str, Any]],
    freshnesses: Iterable[EvidenceFreshness],
    *,
    now: datetime | None = None,
) -> list[dict[str, Any]]:
    """Build the alert list implied by the current freshness of the proofs.

    One alert per proof and per cause.  A proof that expired raises a
    ``critical`` alert; it does not also raise an ``info`` alert for a
    warning window it has already left.
    """
    reference = now or utc_now()
    by_id = {clean_text(record.get("id"), limit=80): record for record in records}
    alerts: list[dict[str, Any]] = []
    for freshness in freshnesses:
        record = by_id.get(freshness.evidence_id, {})
        label = clean_text(record.get("label"), limit=200) or freshness.evidence_id
        actions = planned_actions(record, freshness, now=reference)
        if "alert_critical" in actions:
            alerts.append(
                _alert(
                    evidence_id=freshness.evidence_id,
                    evidence_type=freshness.evidence_type,
                    label=label,
                    level=ALERT_CRITICAL,
                    code="evidence_expired",
                    message=f"« {label} » a expiré le {freshness.expires_at or '—'}.",
                    created_at=reference,
                    expires_at=freshness.expires_at,
                )
            )
        elif "alert_warning" in actions:
            remaining = days_to_expiry(freshness, now=reference)
            alerts.append(
                _alert(
                    evidence_id=freshness.evidence_id,
                    evidence_type=freshness.evidence_type,
                    label=label,
                    level=ALERT_WARNING,
                    code="expiring_soon",
                    message=f"« {label} » expire dans {remaining} jour(s).",
                    created_at=reference,
                    expires_at=freshness.expires_at,
                )
            )
        elif "alert_info" in actions:
            alerts.append(
                _alert(
                    evidence_id=freshness.evidence_id,
                    evidence_type=freshness.evidence_type,
                    label=label,
                    level=ALERT_INFO,
                    code="entering_warning",
                    message=f"« {label} » entre dans sa fenêtre d’avertissement.",
                    created_at=reference,
                    expires_at=freshness.expires_at,
                )
            )
    return alerts


def source_check_alert(record: dict[str, Any], check: SourceCheck, *, now: datetime | None = None) -> dict[str, Any] | None:
    """Return the alert implied by the outcome of an external check.

    A changed source means the proof must be verified again, a removed
    source is treated as an immediate revocation, and a failed check is
    reported as a fact about the check, never about the proof.
    """
    reference = now or utc_now()
    evidence_id = clean_text(record.get("id"), limit=80)
    evidence_type = clean_text(record.get("type"), limit=40)
    label = clean_text(record.get("label"), limit=200) or evidence_id
    if check.result == "removed":
        return _alert(
            evidence_id=evidence_id,
            evidence_type=evidence_type,
            label=label,
            level=ALERT_CRITICAL,
            code="source_revoked",
            message=f"La source de « {label} » n’est plus disponible : la preuve est signalée comme expirée.",
            created_at=reference,
        )
    if check.result == "updated":
        return _alert(
            evidence_id=evidence_id,
            evidence_type=evidence_type,
            label=label,
            level=ALERT_WARNING,
            code="source_changed",
            message=f"La source de « {label} » a changé : la preuve doit être revérifiée.",
            created_at=reference,
        )
    if check.result == "error":
        return _alert(
            evidence_id=evidence_id,
            evidence_type=evidence_type,
            label=label,
            level=ALERT_INFO,
            code="source_check_failed",
            message=f"La vérification de « {label} » n’a pas abouti : le statut de la preuve est inchangé.",
            created_at=reference,
        )
    return None


# --------------------------------------------------------------------------
# Scheduling
# --------------------------------------------------------------------------


def check_frequency(record: dict[str, Any], freshness: EvidenceFreshness, *, now: datetime | None = None) -> str:
    """Return the scheduled verification frequency of a proof.

    A proof already inside its warning window is re-checked every day; the
    type then decides the slower default cadence.
    """
    reference = now or utc_now()
    if freshness.status in (STATUS_WARNING, STATUS_EXPIRED):
        return "daily"
    remaining = days_to_expiry(freshness, now=reference)
    if remaining is not None and remaining <= 30:
        return "daily"
    if remaining is not None and remaining <= 90 and freshness.evidence_type in ("certification", "language"):
        return "weekly"
    return CHECK_FREQUENCIES.get(freshness.evidence_type, "quarterly")


def is_check_due(last_checked_at: Any, frequency: str, *, now: datetime | None = None) -> bool:
    """Return whether a verification is due for the given cadence."""
    reference = now or utc_now()
    interval = FREQUENCY_INTERVAL_DAYS.get(frequency, FREQUENCY_INTERVAL_DAYS["quarterly"])
    previous = parse_instant(last_checked_at)
    if previous is None:
        return True
    return reference - previous >= timedelta(days=interval)


# --------------------------------------------------------------------------
# Refresh cycle
# --------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class RefreshResult:
    """Outcome of a freshness sweep over a collection of proofs.

    Attributes:
        records: The proofs, updated with the automatic actions.
        freshnesses: The computed freshness of every proof.
        alerts: The alerts implied by the current freshness.
        changed: Identifiers of the proofs whose coverage actually changed.
    """

    records: list[dict[str, Any]]
    freshnesses: list[EvidenceFreshness]
    alerts: list[dict[str, Any]]
    changed: list[str]


def refresh(
    records: Iterable[dict[str, Any]],
    *,
    now: datetime | None = None,
    apply: bool = True,
) -> RefreshResult:
    """Evaluate every proof, apply the automatic actions and build alerts.

    ``apply=False`` returns the outcome without mutating the proofs, which
    is what a dry run of the scheduled monitoring needs.
    """
    reference = now or utc_now()
    materialized = [dict(record) for record in records]
    evaluated = evaluate_all(materialized, now=reference)
    changed: list[str] = []
    updated: list[dict[str, Any]] = []
    freshnesses: list[EvidenceFreshness] = []
    for record, freshness in zip(materialized, evaluated):
        actions = planned_actions(record, freshness, now=reference)
        freshnesses.append(replace(freshness, auto_actions=list(actions)))
        if not actions:
            updated.append(record)
            continue
        refreshed = apply_actions(record, actions, now=reference) if apply else record
        if refreshed.get("coverage_status") != record.get("coverage_status"):
            changed.append(freshness.evidence_id)
        updated.append(refreshed)
    alerts = build_alerts(materialized, freshnesses, now=reference)
    return RefreshResult(
        records=updated,
        freshnesses=freshnesses,
        alerts=alerts,
        changed=changed,
    )


def freshness_to_dict(freshness: EvidenceFreshness) -> dict[str, Any]:
    """Serialize a freshness for the local API."""
    return {
        "evidence_id": freshness.evidence_id,
        "evidence_type": freshness.evidence_type,
        "created_at": freshness.created_at,
        "last_verified_at": freshness.last_verified_at,
        "expires_at": freshness.expires_at,
        "warning_at": freshness.warning_at,
        "status": freshness.status,
        "auto_actions": list(freshness.auto_actions),
        "source_checks": [
            {
                "check_id": check.check_id,
                "checked_at": check.checked_at,
                "source_url": check.source_url,
                "method": check.method,
                "result": check.result,
                "details": dict(check.details),
            }
            for check in freshness.source_checks
        ],
    }
