"""SPEC-029 — moteur local de relances chronologiques.

Le tableau de bord (CVBOOST-09 / SPEC-025) dit *qui* relancer.  Ce module dit
*quand* et *combien*, sans jamais envoyer quoi que ce soit :

* ``FollowupPolicy`` rend les règles explicites et testables (première relance
  à J+7, jamais moins de 5 jours entre deux relances, plafond anti-spam) ;
* ``plan_today`` transforme des candidatures et leur historique local en un
  plan du jour déterministe — les actions dues, et pour chaque autre
  candidature la raison exacte du blocage ;
* ``spam_guard`` répond à une question précise : « une relance à cette date
  est-elle autorisée pour cette candidature ? » ;
* ``application_view`` normalise les enregistrements locaux (lignes SQLite et
  événements ``application_events``) sans E/S, sans réseau et sans modèle.

Garanties :

* module pur et déterministe : mêmes entrées + même date ⇒ même plan ;
* aucune relance n'est un e-mail : le canal est une indication à utiliser
  manuellement par la personne, jamais un envoi automatique ;
* une donnée absente ou illisible reste un blocage nommé, jamais une date
  inventée ;
* aucun changement de schéma : l'historique des relances vit dans les
  événements existants, sous le type ``followup_recorded`` et une charge JSON
  ``{"date": ..., "channel": ..., "reason": ...}``.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from typing import Any, Iterable, Literal, Mapping

from .models import clean_text

Channel = Literal["email", "portal", "in_person"]
Reason = Literal["no_response_j7", "viewed_no_reply", "deadline_soon"]

CHANNELS: tuple[str, ...] = ("email", "portal", "in_person")
REASONS: tuple[str, ...] = ("no_response_j7", "viewed_no_reply", "deadline_soon")

FOLLOWUP_EVENT_TYPE = "followup_recorded"
"""Type d'événement local portant une relance effectuée (aucune migration)."""

VIEW_EVENT_TYPES = frozenset({"application_viewed", "offer_viewed", "viewed"})
"""Types d'événements optionnels signalant une consultation par l'employeur."""

SENT_STAGES = frozenset({"submitted", "submitted_confirmed", "receipt_unknown"})
"""États où une relance chronologique peut avoir du sens."""

RESPONDED_STAGES = frozenset({"response_received", "interview", "offer_received"})
"""États où une réponse existe déjà : plus rien à relancer."""

CLOSED_STAGES = frozenset({"rejected", "refused", "withdrawn"})
"""États terminaux : aucune relance proposée."""

DEFAULT_CHANNEL: Channel = "portal"
"""Canal prudent par défaut : le portail officiel, jamais un e-mail implicite."""

MAX_APPLICATIONS = 500
"""Borne de sécurité pour une projection locale économe."""


@dataclass(frozen=True)
class FollowupPolicy:
    """Règles de cadencement, toutes visibles et surchargeables en test.

    Les valeurs par défaut suivent la mission SPEC-029 : première relance à
    J+7 après l'envoi déclaré, jamais moins de 5 jours entre deux relances,
    trois relances maximum (la première incluse) pour éviter le harcèlement.
    """

    first_followup_days: int = 7
    min_interval_days: int = 5
    max_followups: int = 3
    deadline_soon_days: int = 7
    default_channel: Channel = DEFAULT_CHANNEL
    max_applications: int = MAX_APPLICATIONS

    def __post_init__(self) -> None:
        if self.first_followup_days < 1:
            raise ValueError("first_followup_days doit être au moins 1.")
        if self.min_interval_days < 1:
            raise ValueError("min_interval_days doit être au moins 1.")
        if self.max_followups < 1:
            raise ValueError("max_followups doit être au moins 1.")
        if self.deadline_soon_days < 0:
            raise ValueError("deadline_soon_days ne peut pas être négatif.")
        if self.max_applications < 1:
            raise ValueError("max_applications doit être au moins 1.")
        if self.default_channel not in CHANNELS:
            raise ValueError("default_channel doit être email, portal ou in_person.")


DEFAULT_POLICY = FollowupPolicy()


@dataclass(frozen=True)
class FollowupAction:
    """Une relance due, à effectuer manuellement par la personne."""

    application_id: str
    due_date: str
    reason: Reason
    channel: Channel

    def to_dict(self) -> dict[str, str]:
        return {
            "application_id": self.application_id,
            "due_date": self.due_date,
            "reason": self.reason,
            "channel": self.channel,
        }


@dataclass(frozen=True)
class FollowupPlan:
    """Plan du jour : actions dues et raisons de ne pas relancer le reste."""

    date: str
    actions: list[FollowupAction] = field(default_factory=list)
    blocked_reasons: dict[str, str] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "date": self.date,
            "actions": [action.to_dict() for action in self.actions],
            "blocked_reasons": dict(self.blocked_reasons),
        }


@dataclass(frozen=True)
class SpamGuardResult:
    """Verdict du garde-fou anti-sur-relance pour une date donnée."""

    allowed: bool
    reason: str
    next_allowed_date: str | None
    followups_used: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "allowed": self.allowed,
            "reason": self.reason,
            "next_allowed_date": self.next_allowed_date,
            "followups_used": self.followups_used,
        }


def _as_date(value: Any) -> date | None:
    """Lit une date ISO (ou un horodatage ISO) sans jamais lever d'exception."""
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    text = clean_text(value, limit=40)
    if not text:
        return None
    try:
        return date.fromisoformat(text[:10])
    except ValueError:
        pass
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00")).date()
    except ValueError:
        return None


def _json_object(value: Any) -> dict[str, Any]:
    if isinstance(value, Mapping):
        return dict(value)
    text = clean_text(value, limit=2_000)
    if not text:
        return {}
    try:
        parsed = json.loads(text)
    except (ValueError, TypeError):
        return {}
    return dict(parsed) if isinstance(parsed, Mapping) else {}


def _event_date(event: Mapping[str, Any]) -> date | None:
    for key in ("date", "created_at", "at"):
        parsed = _as_date(event.get(key))
        if parsed is not None:
            return parsed
    return None


def application_view(
    record: Mapping[str, Any] | Any,
    events: Iterable[Mapping[str, Any]] | None = None,
    *,
    default_channel: Channel = DEFAULT_CHANNEL,
) -> dict[str, Any]:
    """Normalise une candidature et son journal en entrée pure du moteur.

    Accepte les lignes du service (``application_id``, ``stage``,
    ``deadline_date``, ``source_status``…) et les événements ``application_events``.
    Les données malformées sont ignorées une par une : elles ne doivent jamais
    faire échouer le plan du jour.
    """
    source = dict(record) if isinstance(record, Mapping) else {}
    event_list = [dict(item) for item in (events or []) if isinstance(item, Mapping)]

    application_id = clean_text(
        source.get("application_id") or source.get("id"), limit=120
    )
    stage = clean_text(source.get("stage"), limit=80)
    channel = clean_text(
        source.get("channel") or default_channel, limit=40
    ).lower()
    availability = clean_text(
        source.get("availability_status") or source.get("source_status"), limit=40
    ).lower()
    sent_on = _as_date(
        source.get("sent_on") or source.get("sent_date") or source.get("submitted_on")
    )
    viewed_on = _as_date(
        source.get("viewed_on") or source.get("viewed_at") or source.get("seen_on")
    )
    deadline_date = _as_date(
        source.get("deadline_date") or source.get("deadline")
    )

    followups: list[dict[str, str]] = []
    for raw in source.get("followups") or []:
        if not isinstance(raw, Mapping):
            continue
        followup_date = _event_date(raw)
        if followup_date is None:
            continue
        followups.append(
            {
                "date": followup_date.isoformat(),
                "channel": clean_text(raw.get("channel"), limit=40).lower(),
                "reason": clean_text(raw.get("reason"), limit=60),
            }
        )

    for event in event_list:
        event_type = clean_text(event.get("event_type"), limit=80)
        event_date = _event_date(event)
        if event_type in VIEW_EVENT_TYPES and event_date is not None:
            if viewed_on is None or event_date > viewed_on:
                viewed_on = event_date
            continue
        if event_type == FOLLOWUP_EVENT_TYPE:
            payload = _json_object(event.get("detail"))
            followup_date = _as_date(payload.get("date")) or event_date
            if followup_date is None:
                continue
            followups.append(
                {
                    "date": followup_date.isoformat(),
                    "channel": clean_text(payload.get("channel"), limit=40).lower(),
                    "reason": clean_text(payload.get("reason"), limit=60),
                }
            )
            continue
        # Pour une candidature envoyée, le dernier ``stage_updated`` est la
        # déclaration d'envoi.  Les événements ultérieurs (checklist, relance,
        # accusé de réception) ne déplacent jamais cette date d'envoi.
        if event_type == "stage_updated" and stage in SENT_STAGES and event_date is not None:
            if sent_on is None or event_date > sent_on:
                sent_on = event_date

    unique: dict[tuple[str, str, str], dict[str, str]] = {}
    for followup in followups:
        key = (followup["date"], followup["channel"], followup["reason"])
        unique[key] = followup
    ordered = [unique[key] for key in sorted(unique)]

    return {
        "application_id": application_id,
        "stage": stage,
        "channel": channel,
        "sent_on": sent_on.isoformat() if sent_on else "",
        "viewed_on": viewed_on.isoformat() if viewed_on else "",
        "deadline_date": deadline_date.isoformat() if deadline_date else "",
        "availability_status": availability,
        "followups": ordered,
    }


def _guard_view(
    view: Mapping[str, Any],
    *,
    on_date: date,
    policy: FollowupPolicy,
) -> SpamGuardResult:
    stage = clean_text(view.get("stage"), limit=80)
    application_id = clean_text(view.get("application_id"), limit=120)
    channel = clean_text(view.get("channel"), limit=40).lower()
    sent_on = _as_date(view.get("sent_on"))
    availability = clean_text(view.get("availability_status"), limit=40).lower()
    used = len(view.get("followups") or [])

    if stage in CLOSED_STAGES:
        return SpamGuardResult(False, "closed", None, used)
    if stage in RESPONDED_STAGES:
        return SpamGuardResult(False, "responded", None, used)
    if availability == "closed":
        return SpamGuardResult(False, "offer_closed", None, used)
    if stage not in SENT_STAGES:
        return SpamGuardResult(False, "not_sent", None, used)
    if not application_id:
        return SpamGuardResult(False, "missing_application_id", None, used)
    if sent_on is None:
        return SpamGuardResult(False, "missing_sent_date", None, used)
    if sent_on > on_date:
        return SpamGuardResult(False, "invalid_sent_date", None, used)
    if channel not in CHANNELS:
        return SpamGuardResult(False, "invalid_channel", None, used)

    elapsed: list[date] = []
    for followup in view.get("followups") or []:
        if not isinstance(followup, Mapping):
            continue
        followup_date = _as_date(followup.get("date"))
        # Une date future ne prouve aucune relance : elle est ignorée pour la
        # cadence, même si elle reste visible dans l'historique local.
        if followup_date is not None and followup_date <= on_date:
            elapsed.append(followup_date)
    elapsed.sort()
    used = len(elapsed)

    if used >= policy.max_followups:
        return SpamGuardResult(False, "max_followups_reached", None, used)

    baseline = elapsed[-1] if elapsed else sent_on
    delay = policy.first_followup_days if not elapsed else policy.min_interval_days
    next_allowed = baseline + timedelta(days=delay)
    if on_date < next_allowed:
        reason = "not_due" if not elapsed else "min_interval_not_elapsed"
        return SpamGuardResult(False, reason, next_allowed.isoformat(), used)
    return SpamGuardResult(True, "due", next_allowed.isoformat(), used)


def spam_guard(
    application: Mapping[str, Any] | Any,
    *,
    on_date: date | str | None = None,
    policy: FollowupPolicy = DEFAULT_POLICY,
    events: Iterable[Mapping[str, Any]] | None = None,
) -> SpamGuardResult:
    """Vérifie qu'une relance est autorisée à ``on_date``.

    Accepte une candidature déjà normalisée par :func:`application_view` ou un
    enregistrement brut accompagné de ses événements.
    """
    target = _as_date(on_date) or date.today()
    view = application_view(
        application, events, default_channel=policy.default_channel
    )
    return _guard_view(view, on_date=target, policy=policy)


def followup_reason(
    application: Mapping[str, Any] | Any,
    *,
    on_date: date | str | None = None,
    policy: FollowupPolicy = DEFAULT_POLICY,
    events: Iterable[Mapping[str, Any]] | None = None,
) -> Reason:
    """Choisit la raison lisible d'une relance due, par priorité explicite."""
    target = _as_date(on_date) or date.today()
    view = application_view(
        application, events, default_channel=policy.default_channel
    )
    deadline = _as_date(view.get("deadline_date"))
    if (
        deadline is not None
        and target <= deadline
        and (deadline - target).days <= policy.deadline_soon_days
    ):
        return "deadline_soon"
    viewed_on = _as_date(view.get("viewed_on"))
    if viewed_on is not None and viewed_on <= target:
        return "viewed_no_reply"
    return "no_response_j7"


def _blocked_text(guard: SpamGuardResult) -> str:
    if guard.reason in {"not_due", "min_interval_not_elapsed"} and guard.next_allowed_date:
        return f"{guard.reason}:{guard.next_allowed_date}"
    return guard.reason


def plan_today(
    applications: Iterable[Mapping[str, Any] | Any] | None,
    *,
    today: date | str | None = None,
    policy: FollowupPolicy = DEFAULT_POLICY,
) -> FollowupPlan:
    """Calcule les relances dues aujourd'hui et les blocages explicites.

    ``due_date`` est la date à laquelle la relance est devenue due.  Une
    relance en retard reste donc visible avec sa date d'origine (jamais une
    date réécrite en silence).  Les applications en double identifiant sont
    refusées pour éviter deux relances le même jour.
    """
    target = _as_date(today) or date.today()
    actions: list[FollowupAction] = []
    blocked: dict[str, str] = {}

    records = list(applications or [])[: policy.max_applications]
    views = [
        view
        for view in (
            application_view(raw, default_channel=policy.default_channel)
            for raw in records
        )
        if clean_text(view.get("application_id"), limit=120)
    ]
    counts: dict[str, int] = {}
    for view in views:
        application_id = clean_text(view.get("application_id"), limit=120)
        counts[application_id] = counts.get(application_id, 0) + 1

    for view in views:
        application_id = clean_text(view.get("application_id"), limit=120)
        if counts.get(application_id, 0) > 1:
            blocked[application_id] = "duplicate_application_id"
            continue

        guard = _guard_view(view, on_date=target, policy=policy)
        if not guard.allowed:
            blocked[application_id] = _blocked_text(guard)
            continue
        due_date = _as_date(guard.next_allowed_date)
        if due_date is None:
            blocked[application_id] = "invalid_schedule"
            continue
        actions.append(
            FollowupAction(
                application_id=application_id,
                due_date=due_date.isoformat(),
                reason=followup_reason(view, on_date=target, policy=policy),
                channel=view["channel"],  # validé par le garde-fou
            )
        )

    actions.sort(key=lambda action: (action.due_date, action.application_id))
    return FollowupPlan(
        date=target.isoformat(),
        actions=actions,
        blocked_reasons=dict(sorted(blocked.items())),
    )
