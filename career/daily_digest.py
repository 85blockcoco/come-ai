"""Deterministic daily digest for the local Côme AI Career workspace.

The digest answers four questions on one screen: what appeared since the last
visit, what changed, what expires soon and what stays uncertain.

Three rules shape the whole module:

* it only projects facts already stored in the local database, so it can never
  invent an offer, a score, a date or a source;
* an empty category stays empty - there is no placeholder that could look
  like data;
* it performs no network call at all, so opening the page can never query a
  source behind the user's back.

The cache and the TTL live here too, but the state itself is a small JSON
document stored in the existing ``career_settings`` key/value table.  No
schema change is required, and nothing else in the workspace is rewritten.
"""

from __future__ import annotations

import hashlib
from collections.abc import Mapping, Sequence
from datetime import date, datetime, timedelta, timezone
from typing import Any

from .models import clean_text, deadline_state


# Where the digest state (watermarks, offer tracks, cached payload) is stored.
DAILY_DIGEST_SETTING = "daily_digest_state"
# Where an explicit TTL override is stored.
DAILY_DIGEST_TTL_SETTING = "daily_digest_ttl_seconds"
# Default lifetime of a cached digest: fifteen minutes.
DAILY_DIGEST_TTL_SECONDS = 900
MIN_TTL_SECONDS = 60
MAX_TTL_SECONDS = 86_400

# At most two official sources are read at the same time. The bound is a
# resource guarantee, not a tuning knob: a slower machine must not trigger
# more concurrent requests.
MAX_PARALLEL_SOURCES = 2

MAX_NEW_OFFERS = 40
MAX_UPDATED_OFFERS = 40
MAX_EXPIRING_OFFERS = 40
MAX_UNAVAILABLE_OFFERS = 40
MAX_TOP_MATCHES = 10
# Only the most recent offers are tracked for change detection, so the stored
# state stays small and bounded.
MAX_TRACKED_OFFERS = 300

# An offer is announced as expiring when its deadline is within this window.
EXPIRING_SOON_DAYS = 14
# A failing source is proposed again after this delay.
BROKEN_SOURCE_RETRY_SECONDS = 1_800

# An offer the person explicitly rejected or archived is never presented
# again as new, updated or recommended.
SEPARATED_STATUSES = frozenset({"rejected", "archived"})

# Fields compared between two builds to name what actually changed.
TRACKED_FIELDS = (
    "title",
    "company",
    "city",
    "country",
    "employment_type",
    "role_level",
    "posted_date",
    "deadline_date",
    "duration_months",
    "source_name",
    "source_status",
)
# Facts whose absence keeps an offer unusable: without them a person cannot
# decide whether the offer is worth an application.
CRITICAL_QUALIFICATION_FIELDS = ("publication", "début", "durée", "pays")

_TRUST_VERIFIED = "verified"
_TRUST_UNVERIFIED = "unverified"
_TRUST_UNKNOWN = "unknown"


def normalize_ttl(value: Any) -> int:
    """Return a usable TTL in seconds; anything invalid falls back to the default."""
    try:
        seconds = int(value)
    except (TypeError, ValueError):
        return DAILY_DIGEST_TTL_SECONDS
    return max(MIN_TTL_SECONDS, min(MAX_TTL_SECONDS, seconds))


def parse_moment(value: Any) -> datetime | None:
    """Parse an ISO timestamp or date into an aware UTC datetime."""
    text = clean_text(value, limit=40)
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        try:
            parsed = datetime.combine(date.fromisoformat(text[:10]), datetime.min.time())
        except ValueError:
            return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def moment_text(value: datetime | None) -> str:
    """Render an aware datetime as a readable ISO-8601 UTC timestamp."""
    if value is None:
        return ""
    return value.astimezone(timezone.utc).isoformat(timespec="seconds")


def safe_date(value: Any) -> date | None:
    """Read a stored date without letting a malformed row break the screen."""
    text = clean_text(value, limit=32)
    if not text:
        return None
    try:
        return date.fromisoformat(text[:10])
    except ValueError:
        return None


def _track_value(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return str(value)
    return clean_text(value, limit=200)


def offer_track(job: Mapping[str, Any]) -> dict[str, str]:
    """Return the comparable state of one offer, used to name real changes."""
    track = {field: _track_value(job.get(field)) for field in TRACKED_FIELDS}
    description = clean_text(job.get("description_original"), limit=30_000)
    track["description_sha256"] = hashlib.sha256(description.encode("utf-8")).hexdigest() if description else ""
    return track


def changed_fields(previous: Mapping[str, Any], current: Mapping[str, Any]) -> list[str]:
    """Name the fields that differ between two tracks of the same offer."""
    names = set(previous) | set(current)
    return sorted(name for name in names if previous.get(name, "") != current.get(name, ""))


def source_trust(job: Mapping[str, Any]) -> str:
    """State how far the trust of one offer goes, without inventing it."""
    if job.get("source_verified"):
        return _TRUST_VERIFIED
    if clean_text(job.get("official_url"), limit=2_000):
        return _TRUST_UNVERIFIED
    return _TRUST_UNKNOWN


def _match_score(job: Mapping[str, Any], stage_match: Mapping[str, Any] | None) -> int | None:
    scoring = job.get("scoring") if isinstance(job.get("scoring"), Mapping) else {}
    raw = None
    if isinstance(stage_match, Mapping):
        raw = stage_match.get("score")
    if raw is None:
        raw = scoring.get("score")
    try:
        return max(0, min(100, int(raw)))
    except (TypeError, ValueError):
        return None


def _location(job: Mapping[str, Any]) -> str:
    parts = [
        clean_text(job.get("city"), limit=160),
        clean_text(job.get("country"), limit=120),
    ]
    location = ", ".join(part for part in parts if part)
    return location or "Localisation à vérifier"


def _appearance_moment(job: Mapping[str, Any]) -> datetime | None:
    """When the offer became visible to the person: publication, else first import."""
    published = safe_date(job.get("posted_date"))
    if published is not None:
        return datetime.combine(published, datetime.min.time(), tzinfo=timezone.utc)
    return parse_moment(job.get("created_at"))


def _missing_critical_count(qualification: Mapping[str, Any]) -> int:
    missing = qualification.get("missing_fields")
    labels = {clean_text(item, limit=120) for item in missing} if isinstance(missing, (list, tuple)) else set()
    return sum(1 for field in CRITICAL_QUALIFICATION_FIELDS if field in labels)


def _unavailable_reason(job: Mapping[str, Any], deadline_closed: bool) -> str:
    reasons: list[str] = []
    if clean_text(job.get("source_status"), limit=40).casefold() == "closed":
        reasons.append("La source officielle indique que l’offre est clôturée.")
    if deadline_closed:
        reasons.append("La date limite de candidature est passée.")
    return " ".join(reasons) or "L’offre n’est plus disponible d’après les informations connues."


def _broken_source_entry(name: str, error: str, last_failure: str, *, retry_after: int = BROKEN_SOURCE_RETRY_SECONDS) -> dict[str, Any]:
    failure = parse_moment(last_failure)
    return {
        "source": clean_text(name, limit=240),
        "error": clean_text(error, limit=240) or "échec non détaillé",
        "last_failure": clean_text(last_failure, limit=40),
        "retry_at": moment_text(failure + timedelta(seconds=retry_after)) if failure else None,
    }


def collect_broken_sources(
    sources: Sequence[Mapping[str, Any]],
    explorer_outcomes: Sequence[Mapping[str, Any]] = (),
) -> list[dict[str, Any]]:
    """List every source that is known to be failing, with the next retry time."""
    broken: list[dict[str, Any]] = []
    seen: set[str] = set()
    for source in sources:
        code = clean_text(source.get("last_error_code"), limit=80)
        if not code:
            continue
        name = clean_text(source.get("company"), limit=240) or clean_text(source.get("id"), limit=160)
        key = name.casefold()
        if key in seen:
            continue
        seen.add(key)
        broken.append(
            _broken_source_entry(name, code, clean_text(source.get("last_error_at"), limit=40))
        )
    for outcome in explorer_outcomes:
        if clean_text(outcome.get("status"), limit=40) != "error":
            continue
        name = clean_text(outcome.get("company"), limit=240) or clean_text(outcome.get("source_id"), limit=160)
        key = name.casefold()
        if not name or key in seen:
            continue
        seen.add(key)
        broken.append(
            _broken_source_entry(
                name,
                clean_text(outcome.get("error_code"), limit=80) or "échec de lecture",
                clean_text(outcome.get("registry_verified_at"), limit=40),
            )
        )
    broken.sort(key=lambda item: (-(_parse_order(item.get("last_failure")) or 0), item["source"]))
    return broken


def project_digest(
    *,
    matches: Sequence[Mapping[str, Any]],
    sources: Sequence[Mapping[str, Any]] = (),
    explorer_outcomes: Sequence[Mapping[str, Any]] = (),
    state: Mapping[str, Any] | None = None,
    now: datetime,
    ttl_seconds: int = DAILY_DIGEST_TTL_SECONDS,
) -> dict[str, Any]:
    """Build the daily digest from already stored facts.

    ``matches`` holds one entry per stored offer, each with the serialized
    offer, its qualification against the saved criteria and the brief-relative
    match.  The function is pure: it reads nothing, writes nothing and never
    performs a request.
    """
    state = state or {}
    ttl = normalize_ttl(ttl_seconds)
    tracks = state.get("tracks") if isinstance(state.get("tracks"), Mapping) else {}
    last_visit = parse_moment(state.get("last_visit"))
    last_refresh = clean_text(state.get("last_refresh"), limit=40)
    today = now.date()

    separated_ids: set[str] = set()
    excluded_ids: set[str] = set()
    eligible: list[tuple[Mapping[str, Any], Mapping[str, Any], Mapping[str, Any] | None]] = []
    for match in matches:
        job = match.get("job") if isinstance(match.get("job"), Mapping) else {}
        qualification = match.get("qualification") if isinstance(match.get("qualification"), Mapping) else {}
        stage_match = match.get("stage_match") if isinstance(match.get("stage_match"), Mapping) else None
        job_id = clean_text(job.get("id"), limit=80)
        if clean_text(job.get("status"), limit=40) in SEPARATED_STATUSES:
            separated_ids.add(job_id)
            continue
        if clean_text(qualification.get("geography_status"), limit=40) == "excluded":
            excluded_ids.add(job_id)
            continue
        eligible.append((job, qualification, stage_match))

    # 1. New offers: everything that appeared after the last recorded visit.
    new_candidates: list[tuple[datetime, Mapping[str, Any], Mapping[str, Any], Mapping[str, Any] | None]] = []
    for job, qualification, stage_match in eligible:
        moment = _appearance_moment(job)
        if moment is None:
            continue
        if last_visit is not None and moment <= last_visit:
            continue
        new_candidates.append((moment, job, qualification, stage_match))
    new_candidates.sort(
        key=lambda item: (
            -item[0].timestamp(),
            -(_match_score(item[1], item[3]) or 0),
            clean_text(item[1].get("company"), limit=240).casefold(),
            clean_text(item[1].get("title"), limit=300).casefold(),
        )
    )
    new_offers: list[dict[str, Any]] = []
    # Every new offer is remembered, even the ones the cap hides: an offer
    # that is new is never reported again as an update.
    new_ids: set[str] = {clean_text(item[1].get("id"), limit=80) for item in new_candidates}
    for _, job, _qualification, stage_match in new_candidates[:MAX_NEW_OFFERS]:
        job_id = clean_text(job.get("id"), limit=80)
        new_offers.append(
            {
                "offer_id": job_id,
                "title": clean_text(job.get("title"), limit=300) or "Intitulé à vérifier",
                "employer": clean_text(job.get("company"), limit=240) or "Entreprise à vérifier",
                "location": _location(job),
                "published_date": clean_text(job.get("posted_date"), limit=32) or None,
                "match_score": _match_score(job, stage_match),
                "source_trust": source_trust(job),
            }
        )

    # 2. Updated offers: only the fields that really changed since the last build.
    updated: list[tuple[list[str], Mapping[str, Any], Mapping[str, Any], Mapping[str, Any] | None]] = []
    for job, qualification, stage_match in eligible:
        job_id = clean_text(job.get("id"), limit=80)
        if not job_id or job_id in new_ids:
            continue
        previous = tracks.get(job_id) if isinstance(tracks.get(job_id), Mapping) else None
        if not previous:
            continue
        differences = changed_fields(previous, offer_track(job))
        if not differences:
            continue
        updated.append((differences, job, qualification, stage_match))
    updated.sort(
        key=lambda item: (
            -(_match_score(item[1], item[3]) or 0),
            clean_text(item[1].get("company"), limit=240).casefold(),
            clean_text(item[1].get("title"), limit=300).casefold(),
        )
    )
    updated_offers: list[dict[str, Any]] = []
    for differences, job, _qualification, _stage_match in updated[:MAX_UPDATED_OFFERS]:
        updated_offers.append(
            {
                "offer_id": clean_text(job.get("id"), limit=80),
                "title": clean_text(job.get("title"), limit=300) or "Intitulé à vérifier",
                "employer": clean_text(job.get("company"), limit=240) or "Entreprise à vérifier",
                "changed_fields": differences,
                "updated_at": clean_text(job.get("updated_at"), limit=40),
            }
        )

    # 3. Expiring soon: a known deadline that is still reachable.
    expiring: list[tuple[int, Mapping[str, Any]]] = []
    for job, _qualification, _stage_match in eligible:
        deadline = safe_date(job.get("deadline_date"))
        if deadline is None:
            continue
        days_left = (deadline - today).days
        if days_left < 0 or days_left > EXPIRING_SOON_DAYS:
            continue
        expiring.append((days_left, job))
    expiring.sort(
        key=lambda item: (
            item[0],
            clean_text(item[1].get("company"), limit=240).casefold(),
            clean_text(item[1].get("title"), limit=300).casefold(),
        )
    )
    expiring_soon = [
        {
            "offer_id": clean_text(job.get("id"), limit=80),
            "title": clean_text(job.get("title"), limit=300) or "Intitulé à vérifier",
            "employer": clean_text(job.get("company"), limit=240) or "Entreprise à vérifier",
            "deadline_date": clean_text(job.get("deadline_date"), limit=32),
            "days_left": days_left,
        }
        for days_left, job in expiring[:MAX_EXPIRING_OFFERS]
    ]

    # 4. Unavailable: the offer is known to be closed, never merely forgotten.
    unavailable: list[dict[str, Any]] = []
    for job, _qualification, _stage_match in eligible:
        state_closed = deadline_state(
            job.get("deadline_date"), clean_text(job.get("source_status"), limit=40) or "unknown", today=today
        )
        source_closed = clean_text(job.get("source_status"), limit=40).casefold() == "closed"
        if not (source_closed or state_closed == "closed"):
            continue
        unavailable.append(
            {
                "offer_id": clean_text(job.get("id"), limit=80),
                "title": clean_text(job.get("title"), limit=300) or "Intitulé à vérifier",
                "employer": clean_text(job.get("company"), limit=240) or "Entreprise à vérifier",
                "reason": _unavailable_reason(job, state_closed == "closed"),
                "detected_at": clean_text(job.get("updated_at"), limit=40)
                or clean_text(job.get("last_verified_at"), limit=40),
            }
        )
    unavailable.sort(
        key=lambda item: (
            -(_parse_order(item.get("detected_at")) or 0),
            clean_text(item.get("title"), limit=300).casefold(),
        )
    )
    unavailable_total = len(unavailable)
    unavailable = unavailable[:MAX_UNAVAILABLE_OFFERS]

    # 5. Best compatible offers: the brief-relative ranking, uncertainties kept.
    ranked: list[tuple[tuple[Any, ...], dict[str, Any]]] = []
    uncertain = 0
    for job, qualification, stage_match in eligible:
        status = clean_text(qualification.get("target_status"), limit=40) or "to_verify"
        if status == "non_conforming":
            continue
        missing_critical = _missing_critical_count(qualification)
        if missing_critical:
            uncertain += 1
        score = _match_score(job, stage_match)
        ranked.append(
            (
                (
                    {"conforming": 0, "to_verify": 1}.get(status, 2),
                    missing_critical,
                    -(score or 0),
                    clean_text(job.get("company"), limit=240).casefold(),
                    clean_text(job.get("title"), limit=300).casefold(),
                ),
                {
                    "offer_id": clean_text(job.get("id"), limit=80),
                    "title": clean_text(job.get("title"), limit=300) or "Intitulé à vérifier",
                    "employer": clean_text(job.get("company"), limit=240) or "Entreprise à vérifier",
                    "fit_score": score,
                    "missing_critical_count": missing_critical,
                    "qualification_status": status,
                },
            )
        )
    ranked.sort(key=lambda item: item[0])
    top_matches = [entry for _key, entry in ranked[:MAX_TOP_MATCHES]]

    # 6. Broken sources: every failure that is still standing.
    broken_sources = collect_broken_sources(sources, explorer_outcomes)

    partial = bool(state.get("partial"))
    notes: list[str] = []
    if partial:
        notes.append(
            "La dernière actualisation a été interrompue : les éléments ci-dessous proviennent des données déjà enregistrées."
        )
    if not last_refresh:
        notes.append("Aucune actualisation manuelle n’a encore été lancée depuis l’installation.")

    return {
        "new_offers": new_offers,
        "updated_offers": updated_offers,
        "expiring_soon": expiring_soon,
        "unavailable": unavailable,
        "top_matches": top_matches,
        "broken_sources": broken_sources,
        "last_refresh": last_refresh or None,
        "cache_expires_at": moment_text(now + timedelta(seconds=ttl)),
        "generated_at": moment_text(now),
        "last_visit": clean_text(state.get("last_visit"), limit=40) or None,
        "partial": partial,
        "counts": {
            "new_offers": len(new_candidates),
            "updated_offers": len(updated),
            "expiring_soon": len(expiring),
            "unavailable": unavailable_total,
            "top_matches": len(ranked),
            "broken_sources": len(broken_sources),
            "uncertain_offers": uncertain,
            "excluded_by_criteria": len(excluded_ids),
            "separated_offers": len(separated_ids),
            "considered_offers": len(eligible),
        },
        "notes": notes,
        "disclaimer": (
            "Synthèse calculée localement à partir des offres déjà enregistrées. "
            "Les scores mesurent une adéquation documentaire, pas une probabilité d’embauche. "
            "Aucune candidature n’est envoyée et aucune source n’est consultée au chargement de cette page."
        ),
    }


def _parse_order(value: Any) -> float | None:
    moment = parse_moment(value)
    return moment.timestamp() if moment else None


def build_tracks(matches: Sequence[Mapping[str, Any]]) -> dict[str, dict[str, str]]:
    """Return the new comparison state, bounded to the most recent offers."""
    tracks: dict[str, dict[str, str]] = {}
    ordered = sorted(
        matches,
        key=lambda match: -(
            _parse_order((match.get("job") or {}).get("updated_at"))
            or _parse_order((match.get("job") or {}).get("created_at"))
            or 0.0
        ),
    )
    for match in ordered:
        job = match.get("job") if isinstance(match.get("job"), Mapping) else {}
        job_id = clean_text(job.get("id"), limit=80)
        if not job_id or job_id in tracks:
            continue
        tracks[job_id] = offer_track(job)
        if len(tracks) >= MAX_TRACKED_OFFERS:
            break
    return tracks


def empty_state() -> dict[str, Any]:
    """Return a valid, empty digest state."""
    return {
        "version": 1,
        "status": "idle",
        "last_visit": "",
        "last_refresh": "",
        "built_at": "",
        "expires_at": "",
        "tracks": {},
        "digest": {},
        "partial": False,
        "note": "",
    }
