"""SPEC-005 — cockpit quotidien local (« Aujourd'hui »).

Ce module est **pur** : aucun E/S, aucun réseau, aucun modèle, aucun secret.
Il transforme des enregistrements *déjà locaux* (offres, candidatures,
événements, brouillons) en une projection déterministe :

* ``urgent`` : ce qui mérite une action aujourd'hui — échéance proche, relance
  due, réception à vérifier, entretien déclaré localement ;
* ``opportunities`` : les offres encore ouvertes qui correspondent à tes
  critères, une fois la localisation filtrée ;
* ``progression`` : les compteurs factuels des sept derniers jours ;
* ``interviews`` : les entretiens déclarés dans ton suivi.

Garanties centrales :

* même entrant + même date ⇒ même sortie (aucun horodatage caché) ;
* une donnée absente reste un **inconnu nommé**, jamais un zéro inventé ;
* aucune action externe : ni e-mail, ni message, ni candidature envoyée. Une
  relance reste un brouillon local que la personne utilise elle-même ;
* une ligne SQLite n'est jamais assimilée à un envoi : « envoyée » ne vient que
  d'un état déclaré par la personne.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from hashlib import sha256
from typing import Any, Iterable, Mapping, Sequence

from .models import clean_text, normalized_text

DEFAULT_USER_ID = "local"
"""Identifiant local du cockpit : l'espace Career est mono-utilisateur."""

DEFAULT_TTL_SECONDS = 4 * 60 * 60
"""Durée de vie du cache par défaut (4 heures), configurable."""

EXPIRING_OFFER_WINDOW_DAYS = 7
"""Fenêtre « échéance proche » : au-delà, l'offre n'est plus urgente."""

FOLLOWUP_DELAY_DAYS = 10
"""Délai de respiration avant une relance suggérée (même politique que le radar)."""

FOLLOWUP_PREVIEW_DAYS = 7
"""Le cockpit montre la relance trois jours avant la date raisonnable : le
brouillon se prépare à l'avance, l'envoi reste manuel."""

PROGRESSION_WINDOW_DAYS = 7
"""Fenêtre de la progression : les sept derniers jours, aujourd'hui inclus."""

MAX_URGENT_ITEMS = 12
MAX_OPPORTUNITIES = 8
MAX_SOURCE_RECORDS = 500
"""Enregistrements locaux inspectés au maximum pour un calcul."""

MAX_INTERVIEW_ITEMS = 12

DEFAULT_EXCLUDED_COUNTRIES: tuple[str, ...] = ("France",)
DEFAULT_EXCLUDED_CITIES: tuple[str, ...] = ("Paris",)
"""Exclusions géographiques par défaut : Paris et la France sont retirés des
opportunités. Elles ne masquent jamais une échéance déjà suivie."""

DEFAULT_CALENDAR_NAME = "Côme AI — cockpit quotidien"

SENT_STAGES = frozenset(
    {"submitted", "submitted_confirmed", "response_received", "interview", "offer_received"}
)
"""États déclarés par la personne : la candidature a été déposée à la main."""

AWAITING_REPLY_STAGES = frozenset({"submitted", "submitted_confirmed"})
"""Candidatures déposées, sans réponse connue : candidates à une relance."""

CLOSED_STAGES = frozenset({"rejected", "refused", "withdrawn", "archived"})
CLOSED_JOB_STATES = frozenset({"archived", "rejected", "withdrawn", "closed"})

REJECTED_STAGES = frozenset({"rejected", "refused"})

_URGENT_RANK = {
    "expiring_offer": 0,
    "interview_due": 1,
    "receipt_unknown": 2,
    "followup_due": 3,
}

DISCLAIMER = (
    "Cockpit calculé localement à partir de tes offres, de tes suivis et de tes brouillons. "
    "Aucun e-mail, message, formulaire ou candidature n'est envoyé : les relances sont des "
    "brouillons que tu utilises toi-même, et les scores mesurent une adéquation documentaire, "
    "jamais une probabilité d'embauche."
)

PROGRESSION_FORMULA = (
    "Progression = actions déclarées localement sur les 7 derniers jours. "
    "Candidatures envoyées = suivis déclarés envoyés et encore en attente de réponse. "
    "Taux de conversion = candidatures envoyées / dossiers préparés (0 quand aucun dossier "
    "n'a été préparé). Un envoi n'est compté que s'il a été déclaré par toi."
)


@dataclass
class DailyDigest:
    """Projection locale déterministe d'une journée de travail."""

    user_id: str = DEFAULT_USER_ID
    date: str = ""
    urgent: list[dict[str, Any]] = field(default_factory=list)
    opportunities: list[dict[str, Any]] = field(default_factory=list)
    interviews: list[dict[str, Any]] = field(default_factory=list)
    progression: dict[str, Any] = field(default_factory=dict)
    last_refresh: str = ""
    cache_expires_at: str = ""
    ttl_seconds: int = DEFAULT_TTL_SECONDS
    excluded_countries: list[str] = field(default_factory=list)
    excluded_cities: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    disclaimer: str = DISCLAIMER

    def to_dict(self) -> dict[str, Any]:
        """Retourne le contrat JSON attendu par ``GET /api/career/daily``."""

        return {
            "user_id": self.user_id,
            "date": self.date,
            "urgent": [dict(item) for item in self.urgent],
            "opportunities": [dict(item) for item in self.opportunities],
            "interviews": [dict(item) for item in self.interviews],
            "progression": dict(self.progression),
            "last_refresh": self.last_refresh,
            "cache_expires_at": self.cache_expires_at,
            "ttl_seconds": self.ttl_seconds,
            "exclusions": {
                "countries": list(self.excluded_countries),
                "cities": list(self.excluded_cities),
            },
            "notes": list(self.notes),
            "disclaimer": self.disclaimer,
        }


def compute_daily(
    user_id: str = DEFAULT_USER_ID,
    *,
    today: date | None = None,
    now: datetime | None = None,
    jobs: Sequence[Mapping[str, Any]] = (),
    applications: Sequence[Mapping[str, Any]] = (),
    drafts: Sequence[Mapping[str, Any]] = (),
    opportunity_candidates: Sequence[Mapping[str, Any]] = (),
    ttl_seconds: int = DEFAULT_TTL_SECONDS,
    excluded_countries: Sequence[str] = DEFAULT_EXCLUDED_COUNTRIES,
    excluded_cities: Sequence[str] = DEFAULT_EXCLUDED_CITIES,
) -> DailyDigest:
    """Calcule le cockpit quotidien à partir d'enregistrements locaux.

    La fonction ne lit rien et n'écrit rien : elle reçoit les offres, les
    candidatures (avec leurs événements), les brouillons et les candidats
    d'opportunité déjà préparés par le service local, puis renvoie un
    :class:`DailyDigest`. Deux appels avec le même entrant et la même date
    renvoient exactement le même résultat.

    ``user_id`` identifie le cockpit dans le cache local ; l'espace Career est
    mono-utilisateur, la valeur par défaut suffit.
    """

    current_day = today or date.today()
    moment = _utc(now)
    ttl = max(60, int(ttl_seconds or DEFAULT_TTL_SECONDS))
    countries = [clean_text(item, limit=120) for item in excluded_countries if clean_text(item, limit=120)]
    cities = [clean_text(item, limit=120) for item in excluded_cities if clean_text(item, limit=120)]

    application_by_job: dict[str, Mapping[str, Any]] = {}
    for application in _bounded(applications):
        job_id = _text(application.get("job_id"), 80)
        if job_id:
            application_by_job.setdefault(job_id, application)

    urgent, interviews, expiring_ids = _build_urgent(
        jobs,
        applications,
        application_by_job,
        today=current_day,
    )
    opportunities = _build_opportunities(
        opportunity_candidates,
        expiring_ids=expiring_ids,
        excluded_countries=countries,
        excluded_cities=cities,
        today=current_day,
    )
    progression = _build_progression(
        applications,
        drafts,
        today=current_day,
    )
    notes = _build_notes(
        jobs=jobs,
        applications=applications,
        urgent=urgent,
        opportunities=opportunities,
    )
    return DailyDigest(
        user_id=clean_text(user_id, limit=80) or DEFAULT_USER_ID,
        date=current_day.isoformat(),
        urgent=urgent,
        opportunities=opportunities,
        interviews=interviews,
        progression=progression,
        last_refresh=_iso_z(moment),
        cache_expires_at=_iso_z(moment + timedelta(seconds=ttl)),
        ttl_seconds=ttl,
        excluded_countries=countries,
        excluded_cities=cities,
        notes=notes,
    )


# ---------------------------------------------------------------------------
# Actions urgentes
# ---------------------------------------------------------------------------


def _build_urgent(
    jobs: Sequence[Mapping[str, Any]],
    applications: Sequence[Mapping[str, Any]],
    application_by_job: Mapping[str, Mapping[str, Any]],
    *,
    today: date,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], set[str]]:
    """Construit la liste « à faire aujourd'hui » et les entretiens déclarés."""

    urgent: list[dict[str, Any]] = []
    interviews: list[dict[str, Any]] = []
    expiring_ids: set[str] = set()

    for job in _bounded(jobs):
        job_id = _text(job.get("id"), 80)
        if not job_id:
            continue
        application = application_by_job.get(job_id) or job.get("application") or {}
        stage = _text(application.get("stage"), 80)
        if stage in SENT_STAGES or stage in CLOSED_STAGES:
            # Une offre déjà déposée ou close ne crée plus d'urgence.
            continue
        if _is_closed_job(job):
            continue
        deadline = _date_or_none(job.get("deadline_date"))
        if deadline is None or deadline < today:
            # Une échéance inconnue ou dépassée ne devient jamais une date inventée.
            continue
        days_left = (deadline - today).days
        if days_left > EXPIRING_OFFER_WINDOW_DAYS:
            continue
        title = _text(job.get("title"), 300) or "Offre sans intitulé"
        company = _text(job.get("company"), 240) or "Entreprise non renseignée"
        urgent.append(
            {
                "type": "expiring_offer",
                "offer_id": job_id,
                "title": title,
                "employer": company,
                "location": _location(job),
                "deadline_date": deadline.isoformat(),
                "days_left": days_left,
                "match_score": _match_score(job),
                "action_label": "Candidater avant clôture",
                "action_url": f"/api/career/jobs/{job_id}/prep",
                "is_email": False,
            }
        )
        expiring_ids.add(job_id)

    for application in _bounded(applications):
        application_id = _text(application.get("application_id") or application.get("id"), 80)
        if not application_id:
            continue
        stage = _text(application.get("stage"), 80)
        receipt = _text(application.get("receipt_status"), 40) or "not_submitted"
        if stage in CLOSED_STAGES or stage == "offer_received":
            continue
        title = _text(application.get("title"), 300) or "Offre sans intitulé"
        company = _text(application.get("company"), 240) or "Entreprise non renseignée"
        last_change = _last_event_date(application, {"stage_updated"})
        updated = _date_or_none(application.get("updated_at"))

        if stage == "interview":
            interview_date = last_change or updated
            if interview_date is not None:
                interviews.append(
                    {
                        "type": "interview_due",
                        "application_id": application_id,
                        "offer_title": title,
                        "employer": company,
                        "interview_date": interview_date.isoformat(),
                        "days_left": (interview_date - today).days,
                        "action_label": "Préparer l’entretien",
                        "action_url": f"/api/career/applications/{application_id}",
                        "is_email": False,
                    }
                )
            continue

        if receipt == "unknown":
            sent_date = last_change or updated
            urgent.append(
                {
                    "type": "receipt_unknown",
                    "application_id": application_id,
                    "offer_title": title,
                    "employer": company,
                    "sent_date": sent_date.isoformat() if sent_date else None,
                    "days_since_sent": max((today - sent_date).days, 0) if sent_date else None,
                    "action_label": "Vérifier la réception",
                    "action_url": f"/api/career/applications/{application_id}",
                    "is_email": False,
                }
            )
            continue

        if stage in AWAITING_REPLY_STAGES:
            sent_date = last_change or updated
            if sent_date is None:
                # Sans date locale déclarée, aucun délai de relance n'est inventé.
                continue
            days_since = max((today - sent_date).days, 0)
            if days_since < FOLLOWUP_PREVIEW_DAYS:
                continue
            urgent.append(
                {
                    "type": "followup_due",
                    "application_id": application_id,
                    "offer_title": title,
                    "employer": company,
                    "sent_date": sent_date.isoformat(),
                    "sent_date_source": "stage_updated_event" if last_change else "application_updated_at",
                    "days_since_sent": days_since,
                    "suggested_followup_date": (sent_date + timedelta(days=FOLLOWUP_DELAY_DAYS)).isoformat(),
                    "status": "due" if days_since >= FOLLOWUP_DELAY_DAYS else "upcoming",
                    "action_label": "Relancer",
                    "action_url": f"/api/career/applications/{application_id}",
                    "is_email": False,
                }
            )

    urgent.sort(key=_urgent_sort_key)
    interviews.sort(key=lambda item: (item.get("interview_date") or "9999-12-31", item.get("employer", "")))
    return urgent[:MAX_URGENT_ITEMS], interviews[:MAX_INTERVIEW_ITEMS], expiring_ids


def _urgent_sort_key(item: Mapping[str, Any]) -> tuple[int, str, str, str]:
    return (
        _URGENT_RANK.get(str(item.get("type")), 9),
        str(item.get("deadline_date") or item.get("suggested_followup_date") or "9999-12-31"),
        str(item.get("employer", "")).casefold(),
        str(item.get("title") or item.get("offer_title") or "").casefold(),
    )


# ---------------------------------------------------------------------------
# Opportunités
# ---------------------------------------------------------------------------


def _build_opportunities(
    candidates: Sequence[Mapping[str, Any]],
    *,
    expiring_ids: set[str],
    excluded_countries: Sequence[str],
    excluded_cities: Sequence[str],
    today: date,
) -> list[dict[str, Any]]:
    """Liste les offres encore ouvertes, une fois la localisation filtrée."""

    opportunities: list[dict[str, Any]] = []
    for candidate in _bounded(candidates):
        job_id = _text(candidate.get("job_id") or candidate.get("offer_id"), 80)
        if not job_id or job_id in expiring_ids:
            continue
        if _text(candidate.get("source_status"), 40) == "closed":
            continue
        stage = _text(candidate.get("application_stage"), 80)
        if stage in SENT_STAGES or stage in CLOSED_STAGES:
            continue
        city = _text(candidate.get("city"), 160)
        country = _text(candidate.get("country"), 120)
        if _is_excluded_location(city, country, excluded_countries, excluded_cities):
            continue
        posted = _date_or_none(candidate.get("posted_date"))
        opportunities.append(
            {
                "offer_id": job_id,
                "title": _text(candidate.get("title"), 300) or "Offre sans intitulé",
                "employer": _text(candidate.get("company"), 240) or "Entreprise non renseignée",
                "location": _location(candidate),
                "match_score": _candidate_score(candidate),
                "mandatory_coverage": _coverage_label(
                    candidate.get("mandatory_covered"),
                    candidate.get("mandatory_total"),
                ),
                "source_trust": _source_trust(candidate),
                "published_days_ago": (today - posted).days if posted else None,
                "action_label": "Préparer ce dossier",
                "action_url": f"/api/career/jobs/{job_id}/prep",
            }
        )
    opportunities.sort(
        key=lambda item: (
            -(item["match_score"] if isinstance(item["match_score"], int) else -1),
            item["published_days_ago"] if isinstance(item["published_days_ago"], int) else 9999,
            item["employer"].casefold(),
            item["title"].casefold(),
        )
    )
    return opportunities[:MAX_OPPORTUNITIES]


# ---------------------------------------------------------------------------
# Progression
# ---------------------------------------------------------------------------


def _build_progression(
    applications: Sequence[Mapping[str, Any]],
    drafts: Sequence[Mapping[str, Any]],
    *,
    today: date,
) -> dict[str, Any]:
    """Compte les actions déclarées localement sur les sept derniers jours."""

    window_start = today - timedelta(days=PROGRESSION_WINDOW_DAYS - 1)
    prepared = 0
    for draft in _bounded(drafts):
        created = _date_or_none(draft.get("created_at"))
        if created is not None and created >= window_start:
            prepared += 1

    sent = 0
    responses = 0
    interviews = 0
    rejections = 0
    for application in _bounded(applications):
        stage = _text(application.get("stage"), 80)
        last_change = _last_event_date(application, {"stage_updated"})
        updated = _date_or_none(application.get("updated_at"))
        if stage in AWAITING_REPLY_STAGES:
            # « Envoyée » = déclarée envoyée et encore en attente de réponse.
            stamp = last_change or updated
            if stamp is not None and stamp >= window_start:
                sent += 1
        if stage in {"response_received", "interview", "offer_received"}:
            stamp = last_change or updated
            if stamp is not None and stamp >= window_start:
                responses += 1
        if stage == "interview":
            stamp = last_change or updated
            if stamp is not None and stamp >= window_start:
                interviews += 1
        if stage in REJECTED_STAGES:
            stamp = last_change or updated
            if stamp is not None and stamp >= window_start:
                rejections += 1

    conversion_known = prepared > 0
    conversion_rate = round(sent / prepared, 3) if conversion_known else 0.0
    return {
        "prepared_this_week": prepared,
        "sent_this_week": sent,
        "responses_this_week": responses,
        "interviews_this_week": interviews,
        "rejections_this_week": rejections,
        "conversion_rate": conversion_rate,
        "conversion_known": conversion_known,
        "window_days": PROGRESSION_WINDOW_DAYS,
        "formula": PROGRESSION_FORMULA,
    }


# ---------------------------------------------------------------------------
# Notes de contexte
# ---------------------------------------------------------------------------


def _build_notes(
    *,
    jobs: Sequence[Mapping[str, Any]],
    applications: Sequence[Mapping[str, Any]],
    urgent: Sequence[Mapping[str, Any]],
    opportunities: Sequence[Mapping[str, Any]],
) -> list[str]:
    """Explicite ce qui manque pour que la journée soit lisible."""

    notes: list[str] = []
    if not jobs:
        notes.append("Aucune offre enregistrée : importe une offre pour obtenir des échéances.")
    if not applications:
        notes.append("Aucune candidature suivie : le radar de relance reste vide.")
    if not urgent:
        notes.append("Aucune action urgente aujourd’hui.")
    if not opportunities:
        notes.append("Aucune opportunité ne correspond à tes critères locaux.")
    unknown_deadlines = sum(
        1 for job in _bounded(jobs) if not _text(job.get("deadline_date"), 32)
    )
    if unknown_deadlines:
        notes.append(
            f"{unknown_deadlines} offre(s) sans date limite connue : vérifie la page officielle."
        )
    return notes


# ---------------------------------------------------------------------------
# Export calendrier local
# ---------------------------------------------------------------------------


def build_daily_calendar_ics(
    digest: Mapping[str, Any],
    *,
    calendar_name: str = DEFAULT_CALENDAR_NAME,
) -> str:
    """Construit un fichier ``.ics`` local et déterministe pour la journée.

    Trois familles d'événements sont écrites :

    * les échéances d'offres (``DTEND`` = date limite, la fenêtre d'action
      commence le jour du digest) ;
    * les relances suggérées (``DTSTART`` = date de relance, avec une
      récurrence hebdomadaire bornée pour un suivi qui reste ouvert) ;
    * les entretiens déclarés localement (``DTSTART`` = date déclarée).

    Les ``UID`` sont dérivés du type et de la clé de l'élément : réimporter le
    fichier met donc à jour les mêmes événements au lieu d'en créer de
    nouveaux. Aucun horodatage de génération n'est utilisé : deux exports du
    même digest sont identiques.
    """

    from .calendar_export import escape_ical_text, fold_ical_line

    day = _text(digest.get("date"), 32) or date.today().isoformat()
    stamp = f"{day.replace('-', '')}T000000Z"
    lines = [
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        "PRODID:-//Come AI//Career local daily command center//FR",
        "CALSCALE:GREGORIAN",
        "METHOD:PUBLISH",
        f"X-WR-CALNAME:{escape_ical_text(clean_text(calendar_name, limit=160) or DEFAULT_CALENDAR_NAME)}",
    ]
    for item in digest.get("urgent") or []:
        if not isinstance(item, Mapping):
            continue
        event = _deadline_event(item, day=day, stamp=stamp)
        if event:
            lines.extend(event)
    for item in digest.get("interviews") or []:
        if not isinstance(item, Mapping):
            continue
        event = _interview_event(item, stamp=stamp)
        if event:
            lines.extend(event)
    lines.append("END:VCALENDAR")
    return "".join(fold_ical_line(line) + "\r\n" for line in lines)


def _deadline_event(item: Mapping[str, Any], *, day: str, stamp: str) -> list[str] | None:
    from .calendar_export import escape_ical_text

    kind = _text(item.get("type"), 40)
    if kind == "expiring_offer":
        deadline = _date_or_none(item.get("deadline_date"))
        if deadline is None:
            return None
        start = _date_or_none(day) or deadline
        end = deadline
        if end <= start:
            end = start + timedelta(days=1)
        summary = f"Échéance : {_text(item.get('employer'), 240)} — {_text(item.get('title'), 300)}"
        description = (
            "Fenêtre d'action locale Côme AI : la date limite est le DTEND de cet événement."
        )
        uid = _uid("deadline", _text(item.get("offer_id"), 80))
        return [
            "BEGIN:VEVENT",
            f"UID:{uid}",
            f"DTSTAMP:{stamp}",
            f"DTSTART;VALUE=DATE:{start:%Y%m%d}",
            f"DTEND;VALUE=DATE:{end:%Y%m%d}",
            f"SUMMARY:{escape_ical_text(summary)}",
            f"DESCRIPTION:{escape_ical_text(description)}",
            "TRANSP:TRANSPARENT",
            "END:VEVENT",
        ]
    if kind == "followup_due":
        start = _date_or_none(item.get("suggested_followup_date"))
        if start is None:
            return None
        summary = f"Relance à préparer : {_text(item.get('employer'), 240)} — {_text(item.get('offer_title'), 300)}"
        description = (
            "Brouillon de relance local : aucun e-mail n'est envoyé, tu utilises le brouillon toi-même."
        )
        uid = _uid("followup", _text(item.get("application_id"), 80))
        return [
            "BEGIN:VEVENT",
            f"UID:{uid}",
            f"DTSTAMP:{stamp}",
            f"DTSTART;VALUE=DATE:{start:%Y%m%d}",
            f"DTEND;VALUE=DATE:{start + timedelta(days=1):%Y%m%d}",
            f"SUMMARY:{escape_ical_text(summary)}",
            f"DESCRIPTION:{escape_ical_text(description)}",
            "RRULE:FREQ=WEEKLY;INTERVAL=1;COUNT=4",
            "TRANSP:TRANSPARENT",
            "END:VEVENT",
        ]
    return None


def _interview_event(item: Mapping[str, Any], *, stamp: str) -> list[str] | None:
    from .calendar_export import escape_ical_text

    start = _date_or_none(item.get("interview_date"))
    if start is None:
        return None
    summary = f"Entretien : {_text(item.get('employer'), 240)} — {_text(item.get('offer_title'), 300)}"
    description = (
        "Entretien déclaré dans ton suivi local. L'heure exacte n'est pas enregistrée : "
        "confirme-la sur le canal officiel."
    )
    uid = _uid("interview", _text(item.get("application_id"), 80))
    return [
        "BEGIN:VEVENT",
        f"UID:{uid}",
        f"DTSTAMP:{stamp}",
        f"DTSTART;VALUE=DATE:{start:%Y%m%d}",
        f"DTEND;VALUE=DATE:{start + timedelta(days=1):%Y%m%d}",
        f"SUMMARY:{escape_ical_text(summary)}",
        f"DESCRIPTION:{escape_ical_text(description)}",
        "TRANSP:TRANSPARENT",
        "END:VEVENT",
    ]


def _uid(kind: str, key: str) -> str:
    digest = sha256(f"come-ai-career-daily:{kind}:{key}".encode("utf-8")).hexdigest()[:32]
    return f"come-ai-career-daily-{digest}@local"


# ---------------------------------------------------------------------------
# Petits utilitaires tolérants
# ---------------------------------------------------------------------------


def _bounded(records: Iterable[Mapping[str, Any]] | None) -> tuple[Mapping[str, Any], ...]:
    """Lit un nombre borné de mappings sans matérialiser un itérateur non fiable."""

    if not records:
        return ()
    try:
        iterator = iter(records)
    except TypeError:
        return ()
    result: list[Mapping[str, Any]] = []
    for record in iterator:
        if len(result) >= MAX_SOURCE_RECORDS:
            break
        if isinstance(record, Mapping):
            result.append(record)
    return tuple(result)


def _text(value: Any, limit: int = 200) -> str:
    return clean_text(value, limit=limit)


def _date_or_none(value: Any) -> date | None:
    """Lit une date ISO ; une valeur illisible reste un inconnu, jamais une erreur."""

    text = _text(value, 32)
    if not text:
        return None
    try:
        return date.fromisoformat(text[:10])
    except ValueError:
        return None


def _utc(moment: datetime | None) -> datetime:
    if moment is None:
        return datetime.now(timezone.utc)
    if moment.tzinfo is None:
        return moment.replace(tzinfo=timezone.utc)
    return moment.astimezone(timezone.utc)


def _iso_z(moment: datetime) -> str:
    return moment.astimezone(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _last_event_date(application: Mapping[str, Any], event_types: set[str]) -> date | None:
    """Date du dernier événement local d'un type donné (jamais d'horloge système)."""

    events = application.get("events")
    if not isinstance(events, list):
        return None
    stamps: list[date] = []
    for event in events:
        if not isinstance(event, Mapping):
            continue
        if _text(event.get("event_type"), 40) not in event_types:
            continue
        parsed = _date_or_none(event.get("created_at"))
        if parsed is not None:
            stamps.append(parsed)
    return max(stamps) if stamps else None


def _is_closed_job(job: Mapping[str, Any]) -> bool:
    if _text(job.get("source_status"), 40) == "closed":
        return True
    return _text(job.get("status"), 40) in CLOSED_JOB_STATES


def _is_excluded_location(
    city: str,
    country: str,
    excluded_countries: Sequence[str],
    excluded_cities: Sequence[str],
) -> bool:
    country_key = normalized_text(country)
    if country_key and country_key in {normalized_text(item) for item in excluded_countries}:
        return True
    city_parts = {normalized_text(part) for part in city.split(",") if normalized_text(part)}
    return bool(city_parts & {normalized_text(item) for item in excluded_cities})


def _location(record: Mapping[str, Any]) -> str:
    parts = [
        _text(record.get("city"), 160),
        _text(record.get("country"), 120),
    ]
    return ", ".join(part for part in parts if part) or "Localisation à vérifier"


def _match_score(job: Mapping[str, Any]) -> int | None:
    scoring = job.get("scoring") if isinstance(job.get("scoring"), Mapping) else {}
    raw = scoring.get("score")
    try:
        return max(0, min(100, int(raw)))
    except (TypeError, ValueError):
        return None


def _candidate_score(candidate: Mapping[str, Any]) -> int | None:
    raw = candidate.get("match_score")
    if raw is None:
        return _match_score(candidate)
    try:
        return max(0, min(100, int(raw)))
    except (TypeError, ValueError):
        return None


def _coverage_label(covered: Any, total: Any) -> str:
    try:
        covered_value = int(covered)
        total_value = int(total)
    except (TypeError, ValueError):
        return "inconnue"
    if total_value <= 0:
        return "inconnue"
    return f"{max(covered_value, 0)}/{total_value}"


def _source_trust(candidate: Mapping[str, Any]) -> str:
    if candidate.get("source_verified"):
        return "verified"
    if _text(candidate.get("official_url"), 2_000):
        return "unverified"
    return "unknown"
