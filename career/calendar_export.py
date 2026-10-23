"""Local, deterministic iCalendar export for Career application deadlines.

The Career tracker deliberately keeps calendar generation separate from its
router and service layers.  This module receives already-local records,
performs no I/O, never follows an offer URL, and does not use a model or a
personal secret.  Its only output is an inert UTF-8 ``.ics`` string that a
person may choose to import into their own calendar.

The implementation is intentionally conservative: an offer gets an event only
when its deadline is known, not in the past, and it has not been closed or
advanced beyond the manual-submission workflow.  Text is escaped and folded so
that untrusted job-board content cannot create additional iCalendar fields.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from datetime import date, timedelta
from hashlib import sha256
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit


DEFAULT_CALENDAR_NAME = "Côme AI — échéances de candidature"
"""Human-readable calendar title used when the caller does not choose one."""

MAX_INPUT_RECORDS = 1_000
"""Maximum job/application records inspected in one in-memory export."""

MAX_EVENTS = 250
"""Maximum all-day events emitted in one calendar export."""

MAX_TEXT_LENGTH = 1_200
MAX_URL_LENGTH = 2_000

_TERMINAL_JOB_STATES = frozenset({"archived", "rejected", "withdrawn", "closed"})
_TERMINAL_APPLICATION_STAGES = frozenset(
    {
        "submitted",
        "submitted_confirmed",
        "confirmed_submitted",
        "response_received",
        "interview",
        "offer_received",
        "rejected",
        "refused",
        "withdrawn",
        "archived",
    }
)
_TERMINAL_RECEIPT_STATUSES = frozenset({"confirmed", "submitted", "confirmed_submitted"})
_SENSITIVE_URL_QUERY_KEYS = frozenset(
    {
        "access_token",
        "api_key",
        "apikey",
        "auth",
        "authorization",
        "key",
        "password",
        "secret",
        "signature",
        "sig",
        "token",
    }
)


def build_deadline_calendar_ics(
    jobs: Iterable[Mapping[str, Any]] | None,
    applications: Iterable[Mapping[str, Any]] | None,
    *,
    calendar_name: str = DEFAULT_CALENDAR_NAME,
) -> str:
    """Build a bounded, deterministic all-day calendar of open deadlines.

    ``jobs`` and ``applications`` are plain local mappings, such as the
    records returned by :class:`career.service.CareerService`.  They are data,
    never instructions: no value is evaluated, opened, fetched, or otherwise
    executed.  At most :data:`MAX_INPUT_RECORDS` records from each iterable
    and :data:`MAX_EVENTS` eligible job events are considered.

    An event is included only when all of these statements are true:

    * the job has an ISO ``deadline_date`` today or later;
    * the job has not been marked closed, archived, rejected, or withdrawn;
    * neither an embedded nor matching application is already confirmed,
      submitted, in interview, rejected, withdrawn, or archived.

    No timestamp is generated, making the export byte-for-byte deterministic
    for the same local data on the same calendar day.  The resulting string
    uses CRLF, RFC 5545 text escaping, and UTF-8-safe line folding.
    """

    today = date.today()
    applications_by_job = _applications_by_job(applications)
    candidates: list[_CalendarCandidate] = []

    for job in _bounded_mappings(jobs):
        candidate = _candidate_from_job(job, applications_by_job, today=today)
        if candidate is not None:
            candidates.append(candidate)

    # Calendar applications use the UID as their reconciliation key.  A local
    # job id therefore must result in no more than one VEVENT even if a caller
    # accidentally supplies a duplicated tracker record.  Sorting first also
    # gives stable output independent of the normal database listing order.
    candidates.sort(key=lambda item: item.sort_key)
    unique_candidates: list[_CalendarCandidate] = []
    seen_job_ids: set[str] = set()
    for candidate in candidates:
        if candidate.job_id in seen_job_ids:
            continue
        seen_job_ids.add(candidate.job_id)
        unique_candidates.append(candidate)
        if len(unique_candidates) >= MAX_EVENTS:
            break

    lines = [
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        "PRODID:-//Come AI//Career local deadline calendar//FR",
        "CALSCALE:GREGORIAN",
        "METHOD:PUBLISH",
        f"X-WR-CALNAME:{_escape_text(_bounded_text(calendar_name, limit=160) or DEFAULT_CALENDAR_NAME)}",
    ]
    for candidate in unique_candidates:
        lines.extend(_event_lines(candidate))
    lines.append("END:VCALENDAR")
    return "".join(_fold_ical_line(line) + "\r\n" for line in lines)


class _CalendarCandidate:
    """A small immutable-in-practice representation of one safe VEVENT."""

    __slots__ = ("job_id", "deadline", "company", "title", "official_url")

    def __init__(self, *, job_id: str, deadline: date, company: str, title: str, official_url: str) -> None:
        self.job_id = job_id
        self.deadline = deadline
        self.company = company
        self.title = title
        self.official_url = official_url

    @property
    def sort_key(self) -> tuple[str, str, str, str]:
        return (
            self.deadline.isoformat(),
            self.company.casefold(),
            self.title.casefold(),
            self.job_id,
        )


def _bounded_mappings(records: Iterable[Mapping[str, Any]] | None) -> tuple[Mapping[str, Any], ...]:
    """Read a limited number of mappings without materialising an untrusted iterable."""

    if records is None:
        return ()
    if isinstance(records, Mapping):
        # Accepting one mapping is friendlier than iterating its field names,
        # while keeping an accidental scalar harmless.
        return (records,)
    try:
        iterator = iter(records)
    except TypeError:
        return ()

    result: list[Mapping[str, Any]] = []
    for record in iterator:
        if len(result) >= MAX_INPUT_RECORDS:
            break
        if isinstance(record, Mapping):
            result.append(record)
    return tuple(result)


def _applications_by_job(
    applications: Iterable[Mapping[str, Any]] | None,
) -> dict[str, tuple[Mapping[str, Any], ...]]:
    grouped: dict[str, list[Mapping[str, Any]]] = {}
    for application in _bounded_mappings(applications):
        job_id = _bounded_text(application.get("job_id"), limit=256)
        if job_id:
            grouped.setdefault(job_id, []).append(application)
    return {job_id: tuple(records) for job_id, records in grouped.items()}


def _candidate_from_job(
    job: Mapping[str, Any],
    applications_by_job: Mapping[str, tuple[Mapping[str, Any], ...]],
    *,
    today: date,
) -> _CalendarCandidate | None:
    job_id = _bounded_text(job.get("id"), limit=256)
    deadline = _date_or_none(job.get("deadline_date"))
    if not job_id or deadline is None or deadline < today:
        return None
    if _job_is_terminal(job):
        return None

    related = list(applications_by_job.get(job_id, ()))
    embedded = job.get("application")
    if isinstance(embedded, Mapping):
        related.append(embedded)
    if any(_application_is_terminal(application) for application in related):
        return None

    company = _bounded_text(job.get("company"), limit=180) or "Entreprise à préciser"
    title = _bounded_text(job.get("title"), limit=260) or "Offre à préciser"
    return _CalendarCandidate(
        job_id=job_id,
        deadline=deadline,
        company=company,
        title=title,
        official_url=_safe_offer_url(job.get("official_url")),
    )


def _job_is_terminal(job: Mapping[str, Any]) -> bool:
    state_values = (
        job.get("status"),
        job.get("source_status"),
        job.get("deadline_status"),
    )
    normalized_states = {_normalized_state(value) for value in state_values}
    return bool(normalized_states & _TERMINAL_JOB_STATES)


def _application_is_terminal(application: Mapping[str, Any]) -> bool:
    stage = _normalized_state(application.get("stage"))
    receipt = _normalized_state(application.get("receipt_status"))
    status = _normalized_state(application.get("status"))
    return (
        stage in _TERMINAL_APPLICATION_STAGES
        or status in _TERMINAL_APPLICATION_STAGES
        or receipt in _TERMINAL_RECEIPT_STATUSES
    )


def _normalized_state(value: Any) -> str:
    return _bounded_text(value, limit=80).casefold().replace("-", "_").replace(" ", "_")


def _date_or_none(value: Any) -> date | None:
    raw = _bounded_text(value, limit=32)
    if not raw:
        return None
    try:
        return date.fromisoformat(raw)
    except ValueError:
        return None


def _bounded_text(value: Any, *, limit: int = MAX_TEXT_LENGTH) -> str:
    """Coerce text safely, remove control characters, and cap memory use."""

    try:
        raw = str(value or "")
    except Exception:
        # A hostile custom object must not prevent a calendar export.  It is
        # represented by nothing, and importantly never invoked beyond str().
        return ""
    # Keep newlines long enough for the ICS text encoder to make them literal
    # ``\\n`` escape sequences.  All other C0/C1 controls are discarded.
    cleaned: list[str] = []
    for character in raw:
        codepoint = ord(character)
        if character in {"\r", "\n"}:
            cleaned.append(character)
        elif codepoint < 32 or 127 <= codepoint <= 159:
            continue
        else:
            cleaned.append(character)
        if len(cleaned) >= limit:
            break
    return "".join(cleaned).strip()


def _escape_text(value: str) -> str:
    """Escape RFC 5545 TEXT values without permitting field injection."""

    normalized_newlines = value.replace("\r\n", "\n").replace("\r", "\n")
    return (
        normalized_newlines.replace("\\", "\\\\")
        .replace(";", "\\;")
        .replace(",", "\\,")
        .replace("\n", "\\n")
    )


def _safe_offer_url(value: Any) -> str:
    """Return an inert, credential-free public URL or an empty string.

    The calendar may contain a link to the official public offer, but query
    parameters commonly used to hold credentials are removed rather than
    copied into a calendar.  Invalid URLs are simply omitted from the export.
    """

    raw = _bounded_text(value, limit=MAX_URL_LENGTH)
    if not raw or any(ord(character) < 32 or ord(character) == 127 for character in raw):
        return ""
    try:
        parsed = urlsplit(raw)
    except ValueError:
        return ""
    if parsed.scheme.casefold() not in {"http", "https"} or not parsed.netloc:
        return ""
    if parsed.username or parsed.password or not parsed.hostname:
        return ""
    try:
        filtered_query = [
            (key, item)
            for key, item in parse_qsl(parsed.query, keep_blank_values=True)
            if key.casefold() not in _SENSITIVE_URL_QUERY_KEYS
        ]
    except ValueError:
        return ""
    # ``urlunsplit`` deliberately drops the fragment, which often contains a
    # local navigation hint and never needs to become calendar data.
    return urlunsplit((parsed.scheme.casefold(), parsed.netloc, parsed.path or "/", urlencode(filtered_query), ""))


def _event_lines(candidate: _CalendarCandidate) -> list[str]:
    next_day = candidate.deadline + timedelta(days=1)
    summary = f"Échéance : {candidate.company} — {candidate.title}"
    description_parts = [
        "Rappel local Côme AI pour suivre cette date limite.",
        "Aucune candidature n’est envoyée automatiquement depuis ce calendrier.",
    ]
    if candidate.official_url:
        description_parts.append(f"Offre officielle : {candidate.official_url}")
    description = "\n".join(description_parts)
    uid_digest = sha256(f"come-ai-career-deadline:{candidate.job_id}".encode("utf-8")).hexdigest()[:32]
    lines = [
        "BEGIN:VEVENT",
        f"UID:come-ai-career-{uid_digest}@local",
        f"DTSTART;VALUE=DATE:{candidate.deadline:%Y%m%d}",
        f"DTEND;VALUE=DATE:{next_day:%Y%m%d}",
        f"SUMMARY:{_escape_text(summary)}",
        f"DESCRIPTION:{_escape_text(description)}",
        "TRANSP:TRANSPARENT",
    ]
    if candidate.official_url:
        lines.append(f"URL:{candidate.official_url}")
    lines.append("END:VEVENT")
    return lines


def escape_ical_text(value: str) -> str:
    """Public RFC 5545 text escaper, shared with the other local calendar exports.

    Exposed so that every calendar produced by Career escapes and folds its
    content lines the same way, instead of each module re-implementing the
    encoding rules.
    """

    return _escape_text(value)


def fold_ical_line(line: str) -> str:
    """Public ICS line folder, shared with the other local calendar exports."""

    return _fold_ical_line(line)


def _fold_ical_line(line: str) -> str:
    """Fold an ICS content line at 75 UTF-8 octets, preserving characters.

    RFC 5545 consumers unfold a ``CRLF`` followed by one space before reading
    the property.  The whitespace is therefore structural and never derived
    from an untrusted field value.
    """

    encoded_length = len(line.encode("utf-8"))
    if encoded_length <= 75:
        return line

    chunks: list[str] = []
    current: list[str] = []
    current_length = 0
    # Continuation rows start with a single space, so they carry at most 74
    # bytes of text while still respecting the 75-octet physical line limit.
    capacity = 75
    for character in line:
        character_length = len(character.encode("utf-8"))
        if current and current_length + character_length > capacity:
            chunks.append("".join(current))
            current = [character]
            current_length = character_length
            capacity = 74
        else:
            current.append(character)
            current_length += character_length
    if current:
        chunks.append("".join(current))

    return "\r\n ".join(chunks)

