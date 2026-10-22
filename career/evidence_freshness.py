"""Evidence freshness core for SPEC-012 (CVBOOST-47).

Pure domain logic: policies, expiry dates, freshness statuses, proactive
alerts, automatic actions and the monitoring schedule.  This module never
touches the network, the file system or an implicit clock — every function
that needs "now" receives an explicit :class:`datetime`.

VOCABULARY (SPEC-012 contract)
------------------------------
``FRESHNESS_POLICIES``
    One policy per ``evidence_type``.  A policy says how long a piece of
    evidence stays trustworthy (``max_age_days``), how early the user must be
    warned (``warning_days``) and whether an expired proof may be degraded
    automatically (``auto_expire``).
:class:`EvidenceFreshness`
    The freshness state of one proof (skill, certification, language…).
:class:`SourceCheck`
    One verification of a proof, manual or external.
:class:`FreshnessAlert`
    One proactive alert, at level ``info``, ``warning`` or ``critical``.
:class:`ScheduledCheck`
    One planned monitoring action, derived from the cadence of the proof.

RULES
-----
* Unknown stays unknown: an unknown ``evidence_type`` never expires and never
  warns on its own (``DEFAULT_POLICY`` has no age and no warning window).
* The status is always derived from the dates, never stored as a fact: a
  proof that passed its ``expires_at`` is ``expired`` whatever the record
  said before.
* An expired proof is degraded only when its policy allows it
  (``auto_expire``): a mandatory proof is downgraded to ``warning`` and an
  optional one is archived.
* Dates can be pinned by the user (an explicit override).  A pinned proof is
  never re-computed by a policy change until it is verified again.
* Every identifier is derived from its content, so the same data always
  produces the same ids — no clock, no randomness, no network.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field, replace
from datetime import datetime, timedelta, timezone
from typing import Any, Iterable, Literal, Mapping, Sequence

# ──────────────────────────────────────────────────────────────────────
# Constants
# ──────────────────────────────────────────────────────────────────────

FreshnessStatus = Literal["fresh", "warning", "expired", "archived"]
AlertLevel = Literal["info", "warning", "critical"]
CheckMethod = Literal["http", "api", "manual", "ocr", "api_partner"]
CheckResult = Literal["unchanged", "updated", "removed", "error"]

#: Documented policy per evidence type (SPEC-012 contract).
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

#: Applied to an evidence type nobody defined yet: no expiry, no warning.
DEFAULT_POLICY: dict[str, Any] = {"max_age_days": None, "warning_days": None, "auto_expire": False}

EVIDENCE_TYPES: frozenset[str] = frozenset(FRESHNESS_POLICIES)
FRESHNESS_STATUSES: frozenset[str] = frozenset({"fresh", "warning", "expired", "archived"})
ALERT_LEVELS: frozenset[str] = frozenset({"info", "warning", "critical"})
CHECK_METHODS: frozenset[str] = frozenset({"http", "api", "manual", "ocr", "api_partner"})
CHECK_RESULTS: frozenset[str] = frozenset({"unchanged", "updated", "removed", "error"})

#: Coverage states used when a proof is degraded.
COVERAGE_UNKNOWN = "unknown"
COVERAGE_COVERED = "covered"
COVERAGE_WARNING = "warning"
COVERAGE_ARCHIVED = "archived"
COVERAGE_STATUSES: frozenset[str] = frozenset(
    {COVERAGE_UNKNOWN, COVERAGE_COVERED, COVERAGE_WARNING, COVERAGE_ARCHIVED}
)

#: A proof is checked every day during the last 30 days before its expiry.
DAILY_HORIZON_DAYS = 30
#: Certifications and languages are checked every week during the last 90 days.
WEEKLY_HORIZON_DAYS = 90
#: A proof expiring in less than 7 days raises a ``warning`` alert.
EXPIRING_SOON_DAYS = 7

#: Base monitoring cadence per evidence type (SPEC-012 surveillance table).
BASE_CADENCE_DAYS: dict[str, int] = {
    "certification": 30,
    "language": 30,
    "skill_technical": 30,
    "skill_soft": 30,
    "tool": 30,
    "experience": 90,
    "project": 90,
    "education": 90,
}
DEFAULT_CADENCE_DAYS = 30

CADENCE_DAILY = "daily"
CADENCE_WEEKLY = "weekly"
CADENCE_MONTHLY = "monthly"
CADENCE_QUARTERLY = "quarterly"
CADENCES: frozenset[str] = frozenset({CADENCE_DAILY, CADENCE_WEEKLY, CADENCE_MONTHLY, CADENCE_QUARTERLY})

#: Automatic actions recorded in ``EvidenceFreshness.auto_actions``.
ACTION_DOWNGRADE = "downgrade_to_warning"
ACTION_ARCHIVE = "archive_expired"
ACTION_EXPIRED_NO_AUTO = "expired_no_auto_action"
ACTION_TO_REVERIFY = "to_reverify"
ACTION_REVOKED = "revoked"
ACTION_REACTIVATED = "reactivated"
ACTION_EXTENDED = "extended_expiry"
ACTION_VERIFIED = "verified"
ACTION_CHECK_ERROR = "check_error"


# ──────────────────────────────────────────────────────────────────────
# Data structures
# ──────────────────────────────────────────────────────────────────────


@dataclass(frozen=True, slots=True)
class FreshnessPolicy:
    """The freshness policy applied to one evidence type."""

    evidence_type: str
    max_age_days: int | None
    warning_days: int | None
    auto_expire: bool

    def to_dict(self) -> dict[str, Any]:
        return {
            "evidence_type": self.evidence_type,
            "max_age_days": self.max_age_days,
            "warning_days": self.warning_days,
            "auto_expire": self.auto_expire,
        }


@dataclass(frozen=True, slots=True)
class SourceCheck:
    """One verification of a piece of evidence.

    ``result`` is the observable outcome: the source is unchanged, it changed
    (``updated``), it disappeared or was revoked (``removed``) or the check
    itself failed (``error``).
    """

    check_id: str
    checked_at: str
    source_url: str | None
    method: CheckMethod
    result: CheckResult
    details: dict = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "check_id": self.check_id,
            "checked_at": self.checked_at,
            "source_url": self.source_url,
            "method": self.method,
            "result": self.result,
            "details": dict(self.details),
        }


@dataclass(frozen=True, slots=True)
class EvidenceFreshness:
    """The freshness state of one piece of evidence.

    The first nine fields are the documented SPEC-012 contract; the fields
    below them are optional extensions and always carry a default value.
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
    # --- optional extensions -------------------------------------------------
    title: str = ""
    mandatory: bool = False
    source_url: str = ""
    coverage_status: str = COVERAGE_UNKNOWN
    needs_reverification: bool = False
    archived: bool = False
    dates_pinned: bool = False
    policy_override: dict = field(default_factory=dict)
    notes: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "evidence_id": self.evidence_id,
            "evidence_type": self.evidence_type,
            "created_at": self.created_at,
            "last_verified_at": self.last_verified_at,
            "expires_at": self.expires_at,
            "warning_at": self.warning_at,
            "status": self.status,
            "source_checks": [check.to_dict() for check in self.source_checks],
            "auto_actions": list(self.auto_actions),
            "title": self.title,
            "mandatory": self.mandatory,
            "source_url": self.source_url,
            "coverage_status": self.coverage_status,
            "needs_reverification": self.needs_reverification,
            "archived": self.archived,
            "dates_pinned": self.dates_pinned,
            "policy_override": dict(self.policy_override),
            "notes": self.notes,
        }


@dataclass(frozen=True, slots=True)
class FreshnessAlert:
    """One proactive alert about a piece of evidence."""

    alert_id: str
    evidence_id: str
    evidence_type: str
    level: AlertLevel
    kind: str
    title: str
    message: str
    created_at: str
    expires_at: str | None = None
    acknowledged: bool = False
    acknowledged_at: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "alert_id": self.alert_id,
            "evidence_id": self.evidence_id,
            "evidence_type": self.evidence_type,
            "level": self.level,
            "kind": self.kind,
            "title": self.title,
            "message": self.message,
            "created_at": self.created_at,
            "expires_at": self.expires_at,
            "acknowledged": self.acknowledged,
            "acknowledged_at": self.acknowledged_at,
        }


@dataclass(frozen=True, slots=True)
class ScheduledCheck:
    """One monitoring action planned by the surveillance schedule."""

    evidence_id: str
    evidence_type: str
    title: str
    cadence: str
    due_at: str
    days_until_due: int
    overdue: bool
    priority: str
    reason: str
    source_url: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "evidence_id": self.evidence_id,
            "evidence_type": self.evidence_type,
            "title": self.title,
            "cadence": self.cadence,
            "due_at": self.due_at,
            "days_until_due": self.days_until_due,
            "overdue": self.overdue,
            "priority": self.priority,
            "reason": self.reason,
            "source_url": self.source_url,
        }


# ──────────────────────────────────────────────────────────────────────
# Time helpers
# ──────────────────────────────────────────────────────────────────────


def parse_timestamp(value: Any) -> datetime | None:
    """Parse an ISO-8601 timestamp into an aware UTC datetime.

    Returns ``None`` for an empty value and raises ``ValueError`` for a
    malformed one: the caller decides how to report it to the user.
    """
    text = str(value or "").strip()
    if not text:
        return None
    normalized = text[:-1] + "+00:00" if text.endswith(("Z", "z")) else text
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError as error:
        raise ValueError(f"Date invalide : {text}") from error
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def format_timestamp(value: datetime | None) -> str | None:
    """Serialize an aware datetime as a canonical UTC ISO-8601 string."""
    if value is None:
        return None
    return value.astimezone(timezone.utc).isoformat(timespec="seconds")


def as_datetime(value: datetime | str | None) -> datetime | None:
    """Accept a datetime or an ISO-8601 string and return an aware UTC one."""
    if value is None or isinstance(value, datetime):
        return parse_timestamp(value) if isinstance(value, str) else value
    return parse_timestamp(value)


def days_until(target: datetime | None, now: datetime) -> int | None:
    """Whole days between ``now`` and ``target`` (negative when overdue).

    A positive remainder is rounded up: a proof expiring in 7,2 days is
    reported as 8 days left, never as 7 — the alert must never arrive
    later than the deadline it protects.
    """
    if target is None:
        return None
    delta = target - now
    seconds = delta.total_seconds()
    if seconds > 0:
        return -(-seconds // 86400)
    return int(seconds // 86400)


# ──────────────────────────────────────────────────────────────────────
# Policies
# ──────────────────────────────────────────────────────────────────────


def policy_for(
    evidence_type: str,
    overrides: Mapping[str, Mapping[str, Any]] | None = None,
    local: Mapping[str, Any] | None = None,
) -> FreshnessPolicy:
    """Return the policy of ``evidence_type``.

    ``overrides`` holds the global overrides (one per evidence type) and
    ``local`` the override pinned on a single piece of evidence.  The lookup
    order is: base policy, then global override, then local override.
    """
    key = str(evidence_type or "").strip() or "unknown"
    base = dict(FRESHNESS_POLICIES.get(key, DEFAULT_POLICY))
    if overrides:
        candidate = overrides.get(key)
        if candidate:
            base.update({name: value for name, value in candidate.items() if value is not None or name == "auto_expire"})
    if local:
        base.update({name: value for name, value in local.items() if name in base})
    return FreshnessPolicy(
        evidence_type=key,
        max_age_days=base.get("max_age_days"),
        warning_days=base.get("warning_days"),
        auto_expire=bool(base.get("auto_expire", False)),
    )


def validate_policy_values(
    max_age_days: int | None,
    warning_days: int | None,
    auto_expire: bool,
) -> tuple[int | None, int | None, bool]:
    """Validate the three tunable values of a policy."""
    if max_age_days is not None and max_age_days < 0:
        raise ValueError("La durée de validité ne peut pas être négative.")
    if warning_days is not None and warning_days < 0:
        raise ValueError("Le délai d’alerte ne peut pas être négatif.")
    if max_age_days is not None and warning_days is not None and warning_days > max_age_days:
        raise ValueError("Le délai d’alerte doit être inférieur ou égal à la durée de validité.")
    return max_age_days, warning_days, bool(auto_expire)


# ──────────────────────────────────────────────────────────────────────
# Dates and status
# ──────────────────────────────────────────────────────────────────────


def compute_expiry(policy: FreshnessPolicy, anchor: datetime | None) -> datetime | None:
    """Expiry date of a proof anchored on ``anchor`` (last verification)."""
    if policy.max_age_days is None or anchor is None:
        return None
    return anchor + timedelta(days=policy.max_age_days)


def compute_warning(policy: FreshnessPolicy, expires_at: datetime | None) -> datetime | None:
    """Start of the warning window for a proof expiring at ``expires_at``."""
    if policy.warning_days is None or expires_at is None:
        return None
    return expires_at - timedelta(days=policy.warning_days)


def status_for(
    *,
    expires_at: datetime | None,
    warning_at: datetime | None,
    now: datetime,
    archived: bool = False,
) -> FreshnessStatus:
    """Derive the freshness status from the dates only."""
    if archived:
        return "archived"
    if expires_at is not None and now >= expires_at:
        return "expired"
    if warning_at is not None and now >= warning_at:
        return "warning"
    return "fresh"


def build_evidence(
    *,
    evidence_id: str,
    evidence_type: str,
    created_at: datetime,
    policy: FreshnessPolicy,
    title: str = "",
    mandatory: bool = False,
    source_url: str = "",
    last_verified_at: datetime | str | None = None,
    expires_at: datetime | str | None = None,
    warning_at: datetime | str | None = None,
    coverage_status: str = COVERAGE_UNKNOWN,
    notes: str = "",
    policy_override: Mapping[str, Any] | None = None,
    dates_pinned: bool = False,
) -> EvidenceFreshness:
    """Create one evidence record with its dates and its status.

    An explicit ``expires_at`` (a user override) wins over the computed one;
    a pinned record keeps its dates until it is verified again.  Dates may be
    given as ``datetime`` or as an ISO-8601 string.
    """
    verified_at = as_datetime(last_verified_at)
    anchor = verified_at or created_at
    explicit_expiry = as_datetime(expires_at)
    explicit_warning = as_datetime(warning_at)
    computed_expiry = compute_expiry(policy, anchor)
    effective_expiry = explicit_expiry if explicit_expiry is not None else computed_expiry
    if explicit_expiry is not None:
        # A pinned expiry keeps the warning window of the policy: the user
        # chose the date, not the moment the alert should start.
        effective_warning = (
            explicit_warning if explicit_warning is not None else compute_warning(policy, explicit_expiry)
        )
    else:
        effective_warning = compute_warning(policy, effective_expiry)
    now = created_at
    return EvidenceFreshness(
        evidence_id=evidence_id,
        evidence_type=policy.evidence_type,
        created_at=format_timestamp(created_at) or "",
        last_verified_at=format_timestamp(verified_at),
        expires_at=format_timestamp(effective_expiry),
        warning_at=format_timestamp(effective_warning),
        status=status_for(
            expires_at=effective_expiry,
            warning_at=effective_warning,
            now=now,
            archived=False,
        ),
        source_checks=[],
        auto_actions=[],
        title=title,
        mandatory=bool(mandatory),
        source_url=source_url,
        coverage_status=coverage_status,
        needs_reverification=False,
        archived=False,
        dates_pinned=dates_pinned,
        policy_override=dict(policy_override or {}),
        notes=notes,
    )


def effective_dates(
    evidence: EvidenceFreshness,
    policy: FreshnessPolicy,
) -> tuple[datetime | None, datetime | None]:
    """Return the dates that apply to ``evidence`` right now.

    A pinned record keeps its own dates; a computed record is refreshed from
    the policy and its last verification.
    """
    if evidence.dates_pinned:
        return parse_timestamp(evidence.expires_at), parse_timestamp(evidence.warning_at)
    anchor = parse_timestamp(evidence.last_verified_at) or parse_timestamp(evidence.created_at)
    expiry = compute_expiry(policy, anchor)
    return expiry, compute_warning(policy, expiry)


def refresh_evidence(
    evidence: EvidenceFreshness,
    now: datetime,
    policy: FreshnessPolicy,
) -> tuple[EvidenceFreshness, list[str]]:
    """Recompute the status of ``evidence`` and apply the automatic actions.

    Returns the refreshed record and the list of automatic actions that were
    triggered by this refresh (empty when nothing happened).
    """
    expires_at, warning_at = effective_dates(evidence, policy)
    archived = evidence.archived
    status = status_for(expires_at=expires_at, warning_at=warning_at, now=now, archived=archived)
    actions: list[str] = []
    coverage_status = evidence.coverage_status

    if status == "expired" and policy.auto_expire:
        if evidence.mandatory:
            if coverage_status in (COVERAGE_COVERED, COVERAGE_UNKNOWN):
                # A proof already downgraded stays downgraded: the action is
                # recorded once, not on every refresh.
                coverage_status = COVERAGE_WARNING
                actions.append(ACTION_DOWNGRADE)
        else:
            archived = True
            status = "archived"
            coverage_status = COVERAGE_ARCHIVED
            actions.append(ACTION_ARCHIVE)
    elif status == "expired" and not policy.auto_expire:
        actions.append(ACTION_EXPIRED_NO_AUTO)

    refreshed = replace(
        evidence,
        expires_at=format_timestamp(expires_at),
        warning_at=format_timestamp(warning_at),
        status=status,
        archived=archived,
        coverage_status=coverage_status,
    )
    if actions:
        refreshed = replace(refreshed, auto_actions=_merge_actions(evidence.auto_actions, actions))
    return refreshed, actions


def _merge_actions(existing: Sequence[str], new_actions: Iterable[str]) -> list[str]:
    """Append actions, keeping the order and dropping the duplicates."""
    merged = list(existing)
    for action in new_actions:
        if action not in merged:
            merged.append(action)
    return merged


def blocks_export(evidence: EvidenceFreshness) -> bool:
    """Tell whether a proof must block the export of a CV.

    A mandatory proof that expired cannot be presented as a covered skill:
    the export is blocked until the proof is verified again.  This is the
    seam used by the traceability registry (SPEC-011) and by the export
    pipeline.
    """
    return bool(evidence.mandatory and evidence.status == "expired")


# ──────────────────────────────────────────────────────────────────────
# Source checks
# ──────────────────────────────────────────────────────────────────────


def make_check_id(evidence_id: str, checked_at: datetime, method: str, result: str) -> str:
    """Deterministic identifier of a source check."""
    payload = f"{evidence_id}|{format_timestamp(checked_at)}|{method}|{result}"
    return f"chk_{hashlib.sha256(payload.encode('utf-8')).hexdigest()[:16]}"


def apply_source_check(
    evidence: EvidenceFreshness,
    check: SourceCheck,
    now: datetime,
    policy: FreshnessPolicy,
) -> tuple[EvidenceFreshness, list[str]]:
    """Apply the consequence of a source check to ``evidence``.

    * ``unchanged`` — the proof is verified again: the timer restarts.
    * ``updated`` — the source changed: the proof is flagged ``to_reverify``.
    * ``removed`` — the source disappeared or the certification was revoked:
      the proof expires immediately.
    * ``error`` — the check failed: nothing changes but the error is recorded.
    """
    checks = list(evidence.source_checks)
    checks.append(check)
    actions: list[str] = []
    updated = replace(evidence, source_checks=checks)

    if check.result == "unchanged":
        updated = replace(
            updated,
            last_verified_at=format_timestamp(now),
            needs_reverification=False,
            dates_pinned=False,
            archived=False,
        )
        actions.append(ACTION_VERIFIED)
    elif check.result == "updated":
        updated = replace(updated, needs_reverification=True)
        actions.append(ACTION_TO_REVERIFY)
    elif check.result == "removed":
        updated = replace(
            updated,
            expires_at=format_timestamp(now),
            warning_at=format_timestamp(now),
            needs_reverification=False,
            dates_pinned=True,
        )
        actions.append(ACTION_REVOKED)
    else:
        actions.append(ACTION_CHECK_ERROR)

    refreshed, refresh_actions = refresh_evidence(updated, now, policy)
    return refreshed, actions + refresh_actions


# ──────────────────────────────────────────────────────────────────────
# Alerts
# ──────────────────────────────────────────────────────────────────────


def make_alert_id(evidence_id: str, kind: str, expires_at: str | None) -> str:
    """Deterministic identifier of an alert.

    The expiry date is part of the hash so a proof that expires, is renewed
    and expires again produces two distinct alerts.
    """
    payload = f"{evidence_id}|{kind}|{expires_at or ''}"
    return f"alert_{hashlib.sha256(payload.encode('utf-8')).hexdigest()[:16]}"


def build_alerts(evidence: EvidenceFreshness, now: datetime) -> list[FreshnessAlert]:
    """Build the alerts an evidence deserves right now.

    * ``critical`` — the proof expired (or was revoked), whatever the
      automatic action did with it: an optional proof may have been archived,
      the expiry still deserves a critical alert.
    * ``warning`` — the proof expires within seven days.
    * ``info`` — the proof just entered its warning window.
    """
    alerts: list[FreshnessAlert] = []
    expires_at = parse_timestamp(evidence.expires_at)
    remaining = days_until(expires_at, now)
    label = evidence.title or evidence.evidence_id

    if expires_at is not None and remaining is not None and remaining <= 0:
        alerts.append(
            FreshnessAlert(
                alert_id=make_alert_id(evidence.evidence_id, "expired", evidence.expires_at),
                evidence_id=evidence.evidence_id,
                evidence_type=evidence.evidence_type,
                level="critical",
                kind="expired",
                title=f"Preuve expirée : {label}",
                message=(
                    f"La preuve « {label} » a expiré le {evidence.expires_at}. "
                    "Vérifie-la ou renouvelle-la avant de l'utiliser."
                ),
                created_at=format_timestamp(now) or "",
                expires_at=evidence.expires_at,
            )
        )
        return alerts

    warning_at = parse_timestamp(evidence.warning_at)
    in_warning_window = warning_at is not None and now >= warning_at
    if in_warning_window and remaining is not None and remaining > 0:
        if remaining <= EXPIRING_SOON_DAYS:
            kind = "expiring_soon"
            level: AlertLevel = "warning"
            message = f"La preuve « {label} » expire dans {remaining} jour(s)."
        else:
            kind = "entered_warning_zone"
            level = "info"
            message = f"La preuve « {label} » expire dans {remaining} jour(s)."
        alerts.append(
            FreshnessAlert(
                alert_id=make_alert_id(evidence.evidence_id, kind, evidence.expires_at),
                evidence_id=evidence.evidence_id,
                evidence_type=evidence.evidence_type,
                level=level,
                kind=kind,
                title=f"Preuve à surveiller : {label}",
                message=message,
                created_at=format_timestamp(now) or "",
                expires_at=evidence.expires_at,
            )
        )
    return alerts


# ──────────────────────────────────────────────────────────────────────
# Monitoring schedule
# ──────────────────────────────────────────────────────────────────────


def resolve_cadence(evidence: EvidenceFreshness, now: datetime) -> str:
    """Monitoring cadence of one proof.

    * daily — the proof is in its warning window (less than 30 days left);
    * weekly — a certification or a language expires in less than 90 days;
    * monthly — technical skills, tools, certifications and languages;
    * quarterly — experiences, projects and diplomas.
    """
    remaining = days_until(parse_timestamp(evidence.expires_at), now)
    if remaining is not None and remaining <= DAILY_HORIZON_DAYS:
        return CADENCE_DAILY
    if (
        evidence.evidence_type in {"certification", "language"}
        and remaining is not None
        and remaining <= WEEKLY_HORIZON_DAYS
    ):
        return CADENCE_WEEKLY
    base_days = BASE_CADENCE_DAYS.get(evidence.evidence_type, DEFAULT_CADENCE_DAYS)
    if base_days >= 90:
        return CADENCE_QUARTERLY
    return CADENCE_MONTHLY


def cadence_days(cadence: str) -> int:
    """Number of days between two checks of a cadence."""
    return {
        CADENCE_DAILY: 1,
        CADENCE_WEEKLY: 7,
        CADENCE_MONTHLY: 30,
        CADENCE_QUARTERLY: 90,
    }.get(cadence, DEFAULT_CADENCE_DAYS)


def plan_check(evidence: EvidenceFreshness, now: datetime) -> ScheduledCheck:
    """Plan the next verification of one proof."""
    cadence = resolve_cadence(evidence, now)
    interval = timedelta(days=cadence_days(cadence))
    last_check = None
    if evidence.source_checks:
        last_check = parse_timestamp(evidence.source_checks[-1].checked_at)
    anchor = last_check or parse_timestamp(evidence.created_at) or now
    due_at = anchor + interval
    remaining = days_until(due_at, now)
    overdue = due_at <= now
    if overdue:
        reason = "Vérification en retard."
    elif remaining is not None and remaining <= DAILY_HORIZON_DAYS:
        reason = "Preuve proche de l'expiration."
    elif cadence == CADENCE_DAILY:
        reason = "Surveillance quotidienne (zone d'avertissement)."
    elif cadence == CADENCE_WEEKLY:
        reason = "Surveillance hebdomadaire (certification ou langue)."
    elif cadence == CADENCE_QUARTERLY:
        reason = "Surveillance trimestrielle."
    else:
        reason = "Surveillance mensuelle."
    priority = "high" if evidence.status in {"warning", "expired"} else "normal"
    return ScheduledCheck(
        evidence_id=evidence.evidence_id,
        evidence_type=evidence.evidence_type,
        title=evidence.title,
        cadence=cadence,
        due_at=format_timestamp(due_at) or "",
        days_until_due=remaining if remaining is not None else 0,
        overdue=overdue,
        priority=priority,
        reason=reason,
        source_url=evidence.source_url,
    )


def plan_checks(evidences: Sequence[EvidenceFreshness], now: datetime) -> list[ScheduledCheck]:
    """Plan the verification of every proof, most urgent first."""
    planned = [plan_check(evidence, now) for evidence in evidences]
    planned.sort(key=lambda item: (item.days_until_due, item.evidence_id))
    return planned


# ──────────────────────────────────────────────────────────────────────
# Manual actions
# ──────────────────────────────────────────────────────────────────────


def reactivate_evidence(
    evidence: EvidenceFreshness,
    now: datetime,
    policy: FreshnessPolicy,
) -> tuple[EvidenceFreshness, list[str]]:
    """Reactivate a proof: the timer restarts from ``now``."""
    anchor = now
    expires_at = compute_expiry(policy, anchor)
    warning_at = compute_warning(policy, expires_at)
    updated = replace(
        evidence,
        last_verified_at=format_timestamp(now),
        expires_at=format_timestamp(expires_at),
        warning_at=format_timestamp(warning_at),
        status=status_for(expires_at=expires_at, warning_at=warning_at, now=now),
        archived=False,
        needs_reverification=False,
        dates_pinned=False,
    )
    return updated, [ACTION_REACTIVATED]


def extend_expiry(
    evidence: EvidenceFreshness,
    days: int,
    now: datetime,
    policy: FreshnessPolicy,
) -> tuple[EvidenceFreshness, list[str]]:
    """Push the expiry of a proof further away (batch action)."""
    if days <= 0:
        raise ValueError("Le délai d'extension doit être positif.")
    expires_at = parse_timestamp(evidence.expires_at)
    if expires_at is None:
        expires_at = now + timedelta(days=days)
    else:
        expires_at = expires_at + timedelta(days=days)
    warning_at = compute_warning(policy, expires_at)
    updated = replace(
        evidence,
        expires_at=format_timestamp(expires_at),
        warning_at=format_timestamp(warning_at),
        dates_pinned=True,
        status=status_for(expires_at=expires_at, warning_at=warning_at, now=now),
    )
    return updated, [ACTION_EXTENDED]


def archive_evidence(evidence: EvidenceFreshness, now: datetime) -> tuple[EvidenceFreshness, list[str]]:
    """Archive a proof without deleting its history."""
    updated = replace(
        evidence,
        archived=True,
        status="archived",
        coverage_status=COVERAGE_ARCHIVED,
    )
    return updated, [ACTION_ARCHIVE]


# ──────────────────────────────────────────────────────────────────────
# Serialization
# ──────────────────────────────────────────────────────────────────────


def check_from_dict(payload: Mapping[str, Any]) -> SourceCheck:
    """Rebuild a source check from its serialized form."""
    method = str(payload.get("method", "manual"))
    if method not in CHECK_METHODS:
        method = "manual"
    result = str(payload.get("result", "unchanged"))
    if result not in CHECK_RESULTS:
        result = "error"
    details = payload.get("details")
    return SourceCheck(
        check_id=str(payload.get("check_id", "")),
        checked_at=str(payload.get("checked_at", "")),
        source_url=(str(payload["source_url"]) if payload.get("source_url") else None),
        method=method,  # type: ignore[arg-type]
        result=result,  # type: ignore[arg-type]
        details=dict(details) if isinstance(details, Mapping) else {},
    )


def evidence_from_dict(payload: Mapping[str, Any]) -> EvidenceFreshness:
    """Rebuild an evidence record from its serialized form."""
    checks_payload = payload.get("source_checks")
    checks = [check_from_dict(item) for item in checks_payload] if isinstance(checks_payload, list) else []
    status = str(payload.get("status", "fresh"))
    if status not in FRESHNESS_STATUSES:
        status = "fresh"
    coverage = str(payload.get("coverage_status", COVERAGE_UNKNOWN))
    if coverage not in COVERAGE_STATUSES:
        coverage = COVERAGE_UNKNOWN
    override = payload.get("policy_override")
    return EvidenceFreshness(
        evidence_id=str(payload.get("evidence_id", "")),
        evidence_type=str(payload.get("evidence_type", "unknown")),
        created_at=str(payload.get("created_at", "")),
        last_verified_at=(str(payload["last_verified_at"]) if payload.get("last_verified_at") else None),
        expires_at=(str(payload["expires_at"]) if payload.get("expires_at") else None),
        warning_at=(str(payload["warning_at"]) if payload.get("warning_at") else None),
        status=status,  # type: ignore[arg-type]
        source_checks=checks,
        auto_actions=[str(action) for action in payload.get("auto_actions", []) or []],
        title=str(payload.get("title", "")),
        mandatory=bool(payload.get("mandatory", False)),
        source_url=str(payload.get("source_url", "")),
        coverage_status=coverage,
        needs_reverification=bool(payload.get("needs_reverification", False)),
        archived=bool(payload.get("archived", False)),
        dates_pinned=bool(payload.get("dates_pinned", False)),
        policy_override=dict(override) if isinstance(override, Mapping) else {},
        notes=str(payload.get("notes", "")),
    )


def alert_from_dict(payload: Mapping[str, Any]) -> FreshnessAlert:
    """Rebuild an alert from its serialized form."""
    level = str(payload.get("level", "info"))
    if level not in ALERT_LEVELS:
        level = "info"
    return FreshnessAlert(
        alert_id=str(payload.get("alert_id", "")),
        evidence_id=str(payload.get("evidence_id", "")),
        evidence_type=str(payload.get("evidence_type", "unknown")),
        level=level,  # type: ignore[arg-type]
        kind=str(payload.get("kind", "")),
        title=str(payload.get("title", "")),
        message=str(payload.get("message", "")),
        created_at=str(payload.get("created_at", "")),
        expires_at=(str(payload["expires_at"]) if payload.get("expires_at") else None),
        acknowledged=bool(payload.get("acknowledged", False)),
        acknowledged_at=(str(payload["acknowledged_at"]) if payload.get("acknowledged_at") else None),
    )
