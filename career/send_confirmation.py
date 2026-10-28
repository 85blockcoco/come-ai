"""SPEC-047 — Confirmation d'envoi humaine et relance optimale.

Règle absolue : **aucune soumission automatique, jamais.** Ce module enregistre
un envoi qu'une personne déclare avoir effectué elle-même (dépôt manuel sur le
site carrières, l'e-mail ou le portail de l'entreprise) et calcule la date de
relance conseillée. La relance reste un **brouillon local** à copier : aucun
e-mail, message ou formulaire ne part de ce programme.

Persistance : le store existant (tables ``applications`` +
``application_events``) reste la seule source de vérité — aucune migration,
aucune colonne nouvelle, ``schema_version`` inchangé. L'envoi déclaré est
porté par un événement de journal ``send_confirmation`` dont le détail JSON
est relu pour reconstruire le ``SendRecord`` : l'état reste calculable depuis
le seul journal, donc rejouable. Une relance déjà faite est un événement
``followup_recorded`` qui décale la prochaine échéance de sept jours ouvrés.

Garanties :
* ``tracking_stage`` ne passe à « envoyée » (``submitted``) qu'après la
  déclaration explicite de la personne, elle-même encadrée par l'approbation
  de dépôt manuel déjà exigée par le service ;
* anti-fraude : un ``sent_at`` à plus de 24 h dans le futur est refusé ;
* double envoi : idempotent — la même preuve ne duplique ni l'historique ni
  l'événement, une preuve différente met l'envoi déclaré à jour en place ;
* ``follow_up_due`` = +7 jours ouvrés (samedis et dimanches exclus ; aucun
  jeu de jours fériés n'est inventé, un jour férié reste un jour compté).

Le module est pur : aucun E/S, aucun réseau, aucun modèle ; le même entrant
produit à tout instant le même résultat.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import date, datetime, time, timedelta, timezone
from typing import Any, Literal

from .models import clean_text

SEND_CONFIRMATION_EVENT_TYPE = "send_confirmation"
"""Type d'événement du journal portant l'envoi déclaré (détail JSON)."""

FOLLOWUP_RECORDED_EVENT_TYPE = "followup_recorded"
"""Type d'événement du journal portant une relance déjà faite (détail JSON)."""

SEND_CHANNELS: tuple[str, ...] = ("website", "email", "portal")
"""Canaux de dépôt manuel que la personne peut déclarer."""

Channel = Literal["website", "email", "portal"]

FOLLOW_UP_BUSINESS_DAYS = 7
"""Délai conseillé avant relance, en jours ouvrés (week-ends exclus)."""

MAX_SENT_AT_FUTURE_LEEWAY = timedelta(hours=24)
"""Marge anti-fraude : au-delà de 24 h dans le futur, l'horodatage est refusé."""

MAX_TRACKER_APPLICATIONS = 200
"""Plafond de candidatures parcourues par le suivi de relance (apply-tracker)."""

STAGES_AT_OR_AFTER_SENT = frozenset(
    {"submitted", "submitted_confirmed", "response_received", "interview", "offer_received"}
)
"""États à partir desquels un envoi est déjà compté — jamais régressé."""

CHANNEL_LABELS: dict[str, str] = {
    "website": "le site carrières",
    "email": "l'e-mail de candidature",
    "portal": "le portail de recrutement",
}

TRACKER_HONESTY_NOTE = (
    "Sont listées les candidatures déclarées envoyées et sans réponse enregistrée. "
    "La relance proposée est un brouillon local à copier toi-même : Côme AI n'envoie "
    "aucun e-mail, message ou candidature, et une ligne SQLite n'est jamais un envoi."
)


class SendConfirmationError(ValueError):
    """Erreur métier de confirmation d'envoi (canal invalide, anti-fraude…)."""


@dataclass(frozen=True)
class SendEvidence:
    """Preuve déclarée par la personne d'un dépôt manuel déjà effectué."""

    channel: Channel
    sent_at: datetime
    note: str | None = None


@dataclass(frozen=True)
class SendRecord:
    """Envoi déclaré pour une offre, avec l'échéance de relance conseillée."""

    job_id: str
    sent_at: datetime
    channel: str
    follow_up_due: datetime


def parse_sent_datetime(value: Any) -> datetime | None:
    """Parse un horodatage ISO de façon tolérante ; une valeur naïve vaut UTC.

    Les écritures du service portent un offset UTC explicite ; lire une valeur
    naïve comme UTC évite toute comparaison avec l'heure locale du serveur
    (déviation de fuseau interdite).
    """
    if isinstance(value, datetime):
        parsed = value
    else:
        text = clean_text(value, limit=64)
        if not text:
            return None
        try:
            parsed = datetime.fromisoformat(text)
        except ValueError:
            return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed


def _as_utc(value: datetime) -> datetime:
    return value.astimezone(timezone.utc) if value.tzinfo else value.replace(tzinfo=timezone.utc)


def validate_evidence(evidence: SendEvidence, *, now: datetime) -> None:
    """Valide une preuve d'envoi déclarée ; lève ``SendConfirmationError``.

    Anti-fraude : ``sent_at`` strictement postérieur à ``now + 24 h`` est une
    erreur métier — un envoi ne peut pas être déclaré très en avance. Une
    déclaration exactement à la limite (+24 h) reste acceptée.
    """
    if evidence.channel not in SEND_CHANNELS:
        raise SendConfirmationError(
            "Canal d'envoi invalide : choisis parmi « website », « email » ou « portal »."
        )
    aware_now = _as_utc(now)
    sent_at = evidence.sent_at if evidence.sent_at.tzinfo else _as_utc(evidence.sent_at)
    if sent_at - aware_now > MAX_SENT_AT_FUTURE_LEEWAY:
        raise SendConfirmationError(
            "Horodatage d'envoi impossible : il est à plus de 24 h dans le futur. "
            "Enregistre l'envoi après l'avoir réellement effectué toi-même."
        )


def evidence_payload(evidence: SendEvidence) -> dict[str, Any]:
    """Détail JSON normalisé stocké dans le journal (source du ``SendRecord``)."""
    note = clean_text(evidence.note or "", limit=1_000)
    return {
        "channel": clean_text(evidence.channel, limit=20),
        "sent_at": _as_utc(evidence.sent_at).isoformat(),
        "note": note or None,
    }


def evidence_fingerprint(evidence: SendEvidence) -> str:
    """Empreinte canonique d'une preuve — l'idempotence compare ces empreintes."""
    return json.dumps(evidence_payload(evidence), sort_keys=True, ensure_ascii=False)


def add_business_days(start: date, count: int) -> date:
    """Avance de ``count`` jours ouvrés : samedis et dimanches exclus.

    Aucun calendrier de jours fériés n'est inventé : un jour férié tombant un
    jour de semaine reste compté (inconnu nommé plutôt que donnée fabriquée).
    """
    current = start
    remaining = int(count)
    while remaining > 0:
        current += timedelta(days=1)
        if current.weekday() < 5:
            remaining -= 1
    return current


def compute_follow_up_due(
    *,
    sent_at: datetime,
    last_followup_on: date | None = None,
) -> datetime:
    """Échéance de relance : +7 jours ouvrés depuis l'envoi déclaré.

    Si une relance a déjà été faite (``last_followup_on``), la prochaine
    échéance repart de ce jour-là : +7 jours ouvrés encore. Le ``datetime``
    renvoyé reprend le fuseau de ``sent_at``, à minuit, pour rester
    déterministe et comparable.
    """
    base = last_followup_on or sent_at.date()
    due_date = add_business_days(base, FOLLOW_UP_BUSINESS_DAYS)
    tzinfo = sent_at.tzinfo or timezone.utc
    return datetime.combine(due_date, time.min, tzinfo=tzinfo)


def send_record_from_payload(
    job_id: str,
    payload: dict[str, Any],
    *,
    last_followup_on: date | None = None,
) -> SendRecord | None:
    """Reconstruit le ``SendRecord`` depuis un détail de journal (rejouable).

    Un détail illisible tombe en ``None`` : l'inconnu est affiché, jamais un
    enregistrement inventé.
    """
    channel = clean_text(payload.get("channel"), limit=20)
    sent_at = parse_sent_datetime(payload.get("sent_at"))
    if not channel or sent_at is None:
        return None
    return SendRecord(
        job_id=clean_text(job_id, limit=80),
        sent_at=sent_at,
        channel=channel,
        follow_up_due=compute_follow_up_due(sent_at=sent_at, last_followup_on=last_followup_on),
    )


def parse_followup_date(value: Any) -> date | None:
    """Lit la date d'une relance déjà faite depuis un détail de journal.

    Le détail est un JSON (``{"done_on": "2026-01-05"}``) ou une date ISO
    nue ; tout le reste tombe en ``None`` (inconnu affiché, jamais inventé).
    """
    if isinstance(value, dict):
        value = value.get("done_on")
    text = clean_text(value, limit=1_000)
    if not text:
        return None
    if text.startswith("{"):
        try:
            decoded = json.loads(text)
        except (ValueError, TypeError):
            return None
        if not isinstance(decoded, dict):
            return None
        text = clean_text(decoded.get("done_on"), limit=32)
        if not text:
            return None
    try:
        return date.fromisoformat(text)
    except ValueError:
        return None


def latest_send_evidence(events: list[dict[str, Any]]) -> tuple[str, dict[str, Any]] | None:
    """Retourne ``(event_id, payload)`` du dernier envoi déclaré, sinon ``None``.

    Le dernier événement gagne : une preuve différente mise à jour en place
    reste lisible, et un détail illisible est ignoré plutôt que bloquant.
    """
    epoch = datetime.min.replace(tzinfo=timezone.utc)
    candidates: list[tuple[datetime, int, str, dict[str, Any]]] = []
    for index, event in enumerate(events):
        if clean_text(event.get("event_type"), limit=40) != SEND_CONFIRMATION_EVENT_TYPE:
            continue
        created = parse_sent_datetime(event.get("created_at"))
        detail = clean_text(event.get("detail"), limit=1_000)
        try:
            payload = json.loads(detail)
        except (ValueError, TypeError):
            continue
        if not isinstance(payload, dict):
            continue
        candidates.append((created or epoch, index, clean_text(event.get("id"), limit=80), payload))
    if not candidates:
        return None
    _, _, event_id, payload = max(candidates, key=lambda item: (item[0], item[1]))
    return event_id, payload


def latest_followup_on(events: list[dict[str, Any]]) -> date | None:
    """Dernière relance déclarée faite, lue depuis le journal (rejouable)."""
    epoch = datetime.min.replace(tzinfo=timezone.utc)
    latest: tuple[datetime, int, date] | None = None
    for index, event in enumerate(events):
        if clean_text(event.get("event_type"), limit=40) != FOLLOWUP_RECORDED_EVENT_TYPE:
            continue
        done_on = parse_followup_date(event.get("detail"))
        if done_on is None:
            continue
        created = parse_sent_datetime(event.get("created_at")) or epoch
        candidate = (created, index, done_on)
        if latest is None or candidate[:2] > latest[:2]:
            latest = candidate
    return latest[2] if latest else None


def send_record_to_dict(record: SendRecord, *, note: str | None = None) -> dict[str, Any]:
    """Sérialisation JSON stable du ``SendRecord`` (datetimes en ISO)."""
    payload = asdict(record)
    payload["sent_at"] = record.sent_at.isoformat()
    payload["follow_up_due"] = record.follow_up_due.isoformat()
    payload["follow_up_due_date"] = record.follow_up_due.date().isoformat()
    payload["note"] = note
    return payload


def elapsed_waiting_days(sent_at: datetime, *, now: datetime) -> int:
    """Return complete UTC days elapsed since a declared send.

    Calendar-date subtraction is wrong around midnight: an application sent
    one hour ago can have a different date from the local machine and must
    still report zero waiting days.  The tracker therefore counts complete
    24-hour periods between two timezone-aware instants.
    """
    sent_utc = sent_at.astimezone(timezone.utc)
    now_utc = now.astimezone(timezone.utc)
    elapsed_seconds = (now_utc - sent_utc).total_seconds()
    return max(int(elapsed_seconds // timedelta(days=1).total_seconds()), 0)


def build_followup_draft(
    *,
    title: str,
    company: str,
    channel: str,
    sent_at: datetime,
    reference: str = "",
    candidate_name: str = "",
) -> str:
    """Brouillon de relance court, en français, prêt à copier.

    Le texte reste une proposition locale : il n'est transmis à personne par
    ce programme, et le canal de reprise est celui du dépôt d'origine.
    """
    safe_title = clean_text(title, limit=300) or "poste sans intitulé"
    safe_company = clean_text(company, limit=240) or "entreprise non renseignée"
    channel_label = CHANNEL_LABELS.get(clean_text(channel, limit=20), "le canal utilisé au dépôt")
    sent_day = sent_at.date().isoformat()
    safe_reference = clean_text(reference, limit=200) or "non enregistrée"
    signature = clean_text(candidate_name, limit=160) or "[ton nom]"
    return (
        "[Brouillon local — Côme AI n'envoie rien ; copie ce texte toi-même]\n"
        f"Objet : Suivi de ma candidature — {safe_title} ({safe_company})\n"
        "\n"
        "Bonjour,\n"
        "\n"
        f"J'ai déposé ma candidature pour le poste « {safe_title} » ({safe_company}) "
        f"le {sent_day} via {channel_label}. Sans retour à ce jour, je me permets "
        "de m'assurer que mon dossier est bien parvenu et je reste disponible "
        "pour un échange à votre convenance.\n"
        "\n"
        f"Référence connue : {safe_reference}.\n"
        "\n"
        "Bien cordialement,\n"
        f"{signature}"
    )
