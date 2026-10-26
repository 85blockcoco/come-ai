"""Confirmation d'envoi manuelle et relance optimale (CVBOOST-84 / SPEC-047).

Règle absolue : **aucune soumission automatique, jamais.**  Ce module
n'envoie jamais rien : il *enregistre* un envoi que la personne vient de
faire elle-même (poste, e-mail, portail) et calcule quand une relance
devient appropriée.

Logique d'affaires portée ici (deterministic, sans E/S) :

* ``validate_evidence`` rejette une date d'envoi plus de 24 h dans le futur
  (anti-fraude : un "envoi" ne peut pas être prédit) ;
* ``compute_follow_up_due`` renvoie +7 jours **ouvrés** (samedis, dimanches
  et jours fériés fournis exclus).  Le jour d'envoi compte comme premier
  jour ouvré : un envoi un vendredi échoit lundi qui suit ;
* si une relance a déjà été faite, la prochaine échoit +7 jours ouvrés
  après cette relance ;
* ``build_followup_draft`` produit un brouillon de relance court, en
  français, prêt à copier — jamais un envoi automatique.

Le module est pur : même entrée → même sortie, à ``now`` égal ; aucune
donnée réelle, aucun réseau, aucun modèle.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from typing import Iterable, Literal

SEND_CHANNELS: tuple[str, ...] = ("website", "email", "portal")
"""Canaux de dépôt manuel que la personne peut déclarer."""

MAX_FUTURE_MARGIN = timedelta(hours=24)
"""Marge anti-fraude : un envoi déclaré ne peut pas être plus de 24 h dans le futur."""

FOLLOWUP_BUSINESS_DAYS = 7
"""Délai avant relance : 7 jours ouvrés (week-ends et jours fériés exclus)."""


class SendConfirmationError(ValueError):
    """Erreur de validation métier d'une confirmation d'envoi déclarée."""


@dataclass(frozen=True)
class SendEvidence:
    """Ce que la personne déclare avoir fait elle-même."""

    channel: Literal["website", "email", "portal"]
    sent_at: datetime
    note: str | None = None


@dataclass(frozen=True)
class SendRecord:
    """Enregistrement local idempotent d'un envoi déclaré."""

    job_id: str
    sent_at: datetime
    channel: str
    follow_up_due: datetime


@dataclass(frozen=True)
class FollowUpRecord:
    """Une relance déjà faite, déclarée localement."""

    job_id: str
    sent_at: datetime
    note: str | None = None


def parse_sent_at(value: str | datetime) -> datetime:
    """Parse a declared send or follow-up timestamp as aware UTC."""

    if isinstance(value, datetime):
        parsed = value
    else:
        text = str(value).replace("Z", "+00:00").strip()
        if not text:
            raise SendConfirmationError("La date d'envoi déclarée est requise.")
        try:
            parsed = datetime.fromisoformat(text)
        except ValueError as error:
            raise SendConfirmationError(
                "La date d'envoi déclarée n'est pas une date-heure valide."
            ) from error
    if parsed.tzinfo is None:
        # A declared local timestamp without offset stays honest: it is
        # read as UTC (single-machine local workspace).
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def is_business_day(day: date, holidays: Iterable[date] = ()) -> bool:
    """A business day is neither a week-end nor a supplied holiday."""

    if day.weekday() >= 5:
        return False
    return day not in frozenset(holidays)


def _to_utc_date(value: datetime) -> date:
    return value.astimezone(timezone.utc).date()


def next_business_day(day: date, holidays: Iterable[date] = ()) -> date:
    """Return the first business day strictly after ``day``."""

    candidate = day + timedelta(days=1)
    while not is_business_day(candidate, holidays):
        candidate += timedelta(days=1)
    return candidate


def compute_follow_up_due(
    sent_at: datetime,
    holidays: Iterable[date] = (),
) -> datetime:
    """Return the follow-up due date, ``FOLLOWUP_BUSINESS_DAYS`` business days away.

    Le jour d'envoi compte pour le premier jour ouvré (un envoi fait un
    vendredi échoit donc lundi) ; un envoi déclaré pendant un week-end
    compte à partir du prochain jour ouvré.  Les jours fériés, quand ils
    sont fournis, sont ignorés (« hors données » → aucun jour retiré).
    """

    holidays = frozenset(holidays)
    day = _to_utc_date(sent_at)
    counted = 1 if is_business_day(day, holidays) else 0
    if counted == 0:
        day = next_business_day(day, holidays)
        counted = 1
    while counted < FOLLOWUP_BUSINESS_DAYS:
        day = next_business_day(day, holidays)
        counted += 1
    # Keep the declared sending time: the reminder stays at the same clock
    # time, only the calendar day moved to a business day.
    return sent_at.replace(
        year=day.year,
        month=day.month,
        day=day.day,
    )


def advance_follow_up_due(
    previous_due: datetime,
    holidays: Iterable[date] = (),
) -> datetime:
    """Next follow-up due date, 7 business days after the previous one."""

    return compute_follow_up_due(previous_due, holidays)


def validate_evidence(evidence: SendEvidence, *, now: datetime) -> datetime:
    """Validate a declared send; return its aware UTC timestamp.

    Anti-fraude : ``sent_at`` strictement postérieur à ``now + 24 h`` est une
    erreur métier — un envoi ne peut pas être futur.  ``sent_at`` passé est
    toujours honnête et accepté.
    """

    reference = parse_sent_at(now)
    channel = str(evidence.channel)
    if channel not in SEND_CHANNELS:
        raise SendConfirmationError(
            "Le canal d'envoi doit valoir website, email ou portal."
        )
    sent_at = parse_sent_at(evidence.sent_at)
    if sent_at > reference + MAX_FUTURE_MARGIN:
        raise SendConfirmationError(
            "Un envoi ne peut pas être déclaré plus de 24 h dans le futur. "
            "C'est l'envoi réel, fait par vous, qui est enregistré."
        )
    return sent_at


def build_send_record(
    job_id: str,
    evidence: SendEvidence,
    *,
    now: datetime,
    holidays: Iterable[date] = (),
) -> SendRecord:
    """Build the honest local record of a declared send."""

    job = str(job_id).strip()
    if not job:
        raise SendConfirmationError("L'identifiant de l'offre suivi est requis.")
    sent_at = validate_evidence(evidence, now=now)
    follow_up_due = compute_follow_up_due(sent_at, holidays)
    return SendRecord(
        job_id=job,
        sent_at=sent_at,
        channel=str(evidence.channel),
        follow_up_due=follow_up_due,
    )


def build_followup_draft(
    *,
    title: str,
    company: str,
    channel: str,
    sent_at: datetime,
    followup_count: int = 0,
) -> str:
    """Rédige un brouillon de relance court, prêt à copier (français).

    Chaque relance antérieure est honnêtement nommée ; rien n'est envoyé
    automatiquement — le texte est copié-collé par la personne.
    """

    safe_title = title.strip() or "votre offre"
    safe_company = company.strip() or "votre société"
    channel_label = {
        "website": "sur votre site carrières",
        "email": "par e-mail",
        "portal": "via votre portail de recrutement",
    }.get(channel.strip(), "sur votre site carrières")
    ordinal = "première" if followup_count <= 0 else f"{followup_count + 1}ᵉ"
    sent_iso = sent_at.strftime("%d/%m/%Y")
    return (
        f"Objet : Candidature {safe_title} — {safe_company} (relance {ordinal})\n"
        "\n"
        "Bonjour,\n"
        "\n"
        f"J'ai envoyé ma candidature au poste de {safe_title} {channel_label} "
        f"le {sent_iso}. Je me permets de revenir vers vous pour confirmer "
        "son bon dépôt et exposer mon intérêt pour le rôle proposé.\n"
        "\n"
        "Je reste à votre disposition pour tout complément (CV détaillé, "
        "copie de travaux, échange), et disponible pour un entretien à votre convenance.\n"
        "\n"
        "Bonne journée,\n"
        "Meilleures salutations,\n"
        "— relance rédigée localement, à envoyer vous-même"
    )


def followup_due_status(
    follow_up_due: datetime,
    *,
    now: datetime,
) -> str:
    """Classify a due date: overdue, due (today), or scheduled."""

    due_day = _to_utc_date(follow_up_due)
    today = _to_utc_date(now)
    if due_day < today:
        return "overdue"
    if due_day == today:
        return "due"
    return "scheduled"


def prioritize_followups(
    records: Iterable[dict[str, object]],
    *,
    now: datetime,
    limit: int = 50,
) -> list[dict[str, object]]:
    """Priorize sent, unanswered applications to follow up.

    Ordre : échu le plus ancien d'abord, puis restant par date d'échéance.
    ``records`` sont des dictionnaires arborant ``follow_up_due`` (ISO) et
    un ``response_received`` booléen ; les dossiers avec réponse sont sortis.
    """

    reference = parse_sent_at(now)
    tuned: list[tuple[datetime, dict[str, object]]] = []
    for record in records:
        if not isinstance(record, dict):
            continue
        if bool(record.get("response_received")):
            continue
        raw_due = record.get("follow_up_due")
        try:
            due = parse_sent_at(raw_due)  # type: ignore[arg-type]
        except (SendConfirmationError, TypeError):
            continue
        tuned.append((due, record))
    tuned.sort(key=lambda pair: pair[0])
    results: list[dict[str, object]] = []
    for due, record in tuned:
        entry = dict(record)
        entry["follow_up_due"] = due.isoformat()
        entry["due_status"] = followup_due_status(due, now=reference)
        results.append(entry)
        if len(results) >= limit:
            break
    # Les relances échues sont les plus urgentes : elles passent devant.
    overdue = [entry for entry in results if entry["due_status"] == "overdue"]
    rest = [entry for entry in results if entry["due_status"] != "overdue"]
    return sorted(overdue, key=lambda e: str(e["follow_up_due"])) + rest  # type: ignore[arg-type, return-value]
