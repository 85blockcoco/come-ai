"""Deterministic models and normalization for the local Côme AI Career workspace."""

from __future__ import annotations

import re
import unicodedata
import urllib.parse
from datetime import date, datetime, timezone
from enum import Enum
from typing import Any

from workspace_core import UserFacingError


AVAILABILITY_START = date(2027, 1, 1)
AVAILABILITY_END = date(2027, 6, 30)
MIN_DURATION_MONTHS = 3
MAX_DURATION_MONTHS = 6

JOB_FAMILIES = (
    "M&A / Investment Banking",
    "Private Equity",
    "Asset Management",
    "Sales & Trading",
    "Corporate Finance",
    "Consulting",
)

PRIMARY_LOCATIONS = (
    ("paris", "Paris", "primary"),
    ("london", "Londres", "primary"),
    ("milan", "Milan", "primary"),
    ("luxembourg", "Luxembourg", "primary"),
    ("frankfurt", "Francfort", "primary"),
    ("geneva", "Genève", "primary"),
    ("other-europe", "Autres villes européennes", "secondary"),
)

JOB_STATES = {"discovered", "shortlisted", "rejected", "archived"}
AVAILABILITY_STATES = {"open", "closed", "unknown"}
APPLICATION_STAGES = {
    "to_review",
    "to_prepare",
    "ready_to_apply",
    "approved_for_manual_submission",
    "deferred",
    "rejected",
    "refused",
    "withdrawn",
    "receipt_unknown",
    "submitted",
    "submitted_confirmed",
    "response_received",
    "interview",
    "offer_received",
}
# Stages a person may record directly.  ``approved_for_manual_submission``
# stays out (it is granted through the explicit approval flow) and
# ``submitted_confirmed`` stays out (it requires a receipt confirmation
# reference).  ``submitted`` is a person-declared fact: the person states
# they completed the manual deposit themselves; it claims nothing about the
# employer receiving it.
GENERIC_APPLICATION_STAGES = {
    "to_review",
    "to_prepare",
    "ready_to_apply",
    "deferred",
    "rejected",
    "refused",
    "withdrawn",
    "receipt_unknown",
    "submitted",
    "response_received",
    "interview",
    "offer_received",
}


class PipelineStage(str, Enum):
    """Derived progress through the local offer-to-application workflow."""

    DISCOVERED = "discovered"
    QUALIFIED = "qualified"
    SPRINT_QUEUED = "sprint_queued"
    PREP_ANALYZED = "prep_analyzed"
    VARIANT_SELECTED = "variant_selected"
    KIT_GENERATED = "kit_generated"
    TRACKING_CREATED = "tracking_created"

    def __str__(self) -> str:
        return self.value


def utc_now() -> str:
    # Profile-import review uses this value as an optimistic-concurrency
    # revision. Second precision would let an extraction and a manual profile
    # edit made in the same second overwrite one another unnoticed.
    return datetime.now(timezone.utc).isoformat(timespec="microseconds")


def clean_text(value: Any, *, limit: int = 10_000) -> str:
    text = str(value or "").replace("\x00", "").strip()
    return text[:limit]


#: The single marker used whenever a fact is missing from the approved
#: profile.  The targeted generator (``career.application_studio``) writes it,
#: the review workspace (``career.cv_review``) reads it: one convention, one
#: meaning — "a proof is still missing here".
EVIDENCE_PLACEHOLDER = "[AJOUTER PREUVE CHIFFRÉE]"


def normalized_text(value: Any) -> str:
    text = unicodedata.normalize("NFKD", clean_text(value).lower())
    text = "".join(character for character in text if not unicodedata.combining(character))
    return re.sub(r"[^a-z0-9]+", " ", text).strip()


def parse_date(value: Any, field_label: str) -> date | None:
    text = clean_text(value, limit=32)
    if not text:
        return None
    try:
        return date.fromisoformat(text)
    except ValueError as error:
        raise UserFacingError(f"{field_label} doit être au format AAAA-MM-JJ.") from error


def date_text(value: date | None) -> str | None:
    return value.isoformat() if value else None


def canonical_url(value: Any) -> str:
    raw = clean_text(value, limit=2_000)
    if not raw:
        return ""
    parsed = urllib.parse.urlsplit(raw)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise UserFacingError("L’URL officielle doit commencer par http:// ou https://.")
    # An official job URL must never be used as a place to retain credentials.
    # This also avoids presenting a credential-bearing link back to the user.
    if parsed.username or parsed.password:
        raise UserFacingError("L’URL officielle ne doit pas contenir d’identifiant ni de mot de passe.")
    hostname = parsed.hostname.lower() if parsed.hostname else ""
    if not hostname:
        raise UserFacingError("L’URL officielle est invalide.")
    try:
        parsed_port = parsed.port
    except ValueError as error:
        raise UserFacingError("Le port de l’URL officielle est invalide.") from error
    # ``https://example.org`` and ``https://example.org:443`` identify the
    # same page.  Retain only non-default ports in the deduplication key.
    port = f":{parsed_port}" if parsed_port and (parsed.scheme, parsed_port) not in {("http", 80), ("https", 443)} else ""
    # Query parameters used only for marketing or tracking must not create a
    # new opportunity when the same ATS posting is imported again.
    tracking = {"gclid", "fbclid", "ref", "source", "sourceid"}
    query = [
        (key, item)
        for key, item in urllib.parse.parse_qsl(parsed.query, keep_blank_values=True)
        if not key.lower().startswith("utm_") and key.lower() not in tracking
    ]
    path = re.sub(r"/+", "/", parsed.path or "/").rstrip("/") or "/"
    return urllib.parse.urlunsplit((parsed.scheme.lower(), hostname + port, path, urllib.parse.urlencode(sorted(query)), ""))


def dedup_key(
    *,
    source_name: str,
    source_id: str,
    official_url: str,
    company: str,
    title: str,
    city: str,
) -> str:
    # A manually pasted optional ATS field is not globally unique until a source
    # connector has identified its provider, so it must not overwrite an
    # unrelated manual offer.  Real connectors pass a non-manual source name.
    if source_id and normalized_text(source_name) not in {"", "manual", "import manuel"}:
        return f"source:{normalized_text(source_name)}:{normalized_text(source_id)}"
    if official_url:
        return f"url:{canonical_url(official_url)}"
    pieces = (normalized_text(company), normalized_text(title), normalized_text(city))
    return "manual:" + "|".join(pieces)


def availability_assessment(
    *,
    start_date: str | None,
    end_date: str | None,
    duration_months: int | None,
    availability_start: date | str | None = None,
    availability_end: date | str | None = None,
    minimum_duration_months: int | None = None,
    maximum_duration_months: int | None = None,
) -> dict[str, Any]:
    """Classify known dates against an explicit or default search window.

    The optional window arguments keep the pure classifier reusable: a job is
    never assigned a date that was absent from its source, but a person may
    change the period and duration they want the local tracker to compare.
    """
    start = parse_date(start_date, "La date de début")
    end = parse_date(end_date, "La date de fin")
    window_start = (
        availability_start
        if isinstance(availability_start, date)
        else parse_date(availability_start, "La disponibilité de début")
    ) or AVAILABILITY_START
    window_end = (
        availability_end
        if isinstance(availability_end, date)
        else parse_date(availability_end, "La disponibilité de fin")
    ) or AVAILABILITY_END
    minimum_duration = MIN_DURATION_MONTHS if minimum_duration_months is None else int(minimum_duration_months)
    maximum_duration = MAX_DURATION_MONTHS if maximum_duration_months is None else int(maximum_duration_months)
    if window_end < window_start:
        raise UserFacingError("La disponibilité de fin ne peut pas précéder la disponibilité de début.")
    if minimum_duration < 1 or maximum_duration > 24 or minimum_duration > maximum_duration:
        raise UserFacingError("La plage de durée de stage est invalide.")
    reasons: list[str] = []
    if start and end and end < start:
        raise UserFacingError("La date de fin ne peut pas précéder la date de début.")

    if start and end:
        duration_note = ""
        if duration_months is not None and not minimum_duration <= duration_months <= maximum_duration:
            duration_note = (
                f"La durée annoncée de {duration_months} mois est hors préférence de "
                f"{minimum_duration} à {maximum_duration} mois."
            )
        if end < window_start or start > window_end:
            return {
                "status": "incompatible",
                "label": "Incompatible",
                "reasons": ["La période connue ne recouvre pas la disponibilité configurée."],
            }
        if end > window_end:
            return {
                "status": "potentially_incompatible",
                "label": "Potentiellement incompatible",
                "reasons": [f"Le stage se termine après le {window_end.isoformat()}."],
            }
        if start < window_start:
            return {
                "status": "partial",
                "label": "Partiellement compatible",
                "reasons": [f"Le stage commence avant le {window_start.isoformat()}."],
            }
        if duration_note:
            return {
                "status": "potentially_incompatible",
                "label": "Potentiellement incompatible",
                "reasons": [duration_note],
            }
        return {
            "status": "compatible",
            "label": "Compatible",
            "reasons": ["Les dates connues sont comprises dans la disponibilité configurée."],
        }

    if start and start > window_end:
        return {
            "status": "incompatible",
            "label": "Incompatible",
            "reasons": [f"Le début connu est postérieur au {window_end.isoformat()}."],
        }
    if end and end < window_start:
        return {
            "status": "incompatible",
            "label": "Incompatible",
            "reasons": [f"La fin connue est antérieure au {window_start.isoformat()}."],
        }
    if duration_months is not None:
        if duration_months < minimum_duration or duration_months > maximum_duration:
            reasons.append(
                f"Durée annoncée de {duration_months} mois, hors préférence de {minimum_duration} à {maximum_duration} mois."
            )
            return {
                "status": "potentially_incompatible",
                "label": "Potentiellement incompatible",
                "reasons": reasons,
            }
        reasons.append("Durée compatible, mais calendrier précis non renseigné.")
    else:
        reasons.append("Dates et durée non renseignées.")
    return {"status": "to_verify", "label": "À vérifier", "reasons": reasons}


def deadline_state(deadline: str | None, availability_status: str, *, today: date | None = None) -> str:
    if availability_status == "closed":
        return "closed"
    parsed = parse_date(deadline, "La date limite")
    if parsed and parsed < (today or date.today()):
        return "closed"
    if availability_status == "open":
        return "open"
    return "unknown"


def validate_choice(value: Any, allowed: set[str], label: str, default: str) -> str:
    cleaned = clean_text(value, limit=80).lower().replace(" ", "_") or default
    if cleaned not in allowed:
        raise UserFacingError(f"{label} est invalide.")
    return cleaned
