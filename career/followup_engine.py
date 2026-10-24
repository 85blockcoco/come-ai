"""Deterministic, local follow-up planner for Career applications.

SPEC-029 — Moteur de relances chronologiques.

The module is pure: no network, no hidden state, no automatic sending.  It
turns already-local application records and their event journal into a plan of
follow-up *actions* for one day, while refusing over-follow-ups (spam guard).

Public contract (stable):
    @dataclass FollowupAction: application_id, due_date, reason, channel
    @dataclass FollowupPlan:     date, actions, blocked_reasons

Reasons: ``no_response_j7``, ``viewed_no_reply``, ``deadline_soon``.
Channels: ``email``, ``portal``, ``in_person``.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from typing import Any, Mapping

from .models import clean_text, parse_date

_date_cls = date


REASONS = ("no_response_j7", "viewed_no_reply", "deadline_soon")
CHANNELS = ("email", "portal", "in_person")

# Priority used when several reasons apply to the same application (most urgent
# first).  Only one action is emitted per application per day.
REASON_PRIORITY = ("deadline_soon", "viewed_no_reply", "no_response_j7")

SENT_DECLARED_STAGES = frozenset(
    {"submitted", "submitted_confirmed", "response_received", "interview", "offer_received"}
)
CLOSED_STAGES = frozenset({"rejected", "refused", "withdrawn"})
OFFER_STAGES = frozenset({"offer_received"})


@dataclass
class FollowupAction:
    application_id: str
    due_date: str
    reason: str
    channel: str


@dataclass
class FollowupPlan:
    date: str
    actions: list[FollowupAction] = field(default_factory=list)
    blocked_reasons: dict[str, str] = field(default_factory=dict)


@dataclass
class FollowupPolicy:
    """Thresholds for the local follow-up planner.

    ``first_followup_days``  — first follow-up only after this many days.
    ``min_gap_days``         — never two follow-ups of the same application
                               closer than this.
    """

    first_followup_days: int = 7
    min_gap_days: int = 5
    max_followups_per_application: int = 3
    deadline_soon_days: int = 7
    viewed_no_reply_days: int = 3
    channels: dict[str, str] = field(
        default_factory=lambda: {
            "no_response_j7": "email",
            "viewed_no_reply": "email",
            "deadline_soon": "portal",
        }
    )
    # Alias fields kept in sync (tolerance for callers using other names).
    first_followup_delay_days: int | None = None
    min_days_between_followups: int | None = None
    minimum_gap_days: int | None = None
    max_followups: int | None = None
    channels_by_reason: dict[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.first_followup_delay_days is not None:
            self.first_followup_days = int(self.first_followup_delay_days)
        if self.min_days_between_followups is not None:
            self.min_gap_days = int(self.min_days_between_followups)
        if self.minimum_gap_days is not None:
            self.min_gap_days = int(self.minimum_gap_days)
        if self.max_followups is not None:
            self.max_followups_per_application = int(self.max_followups)
        # keep aliases in sync
        self.first_followup_delay_days = self.first_followup_days
        self.min_days_between_followups = self.min_gap_days
        self.minimum_gap_days = self.min_gap_days
        self.max_followups = self.max_followups_per_application
        if self.channels_by_reason:
            merged = dict(self.channels)
            merged.update(self.channels_by_reason)
            self.channels = merged
            self.channels_by_reason = dict(self.channels)


def _as_date(value: Any, default: date | None = None) -> date:
    if isinstance(value, datetime):
        return value.astimezone(timezone.utc).date() if value.tzinfo else value.date()
    if isinstance(value, date):
        return value
    text = clean_text(value, limit=64)
    if not text:
        return default if default is not None else date.today()
    try:
        return date.fromisoformat(text[:10])
    except ValueError:
        try:
            return datetime.fromisoformat(text.replace("Z", "+00:00")).date()
        except ValueError:
            return default if default is not None else date.today()


def _app_id(app: Mapping[str, Any]) -> str:
    for key in ("application_id", "id", "app_id", "application"):
        value = app.get(key)
        if value is not None and clean_text(value, limit=120):
            return clean_text(value, limit=120)
    return ""


def _stage(app: Mapping[str, Any]) -> str:
    return clean_text(app.get("stage"), limit=80).lower()


def _receipt_status(app: Mapping[str, Any]) -> str:
    return clean_text(app.get("receipt_status"), limit=80).lower() or "not_submitted"


def _deadline(app: Mapping[str, Any]) -> date | None:
    for key in ("deadline_date", "deadline", "job_deadline", "due_date"):
        value = app.get(key)
        if value not in (None, ""):
            try:
                return parse_date(value, "deadline")
            except Exception:
                try:
                    return _as_date(value, None)
                except Exception:
                    return None
    # nested job
    job = app.get("job")
    if isinstance(job, Mapping):
        return _deadline(job)
    return None


def _channel_for(policy: FollowupPolicy, reason: str, app: Mapping[str, Any]) -> str:
    app_channel = clean_text(app.get("preferred_channel") or app.get("channel"), limit=40)
    if app_channel in CHANNELS:
        return app_channel
    channel = (policy.channels or {}).get(reason)
    if channel in CHANNELS:
        return channel
    defaults = {"no_response_j7": "email", "viewed_no_reply": "email", "deadline_soon": "portal"}
    return defaults.get(reason, "email")


def _ingest_history(item: Any, by_app: dict[str, list[Any]], global_events: list[Any]) -> None:
    if isinstance(item, Mapping):
        app_id = None
        for key in ("application_id", "app_id", "application", "applicationId"):
            if item.get(key) not in (None, ""):
                app_id = clean_text(item.get(key), limit=120)
                break
        # If the mapping looks like {app_id: [...]}, handled by caller.
        if app_id is not None:
            by_app.setdefault(app_id, []).append(item)
        else:
            # Could be a container with an "events"/"followups" list.
            for container_key in ("events", "followups", "history", "items", "actions", "followup_dates"):
                value = item.get(container_key)
                if isinstance(value, list):
                    for sub in value:
                        _ingest_history(sub, by_app, global_events)
            # If nothing nested was found, keep as global.
            if not any(isinstance(item.get(k), list) for k in ("events", "followups", "history", "items", "actions")):
                global_events.append(item)
    elif isinstance(item, (list, tuple)):
        for sub in item:
            _ingest_history(sub, by_app, global_events)
    else:
        global_events.append(item)


def _normalize_history(history: Any, events: Any = None, events_by_application: Any = None, **kwargs: Any) -> dict[str, list[Any]]:
    by_app: dict[str, list[Any]] = {}
    global_events: list[Any] = []

    def _add_mapping_container(container: Any) -> None:
        if isinstance(container, Mapping):
            # {app_id: events}
            looks_like_map = True
            for key, value in container.items():
                if key in {"applications", "events", "followups", "history", "items", "actions", "data", "results"}:
                    looks_like_map = False
                    break
                if not isinstance(value, (list, tuple, Mapping)):
                    looks_like_map = False
                    break
            if looks_like_map and container:
                for key, value in container.items():
                    aid = clean_text(key, limit=120)
                    if isinstance(value, (list, tuple)):
                        by_app.setdefault(aid, []).extend(list(value))
                    else:
                        by_app.setdefault(aid, []).append(value)
                return
            # known containers
            for key in ("applications", "events", "followups", "history", "items", "actions", "data", "results", "followup_dates"):
                value = container.get(key)
                if value is not None:
                    _ingest_history(value, by_app, global_events)
            # events_by_application nested
            eba = container.get("events_by_application")
            if isinstance(eba, Mapping):
                for key, value in eba.items():
                    aid = clean_text(key, limit=120)
                    if isinstance(value, (list, tuple)):
                        by_app.setdefault(aid, []).extend(list(value))
                    else:
                        by_app.setdefault(aid, []).append(value)

    if isinstance(history, Mapping):
        _add_mapping_container(history)
    elif isinstance(history, (list, tuple)):
        _ingest_history(list(history), by_app, global_events)
    elif history is not None:
        global_events.append(history)

    if isinstance(events_by_application, Mapping):
        for key, value in events_by_application.items():
            aid = clean_text(key, limit=120)
            if isinstance(value, (list, tuple)):
                by_app.setdefault(aid, []).extend(list(value))
            else:
                by_app.setdefault(aid, []).append(value)

    if isinstance(events, Mapping):
        _add_mapping_container(events)
    elif isinstance(events, (list, tuple)):
        _ingest_history(list(events), by_app, global_events)
    elif events is not None:
        global_events.append(events)

    for key in ("history", "events", "followups", "application_events", "followup_history", "followup_dates", "items"):
        value = kwargs.get(key)
        if value is None:
            continue
        if isinstance(value, Mapping):
            _add_mapping_container(value)
        elif isinstance(value, (list, tuple)):
            _ingest_history(list(value), by_app, global_events)
        else:
            global_events.append(value)

    return {"by_app": by_app, "global": global_events}


def _events_for_app(app: Mapping[str, Any], hist: dict[str, list[Any]]) -> list[Any]:
    aid = _app_id(app)
    events: list[Any] = []
    if isinstance(app.get("events"), list):
        events.extend(app["events"])
    if aid and aid in hist["by_app"]:
        events.extend(hist["by_app"][aid])
    # global events filtered by application id when possible
    for item in hist["global"]:
        if isinstance(item, Mapping):
            item_aid = None
            for key in ("application_id", "app_id", "application"):
                if item.get(key) not in (None, ""):
                    item_aid = clean_text(item.get(key), limit=120)
                    break
            if item_aid is None or item_aid == aid:
                events.append(item)
        else:
            events.append(item)
    return events


def _event_date(item: Any) -> date | None:
    if isinstance(item, (date, datetime)):
        return _as_date(item, None)
    if isinstance(item, str):
        return _as_date(item, None)
    if isinstance(item, Mapping):
        for key in ("date", "due_date", "created_at", "timestamp", "at", "occurred_at", "followup_date", "sent_at", "last_followup", "last_followup_at", "updated_at"):
            value = item.get(key)
            if value not in (None, ""):
                parsed = _as_date(value, None)
                if parsed is not None:
                    return parsed
    return None


def _is_followup_event(item: Any) -> bool:
    if isinstance(item, Mapping):
        etype = clean_text(item.get("event_type") or item.get("type") or item.get("kind") or item.get("reason"), limit=80).lower()
        if any(token in etype for token in ("followup", "relance", "follow_up", "follow-up")):
            return True
        # A mapping with a follow-up date field is also a follow-up record.
        if any(item.get(k) not in (None, "") for k in ("followup_date", "last_followup", "last_followup_at")):
            return True
        return False
    if isinstance(item, str):
        low = item.lower()
        return "followup" in low or "relance" in low or "follow-up" in low
    return False


def _followup_dates(events: list[Any]) -> list[date]:
    result: list[date] = []
    for item in events:
        if _is_followup_event(item):
            parsed = _event_date(item)
            if parsed is not None:
                result.append(parsed)
    return result


def _all_event_dates(events: list[Any]) -> list[date]:
    result: list[date] = []
    for item in events:
        parsed = _event_date(item)
        if parsed is not None:
            result.append(parsed)
    return result


def _has_viewed(events: list[Any], app: Mapping[str, Any]) -> bool:
    if _receipt_status(app) in {"viewed", "seen", "opened"}:
        return True
    for item in events:
        if isinstance(item, Mapping):
            etype = clean_text(item.get("event_type") or item.get("type") or item.get("kind"), limit=80).lower()
            if "view" in etype or "open" in etype:
                return True
            detail = clean_text(item.get("detail"), limit=200).lower()
            if "view" in detail or "ouvert" in detail:
                return True
    return False


def _normalize_applications(applications: Any, kwargs: dict[str, Any]) -> list[Mapping[str, Any]]:
    # Service object shortcut.
    if applications is not None and not isinstance(applications, (Mapping, list, tuple)) and hasattr(applications, "list_applications"):
        kwargs.setdefault("service", applications)
        applications = None
    service = kwargs.get("service") or kwargs.get("career_service") or kwargs.get("career")
    if applications is None and service is not None:
        try:
            applications = service.list_applications()
        except Exception:
            applications = []
        kwargs.setdefault("_events_by_application", {})
        try:
            for app in applications:
                aid = _app_id(app)
                try:
                    full = service.get_application(aid)
                    app.setdefault("events", full.get("events", []))
                    if not app.get("company") and full.get("company"):
                        app["company"] = full.get("company")
                except Exception:
                    pass
        except Exception:
            pass

    if applications is None:
        for key in ("applications", "items", "data", "results"):
            if key in kwargs and kwargs.get(key) is not None:
                applications = kwargs.get(key)
                break
    if isinstance(applications, Mapping):
        if "applications" in applications:
            applications = applications.get("applications")
        elif "items" in applications:
            applications = applications.get("items")
        elif "data" in applications:
            applications = applications.get("data")
        else:
            applications = [applications]
    if applications is None:
        applications = []
    if not isinstance(applications, (list, tuple)):
        applications = [applications]
    return [app for app in applications if isinstance(app, Mapping)]


def _closed_or_offer(stage: str) -> bool:
    return stage in CLOSED_STAGES or stage in OFFER_STAGES


def spam_guard(
    application_id: Any,
    history: Any = None,
    policy: Any = None,
    *,
    today: Any = None,
    application: Any = None,
    applications: Any = None,
    events: Any = None,
    events_by_application: Any = None,
    service: Any = None,
    career_service: Any = None,
    **kwargs: Any,
) -> bool:
    """Return ``True`` when a follow-up is allowed for *application_id* today."""

    if policy is None:
        policy = kwargs.get("policy")
    if policy is None:
        policy = FollowupPolicy()
    elif isinstance(policy, Mapping):
        policy = FollowupPolicy(**{k: v for k, v in policy.items() if k in FollowupPolicy.__dataclass_fields__})
    if not isinstance(policy, FollowupPolicy):
        try:
            policy = FollowupPolicy()
        except Exception:
            return True

    if today is None:
        today = kwargs.get("today") or kwargs.get("now") or kwargs.get("date") or kwargs.get("as_of")
    today = _as_date(today, date.today())

    if applications is not None and not isinstance(applications, (list, tuple, Mapping)) and hasattr(applications, "list_applications"):
        service = applications
        applications = None
    if application is None and isinstance(applications, (list, tuple)):
        for app in applications:
            if isinstance(app, Mapping) and _app_id(app) == clean_text(application_id, limit=120):
                application = app
                break
    if application is None and service is None:
        service = kwargs.get("service") or career_service or kwargs.get("career")
    if application is None and service is not None:
        try:
            application = service.get_application(str(application_id))
        except Exception:
            application = None

    hist = _normalize_history(history, events, events_by_application, **kwargs)

    aid = clean_text(application_id, limit=120)
    app = application if isinstance(application, Mapping) else {}
    stage = _stage(app) if app else ""
    # closed/offer applications never get a follow-up
    if stage and _closed_or_offer(stage):
        return False

    events_for_app = _events_for_app(app, hist) if app else (hist["by_app"].get(aid, []) + hist["global"])
    followup_dates = _followup_dates(events_for_app)
    if len(followup_dates) >= int(policy.max_followups_per_application or 0) and int(policy.max_followups_per_application or 0) > 0:
        return False
    if followup_dates:
        last_followup = max(followup_dates)
        if (today - last_followup).days < int(policy.min_gap_days):
            return False
    else:
        # first follow-up delay applies to declared submissions (relances);
        # pre-submission work (deadline soon, review) is not subject to J+7.
        stage = _stage(app) if isinstance(app, Mapping) else ""
        sent = stage in SENT_DECLARED_STAGES or bool(app.get("sent_declared")) if isinstance(app, Mapping) else False
        if sent:
            base_dates = _all_event_dates(events_for_app)
            if base_dates:
                last_activity = max(base_dates)
                if (today - last_activity).days < int(policy.first_followup_days):
                    return False
            elif isinstance(app, Mapping):
                for key in ("updated_at", "created_at", "application_created_at", "application_updated_at"):
                    if app.get(key):
                        base = _as_date(app.get(key), None)
                        if base is not None and (today - base).days < int(policy.first_followup_days):
                            return False
                        break
    return True


def _candidate_reasons(
    app: Mapping[str, Any],
    events: list[Any],
    policy: FollowupPolicy,
    today: date,
) -> list[str]:
    stage = _stage(app)
    if not stage or _closed_or_offer(stage):
        return []
    reasons: list[str] = []
    # deadline soon
    deadline = _deadline(app)
    if deadline is not None:
        delta = (deadline - today).days
        if 0 <= delta <= int(policy.deadline_soon_days):
            reasons.append("deadline_soon")
    # no response j7
    sent = stage in SENT_DECLARED_STAGES or bool(app.get("sent_declared"))
    if sent:
        base_dates = _all_event_dates(events)
        if not base_dates:
            for key in ("updated_at", "created_at", "application_created_at", "application_updated_at"):
                if app.get(key):
                    parsed = _as_date(app.get(key), None)
                    if parsed is not None:
                        base_dates = [parsed]
                        break
        if base_dates:
            last_activity = max(base_dates)
            if (today - last_activity).days >= int(policy.first_followup_days):
                if _receipt_status(app) != "confirmed":
                    reasons.append("no_response_j7")
    # viewed no reply
    if _has_viewed(events, app):
        viewed_dates = []
        for item in events:
            if isinstance(item, Mapping):
                etype = clean_text(item.get("event_type") or item.get("type") or item.get("kind"), limit=80).lower()
                if "view" in etype or "open" in etype:
                    parsed = _event_date(item)
                    if parsed is not None:
                        viewed_dates.append(parsed)
        base = max(viewed_dates) if viewed_dates else None
        if base is None:
            base = max(_all_event_dates(events)) if _all_event_dates(events) else None
        if base is not None and (today - base).days >= int(policy.viewed_no_reply_days):
            if _receipt_status(app) not in {"confirmed", "replied", "response_received"}:
                reasons.append("viewed_no_reply")
    # de-duplicate preserving priority
    ordered: list[str] = []
    for reason in REASON_PRIORITY:
        if reason in reasons:
            ordered.append(reason)
    return ordered


def plan_today(
    applications: Any = None,
    history: Any = None,
    policy: Any = None,
    *,
    today: Any = None,
    now: Any = None,
    date_value: Any = None,
    as_of: Any = None,
    events: Any = None,
    events_by_application: Any = None,
    service: Any = None,
    career_service: Any = None,
    **kwargs: Any,
) -> FollowupPlan:
    """Build the follow-up plan for *today*.

    Flexible inputs:
      * ``applications``: list of application mappings (or a service object).
      * ``history``: events/follow-up history (dict keyed by application id,
        list of events, ...).
      * ``today``/``now``/``date``/``as_of``: the planning date.
    """

    # Policy normalization.
    if isinstance(history, FollowupPolicy) and policy is None:
        policy, history = history, None
    if policy is None:
        policy = kwargs.get("policy")
    if policy is None:
        policy = FollowupPolicy()
    elif isinstance(policy, Mapping):
        try:
            policy = FollowupPolicy(**{k: v for k, v in policy.items() if k in FollowupPolicy.__dataclass_fields__})
        except Exception:
            policy = FollowupPolicy()
    if not isinstance(policy, FollowupPolicy):
        try:
            policy = FollowupPolicy()
        except Exception:
            policy = FollowupPolicy()

    if today is None:
        today = now if now is not None else (date_value if date_value is not None else (as_of if as_of is not None else kwargs.get("today") or kwargs.get("now") or kwargs.get("date") or kwargs.get("as_of")))
    if service is None:
        service = career_service or kwargs.get("service") or kwargs.get("career_service") or kwargs.get("career")
    if applications is None and service is not None:
        kwargs.setdefault("service", service)

    applications_list = _normalize_applications(applications, kwargs)
    hist = _normalize_history(history, events, events_by_application, **kwargs)

    # events_by_application passed explicitly via kwargs
    eba = kwargs.get("_events_by_application")
    if isinstance(eba, Mapping):
        for key, value in eba.items():
            aid = clean_text(key, limit=120)
            if isinstance(value, (list, tuple)):
                hist["by_app"].setdefault(aid, []).extend(list(value))

    today_date = _as_date(today, _date_cls.today())
    actions: list[FollowupAction] = []
    blocked: dict[str, str] = {}

    for app in applications_list:
        aid = _app_id(app)
        if not aid:
            continue
        stage = _stage(app)
        # attach events from history
        events_for_app = _events_for_app(app, hist)
        if not isinstance(app.get("events"), list) and events_for_app:
            app = dict(app)
            app["events"] = events_for_app

        if stage and _closed_or_offer(stage):
            # closed/offer: no follow-up; not necessarily "blocked" spam.
            continue

        # spam guard
        allowed = spam_guard(
            aid,
            history=hist,
            policy=policy,
            today=today_date,
            application=app,
            events=events_for_app,
        )
        if not allowed:
            blocked[aid] = "spam_guard: too soon or too many follow-ups"
            continue

        reasons = _candidate_reasons(app, events_for_app, policy, today_date)
        if not reasons:
            continue
        reason = reasons[0]
        channel = _channel_for(policy, reason, app)
        actions.append(
            FollowupAction(
                application_id=aid,
                due_date=today_date.isoformat(),
                reason=reason,
                channel=channel,
            )
        )

    return FollowupPlan(date=today_date.isoformat(), actions=actions, blocked_reasons=blocked)


# Convenience alias used by some callers.
def plan_followups(*args: Any, **kwargs: Any) -> FollowupPlan:
    return plan_today(*args, **kwargs)


def build_plan(*args: Any, **kwargs: Any) -> FollowupPlan:
    return plan_today(*args, **kwargs)
