"""Local, privacy-preserving execution usage ledger for Côme AI.

The ledger is deliberately *observability only*: it never invokes a provider,
loads ``.env``, estimates tokens or prices, or stores prompts, document text,
headers, credentials, or arbitrary request metadata.  Callers record facts
they already know after an execution (or after a policy refusal).  Missing
measurements remain explicitly ``unknown`` rather than being silently turned
into zeroes.

The public API is intentionally small and JSON-ready:

* :meth:`UsageLedger.record_execution` stores one bounded execution event;
* :meth:`UsageLedger.record_zero_spend_refusal` records a refusal before an
  external call, without pretending that an unknown price is ``0``;
* :meth:`UsageLedger.aggregate` exposes UTC hour/day/week/month buckets;
* :meth:`UsageLedger.dashboard_summary` returns a safe dashboard snapshot;
* :meth:`UsageLedger.export_csv` writes a metadata-only CSV without prompt or
  error-message content.

SQLite is used locally in WAL mode.  The implementation uses only the Python
standard library and performs no network I/O.
"""

from __future__ import annotations

import csv
import os
import re
import sqlite3
import uuid
from collections import Counter, defaultdict
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
from enum import StrEnum
from pathlib import Path
from typing import Any


DEFAULT_MAX_EVENTS = 50_000
DEFAULT_LIST_LIMIT = 100
MAX_LIST_LIMIT = 1_000
DEFAULT_MAX_BUCKETS = 500
MAX_BUCKETS = 5_000
MAX_TAG_LENGTH = 128
MAX_CURRENCY_LENGTH = 12
MAX_INTEGER_MEASUREMENT = 10**15


class UsageLedgerError(ValueError):
    """A safe configuration or input error suitable for the local UI."""


class UsageOutcome(StrEnum):
    """Known execution outcomes; no provider-specific success is inferred."""

    SUCCEEDED = "succeeded"
    FAILED = "failed"
    REFUSED = "refused"
    CANCELLED = "cancelled"


class CacheState(StrEnum):
    """Whether the caller explicitly reported a cache outcome."""

    HIT = "hit"
    MISS = "miss"
    BYPASS = "bypass"
    UNKNOWN = "unknown"


class FallbackState(StrEnum):
    """Whether the caller explicitly reported a provider/model fallback."""

    USED = "used"
    NOT_USED = "not_used"
    UNKNOWN = "unknown"


class VerificationState(StrEnum):
    """Whether the caller explicitly verified the result."""

    VERIFIED = "verified"
    NOT_VERIFIED = "not_verified"
    UNKNOWN = "unknown"


class CostState(StrEnum):
    """Cost certainty for one event.

    ``NOT_INCURRED`` is reserved for a deterministic refusal before an
    external call (for example, a zero-spend policy).  It is different from a
    zero-valued known provider invoice and from an unknown provider cost.
    """

    KNOWN = "known"
    UNKNOWN = "unknown"
    NOT_INCURRED = "not_incurred"


class AggregationPeriod(StrEnum):
    """UTC periods supported by the local dashboard."""

    HOUR = "hour"
    DAY = "day"
    WEEK = "week"
    MONTH = "month"


@dataclass(frozen=True, slots=True)
class UsageEvent:
    """A safe, content-free execution record returned by the ledger."""

    id: str
    provider: str
    model: str
    mode: str
    task_kind: str
    outcome: UsageOutcome
    occurred_at: str
    recorded_at: str
    latency_ms: int | None
    input_tokens: int | None
    output_tokens: int | None
    total_tokens: int | None
    cache_state: CacheState
    retry_count: int | None
    error_category: str | None
    fallback_state: FallbackState
    verification_state: VerificationState
    cost_state: CostState
    cost_amount: str | None
    cost_currency: str | None
    zero_spend_refused: bool

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-ready event with no prompt or raw error content."""

        data = asdict(self)
        data["outcome"] = self.outcome.value
        data["cache_state"] = self.cache_state.value
        data["fallback_state"] = self.fallback_state.value
        data["verification_state"] = self.verification_state.value
        data["cost_state"] = self.cost_state.value
        return data


# The ledger accepts only compact identifier-like labels.  This is more robust
# than attempting to redact arbitrary prompt text after it has reached SQLite.
_TAG_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/@+\-]{0,127}$")
_CURRENCY_PATTERN = re.compile(r"^[A-Za-z][A-Za-z0-9_\-]{0,11}$")
_SECRET_PATTERNS = (
    re.compile(r"\bAQ\.[0-9A-Za-z_-]{20,}"),
    re.compile(r"\bsk-or-v1-[0-9A-Za-z_-]{24,}"),
    re.compile(r"\bAIza[0-9A-Za-z_-]{20,}\b"),
    re.compile(r"\b(?:sk|rk|pk)_[A-Za-z0-9_-]{16,}\b", re.IGNORECASE),
    re.compile(
        r"\b(?:authorization|bearer|api[ _-]?key|token|password|secret)\s*"
        r"(?:[:=]\s*|\s+)(?:Bearer\s+)?[A-Za-z0-9_./+=-]{8,}",
        re.IGNORECASE,
    ),
)


def redact_text(value: object, *, limit: int = MAX_TAG_LENGTH) -> str:
    """Redact common credential shapes without retaining a long raw value.

    The function is public mostly for callers that need to display a safe
    validation message.  The ledger itself only persists compact tags, never
    arbitrary text or prompts.
    """

    text = str(value)
    for pattern in _SECRET_PATTERNS:
        text = pattern.sub("[redacted]", text)
    text = " ".join(text.split())
    if len(text) > limit:
        return text[: max(0, limit - 1)] + "…"
    return text


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _timestamp(value: datetime | str | None, *, label: str, default_now: bool = False) -> datetime:
    if value is None:
        if default_now:
            return _utc_now()
        raise UsageLedgerError(f"{label} doit être fourni avec un fuseau horaire UTC.")
    if isinstance(value, str):
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError as error:
            raise UsageLedgerError(f"{label} doit être une date ISO 8601 valide.") from error
    elif isinstance(value, datetime):
        parsed = value
    else:
        raise UsageLedgerError(f"{label} doit être une date ISO 8601 valide.")
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise UsageLedgerError(f"{label} doit inclure un fuseau horaire.")
    return parsed.astimezone(timezone.utc)


def _format_timestamp(value: datetime) -> str:
    """Canonical UTC timestamps sort correctly as text in SQLite."""

    return value.astimezone(timezone.utc).isoformat(timespec="milliseconds")


def _coerce_enum(enum_type: type[StrEnum], value: StrEnum | str, label: str) -> StrEnum:
    try:
        return enum_type(value)
    except (TypeError, ValueError) as error:
        allowed = ", ".join(item.value for item in enum_type)
        raise UsageLedgerError(f"{label} invalide. Valeurs autorisées : {allowed}.") from error


def _safe_tag(value: object, *, label: str, allow_none: bool = False) -> str | None:
    """Return a fixed-format tag, replacing detected credentials safely.

    Tags intentionally do not accept whitespace, JSON, or free-form text, so
    a caller cannot accidentally record a user prompt as a task label.
    """

    if value is None:
        if allow_none:
            return None
        raise UsageLedgerError(f"{label} est obligatoire.")
    if not isinstance(value, str):
        raise UsageLedgerError(f"{label} doit être un identifiant texte compact.")
    raw = value.strip()
    if not raw:
        raise UsageLedgerError(f"{label} est obligatoire.")
    safe = redact_text(raw, limit=MAX_TAG_LENGTH)
    if "[redacted]" in safe:
        return "redacted"
    if not _TAG_PATTERN.fullmatch(safe):
        raise UsageLedgerError(
            f"{label} doit être un identifiant compact sans espace ni contenu libre."
        )
    return safe


def _currency(value: object) -> str:
    if not isinstance(value, str):
        raise UsageLedgerError("La devise doit être un code texte compact.")
    candidate = value.strip().upper()
    if not _CURRENCY_PATTERN.fullmatch(candidate):
        raise UsageLedgerError("La devise doit être un code texte compact.")
    return candidate


def _optional_non_negative_int(value: object, *, label: str) -> int | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int):
        raise UsageLedgerError(f"{label} doit être un entier positif ou nul, ou inconnu.")
    if value < 0 or value > MAX_INTEGER_MEASUREMENT:
        raise UsageLedgerError(f"{label} est hors de la plage locale autorisée.")
    return value


def _decimal_cost(value: object) -> Decimal:
    if isinstance(value, bool):
        raise UsageLedgerError("Le coût doit être un nombre positif ou nul.")
    try:
        parsed = Decimal(str(value))
    except (InvalidOperation, ValueError) as error:
        raise UsageLedgerError("Le coût doit être un nombre valide.") from error
    if not parsed.is_finite() or parsed < 0:
        raise UsageLedgerError("Le coût doit être un nombre positif ou nul.")
    # A cost with thousands of fractional digits cannot be meaningful in the
    # dashboard and is needlessly expensive to carry through SQLite exports.
    if len(parsed.as_tuple().digits) > 28:
        raise UsageLedgerError("Le coût a une précision excessive.")
    return parsed


def _format_decimal(value: Decimal) -> str:
    """A non-exponential stable representation suitable for SQLite/CSV."""

    rendered = format(value, "f")
    if "." in rendered:
        rendered = rendered.rstrip("0").rstrip(".")
    return rendered or "0"


def _metric_summary(values: Sequence[int], *, event_count: int) -> dict[str, Any]:
    """Describe coverage before presenting any partial numeric aggregate."""

    measured_count = len(values)
    unknown_count = event_count - measured_count
    if event_count == 0:
        state = "not_recorded"
    elif measured_count == 0:
        state = "unknown"
    elif unknown_count == 0:
        state = "measured"
    else:
        state = "partial"
    return {
        "state": state,
        "measured_count": measured_count,
        "unknown_count": unknown_count,
        "complete": event_count > 0 and unknown_count == 0,
        # These are explicitly sums of measured values, never invented totals.
        "measured_sum": sum(values) if values else None,
        "measured_average": (sum(values) / measured_count) if measured_count else None,
        "measured_min": min(values) if values else None,
        "measured_max": max(values) if values else None,
    }


def _cost_summary(events: Sequence[UsageEvent]) -> dict[str, Any]:
    known: list[UsageEvent] = [event for event in events if event.cost_state is CostState.KNOWN]
    unknown_count = sum(event.cost_state is CostState.UNKNOWN for event in events)
    not_incurred_count = sum(event.cost_state is CostState.NOT_INCURRED for event in events)
    if not events:
        state = "not_recorded"
    elif not known and unknown_count:
        state = "unknown"
    elif known and unknown_count:
        state = "partial"
    elif known:
        state = "measured"
    else:
        state = "not_incurred"

    grouped: dict[str, Decimal] = defaultdict(Decimal)
    per_currency_count: Counter[str] = Counter()
    for event in known:
        # Constructor invariants guarantee both fields for known costs.
        assert event.cost_amount is not None and event.cost_currency is not None
        grouped[event.cost_currency] += Decimal(event.cost_amount)
        per_currency_count[event.cost_currency] += 1

    return {
        "state": state,
        "known_count": len(known),
        "unknown_count": unknown_count,
        "not_incurred_count": not_incurred_count,
        "complete_for_chargeable_events": bool(events) and unknown_count == 0,
        # Deliberately no cross-currency grand total.
        "by_currency": [
            {
                "currency": currency,
                "measured_sum": _format_decimal(grouped[currency]),
                "event_count": per_currency_count[currency],
                "has_unknown_cost_events": unknown_count > 0,
            }
            for currency in sorted(grouped)
        ],
    }


def _events_summary(events: Sequence[UsageEvent]) -> dict[str, Any]:
    """Create an honest, JSON-ready summary without guessing missing facts."""

    event_count = len(events)
    outcomes = Counter(event.outcome.value for event in events)
    errors = Counter(event.error_category for event in events if event.error_category)
    return {
        "event_count": event_count,
        "outcomes": {outcome.value: outcomes[outcome.value] for outcome in UsageOutcome},
        "latency_ms": _metric_summary(
            [event.latency_ms for event in events if event.latency_ms is not None],
            event_count=event_count,
        ),
        "input_tokens": _metric_summary(
            [event.input_tokens for event in events if event.input_tokens is not None],
            event_count=event_count,
        ),
        "output_tokens": _metric_summary(
            [event.output_tokens for event in events if event.output_tokens is not None],
            event_count=event_count,
        ),
        "total_tokens": _metric_summary(
            [event.total_tokens for event in events if event.total_tokens is not None],
            event_count=event_count,
        ),
        "retry_count": _metric_summary(
            [event.retry_count for event in events if event.retry_count is not None],
            event_count=event_count,
        ),
        "cache": {state.value: sum(event.cache_state is state for event in events) for state in CacheState},
        "fallback": {
            state.value: sum(event.fallback_state is state for event in events)
            for state in FallbackState
        },
        "verification": {
            state.value: sum(event.verification_state is state for event in events)
            for state in VerificationState
        },
        "errors": {
            "event_count": sum(1 for event in events if event.error_category is not None),
            "by_category": {key: errors[key] for key in sorted(errors)},
        },
        "zero_spend_refusal_count": sum(event.zero_spend_refused for event in events),
        "cost": _cost_summary(events),
    }


class UsageLedger:
    """Bounded SQLite ledger for actual, caller-declared execution facts.

    ``database_path`` is explicit by design.  The class neither reads an
    environment variable nor discovers provider configuration.  ``max_events``
    caps persistent history by retaining the newest events; aggregates always
    state their measurement coverage so retention cannot create fake totals.
    """

    def __init__(self, database_path: str | Path, *, max_events: int = DEFAULT_MAX_EVENTS) -> None:
        path = Path(database_path).expanduser()
        if path.exists() and path.is_dir():
            raise UsageLedgerError("Le chemin du journal d’utilisation désigne un dossier.")
        if isinstance(max_events, bool) or not isinstance(max_events, int) or max_events < 1:
            raise UsageLedgerError("La rétention doit être un entier positif.")
        if max_events > 1_000_000:
            raise UsageLedgerError("La rétention demandée est trop grande pour ce journal local.")

        self.database_path = path.resolve()
        self.max_events = max_events
        parent_existed = self.database_path.parent.exists()
        self.database_path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        if not parent_existed:
            try:
                os.chmod(self.database_path.parent, 0o700)
            except OSError:
                pass
        existed = self.database_path.exists()
        self._initialise()
        if not existed:
            try:
                os.chmod(self.database_path, 0o600)
            except OSError:
                pass

    def _connect(self) -> sqlite3.Connection:
        try:
            connection = sqlite3.connect(str(self.database_path), timeout=5.0, isolation_level=None)
        except sqlite3.Error as error:
            raise UsageLedgerError("Le journal local n’est pas accessible.") from error
        connection.row_factory = sqlite3.Row
        try:
            connection.execute("PRAGMA busy_timeout = 5000")
        except sqlite3.Error as error:
            connection.close()
            raise UsageLedgerError("Le journal local n’est pas accessible.") from error
        return connection

    def _initialise(self) -> None:
        outcomes = ", ".join(repr(item.value) for item in UsageOutcome)
        caches = ", ".join(repr(item.value) for item in CacheState)
        fallbacks = ", ".join(repr(item.value) for item in FallbackState)
        verifications = ", ".join(repr(item.value) for item in VerificationState)
        costs = ", ".join(repr(item.value) for item in CostState)
        connection = self._connect()
        try:
            # WAL keeps dashboard reads responsive while an execution finishes.
            connection.execute("PRAGMA journal_mode = WAL")
            connection.execute("PRAGMA synchronous = NORMAL")
            connection.executescript(
                f"""
                CREATE TABLE IF NOT EXISTS usage_ledger_events (
                    id TEXT PRIMARY KEY,
                    provider TEXT NOT NULL,
                    model TEXT NOT NULL,
                    mode TEXT NOT NULL,
                    task_kind TEXT NOT NULL,
                    outcome TEXT NOT NULL CHECK (outcome IN ({outcomes})),
                    occurred_at TEXT NOT NULL,
                    recorded_at TEXT NOT NULL,
                    latency_ms INTEGER,
                    input_tokens INTEGER,
                    output_tokens INTEGER,
                    total_tokens INTEGER,
                    cache_state TEXT NOT NULL CHECK (cache_state IN ({caches})),
                    retry_count INTEGER,
                    error_category TEXT,
                    fallback_state TEXT NOT NULL CHECK (fallback_state IN ({fallbacks})),
                    verification_state TEXT NOT NULL
                        CHECK (verification_state IN ({verifications})),
                    cost_state TEXT NOT NULL CHECK (cost_state IN ({costs})),
                    cost_amount TEXT,
                    cost_currency TEXT,
                    zero_spend_refused INTEGER NOT NULL DEFAULT 0
                        CHECK (zero_spend_refused IN (0, 1)),
                    CHECK (
                        (cost_state = 'known' AND cost_amount IS NOT NULL AND cost_currency IS NOT NULL)
                        OR
                        (cost_state != 'known' AND cost_amount IS NULL AND cost_currency IS NULL)
                    )
                );

                CREATE INDEX IF NOT EXISTS usage_ledger_occurred_idx
                    ON usage_ledger_events(occurred_at DESC, recorded_at DESC, id DESC);
                CREATE INDEX IF NOT EXISTS usage_ledger_provider_idx
                    ON usage_ledger_events(provider, model, occurred_at DESC);
                CREATE INDEX IF NOT EXISTS usage_ledger_task_idx
                    ON usage_ledger_events(task_kind, occurred_at DESC);
                """
            )
        except sqlite3.Error as error:
            raise UsageLedgerError("Le journal local ne peut pas être initialisé.") from error
        finally:
            connection.close()

    @contextmanager
    def _read_connection(self) -> Iterator[sqlite3.Connection]:
        connection = self._connect()
        try:
            yield connection
        finally:
            connection.close()

    @contextmanager
    def _transaction(self) -> Iterator[sqlite3.Connection]:
        connection = self._connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            yield connection
        except BaseException:
            connection.rollback()
            raise
        else:
            connection.commit()
        finally:
            connection.close()

    @staticmethod
    def _event_from_row(row: sqlite3.Row) -> UsageEvent:
        try:
            return UsageEvent(
                id=row["id"],
                provider=row["provider"],
                model=row["model"],
                mode=row["mode"],
                task_kind=row["task_kind"],
                outcome=UsageOutcome(row["outcome"]),
                occurred_at=row["occurred_at"],
                recorded_at=row["recorded_at"],
                latency_ms=row["latency_ms"],
                input_tokens=row["input_tokens"],
                output_tokens=row["output_tokens"],
                total_tokens=row["total_tokens"],
                cache_state=CacheState(row["cache_state"]),
                retry_count=row["retry_count"],
                error_category=row["error_category"],
                fallback_state=FallbackState(row["fallback_state"]),
                verification_state=VerificationState(row["verification_state"]),
                cost_state=CostState(row["cost_state"]),
                cost_amount=row["cost_amount"],
                cost_currency=row["cost_currency"],
                zero_spend_refused=bool(row["zero_spend_refused"]),
            )
        except (KeyError, TypeError, ValueError) as error:
            raise UsageLedgerError("Le journal local contient un événement illisible.") from error

    @staticmethod
    def _validate_window(
        start_at: datetime | str | None,
        end_at: datetime | str | None,
    ) -> tuple[str | None, str | None]:
        start = _timestamp(start_at, label="La date de début") if start_at is not None else None
        end = _timestamp(end_at, label="La date de fin") if end_at is not None else None
        if start is not None and end is not None and start > end:
            raise UsageLedgerError("La date de début doit précéder la date de fin.")
        return (
            _format_timestamp(start) if start is not None else None,
            _format_timestamp(end) if end is not None else None,
        )

    def record_execution(
        self,
        *,
        provider: str,
        model: str,
        mode: str,
        task_kind: str,
        outcome: UsageOutcome | str = UsageOutcome.SUCCEEDED,
        occurred_at: datetime | str | None = None,
        latency_ms: int | None = None,
        input_tokens: int | None = None,
        output_tokens: int | None = None,
        total_tokens: int | None = None,
        cache_state: CacheState | str = CacheState.UNKNOWN,
        retry_count: int | None = None,
        error_category: str | None = None,
        fallback_state: FallbackState | str = FallbackState.UNKNOWN,
        verification_state: VerificationState | str = VerificationState.UNKNOWN,
        cost: Decimal | int | float | str | None = None,
        cost_currency: str | None = None,
        zero_spend_refused: bool = False,
    ) -> UsageEvent:
        """Persist one actual execution result, never an inferred one.

        Every numerical argument is optional.  Leave a value as ``None`` when
        the provider/runtime did not explicitly report it; the dashboard will
        then label the associated aggregate as unknown or partial.  The method
        has no provider side effect and does not derive prices from tokens.
        """

        provider_tag = _safe_tag(provider, label="Le fournisseur")
        model_tag = _safe_tag(model, label="Le modèle")
        mode_tag = _safe_tag(mode, label="Le mode")
        task_tag = _safe_tag(task_kind, label="Le type de tâche")
        error_tag = _safe_tag(error_category, label="La catégorie d’erreur", allow_none=True)
        event_outcome = _coerce_enum(UsageOutcome, outcome, "Le résultat")
        cache = _coerce_enum(CacheState, cache_state, "L’état du cache")
        fallback = _coerce_enum(FallbackState, fallback_state, "L’état du fallback")
        verification = _coerce_enum(VerificationState, verification_state, "L’état de vérification")
        event_time = _timestamp(occurred_at, label="La date de l’événement", default_now=True)
        recorded_time = _utc_now()

        safe_latency = _optional_non_negative_int(latency_ms, label="La latence")
        safe_input = _optional_non_negative_int(input_tokens, label="Les tokens d’entrée")
        safe_output = _optional_non_negative_int(output_tokens, label="Les tokens de sortie")
        safe_total = _optional_non_negative_int(total_tokens, label="Les tokens totaux")
        safe_retries = _optional_non_negative_int(retry_count, label="Le nombre de réessais")
        if safe_retries is not None and safe_retries > 10_000:
            raise UsageLedgerError("Le nombre de réessais est hors de la plage locale autorisée.")

        if not isinstance(zero_spend_refused, bool):
            raise UsageLedgerError("L’indicateur zero-spend doit être booléen.")
        if zero_spend_refused and event_outcome is not UsageOutcome.REFUSED:
            raise UsageLedgerError("Un refus zero-spend doit avoir le résultat 'refused'.")

        if cost is not None:
            if zero_spend_refused:
                raise UsageLedgerError("Un refus zero-spend ne peut pas déclarer de coût fournisseur.")
            if cost_currency is None:
                raise UsageLedgerError("Une devise est obligatoire lorsqu’un coût est déclaré.")
            cost_state = CostState.KNOWN
            cost_amount = _format_decimal(_decimal_cost(cost))
            currency = _currency(cost_currency)
        elif zero_spend_refused:
            if cost_currency is not None:
                raise UsageLedgerError("Un refus zero-spend ne doit pas déclarer de devise de coût.")
            cost_state = CostState.NOT_INCURRED
            cost_amount = None
            currency = None
        else:
            if cost_currency is not None:
                raise UsageLedgerError("Une devise sans coût déclaré n’est pas exploitable.")
            cost_state = CostState.UNKNOWN
            cost_amount = None
            currency = None

        event = UsageEvent(
            id=uuid.uuid4().hex,
            provider=provider_tag or "redacted",
            model=model_tag or "redacted",
            mode=mode_tag or "redacted",
            task_kind=task_tag or "redacted",
            outcome=event_outcome,  # type: ignore[arg-type]
            occurred_at=_format_timestamp(event_time),
            recorded_at=_format_timestamp(recorded_time),
            latency_ms=safe_latency,
            input_tokens=safe_input,
            output_tokens=safe_output,
            total_tokens=safe_total,
            cache_state=cache,  # type: ignore[arg-type]
            retry_count=safe_retries,
            error_category=error_tag,
            fallback_state=fallback,  # type: ignore[arg-type]
            verification_state=verification,  # type: ignore[arg-type]
            cost_state=cost_state,
            cost_amount=cost_amount,
            cost_currency=currency,
            zero_spend_refused=zero_spend_refused,
        )
        self._insert(event)
        return event

    def record_zero_spend_refusal(
        self,
        *,
        provider: str,
        model: str,
        mode: str,
        task_kind: str,
        error_category: str = "zero_spend_policy",
        occurred_at: datetime | str | None = None,
        verification_state: VerificationState | str = VerificationState.NOT_VERIFIED,
    ) -> UsageEvent:
        """Record a deterministic policy refusal before any external spend.

        This makes the refusal observable while preserving the distinction
        between "no call was made" and a priced provider operation worth zero.
        """

        return self.record_execution(
            provider=provider,
            model=model,
            mode=mode,
            task_kind=task_kind,
            outcome=UsageOutcome.REFUSED,
            occurred_at=occurred_at,
            error_category=error_category,
            verification_state=verification_state,
            zero_spend_refused=True,
        )

    def _insert(self, event: UsageEvent) -> None:
        try:
            with self._transaction() as connection:
                connection.execute(
                    """
                    INSERT INTO usage_ledger_events (
                        id, provider, model, mode, task_kind, outcome,
                        occurred_at, recorded_at, latency_ms, input_tokens,
                        output_tokens, total_tokens, cache_state, retry_count,
                        error_category, fallback_state, verification_state,
                        cost_state, cost_amount, cost_currency, zero_spend_refused
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        event.id,
                        event.provider,
                        event.model,
                        event.mode,
                        event.task_kind,
                        event.outcome.value,
                        event.occurred_at,
                        event.recorded_at,
                        event.latency_ms,
                        event.input_tokens,
                        event.output_tokens,
                        event.total_tokens,
                        event.cache_state.value,
                        event.retry_count,
                        event.error_category,
                        event.fallback_state.value,
                        event.verification_state.value,
                        event.cost_state.value,
                        event.cost_amount,
                        event.cost_currency,
                        int(event.zero_spend_refused),
                    ),
                )
                # Retention is an explicit bounded-storage policy, not a
                # replacement for a user-controlled archival/export workflow.
                connection.execute(
                    """
                    DELETE FROM usage_ledger_events
                    WHERE id NOT IN (
                        SELECT id
                        FROM usage_ledger_events
                        ORDER BY occurred_at DESC, recorded_at DESC, id DESC
                        LIMIT ?
                    )
                    """,
                    (self.max_events,),
                )
        except sqlite3.Error as error:
            raise UsageLedgerError("Impossible d’écrire dans le journal local.") from error

    def list_events(
        self,
        *,
        limit: int = DEFAULT_LIST_LIMIT,
        start_at: datetime | str | None = None,
        end_at: datetime | str | None = None,
    ) -> tuple[UsageEvent, ...]:
        """Return recent metadata-only events, newest first."""

        if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= MAX_LIST_LIMIT:
            raise UsageLedgerError(f"La limite doit être comprise entre 1 et {MAX_LIST_LIMIT}.")
        start, end = self._validate_window(start_at, end_at)
        clauses: list[str] = []
        params: list[object] = []
        if start is not None:
            clauses.append("occurred_at >= ?")
            params.append(start)
        if end is not None:
            clauses.append("occurred_at <= ?")
            params.append(end)
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        params.append(limit)
        try:
            with self._read_connection() as connection:
                rows = connection.execute(
                    f"""
                    SELECT * FROM usage_ledger_events
                    {where}
                    ORDER BY occurred_at DESC, recorded_at DESC, id DESC
                    LIMIT ?
                    """,
                    params,
                ).fetchall()
        except sqlite3.Error as error:
            raise UsageLedgerError("Impossible de lire le journal local.") from error
        return tuple(self._event_from_row(row) for row in rows)

    def _all_events(
        self,
        *,
        start_at: datetime | str | None = None,
        end_at: datetime | str | None = None,
    ) -> tuple[UsageEvent, ...]:
        start, end = self._validate_window(start_at, end_at)
        clauses: list[str] = []
        params: list[object] = []
        if start is not None:
            clauses.append("occurred_at >= ?")
            params.append(start)
        if end is not None:
            clauses.append("occurred_at <= ?")
            params.append(end)
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        try:
            with self._read_connection() as connection:
                rows = connection.execute(
                    f"""
                    SELECT * FROM usage_ledger_events
                    {where}
                    ORDER BY occurred_at ASC, recorded_at ASC, id ASC
                    """,
                    params,
                ).fetchall()
        except sqlite3.Error as error:
            raise UsageLedgerError("Impossible de lire le journal local.") from error
        return tuple(self._event_from_row(row) for row in rows)

    @staticmethod
    def _bucket_start(timestamp: str, period: AggregationPeriod) -> datetime:
        value = _timestamp(timestamp, label="La date enregistrée")
        if period is AggregationPeriod.HOUR:
            return value.replace(minute=0, second=0, microsecond=0)
        if period is AggregationPeriod.DAY:
            return value.replace(hour=0, minute=0, second=0, microsecond=0)
        if period is AggregationPeriod.WEEK:
            day = value.replace(hour=0, minute=0, second=0, microsecond=0)
            return day - timedelta(days=day.weekday())
        return value.replace(day=1, hour=0, minute=0, second=0, microsecond=0)

    def aggregate(
        self,
        period: AggregationPeriod | str,
        *,
        start_at: datetime | str | None = None,
        end_at: datetime | str | None = None,
        max_buckets: int = DEFAULT_MAX_BUCKETS,
    ) -> list[dict[str, Any]]:
        """Return chronological UTC buckets with coverage-aware summaries.

        ``max_buckets`` keeps a dashboard request bounded.  If there are more
        historical buckets, the newest ones are retained and the response says
        that it is truncated instead of claiming a complete all-time chart.
        """

        bucket_period = _coerce_enum(AggregationPeriod, period, "La période")
        if (
            isinstance(max_buckets, bool)
            or not isinstance(max_buckets, int)
            or not 1 <= max_buckets <= MAX_BUCKETS
        ):
            raise UsageLedgerError(f"Le nombre de périodes doit être compris entre 1 et {MAX_BUCKETS}.")
        events = self._all_events(start_at=start_at, end_at=end_at)
        buckets: dict[datetime, list[UsageEvent]] = defaultdict(list)
        for event in events:
            buckets[self._bucket_start(event.occurred_at, bucket_period)].append(event)
        ordered = sorted(buckets)
        truncated = len(ordered) > max_buckets
        if truncated:
            ordered = ordered[-max_buckets:]
        return [
            {
                "period": bucket_period.value,
                "start_at": _format_timestamp(start),
                "event_count": len(buckets[start]),
                "summary": _events_summary(buckets[start]),
                "truncated_history": truncated,
            }
            for start in ordered
        ]

    def aggregate_hourly(self, **kwargs: Any) -> list[dict[str, Any]]:
        """Convenience wrapper for :meth:`aggregate` with hour buckets."""

        return self.aggregate(AggregationPeriod.HOUR, **kwargs)

    def aggregate_daily(self, **kwargs: Any) -> list[dict[str, Any]]:
        """Convenience wrapper for :meth:`aggregate` with day buckets."""

        return self.aggregate(AggregationPeriod.DAY, **kwargs)

    def aggregate_weekly(self, **kwargs: Any) -> list[dict[str, Any]]:
        """Convenience wrapper for :meth:`aggregate` with ISO Monday buckets."""

        return self.aggregate(AggregationPeriod.WEEK, **kwargs)

    def aggregate_monthly(self, **kwargs: Any) -> list[dict[str, Any]]:
        """Convenience wrapper for :meth:`aggregate` with month buckets."""

        return self.aggregate(AggregationPeriod.MONTH, **kwargs)

    def dashboard_summary(self, *, now: datetime | str | None = None) -> dict[str, Any]:
        """Return a content-free dashboard snapshot and recent-window facts."""

        instant = _timestamp(now, label="La date du tableau", default_now=True)
        all_events = self._all_events()
        windows = {
            "last_hour": timedelta(hours=1),
            "last_day": timedelta(days=1),
            "last_week": timedelta(days=7),
            "last_month": timedelta(days=30),
        }
        window_summaries = {
            name: _events_summary(
                [
                    event
                    for event in all_events
                    if _timestamp(event.occurred_at, label="La date enregistrée") >= instant - duration
                    and _timestamp(event.occurred_at, label="La date enregistrée") <= instant
                ]
            )
            for name, duration in windows.items()
        }
        latest = all_events[-1].occurred_at if all_events else None
        try:
            database_bytes = self.database_path.stat().st_size
        except OSError:
            database_bytes = None
        return {
            "generated_at": _format_timestamp(instant),
            "retention": {"max_events": self.max_events, "current_events": len(all_events)},
            "database": {"status": "ready", "file_bytes": database_bytes, "journal_mode": "wal"},
            "latest_event_at": latest,
            "all_time": _events_summary(all_events),
            "windows": window_summaries,
        }

    def export_csv(
        self,
        destination: str | Path,
        *,
        start_at: datetime | str | None = None,
        end_at: datetime | str | None = None,
        overwrite: bool = False,
    ) -> dict[str, Any]:
        """Export metadata-only events to a local CSV.

        The method intentionally excludes prompt/document/error-message text
        because none is needed to understand usage.  Existing files are never
        overwritten unless the caller explicitly chooses ``overwrite=True``.
        """

        if not isinstance(overwrite, bool):
            raise UsageLedgerError("L’option d’écrasement doit être booléenne.")
        path = Path(destination).expanduser()
        if path.name in {"", ".", ".."} or path.suffix.lower() != ".csv":
            raise UsageLedgerError("L’export doit cibler un fichier .csv explicite.")
        if path.exists() and (path.is_symlink() or not path.is_file()):
            raise UsageLedgerError("La destination CSV n’est pas un fichier local ordinaire.")
        if path.exists() and not overwrite:
            raise UsageLedgerError("Le fichier CSV existe déjà ; active l’écrasement explicitement.")
        path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        events = self._all_events(start_at=start_at, end_at=end_at)
        fields = (
            "id",
            "occurred_at",
            "recorded_at",
            "provider",
            "model",
            "mode",
            "task_kind",
            "outcome",
            "latency_ms",
            "input_tokens",
            "output_tokens",
            "total_tokens",
            "cache_state",
            "retry_count",
            "error_category",
            "fallback_state",
            "verification_state",
            "cost_state",
            "cost_amount",
            "cost_currency",
            "zero_spend_refused",
        )
        # ``newline=""`` is required by csv on macOS as well as Windows.
        try:
            with path.open("w", encoding="utf-8", newline="") as handle:
                writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
                writer.writeheader()
                for event in events:
                    writer.writerow(event.to_dict())
        except OSError as error:
            raise UsageLedgerError("Impossible d’écrire l’export CSV local.") from error
        try:
            os.chmod(path, 0o600)
        except OSError:
            pass
        return {
            "status": "ready",
            "event_count": len(events),
            "filename": path.name,
            "bytes": path.stat().st_size if path.exists() else None,
            "contains_prompt_content": False,
            "contains_raw_error_messages": False,
        }


__all__ = [
    "AggregationPeriod",
    "CacheState",
    "CostState",
    "DEFAULT_MAX_EVENTS",
    "FallbackState",
    "UsageEvent",
    "UsageLedger",
    "UsageLedgerError",
    "UsageOutcome",
    "VerificationState",
    "redact_text",
]
