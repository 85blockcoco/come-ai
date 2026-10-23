"""Exact coverage and health metrics for one Career Explorer run (SK-04).

The explorer reads public sources, qualifies the announcements it finds and
imports the qualified ones into the local Career database.  This module
measures *what actually happened* for one run.  It never estimates a missing
fact, never samples and never extrapolates.

Two rules drive the whole design.

1. **Synthetic and live data never share a counter.**  Every source and every
   announcement belongs to exactly one bucket (``synthetic`` or ``live``).
   The bundled synthetic fixtures are a demonstration dataset: they are never
   allowed to inflate a counter presented as a measure of the real search.
2. **Every number is recalculable from raw data.**  A metric is only
   published when it can be recomputed from the run snapshot (the per-source
   outcomes) and from the announcements of the run (source facts and the
   recorded qualification verdict).  Nothing is inferred from a missing field.

Coherence rules enforced by :func:`compute_coverage`:

- ``sources_succeeded + sources_cached + sources_failed == sources_queried``
- ``sources_queried <= sources_planned``
- ``offers_post_dedup <= offers_pre_dedup``
- ``compliant + to_verify + non_compliant == valid_offers``
- ``raw_offers >= valid_offers``
- a source that answers with HTTP 200 but returns no valid announcement is
  counted as *consulted* and *failed*, never as *succeeded*.

Determinism: no clock and no random source is read here.  ``computed_at`` is
the timestamp of the measured run, not the time of the measurement, so two
calls on the same run always return the same report.

Public API:

- ``compute_metrics(run_id)`` — the measured run, bound to a loader.
- ``compute_coverage(payload)`` — the pure, deterministic core.
- ``CareerDatabaseLoader`` — reads the last explorer run of the local Career
  database (jobs + recorded qualification snapshots).
- ``synthetic_fixture_payload()`` — the bundled synthetic dataset, measured
  apart from the live search.
"""

from __future__ import annotations

import json
import sqlite3
from dataclasses import asdict, dataclass, field
from datetime import date
from pathlib import Path
from typing import Any, Literal, Mapping, Protocol, Sequence

from workspace_core import UserFacingError

from .exploration import EXPLORATION_LAST_SETTING
from .models import canonical_url, clean_text, normalized_text
from .qualification_persistence import decode_qualification_snapshot


COVERAGE_SCHEMA = "come-career-source-coverage/1"

Bucket = Literal["synthetic", "live"]
BUCKETS: tuple[Bucket, ...] = ("synthetic", "live")

# Source statuses written by the explorer (see career/service.py).
STATUS_SUCCESS = "success"
STATUS_PARTIAL = "partial"
STATUS_CACHED = "cached"
STATUS_ERROR = "error"
STATUS_NOT_QUERIED = "not_queried"
STATUS_UNSUPPORTED = "unsupported"
CONSULTED_STATUSES = frozenset({STATUS_SUCCESS, STATUS_PARTIAL, STATUS_CACHED, STATUS_ERROR})

# Qualification verdicts recorded for an offer.
TARGET_CONFORMING = "conforming"
TARGET_TO_VERIFY = "to_verify"
TARGET_NON_CONFORMING = "non_conforming"
TARGET_STATUSES = (TARGET_CONFORMING, TARGET_TO_VERIFY, TARGET_NON_CONFORMING)

# An identifier carrying one of these markers is synthetic by construction.
SYNTHETIC_MARKERS = frozenset({
    "synthetic", "synthetique", "demo", "demonstration", "sample", "fixture",
    "mock", "fake", "faux", "dummy", "placeholder", "stub", "simulated", "simule",
})

# A source that cannot be attributed to a public feed is neither synthetic nor
# live: it is reported apart instead of silently inflating a counter.
UNATTRIBUTED_SOURCE_NAMES = frozenset({
    "", "manual", "import manuel", "import_manual", "unknown", "inconnu",
})

# The synthetic fixtures carry no deadline; the reference date keeps the
# measurement stable over time.
SYNTHETIC_FIXTURE_AS_OF = date(2026, 1, 1)

# Batch size for the ``IN`` clause of the offer query.
_QUERY_BATCH = 400


class CoverageError(RuntimeError):
    """Base error of the source coverage module."""


class CoverageRunNotFound(CoverageError):
    """The requested run cannot be measured from the available data."""


@dataclass(frozen=True)
class CoverageMetrics:
    """Nineteen measures of one bucket (one synthetic *or* live dataset)."""

    sources_planned: int = 0
    sources_queried: int = 0
    sources_succeeded: int = 0
    sources_cached: int = 0
    sources_failed: int = 0
    unique_employers: int = 0
    raw_offers: int = 0
    valid_offers: int = 0
    offers_pre_dedup: int = 0
    offers_post_dedup: int = 0
    offers_verified_url: int = 0
    offers_with_location: int = 0
    offers_with_published_date: int = 0
    offers_with_start_date: int = 0
    offers_with_duration: int = 0
    offers_with_requirements: int = 0
    compliant: int = 0
    to_verify: int = 0
    non_compliant: int = 0

    def to_dict(self) -> dict[str, int]:
        return dict(asdict(self))


@dataclass(frozen=True)
class CoverageReport:
    """The measurement of one run, with synthetic and live kept apart."""

    run_id: str
    metrics: dict[Bucket, CoverageMetrics]
    computed_at: str = ""
    coherence: dict[str, Any] = field(default_factory=dict)
    run_summary: dict[str, Any] = field(default_factory=dict)
    unattributed: dict[str, int] = field(default_factory=dict)
    notes: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": COVERAGE_SCHEMA,
            "run_id": self.run_id,
            "computed_at": self.computed_at,
            "metrics": {bucket: self.metrics[bucket].to_dict() for bucket in BUCKETS},
            "coherence": dict(self.coherence),
            "run_summary": dict(self.run_summary),
            "unattributed": dict(self.unattributed),
            "notes": list(self.notes),
        }


@dataclass(frozen=True)
class CoveragePayload:
    """Raw material of a measurement: source outcomes and announcements."""

    run_id: str
    sources: tuple[Mapping[str, Any], ...] = ()
    offers: tuple[Mapping[str, Any], ...] = ()
    summary: Mapping[str, Any] = field(default_factory=dict)
    computed_at: str = ""
    synthetic_source_ids: frozenset[str] = frozenset()


class CoverageLoader(Protocol):
    """Anything able to return the raw material of one run."""

    def load(self, run_id: str) -> CoveragePayload:  # pragma: no cover - protocol
        ...


# --------------------------------------------------------------------------
# Small helpers
# --------------------------------------------------------------------------


def _lower(value: Any) -> str:
    """Lowercase a value without touching its separators."""
    return clean_text(value, limit=200).strip().lower()


def _as_int(value: Any) -> int:
    if isinstance(value, bool):
        return 0
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    if isinstance(value, str):
        try:
            return int(value.strip())
        except ValueError:
            return 0
    return 0


def _present(value: Any) -> bool:
    """True when a recorded field carries a fact."""
    if value is None:
        return False
    if isinstance(value, str):
        return bool(value.strip())
    if isinstance(value, (list, tuple, set, dict)):
        return bool(value)
    return True


def _tokens(value: Any) -> set[str]:
    return {token for token in normalized_text(value).split(" ") if token}


def is_synthetic_source(*values: Any) -> bool:
    """Return True when an identifier carries an explicit synthetic marker.

    Only the source identity is inspected: a company name is never used as a
    proof, because a real employer may legitimately look like a marker.
    """
    for value in values:
        if any(token in SYNTHETIC_MARKERS for token in _tokens(value)):
            return True
    return False


def _canonical_url_or_empty(value: Any) -> str:
    """Return the canonical URL, or an empty string when it is unusable."""
    text = clean_text(value, limit=2_000)
    if not text:
        return ""
    try:
        return canonical_url(text)
    except UserFacingError:
        return ""


def _source_identity(source: Mapping[str, Any]) -> str:
    source_id = clean_text(source.get("source_id"), limit=240)
    if source_id:
        return source_id
    provider = clean_text(source.get("provider"), limit=60)
    company = clean_text(source.get("company"), limit=240)
    if provider or company:
        return f"{provider}|{company}"
    return ""


def _source_bucket(source: Mapping[str, Any], synthetic_source_ids: frozenset[str]) -> Bucket | None:
    identity = _source_identity(source)
    if not identity:
        return None
    if identity in synthetic_source_ids:
        return "synthetic"
    if is_synthetic_source(source.get("source_id"), source.get("provider")):
        return "synthetic"
    return "live"


def _offer_bucket(
    offer: Mapping[str, Any],
    source_buckets: Mapping[str, Bucket],
    synthetic_source_ids: frozenset[str],
) -> Bucket | None:
    """Return the bucket of one announcement.

    An explicit synthetic marker always wins: a synthetic announcement can
    never be counted as live, whatever the source it was read from.
    """
    source_name = clean_text(offer.get("source_name"), limit=120)
    source_id = clean_text(offer.get("source_id"), limit=240)
    if source_id and source_id in synthetic_source_ids:
        return "synthetic"
    if is_synthetic_source(source_name, source_id):
        return "synthetic"
    registry_source_id = clean_text(offer.get("registry_source_id"), limit=240)
    if registry_source_id and registry_source_id in source_buckets:
        return source_buckets[registry_source_id]
    if not source_name and not source_id:
        return None
    if normalized_text(source_name) in UNATTRIBUTED_SOURCE_NAMES:
        return None
    return "live"


def _announcement_key(offer: Mapping[str, Any]) -> str:
    """Identity of an announcement, used to remove duplicates."""
    url = _canonical_url_or_empty(offer.get("official_url"))
    if url:
        return f"url:{url}"
    source_name = normalized_text(offer.get("source_name"))
    source_id = clean_text(offer.get("source_id"), limit=240)
    if source_name and source_id:
        return f"source:{source_name}:{normalized_text(source_id)}"
    company = normalized_text(offer.get("company"))
    title = normalized_text(offer.get("title"))
    city = normalized_text(offer.get("city"))
    return f"text:{company}|{title}|{city}"


def _source_retained(source: Mapping[str, Any]) -> int:
    """Number of announcements the source returned for this run."""
    if "retained_count" in source:
        return _as_int(source.get("retained_count"))
    if "relevant_count" in source:
        return _as_int(source.get("relevant_count"))
    return 0


def _offer_verified_url(offer: Mapping[str, Any]) -> bool:
    return _lower(offer.get("verification_status")) == "verified" and bool(
        _canonical_url_or_empty(offer.get("official_url"))
    )


def _offer_has_location(offer: Mapping[str, Any]) -> bool:
    return _present(offer.get("city")) or _present(offer.get("country"))


def _offer_has_published_date(offer: Mapping[str, Any]) -> bool:
    return _present(offer.get("posted_date"))


def _offer_has_start_date(offer: Mapping[str, Any]) -> bool:
    if _present(offer.get("start_date")):
        return True
    month = offer.get("start_month")
    return isinstance(month, int) and not isinstance(month, bool) and month != 0


def _offer_has_duration(offer: Mapping[str, Any]) -> bool:
    for key in ("duration_months", "duration_min_months", "duration_max_months"):
        value = offer.get(key)
        if isinstance(value, bool):
            continue
        if isinstance(value, (int, float)) and value > 0:
            return True
        if isinstance(value, str) and value.strip():
            return True
    return False


def _offer_has_requirements(offer: Mapping[str, Any]) -> bool:
    return _present(offer.get("requirements"))


def _target_status(offer: Mapping[str, Any]) -> str:
    status = _lower(offer.get("target_status"))
    return status if status in TARGET_STATUSES else ""


# --------------------------------------------------------------------------
# Metrics
# --------------------------------------------------------------------------


def _compute_bucket(
    sources: Sequence[Mapping[str, Any]],
    offers: Sequence[Mapping[str, Any]],
) -> CoverageMetrics:
    """Measure one bucket from its sources and its announcements."""
    planned = len(sources)
    queried = succeeded = cached = failed = 0
    raw_offers = 0
    for source in sources:
        status = _lower(source.get("status"))
        raw_offers += _as_int(source.get("raw_count"))
        if status not in CONSULTED_STATUSES:
            # ``not_queried`` and ``unsupported`` sources were planned but
            # never contacted: they are neither a success nor a failure.
            continue
        queried += 1
        if status == STATUS_CACHED:
            cached += 1
        elif status == STATUS_ERROR:
            failed += 1
        elif _source_retained(source) > 0:
            succeeded += 1
        else:
            # HTTP 200 is not a quality signal: a source that answers without
            # a single valid announcement failed to deliver any coverage.
            failed += 1

    unique: dict[str, Mapping[str, Any]] = {}
    for offer in offers:
        unique.setdefault(_announcement_key(offer), offer)
    deduped = list(unique.values())

    employers = {
        normalized_text(offer.get("company"))
        for offer in deduped
        if normalized_text(offer.get("company"))
    }
    compliant = sum(1 for offer in deduped if _target_status(offer) == TARGET_CONFORMING)
    to_verify = sum(1 for offer in deduped if _target_status(offer) == TARGET_TO_VERIFY)
    non_compliant = sum(1 for offer in deduped if _target_status(offer) == TARGET_NON_CONFORMING)

    return CoverageMetrics(
        sources_planned=planned,
        sources_queried=queried,
        sources_succeeded=succeeded,
        sources_cached=cached,
        sources_failed=failed,
        unique_employers=len(employers),
        raw_offers=raw_offers,
        valid_offers=compliant + to_verify + non_compliant,
        offers_pre_dedup=len(offers),
        offers_post_dedup=len(deduped),
        offers_verified_url=sum(1 for offer in deduped if _offer_verified_url(offer)),
        offers_with_location=sum(1 for offer in deduped if _offer_has_location(offer)),
        offers_with_published_date=sum(1 for offer in deduped if _offer_has_published_date(offer)),
        offers_with_start_date=sum(1 for offer in deduped if _offer_has_start_date(offer)),
        offers_with_duration=sum(1 for offer in deduped if _offer_has_duration(offer)),
        offers_with_requirements=sum(1 for offer in deduped if _offer_has_requirements(offer)),
        compliant=compliant,
        to_verify=to_verify,
        non_compliant=non_compliant,
    )


def _coherence_violations(
    metrics: Mapping[Bucket, CoverageMetrics],
    bucket_offers: Mapping[Bucket, Sequence[Mapping[str, Any]]],
    unattributed_offers: int,
    total_offers: int,
) -> list[str]:
    """Return the broken coherence rules, as readable sentences."""
    violations: list[str] = []
    for bucket in BUCKETS:
        values = metrics[bucket]
        label = "live" if bucket == "live" else "synthétique"
        if values.sources_succeeded + values.sources_cached + values.sources_failed != values.sources_queried:
            violations.append(
                f"{label} : succès + cache + échecs ne égale pas les sources consultées."
            )
        if values.sources_queried > values.sources_planned:
            violations.append(f"{label} : plus de sources consultées que de sources prévues.")
        if values.offers_post_dedup > values.offers_pre_dedup:
            violations.append(f"{label} : plus d'offres après déduplication qu'avant.")
        if values.compliant + values.to_verify + values.non_compliant != values.valid_offers:
            violations.append(f"{label} : les statuts de conformité ne totalisent pas les offres valides.")
        if values.raw_offers < values.valid_offers:
            violations.append(f"{label} : moins d'annonces brutes que d'offres valides.")
        if values.unique_employers > values.offers_post_dedup:
            violations.append(f"{label} : plus d'employeurs uniques que d'offres dédupliquées.")
        for name in (
            "offers_verified_url",
            "offers_with_location",
            "offers_with_published_date",
            "offers_with_start_date",
            "offers_with_duration",
            "offers_with_requirements",
        ):
            if getattr(values, name) > values.offers_post_dedup:
                violations.append(f"{label} : « {name} » dépasse le nombre d'offres dédupliquées.")
    # The announcements of the run are partitioned: the two buckets plus the
    # unattributed ones cover every announcement exactly once.
    if metrics["live"].offers_pre_dedup + metrics["synthetic"].offers_pre_dedup + unattributed_offers != total_offers:
        violations.append("Les offres des deux compartiments ne couvrent pas toutes les annonces du parcours.")

    live_keys = {_announcement_key(offer) for offer in bucket_offers["live"]}
    synthetic_keys = {_announcement_key(offer) for offer in bucket_offers["synthetic"]}
    if live_keys & synthetic_keys:
        violations.append("Une même annonce est comptée à la fois en live et en synthétique.")
    return violations


def compute_coverage(payload: CoveragePayload) -> CoverageReport:
    """Measure one run.  Pure and deterministic: same payload, same report."""
    sources = tuple(source for source in payload.sources if isinstance(source, Mapping))
    offers = tuple(offer for offer in payload.offers if isinstance(offer, Mapping))
    synthetic_source_ids = frozenset(payload.synthetic_source_ids)

    source_buckets: dict[str, Bucket] = {}
    bucket_sources: dict[Bucket, list[Mapping[str, Any]]] = {"synthetic": [], "live": []}
    unattributed_sources = 0
    seen_sources: set[str] = set()
    for source in sources:
        identity = _source_identity(source)
        if not identity:
            unattributed_sources += 1
            continue
        if identity in seen_sources:
            # A source is never counted twice, even if the snapshot repeats it.
            continue
        seen_sources.add(identity)
        bucket = _source_bucket(source, synthetic_source_ids)
        if bucket is None:
            unattributed_sources += 1
            continue
        source_buckets[identity] = bucket
        bucket_sources[bucket].append(source)

    bucket_offers: dict[Bucket, list[Mapping[str, Any]]] = {"synthetic": [], "live": []}
    unattributed_offers = 0
    for offer in offers:
        bucket = _offer_bucket(offer, source_buckets, synthetic_source_ids)
        if bucket is None:
            unattributed_offers += 1
            continue
        bucket_offers[bucket].append(offer)

    metrics = {bucket: _compute_bucket(bucket_sources[bucket], bucket_offers[bucket]) for bucket in BUCKETS}
    violations = _coherence_violations(metrics, bucket_offers, unattributed_offers, len(offers))

    notes = [
        "Les annonces synthétiques sont mesurées à part : elles n'augmentent aucun compteur live.",
        "Une source qui répond sans annonce valide est comptée en échec de couverture, pas en succès.",
        "Chaque chiffre est recalculable à partir des résultats bruts des sources et des annonces du parcours.",
    ]
    if metrics["live"].sources_cached:
        notes.append("Les compteurs live incluent les sources servies depuis le cache du parcours.")
    if unattributed_offers or unattributed_sources:
        notes.append("Les éléments sans source identifiable sont rapportés à part et ne gonflent aucun compteur.")

    return CoverageReport(
        run_id=clean_text(payload.run_id, limit=160),
        metrics=metrics,
        computed_at=clean_text(payload.computed_at, limit=64),
        coherence={"ok": not violations, "violations": violations},
        run_summary=dict(payload.summary) if isinstance(payload.summary, Mapping) else {},
        unattributed={"sources": unattributed_sources, "offers": unattributed_offers},
        notes=tuple(notes),
    )


def compute_metrics(
    run_id: str,
    *,
    loader: CoverageLoader | None = None,
    base_dir: Path | None = None,
) -> CoverageReport:
    """Measure one run and return its synthetic and live metrics.

    ``compute_coverage`` is the pure core; this function only binds a run to
    a loader.  The default loader reads the last explorer run of the local
    Career database.
    """
    requested = clean_text(run_id, limit=160)
    if not requested:
        raise CoverageRunNotFound("Identifiant de parcours manquant : aucun parcours ne peut être mesuré.")
    active = loader if loader is not None else CareerDatabaseLoader.from_base_dir(base_dir)
    return compute_coverage(active.load(requested))


# --------------------------------------------------------------------------
# Loaders
# --------------------------------------------------------------------------


class CareerDatabaseLoader:
    """Read one explorer run from the local Career SQLite database.

    The explorer keeps its last snapshot in ``career_settings``; the offers of
    the run are the ``jobs`` rows it imported, joined with the qualification
    snapshot recorded at import time.
    """

    def __init__(self, db_path: Path) -> None:
        self.db_path = Path(db_path)

    @classmethod
    def from_base_dir(cls, base_dir: Path | None = None) -> "CareerDatabaseLoader":
        base = (base_dir or Path(__file__).resolve().parents[1]).resolve()
        return cls(base / "career_data" / "career.sqlite3")

    def load(self, run_id: str) -> CoveragePayload:
        if not self.db_path.exists():
            raise CoverageRunNotFound(
                "Aucune base Career locale n'est disponible : aucun parcours ne peut être mesuré."
            )
        connection = sqlite3.connect(self.db_path, timeout=5.0)
        connection.row_factory = sqlite3.Row
        try:
            snapshot = self._read_snapshot(connection)
            stored_run_id = clean_text(snapshot.get("run_id"), limit=160)
            if stored_run_id != clean_text(run_id, limit=160):
                raise CoverageRunNotFound(
                    "Ce parcours n'est plus disponible : la base Career locale ne conserve que le dernier parcours d'exploration."
                )
            sources = self._read_sources(snapshot)
            offers = self._read_offers(connection, snapshot)
        finally:
            connection.close()
        summary = snapshot.get("summary")
        return CoveragePayload(
            run_id=stored_run_id,
            sources=sources,
            offers=offers,
            summary=dict(summary) if isinstance(summary, Mapping) else {},
            computed_at=clean_text(snapshot.get("finished_at"), limit=64),
        )

    @staticmethod
    def _read_snapshot(connection: sqlite3.Connection) -> dict[str, Any]:
        try:
            row = connection.execute(
                "SELECT setting_value FROM career_settings WHERE setting_key = ?",
                (EXPLORATION_LAST_SETTING,),
            ).fetchone()
        except sqlite3.Error as error:
            raise CoverageRunNotFound(
                "La base Career locale ne contient aucun parcours d'exploration mesurable."
            ) from error
        if not row:
            raise CoverageRunNotFound(
                "La base Career locale ne contient aucun parcours d'exploration mesurable."
            )
        try:
            decoded = json.loads(str(row["setting_value"]))
        except (TypeError, ValueError):
            decoded = None
        if not isinstance(decoded, dict):
            raise CoverageRunNotFound(
                "Le parcours d'exploration enregistré est illisible : aucune mesure fiable n'est possible."
            )
        return decoded

    @staticmethod
    def _read_sources(snapshot: Mapping[str, Any]) -> tuple[Mapping[str, Any], ...]:
        outcomes = snapshot.get("outcomes")
        if not isinstance(outcomes, list):
            return ()
        return tuple(item for item in outcomes if isinstance(item, Mapping))

    @staticmethod
    def _read_offers(
        connection: sqlite3.Connection,
        snapshot: Mapping[str, Any],
    ) -> tuple[Mapping[str, Any], ...]:
        references = snapshot.get("match_refs")
        if not isinstance(references, list):
            return ()
        registry_sources: dict[str, str] = {}
        job_ids: list[str] = []
        for reference in references:
            if not isinstance(reference, Mapping):
                continue
            job_id = clean_text(reference.get("job_id"), limit=120)
            if not job_id or job_id in registry_sources:
                continue
            registry_sources[job_id] = clean_text(reference.get("source_id"), limit=240)
            job_ids.append(job_id)
        if not job_ids:
            return ()

        offers: list[Mapping[str, Any]] = []
        for start in range(0, len(job_ids), _QUERY_BATCH):
            batch = job_ids[start:start + _QUERY_BATCH]
            placeholders = ", ".join("?" for _ in batch)
            rows = connection.execute(
                f"""
                SELECT jobs.id AS job_id, jobs.source_name AS source_name, jobs.source_id AS source_id,
                       jobs.company AS company, jobs.title AS title, jobs.official_url AS official_url,
                       jobs.city AS city, jobs.country AS country, jobs.posted_date AS posted_date,
                       jobs.start_date AS start_date, jobs.duration_months AS duration_months,
                       jobs.requirements AS requirements,
                       job_qualification_snapshots.schema_version AS qualification_schema_version,
                       job_qualification_snapshots.facts_json AS qualification_facts_json,
                       job_qualification_snapshots.provenance_json AS qualification_provenance_json,
                       job_qualification_snapshots.missing_fields_json AS qualification_missing_json,
                       job_qualification_snapshots.reasons_json AS qualification_reasons_json,
                       job_qualification_snapshots.source_fingerprint AS qualification_source_fingerprint,
                       job_qualification_snapshots.updated_at AS qualification_updated_at
                FROM jobs
                LEFT JOIN job_qualification_snapshots ON job_qualification_snapshots.job_id = jobs.id
                WHERE jobs.id IN ({placeholders})
                """,
                tuple(batch),
            ).fetchall()
            for row in rows:
                facts = decode_qualification_snapshot(dict(row))
                job_id = str(row["job_id"])
                offers.append(
                    {
                        "job_id": job_id,
                        "registry_source_id": registry_sources.get(job_id, ""),
                        "source_name": row["source_name"],
                        "source_id": row["source_id"],
                        "company": row["company"],
                        "title": row["title"],
                        "official_url": row["official_url"],
                        "city": row["city"] or facts.get("city") or "",
                        "country": row["country"] or facts.get("country") or "",
                        "posted_date": row["posted_date"] or facts.get("posted_date") or "",
                        "start_date": row["start_date"] or facts.get("start_date") or "",
                        "start_month": facts.get("start_month"),
                        "duration_months": row["duration_months"],
                        "duration_min_months": facts.get("duration_min_months"),
                        "duration_max_months": facts.get("duration_max_months"),
                        "requirements": row["requirements"],
                        "verification_status": facts.get("verification_status") or "",
                        "target_status": facts.get("target_status") or "",
                    }
                )
        order = {job_id: index for index, job_id in enumerate(job_ids)}
        offers.sort(key=lambda offer: order.get(str(offer["job_id"]), len(order)))
        return tuple(offers)


def synthetic_fixture_payload() -> CoveragePayload:
    """Return the bundled synthetic dataset as a run payload.

    The dataset is synthetic by construction (fake companies, fake postings).
    It exists to show that synthetic announcements are measured apart from the
    live search and can never inflate a live counter.
    """
    from .offer_requirements.fixtures import load_fixtures
    from .offer_qualification import qualify_offer

    offers: list[Mapping[str, Any]] = []
    for fixture in load_fixtures():
        offer_id = clean_text(fixture.get("id"), limit=120)
        payload = {
            "title": clean_text(fixture.get("title"), limit=300),
            "company": clean_text(fixture.get("company"), limit=240),
            "description_original": clean_text(fixture.get("description_original"), limit=30_000),
            "requirements": clean_text(fixture.get("requirements"), limit=12_000),
            "source_name": "synthetic",
            "source_id": f"synthetic:{offer_id}",
            "official_url": "",
            "deadline_date": fixture.get("deadline_date") or "",
            "eligibility_requirement": clean_text(fixture.get("eligibility_requirement"), limit=2_000),
            "languages_required": clean_text(fixture.get("languages_required"), limit=2_000),
            "role_level": clean_text(fixture.get("role_level"), limit=120),
        }
        qualification = qualify_offer(payload, as_of=SYNTHETIC_FIXTURE_AS_OF).to_dict()
        offers.append(
            {
                "job_id": offer_id,
                "source_name": "synthetic",
                "source_id": payload["source_id"],
                "company": payload["company"],
                "title": payload["title"],
                "official_url": "",
                "requirements": payload["requirements"],
                "verification_status": qualification.get("verification_status") or "",
                "target_status": qualification.get("target_status") or "",
                "start_month": qualification.get("start_month"),
                "duration_min_months": qualification.get("duration_min_months"),
                "duration_max_months": qualification.get("duration_max_months"),
                "country": qualification.get("country") or "",
                "city": qualification.get("city") or "",
                "posted_date": qualification.get("posted_date") or "",
                "start_date": qualification.get("start_date") or "",
            }
        )
    sources = (
        {
            "source_id": "synthetic:fixtures",
            "provider": "synthetic",
            "company": "Jeu de fixtures synthétique",
            "status": STATUS_SUCCESS,
            "attempted": True,
            "raw_count": len(offers),
            "evaluated_count": len(offers),
            "retained_count": len(offers),
        },
    )
    return CoveragePayload(
        run_id="synthetic-fixtures",
        sources=sources,
        offers=tuple(offers),
        summary={"sources_total": 1, "sources_succeeded": 1, "retained_count": len(offers)},
        computed_at="",
    )


def synthetic_fixture_metrics() -> CoverageMetrics:
    """Return the metrics of the bundled synthetic dataset."""
    return compute_coverage(synthetic_fixture_payload()).metrics["synthetic"]


__all__ = [
    "BUCKETS",
    "COVERAGE_SCHEMA",
    "CareerDatabaseLoader",
    "CoverageError",
    "CoverageLoader",
    "CoverageMetrics",
    "CoveragePayload",
    "CoverageReport",
    "CoverageRunNotFound",
    "compute_coverage",
    "compute_metrics",
    "is_synthetic_source",
    "synthetic_fixture_metrics",
    "synthetic_fixture_payload",
]
