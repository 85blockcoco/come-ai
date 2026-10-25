"""Entonnoir de conversion des candidatures — SPEC-025 (local et déterministe).

Le module transforme des candidatures *déjà locales* (statut courant, journal
``application_events``, brouillons et checklist) en un entonnoir honnête :

* combien de candidatures ont atteint chaque étape ;
* la conversion depuis l'étape précédente ;
* la même lecture par semaine ISO (cohorte = semaine de création) et par canal
  de source (``jobs.source_name``) ;
* l'étape qui perd le plus de candidatures.

Aucune E/S, aucun réseau, aucun modèle : le même entrant produit toujours le
même rapport. Aucune donnée n'est inventée — un signal absent ne compte pas.
Career n'envoie jamais d'e-mail : ``followed_up`` ne représente qu'une relance
*planifiée localement* dans la checklist, jamais un message parti.
"""

from __future__ import annotations

import json
from collections import defaultdict
from dataclasses import asdict, dataclass
from datetime import date, datetime, timezone
from typing import Any, Iterable, Literal, Mapping, Sequence

FUNNEL_STAGES: tuple[str, ...] = (
    "sent",
    "viewed",
    "prepped",
    "lettered",
    "followed_up",
    "interview",
    "offer",
)

StageName = Literal["sent", "viewed", "prepped", "lettered", "followed_up", "interview", "offer"]

#: Statuts de candidature qui prouvent qu'un dépôt manuel a été déclaré.
SENT_STAGES = frozenset(
    {"receipt_unknown", "submitted", "submitted_confirmed", "response_received", "interview", "offer_received"}
)

#: Statuts qui prouvent (ou rendent crédible) qu'un employeur a répondu.
RESPONSE_STAGES = frozenset({"response_received", "interview", "offer_received"})

INTERVIEW_STAGES = frozenset({"interview", "offer_received"})

#: Événements structurés utilisés comme jalons. Le détail libre n'est jamais
#: interprété : une note (« relancé lundi ») ne vaut pas une preuve.
SENT_EVENT_TYPES = frozenset({"application_sent", "application_submitted", "sent"})
VIEWED_EVENT_TYPES = frozenset({"application_viewed", "response_received", "viewed"})
PREP_EVENT_TYPES = frozenset({"kit_prepared", "application_prepared"})
FOLLOWUP_EVENT_TYPES = frozenset({"follow_up", "follow_up_recorded", "followed_up"})
INTERVIEW_EVENT_TYPES = frozenset({"interview", "interview_scheduled"})
OFFER_EVENT_TYPES = frozenset({"offer", "offer_received"})

#: Clés de checklist qui prouvent une préparation locale.
PREP_CHECKLIST_KEYS = frozenset({"cv_reviewed", "documents_checked", "deadline_verified"})
LETTER_CHECKLIST_KEY = "letter_customized"
FOLLOWUP_CHECKLIST_KEY = "followup_planned"

CHECKLIST_EVENT_TYPE = "checklist"
KIT_CONTENT_EVENT_TYPE = "kit_content"

UNKNOWN_CHANNEL = "unknown"
"""Canal exposé quand ``jobs.source_name`` est vide : jamais une invention."""


@dataclass
class FunnelStage:
    stage: StageName
    count: int
    conversion_from_prev: float


@dataclass
class FunnelReport:
    stages: list[FunnelStage]
    weekly_series: dict[str, dict]
    bottleneck_stage: str
    per_channel: dict[str, list[FunnelStage]]

    def to_dict(self) -> dict[str, Any]:
        return {
            "stages": [asdict(stage) for stage in self.stages],
            "weekly_series": self.weekly_series,
            "bottleneck_stage": self.bottleneck_stage,
            "per_channel": {
                channel: [asdict(stage) for stage in stages]
                for channel, stages in self.per_channel.items()
            },
        }


# ---------------------------------------------------------------------------
# Normalisation tolérante (aucune exception sur une base éditée à la main)
# ---------------------------------------------------------------------------

def normalize_channel(value: Any) -> str:
    """Normalise un canal de source ; un canal absent reste ``unknown``."""

    text = " ".join(str(value or "").strip().lower().split())
    return text or UNKNOWN_CHANNEL


def _parse_date(value: Any) -> date | None:
    """Lit une date ISO (avec ou sans fuseau) et la ramène en UTC.

    Une valeur illisible renvoie ``None`` : elle est exclue de la série
    hebdomadaire plutôt que rangée dans une fausse semaine.
    """

    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, date):
        return value
    else:
        text = str(value or "").strip()
        if not text:
            return None
        try:
            parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
        except ValueError:
            try:
                return date.fromisoformat(text[:10])
            except ValueError:
                return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc).date()


def iso_week(value: Any) -> str | None:
    """Retourne la semaine ISO ``YYYY-Www`` d'une date, ou ``None``."""

    parsed = _parse_date(value)
    if parsed is None:
        return None
    year, week, _ = parsed.isocalendar()
    return f"{year}-W{week:02d}"


def _events(record: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    raw = record.get("events")
    if not isinstance(raw, (list, tuple)):
        return []
    return [event for event in raw if isinstance(event, Mapping)]


def _event_types(record: Mapping[str, Any]) -> set[str]:
    return {
        str(event.get("event_type") or "").strip().lower()
        for event in _events(record)
        if str(event.get("event_type") or "").strip()
    }


def _checklist_items(record: Mapping[str, Any]) -> frozenset[str]:
    """Clés vraies du **dernier** événement checklist lisible.

    Le dernier événement fait foi, comme dans le tableau de bord CVBOOST-09 :
    l'état est rejouable et réversible. Un détail illisible est ignoré, jamais
    interprété comme « tout coché ».
    """

    checked: frozenset[str] = frozenset()
    for event in _events(record):
        if str(event.get("event_type") or "").strip().lower() != CHECKLIST_EVENT_TYPE:
            continue
        detail = event.get("detail")
        try:
            payload = json.loads(detail) if isinstance(detail, str) else detail
        except (TypeError, ValueError):
            continue
        if not isinstance(payload, Mapping):
            continue
        items = payload.get("items")
        if isinstance(items, Mapping):
            checked = frozenset(
                str(key) for key, value in items.items() if value is True
            )
            continue
        listed = payload.get("checked")
        if isinstance(listed, (list, tuple)):
            checked = frozenset(str(item) for item in listed)
    return checked


def _has_kit_letter(record: Mapping[str, Any]) -> bool:
    """Détecte une lettre matérialisée dans un événement ``kit_content``."""

    for event in _events(record):
        if str(event.get("event_type") or "").strip().lower() != KIT_CONTENT_EVENT_TYPE:
            continue
        detail = event.get("detail")
        try:
            payload = json.loads(detail) if isinstance(detail, str) else detail
        except (TypeError, ValueError):
            continue
        if isinstance(payload, Mapping) and str(payload.get("letter_markdown") or "").strip():
            return True
    return False


def _reached_stages(record: Mapping[str, Any]) -> set[str]:
    """Jalons réellement démontrés par une candidature.

    Chaque jalon vient d'une preuve locale : statut courant, référence de
    réception, événement structuré, brouillon ou checklist. Une simple ligne
    SQLite ne prouve jamais un envoi.
    """

    reached: set[str] = set()
    stage = str(record.get("stage") or "").strip().lower()
    receipt = str(record.get("receipt_status") or "").strip().lower()
    event_types = _event_types(record)
    checklist = _checklist_items(record)

    sent = (
        stage in SENT_STAGES
        or receipt == "confirmed"
        or bool(event_types & SENT_EVENT_TYPES)
    )
    if sent:
        reached.add("sent")
    if (
        receipt == "confirmed"
        or stage in RESPONSE_STAGES
        or bool(event_types & VIEWED_EVENT_TYPES)
    ):
        reached.update({"viewed", "sent"})

    prepared = (
        bool(record.get("has_draft"))
        or bool(event_types & PREP_EVENT_TYPES)
        or bool(checklist & PREP_CHECKLIST_KEYS)
    )
    if prepared:
        reached.add("prepped")
    if (
        bool(record.get("has_letter"))
        or LETTER_CHECKLIST_KEY in checklist
        or _has_kit_letter(record)
    ):
        reached.add("lettered")
        # Une lettre matérialisée est aussi un travail de préparation.
        reached.add("prepped")
    if FOLLOWUP_CHECKLIST_KEY in checklist or bool(event_types & FOLLOWUP_EVENT_TYPES):
        reached.add("followed_up")
    if stage in INTERVIEW_STAGES or bool(event_types & INTERVIEW_EVENT_TYPES):
        reached.add("interview")
        # Un entretien ou une offre prouve que la candidature a été envoyée et
        # consultée : ces statuts ne sont jamais atteints sans dépôt.
        reached.update({"viewed", "sent"})
    if stage == "offer_received" or bool(event_types & OFFER_EVENT_TYPES):
        reached.add("offer")
        reached.update({"interview", "viewed", "sent"})
    return reached


# ---------------------------------------------------------------------------
# Agrégation
# ---------------------------------------------------------------------------

def _records(applications: Any) -> list[Mapping[str, Any]]:
    if applications is None:
        return []
    if isinstance(applications, Mapping):
        return [applications]
    if isinstance(applications, (str, bytes)):
        return []
    try:
        return [item for item in applications if isinstance(item, Mapping)]
    except TypeError:
        return []


def _milestone_counts(records: Sequence[Mapping[str, Any]]) -> dict[str, int]:
    reached = [_reached_stages(record) for record in records]
    return {stage: sum(1 for items in reached if stage in items) for stage in FUNNEL_STAGES}


def _funnel_stages(counts: Sequence[int]) -> list[FunnelStage]:
    """Construit les étapes en gardant des comptes bruts et honnêtes.

    Chaque compte est le nombre de candidatures ayant réellement démontré ce
    jalon : aucun jalon absent n'est inventé. Les jalons n'étant pas
    strictement séquentiels dans les données locales (une lettre peut être
    écrite avant l'envoi, une relance planifiée peut manquer), une étape peut
    concerner plus de candidatures que la précédente : la conversion est alors
    plafonnée à 100 %, jamais gonflée au-delà de l'intervalle [0, 1].
    """

    stages: list[FunnelStage] = []
    previous = 0
    for index, name in enumerate(FUNNEL_STAGES):
        count = max(0, int(counts[index]))
        if index == 0:
            conversion = 1.0 if count > 0 else 0.0
        elif previous > 0:
            conversion = min(1.0, count / previous)
        else:
            conversion = 0.0
        stages.append(
            FunnelStage(stage=name, count=count, conversion_from_prev=round(conversion, 4))  # type: ignore[arg-type]
        )
        previous = count
    return stages


def _stage_counts(records: Sequence[Mapping[str, Any]]) -> list[int]:
    milestones = _milestone_counts(records)
    return [milestones[stage] for stage in FUNNEL_STAGES]


def weakest_stage(stages: Iterable[FunnelStage] | FunnelReport | Sequence[FunnelStage]) -> str:
    """Retourne l'étape qui perd le plus de candidatures.

    Seules les transitions avec un dénominateur non nul sont comparables. À
    conversion égale, la plus grosse perte absolue gagne, puis l'étape la plus
    précoce (ordre stable). Un entonnoir vide n'a pas de goulot : ``""``.
    """

    if isinstance(stages, FunnelReport):
        return stages.bottleneck_stage
    ordered = list(stages)
    if len(ordered) < 2 or all(stage.count == 0 for stage in ordered):
        return ""
    candidates = [
        (index, stage)
        for index, stage in enumerate(ordered)
        if index > 0 and ordered[index - 1].count > 0
    ]
    if not candidates:
        return ""
    _, chosen = min(
        candidates,
        key=lambda item: (
            item[1].conversion_from_prev,
            -max(0, ordered[item[0] - 1].count - item[1].count),
            item[0],
        ),
    )
    return chosen.stage


def compute_funnel(applications: Any = None, *, channel: str = "") -> FunnelReport:
    """Calcule l'entonnoir global, hebdomadaire et par canal.

    ``applications`` est un itérable de mappings (une entrée par candidature) :

    ``stage``, ``receipt_status``, ``created_at``, ``channel`` /
    ``source_name``, ``events`` (liste de ``{event_type, detail, created_at}``),
    ``has_draft`` et ``has_letter``. Toute clé absente ou illisible est ignorée.

    ``channel`` filtre sur un canal normalisé ; un canal inconnu produit un
    rapport dégénéré cohérent, jamais une erreur.
    """

    records = _records(applications)
    requested_channel = normalize_channel(channel) if str(channel or "").strip() else ""
    if requested_channel:
        records = [
            record
            for record in records
            if normalize_channel(record.get("channel") or record.get("source_name")) == requested_channel
        ]

    stages = _funnel_stages(_stage_counts(records))

    weekly: dict[str, dict[str, int]] = {}
    by_week: dict[str, list[Mapping[str, Any]]] = defaultdict(list)
    for record in records:
        week = iso_week(record.get("created_at", record.get("date")))
        if week is not None:
            by_week[week].append(record)
    for week in sorted(by_week):
        weekly[week] = {
            stage.stage: stage.count for stage in _funnel_stages(_stage_counts(by_week[week]))
        }

    grouped: dict[str, list[Mapping[str, Any]]] = defaultdict(list)
    for record in records:
        grouped[normalize_channel(record.get("channel") or record.get("source_name"))].append(record)
    per_channel = {
        name: _funnel_stages(_stage_counts(grouped[name])) for name in sorted(grouped)
    }

    return FunnelReport(
        stages=stages,
        weekly_series=weekly,
        bottleneck_stage=weakest_stage(stages),
        per_channel=per_channel,
    )


def funnel_by_channel(applications: Any = None) -> dict[str, list[FunnelStage]]:
    """Retourne ``canal -> entonnoir`` (même calcul que ``compute_funnel``)."""

    return compute_funnel(applications).per_channel


__all__ = [
    "FUNNEL_STAGES",
    "UNKNOWN_CHANNEL",
    "FunnelStage",
    "FunnelReport",
    "compute_funnel",
    "funnel_by_channel",
    "iso_week",
    "normalize_channel",
    "weakest_stage",
]
