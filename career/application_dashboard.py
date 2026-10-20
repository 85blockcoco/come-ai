"""Projection locale déterministe du tableau de bord CVBOOST-09.

Ce module transforme des enregistrements *déjà locaux* (tables ``applications``,
``application_events``, ``jobs``, profil) en une projection honnête :

* des compteurs par état tirés du journal existant ;
* des filtres et une chronologie bornée ;
* un radar de relance où une relance est un **brouillon local** avec une date
  suggérée — jamais un e-mail, un message ou un envoi automatique ;
* une note de préparation 0–100 qui combine **uniquement** trois facteurs
  affichés (couverture CV, vérification des faits, checklist), avec les
  inconnues nommées et la formule explicitée.

Garanties centrales :
* une ligne SQLite n'est jamais assimilée à un envoi ; l'état « envoyée » ne
  provient que d'une action déclarée par la personne ;
* aucune valeur n'est inventée : une donnée absente devient un inconnu nommé ;
* le module est pur : aucun E/S, aucun réseau, aucun modèle, aucun effet de
  bord, et le même entrant produit à tout instant le même résultat à ``today``
  égal.
"""

from __future__ import annotations

import json
from datetime import date, datetime, timedelta, timezone
from typing import Any

from .models import APPLICATION_STAGES, clean_text, parse_date
from .application_prep import PROFILE_FIELDS, prepare_application

MAX_DASHBOARD_APPLICATIONS = 200
"""Plafond de candidatures chargées en mémoire pour une projection économie."""

MAX_TIMELINE_EVENTS = 15
"""Nombre d'événements conservés dans la chronologie d'une fiche."""

MAX_RADAR_ITEMS = 20
"""Nombre maximal d'entrées exposées dans le radar de relance."""

FOLLOWUP_DELAY_DAYS = 10
"""Délai d'attente conseillé avant une relance post-envoi."""

REVIEW_INTERVAL_DAYS = 7
"""Intervalle avant de reprendre un dossier qui n'a pas été envoyé."""

DEADLINE_SOON_DAYS = 7
"""Fenêtre « échéance proche » affichée avec priorité."""

DEADLINE_MARGIN_DAYS = 3
"""Marge de sécurité avant une échéance connue pour finaliser le dossier."""

CHECKLIST_EVENT_TYPE = "checklist"
"""Type d'événement du journal existant portant l'état de la checklist.

Aucun changement de schéma : le détail stocke un JSON ``{"items": {clé: bool}}``
(et un format historique ``{"checked": [...]+}`` reste lisible).  Le dernier
événement ``checklist`` fait foi, ce qui rend l'état rejouable et réversible.
"""

PROJECT_CHECKLIST_ITEMS: tuple[dict[str, str], ...] = (
    {"key": "cv_reviewed", "label": "CV relu pour cette offre"},
    {"key": "letter_customized", "label": "Lettre personnalisée"},
    {"key": "documents_checked", "label": "Documents vérifiés (PDF, formats)"},
    {"key": "deadline_verified", "label": "Date limite vérifiée à la source"},
    {"key": "followup_planned", "label": "Relance locale prévue"},
)
CHECKLIST_KEYS = frozenset(item["key"] for item in PROJECT_CHECKLIST_ITEMS)

PRE_SUBMISSION_STAGES = frozenset(
    {"to_review", "to_prepare", "ready_to_apply", "approved_for_manual_submission", "deferred"}
)
SENT_DECLARED_STAGES = frozenset(
    {"submitted", "submitted_confirmed", "response_received", "interview", "offer_received"}
)
CLOSED_STAGES = frozenset({"rejected", "refused", "withdrawn"})

STAGE_ORDER: tuple[str, ...] = tuple(APPLICATION_STAGES)  # ordre stable pour l'UI

RECEIPT_FILTER_VALUES = ("", "not_submitted", "unknown", "confirmed")
DEADLINE_FILTER_VALUES = ("", "next_7_days", "passed", "unset")

HONESTY_NOTE = (
    "Une ligne SQLite n'est jamais un envoi : l'état « Envoyée » ne vient que d'une "
    "action déclarée par toi après un dépôt manuel (approuvé et référencé). Aucun "
    "envoi automatique n'existe dans Career ; toute candidature sans réception "
    "confirmée reste non envoyée et à traiter toi-même. La relance proposée est un "
    "brouillon local, jamais un e-mail envoyé automatiquement."
)
PREP_DISCLAIMER = (
    "La note mesure seulement la complétude documentaire locale (couverture CV, "
    "vérification des faits, checklist) ; ce n'est ni une probabilité d'embauche ni "
    "une note d'un recruteur."
)


def parse_event_timestamp(value: Any) -> datetime | None:
    """Parse un horodatage ISO de façon tolérante et purement locale."""
    text = clean_text(value, limit=64)
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        # Les écritures présentes et passées du service portent un offset UTC
        # explicite ; une valeur naïve est lue comme UTC, jamais comparée à
        # l'heure locale du serveur (déviation de fuseau interdite).
        return parsed.replace(tzinfo=timezone.utc)
    return parsed


def iso_date(value: datetime | None) -> str | None:
    if value is None:
        return None
    return value.astimezone(timezone.utc).date().isoformat()


def checklist_state(events: list[dict[str, Any]]) -> dict[str, Any] | None:
    """Dérive l'état de checklist du dernier événement de ce type.

    Aucun état n'est stocké à part : la projection reste calculable depuis le
    seul journal, donc rejouable et réversible. Un détail illisible tombe en
    « inconnu » au lieu de faire planter ou de prétendre à zéro.
    """
    candidates: list[tuple[datetime | None, int, str]] = []
    for index, event in enumerate(events):
        if clean_text(event.get("event_type"), limit=40) != CHECKLIST_EVENT_TYPE:
            continue
        candidates.append(
            (
                parse_event_timestamp(event.get("created_at")),
                index,
                clean_text(event.get("detail"), limit=1_000),
            )
        )
    if not candidates:
        return None
    epoch = datetime.min.replace(tzinfo=timezone.utc)
    latest = max(candidates, key=lambda item: (item[0] or epoch, item[1]))
    try:
        payload = json.loads(latest[2])
        if not isinstance(payload, dict):
            raise ValueError
    except (ValueError, TypeError):
        return None
    items = payload.get("items") if isinstance(payload.get("items"), dict) else None
    if items is not None:
        checked = {key for key, value in items.items() if value is True}
    else:
        listed = payload.get("checked")
        checked = {clean_text(item, limit=80) for item in listed} if isinstance(listed, list) else set()
    return {
        "checked_keys": sorted(checked & CHECKLIST_KEYS),
        "updated_at": iso_date(latest[0]),
        "unknown": False,
    }


def deadline_bucket(deadline: Any, today: date, availability_status: Any = "") -> str:
    """Classe l'échéance : une date absente reste explicitement inconnue."""
    if clean_text(availability_status, limit=40) == "closed":
        return "closed"
    text = clean_text(deadline, limit=32)
    if not text:
        return "unset"
    try:
        parsed = parse_date(text, "La date limite")
    except Exception:
        # Une base locale accidentellement éditée ne doit pas bloquer le
        # tableau de bord ; l'inconnu est affiché, jamais un faux « ouvert ».
        return "unset"
    delta = (parsed - today).days
    if delta < 0:
        return "passed"
    if delta <= DEADLINE_SOON_DAYS:
        return "soon"
    return "later"


_followup_receipt_unknown = None


def followup_bucket(
    *,
    stage: str,
    sent_declared: bool,
    receipt_status: str,
    approval_granted: bool,
    deadline_date: str,
    availability_status: str = "",
    today: date,
    last_event: datetime | None,
) -> dict[str, Any]:
    """Décide s'il y a quelque chose à relancer — et quoi, localement.

    Une relance n'est jamais un e-mail : toute « kind » localement applicable
    est un brouillon/note locale avec une date suggérée et ``is_email False``.
    """
    bucket: dict[str, Any] = {
        "kind": "none",
        "status": "none",
        "suggested_date": None,
        "waiting_days": None,
        "is_email": False,
        "receipt_unknown": receipt_status == "unknown",
        "draft_sends_nothing": True,
    }
    waiting_days: int | None = None
    if last_event is not None:
        waiting_days = max((today - last_event.astimezone(timezone.utc).date()).days, 0)
    bucket["waiting_days"] = waiting_days

    if stage in CLOSED_STAGES or stage == "offer_received":
        bucket["reason"] = "Candidature close : aucune relance proposée."
        return bucket
    if stage == "interview":
        bucket.update(kind="interview_preparation", status="due")
        bucket["reason"] = "Entretien en cours : prépare la séance localement."
        return bucket

    bucket_deadline = deadline_bucket(deadline_date, today, availability_status)
    if not sent_declared:
        if bucket_deadline == "closed":
            bucket.update(kind="none", status="none")
            bucket["reason"] = "L’offre associée est indiquée fermée : aucune relance proposée."
            return bucket
        if bucket_deadline in {"passed"}:
            bucket.update(kind="deadline_passed", status="due")
            bucket["reason"] = "L'échéance connue est dépassée : vérifie la page officielle avant de poursuivre."
            return bucket
        if bucket_deadline == "soon":
            deadline = parse_date(deadline_date, "La date limite")
            suggested = max(deadline - timedelta(days=DEADLINE_MARGIN_DAYS), today)
            bucket.update(
                kind="deadline_close",
                status="due",
                suggested_date=suggested.isoformat(),
            )
            bucket["reason"] = f"Finalise le dossier avant la date limite connue ({deadline.isoformat()})."
            return bucket
        if last_event is not None:
            last_day = last_event.astimezone(timezone.utc).date()
            suggested = max(last_day + timedelta(days=REVIEW_INTERVAL_DAYS), today)
            status = "due" if suggested <= today else "upcoming"
            bucket.update(kind="review", status=status, suggested_date=suggested.isoformat())
            bucket["reason"] = (
                "Reprise du dossier après un temps d'inactivité ; aucune communication n'est envoyée."
            )
        else:
            bucket.update(kind="review", status="upcoming")
            bucket["reason"] = "Dossier en préparation : reprendre quand tu le décides."
        if receipt_status == "unknown":
            bucket["reason"] += " Réception déclarée inconnue : ne renvoie pas automatiquement."
        return bucket

    # Candidature déclarée envoyée : relance uniquement en brouillon local.
    if last_event is None:
        bucket.update(kind="followup", status="upcoming")
        bucket["reason"] = "Aucun événement daté : relance possible quand tu décides, jamais automatiquement."
        return bucket
    last_day = last_event.astimezone(timezone.utc).date()
    suggested = last_day + timedelta(days=FOLLOWUP_DELAY_DAYS)
    status = "due" if suggested <= today else "upcoming"
    bucket.update(kind="followup", status=status, suggested_date=suggested.isoformat())
    bucket["reason"] = (
        "Relance raisonnable après un délai de respiration ; prépare le brouillon et utilise-le toi-même."
        if status == "upcoming"
        else "Délai d'attente dépassé : le brouillon de relance est prêt, l'envoi reste manuel."
    )
    if receipt_status == "unknown":
        bucket["reason"] = "Réception non confirmée : " + bucket["reason"]
    return bucket


def _followup_draft(followup: dict[str, Any], *, title: str, company: str, reference: str) -> str | None:
    """Rédige le brouillon local — jamais un message partant automatiquement."""
    kind = followup.get("kind")
    if kind in {"followup"} and followup.get("waiting_days") is not None:
        return (
            "[Brouillon local — aucun e-mail n'est envoyé]\n"
            "Bonjour,\n"
            f"J’ai déposé récemment une candidature pour le poste « {title} » ({company}). "
            f"Dernier suivi local enregistré : {followup.get('waiting_days')} jour(s). "
            "Pouvez-vous me confirmer la réception de mon dossier ?\n"
            f"Référence connue : {reference or 'non enregistrée'}. "
            "Envoie-le toi-même, par le canal officiel utilisé lors du dépôt."
        )
    if kind in {"deadline_close", "deadline_passed", "review"}:
        date_text = followup.get("suggested_date") or "à définir"
        return (
            "[Note locale — rien n'est transmis à personne]\n"
            f"Reprends le dossier « {title} » ({company}). Date suggérée : {date_text}. "
            f"{followup.get('reason', '')}"
        )
    return None


def prep_evaluation(
    job: dict[str, Any],
    profile: dict[str, Any] | None,
    intake: dict[str, Any] | None,
    checklist: dict[str, Any] | None,
) -> dict[str, Any]:
    """Note de préparation 0–100, trois facteurs visibles, inconnus nommés.

    La note combine uniquement : couverture CV (exigences de l'offre étayées
    par le profil), vérification des faits (preuves entièrement documentées
    versus preuves sans résultat chiffré) et checklist locale. Rien d'autre
    n'entre dans la formule, et la formule est affichée.
    """
    analysis = prepare_application(profile or {}, intake or {}, job)
    coverage = analysis["cv_coverage"]
    factors: dict[str, dict[str, Any]] = {}
    unknowns: list[dict[str, str]] = []

    has_profile_content = any(
        clean_text((profile or {}).get(field), limit=6_000).lower() not in {"", "unknown"}
        for field in PROFILE_FIELDS
    )
    if coverage["requirements_total"] == 0:
        unknowns.append(
            {
                "factor": "couverture",
                "reason": "Aucune exigence détectable dans l’offre enregistrée.",
            }
        )
    elif not has_profile_content:
        unknowns.append(
            {
                "factor": "couverture",
                "reason": "Le profil local est vide ou incomplet : aucune comparaison possible.",
            }
        )
    else:
        factors["couverture"] = {
            "percent": int(coverage["coverage_percent"]),
            "detail": (
                f"{coverage['supported']}/{coverage['requirements_total']} exigences détectées "
                "sont étayées par ton profil local."
            ),
        }

    matched = analysis["matched_elements"]
    action_plan = analysis["cv_action_plan"]
    supported_items = [item for item in action_plan if item.get("status") == "supported"]
    documented = [
        item for item in supported_items if item.get("evidence_quality") == "documented"
    ]
    if not matched:
        unknowns.append(
            {
                "factor": "faits",
                "reason": (
                    "Aucune preuve étayée dans le profil pour le moment : rien à compter "
                    "pour la vérification des faits."
                ),
            }
        )
    else:
        unknown_facts = []
        for item in supported_items:
            if item.get("evidence_quality") == "needs_quantification":
                unknown_facts.append(item["requirement"])
        factors["faits"] = {
            "percent": round(len(documented) / len(matched) * 100),
            "detail": (
                f"{len(documented)}/{len(matched)} preuves entièrement documentées."
            ),
            "quantifiable_missing": [
                clean_text(item, limit=200) for item in unknown_facts[:6]
            ],
        }

    if checklist is None:
        unknowns.append(
            {
                "factor": "checklist",
                "reason": "Aucune checklist enregistrée pour cette candidature : les cinq cases restent inconnues.",
            }
        )
    else:
        checked = len(checklist["checked_keys"])
        factors["checklist"] = {
            "percent": round(checked / len(PROJECT_CHECKLIST_ITEMS) * 100),
            "detail": f"{checked}/{len(PROJECT_CHECKLIST_ITEMS)} cases cochées localement.",
        }

    known = [factor["percent"] for factor in factors.values()]
    score = round(sum(known) / len(known)) if known else None
    return {
        "score": score,
        "scale": "0-100",
        "partial": bool(unknowns),
        "factors": factors,
        "unknowns": unknowns,
        "formula": (
            "Note = moyenne simple des pourcentages des trois facteurs "
            "(couverture CV, vérification des faits, checklist) ; chaque facteur connu "
            "pèse un tiers, aucun poids caché. Les facteurs inconnus sont exclus de la "
            "moyenne et affichés."
        ),
        "disclaimer": PREP_DISCLAIMER,
    }


def next_action(
    *,
    stage: str,
    receipt_status: str,
    approval_granted: bool,
    followup: dict[str, Any],
    deadline: dict[str, Any],
) -> dict[str, str]:
    """Prochaine action suggérée, honnête et locale."""
    if stage in CLOSED_STAGES:
        return {"label": "Candidature close", "detail": "Archive-la si besoin ; rien à relancer."}
    if stage == "offer_received":
        return {"label": "Décide du suivi de l’offre reçue", "detail": "Note localement ta décision."}
    if stage == "interview":
        return {"label": "Prépare l’entretien", "detail": "Le coach local est disponible dans l’onglet Entretiens."}
    if receipt_status == "unknown":
        return {
            "label": "Vérifie la réception",
            "detail": "Confirme-la avec une référence ou marque-la inconnue ; ne renvoie pas automatiquement.",
        }
    if stage not in SENT_DECLARED_STAGES:
        if deadline.get("bucket") == "passed":
            return {
                "label": "Vérifie l’offre",
                "detail": "La date limite connue est dépassée : contrôle la page officielle avant de poursuivre.",
            }
        detail = "Complète le dossier (CV, lettre, checklist) puis demande l’approbation de dépôt manuel."
        if deadline.get("bucket") == "soon":
            detail = f"{detail} Date limite connue : {deadline.get('date')}."
        elif deadline.get("bucket") == "unset":
            detail = f"{detail} Date limite inconnue : vérifie la page officielle."
        if approval_granted:
            detail = "Dépôt approuvé : effectue-le toi-même sur la page officielle, puis consigne l’envoi."
        return {"label": "Prépare le dossier", "detail": detail}
    detail = f"Attends une réponse ; une relance est raisonnable après {FOLLOWUP_DELAY_DAYS} jours, en brouillon local."
    if receipt_status == "confirmed":
        detail = f"Réception confirmée. {detail}"
    elif deadline.get("bucket") == "unset":
        detail = f"{detail} Date limite inconnue : vérifie la page officielle si tu relances."
    return {"label": "Relance si besoin", "detail": detail}


def timeline(events: list[dict[str, Any]], *, limit: int = MAX_TIMELINE_EVENTS) -> list[dict[str, Any]]:
    """Chronologie bornée, triée du plus récent au plus ancien, horodatage purifié."""
    decorated: list[tuple[datetime | None, str, dict[str, Any]]] = []
    epoch = datetime.min.replace(tzinfo=timezone.utc)
    for event in events:
        decorated.append(
            (
                parse_event_timestamp(event.get("created_at")),
                clean_text(event.get("created_at"), limit=64),
                {
                    "event_type": clean_text(event.get("event_type"), limit=40),
                    "detail": clean_text(event.get("detail"), limit=300),
                    "created_at": event.get("created_at"),
                    "at": parse_event_timestamp(event.get("created_at")).isoformat()
                    if parse_event_timestamp(event.get("created_at")) is not None
                    else None,
                },
            )
        )
    decorated.sort(key=lambda item: (item[0] or epoch, item[1]), reverse=True)
    return [item[2] for item in decorated[:limit]]


def application_entry(
    application: dict[str, Any],
    events: list[dict[str, Any]],
    job: dict[str, Any],
    profile: dict[str, Any] | None,
    intake: dict[str, Any] | None,
    *,
    today: date,
) -> dict[str, Any]:
    """Une fiche honnête : état mesuré, échéance, action, relance, note, chronologie."""
    stage = clean_text(application.get("stage"), limit=80)
    receipt_status = clean_text(application.get("receipt_status"), limit=80) or "not_submitted"
    timestamps = [parse_event_timestamp(event.get("created_at")) for event in events]
    stamps = [value for value in timestamps if value is not None]
    last_event = max(stamps) if stamps else None
    checklist = checklist_state(events)
    deadline_date = clean_text(job.get("deadline_date"), limit=32)
    availability_status = clean_text(job.get("source_status"), limit=40)
    bucket = deadline_bucket(deadline_date, today, availability_status)
    sent_declared = stage in SENT_DECLARED_STAGES
    followup = followup_bucket(
        stage=stage,
        sent_declared=sent_declared,
        receipt_status=receipt_status,
        approval_granted=bool(application.get("approval_granted")),
        deadline_date=deadline_date,
        availability_status=availability_status,
        today=today,
        last_event=last_event,
    )
    title = clean_text(job.get("title"), limit=300) or "Offre sans intitulé"
    company = clean_text(job.get("company"), limit=240)
    followup["draft"] = _followup_draft(
        followup, title=title, company=company or "entreprise non renseignée",
        reference=clean_text(application.get("confirmation_reference"), limit=200),
    )
    deadline = {
        "date": deadline_date or None,
        "bucket": bucket,
        "availability": availability_status or "unknown",
    }
    entry = {
        "application_id": clean_text(application.get("application_id") or application.get("id"), limit=80),
        "job_id": clean_text(application.get("job_id"), limit=80),
        "title": title,
        "company": company,
        "city": clean_text(job.get("city"), limit=160),
        "official_url": clean_text(job.get("official_url"), limit=2_000),
        "stage": stage,
        "receipt_status": receipt_status,
        "confirmation_reference": clean_text(application.get("confirmation_reference"), limit=200),
        "sent_declared": sent_declared,
        "closed": stage in CLOSED_STAGES,
        "deadline": deadline,
        "last_event_at": last_event.isoformat() if last_event else None,
        "days_since_last_event": followup["waiting_days"],
        "followup": {key: followup.get(key) for key in (
            "kind", "status", "suggested_date", "waiting_days", "is_email",
            "receipt_unknown", "draft", "reason",
        )},
        "checklist": checklist if checklist is not None else {"checked_keys": [], "updated_at": None, "unknown": True},
        "prep": prep_evaluation(job, profile, intake, checklist),
        "timeline": timeline(events),
    }
    entry["next_action"] = next_action(
        stage=stage,
        receipt_status=receipt_status,
        approval_granted=bool(application.get("approval_granted")),
        followup=followup,
        deadline=deadline,
    )
    entry["action_required"] = bool(
        stage not in CLOSED_STAGES
        and (
            deadline["bucket"] in {"soon", "passed"}
            or receipt_status == "unknown"
            or stage == "interview"
            or followup.get("status") == "due"
        )
    )
    return entry


def counts_by_stage(entries: list[dict[str, Any]]) -> dict[str, int]:
    """Compteurs par état calculés sur toute la population, filtres ignorés."""
    counts = {stage: 0 for stage in sorted(APPLICATION_STAGES)}
    for entry in entries:
        stage = entry["stage"]
        counts[stage] = counts.get(stage, 0) + 1
    return counts


def filter_entries(
    entries: list[dict[str, Any]],
    *,
    stage: str = "",
    receipt: str = "",
    action_required: bool | None = None,
    deadline: str = "",
    query: str = "",
) -> list[dict[str, Any]]:
    """Filtres déterministes ; aucun piège caché, renvoie les entrées visibles."""
    needle = clean_text(query, limit=120).casefold()
    visible = []
    for entry in entries:
        if needle:
            haystack = f"{entry['title']} {entry['company']} {entry['city']}".casefold()
            if needle not in haystack:
                continue
        if stage and entry["stage"] != stage:
            continue
        if receipt and entry["receipt_status"] != receipt:
            continue
        if deadline and entry["deadline"]["bucket"] != deadline:
            continue
        if action_required is not None and entry["action_required"] != action_required:
            continue
        visible.append(entry)
    return visible


_RADAR_STATUS_RANK = {"followup": 0, "deadline_passed": 1, "deadline_close": 2, "review": 3}
_RADAR_STATUS_LABEL = {
    "due": "relance à faire",
    "upcoming": "relance suggérée plus tard",
    "none": "",
}


def radar_heading(followup: dict[str, Any]) -> str:
    """Texte court et honnête de tête d'une entrée du radar."""
    kind = followup.get("kind")
    status = followup.get("status")
    waiting = followup.get("waiting_days")
    date_text = followup.get("suggested_date")
    if kind == "deadline_close":
        return f"Finalise : date limite connue — suggestion : {date_text}."
    if kind == "deadline_passed":
        return "Échéance dépassée : vérifie l’offre avant de relancer."
    if kind == "followup":
        if status == "upcoming":
            return f"Aucune relance conseillée avant le {date_text}."
        if waiting is not None:
            return f"{waiting} jours sans réponse : brouillon de relance prêt, aucun e-mail envoyé."
    return "Reprise locale du dossier suggérée."


def build_dashboard_payload(
    applications: list[dict[str, Any]],
    events_by_application: dict[str, list[dict[str, Any]]],
    jobs_by_id: dict[str, dict[str, Any]],
    profile: dict[str, Any] | None,
    intake: dict[str, Any] | None,
    *,
    today: date,
    now_iso: str,
    total_applications: int | None = None,
    stage: str = "",
    receipt: str = "",
    action_required: bool | None = None,
    deadline: str = "",
    query: str = "",
) -> dict[str, Any]:
    """Assemble la payload complète du tableau de bord, bornée et déterministe."""
    bounded = applications[:MAX_DASHBOARD_APPLICATIONS]
    real_total = len(applications) if total_applications is None else int(total_applications)
    entries = [
        application_entry(
            application,
            events_by_application.get(str(application.get("application_id") or application.get("id")), []),
            jobs_by_id.get(str(application.get("job_id")), {}),
            profile,
            intake,
            today=today,
        )
        for application in bounded
    ]
    radar = []
    for entry in entries:
        followup = entry["followup"]
        if followup["kind"] == "none" or followup["status"] == "upcoming" and followup["kind"] == "review":
            continue
        draft = followup.get("draft")
        radar.append(
            {
                "application_id": entry["application_id"],
                "job_id": entry["job_id"],
                "title": entry["title"],
                "company": entry["company"],
                "bucket": followup["kind"],
                "status": followup["status"],
                "suggested_date": followup.get("suggested_date"),
                "waiting_days": followup.get("waiting_days"),
                "receipt_unknown": followup["receipt_unknown"],
                "is_email": False,
                "draft": draft,
                "draft_ready": bool(draft),
                "heading": radar_heading(followup),
                "note": (
                    "Brouillon local à copier : Côme AI n’envoie aucun e-mail, message ou candidature."
                ),
            }
        )
    radar.sort(
        key=lambda item: (
            _RADAR_STATUS_RANK.get(item["bucket"], 9),
            0 if item["status"] == "due" else 1,
            item["suggested_date"] or "9999-12-31",
            item["title"].casefold(),
        )
    )
    visible = filter_entries(
        entries,
        stage=stage,
        receipt=receipt,
        action_required=action_required,
        deadline=deadline,
        query=query,
    )
    return {
        "generated_at": now_iso,
        "today": today.isoformat(),
        "counts_by_stage": counts_by_stage(entries),
        "counts_visible": len(visible),
        "totals": {
            "total": len(bounded),
            "closed": sum(1 for entry in entries if entry["closed"]),
            "sent_declared": sum(1 for entry in entries if entry["sent_declared"]),
            "pre_submission": sum(1 for entry in entries if entry["stage"] in PRE_SUBMISSION_STAGES),
            "receipt_unknown": sum(1 for entry in entries if entry["receipt_status"] == "unknown"),
            "action_required": sum(1 for entry in entries if entry["action_required"]),
            "truncated": real_total > len(bounded),
        },
        "radar": radar[:MAX_RADAR_ITEMS],
        "entries": visible,
        "limits": {
            "max_applications": MAX_DASHBOARD_APPLICATIONS,
            "max_timeline_events": MAX_TIMELINE_EVENTS,
            "max_radar_items": MAX_RADAR_ITEMS,
        },
        "honesty": HONESTY_NOTE,
        "truncated_note": (
            f"Projection limitée aux {MAX_DASHBOARD_APPLICATIONS} candidatures les plus récentes "
            f"sur {real_total} ; le solde reste dans la base mais n'apparaît pas ici."
            if real_total > len(bounded)
            else ""
        ),
        "prep_formula": PREP_DISCLAIMER,
    }
