"""Quality, freshness and provenance of one collected offer (SPEC-006).

A CV generator is only useful if the offers it targets are valid.  This
module decides, for one offer:

* **freshness** -- the offer was verified recently, its page still answers
  and its deadline is not passed;
* **completeness** -- the facts needed to write a targeted CV are present;
* **source trust** -- its link is the employer's own source (SPEC-SK-01);
* **deduplication** -- the duplicates published on other boards are merged
  without losing their provenance (SPEC-SK-06).

The module is pure: it reads the offer, the observed URL status and the clock
the caller injects.  It never performs a network request, never writes
anything and never modifies the dictionaries it receives.  The same inputs
always produce the same output.

Design rules the tests enforce:

* a source flag is a *claim*, never a proof -- SPEC-SK-01 decides the trust
  of a link and this module never re-decides it;
* an unknown stays unknown -- a deadline is never invented (SPEC-SK-02 reads
  the dates, a month-only date never becomes a day);
* a duplicate never loses its provenance -- every source of a merged offer
  stays visible and every contradiction stays readable;
* every verdict carries human readable ``reasons`` -- an empty explanation is
  a bug.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from typing import Any, Mapping, Optional, Protocol, Sequence

from .job_deduplication import (
    canonical_city,
    canonical_company,
    deduplicate_jobs,
    title_concept,
)
from .models import clean_text
from .source_trust import check_trust


#: An offer after this many days without verification is considered stale.
STALE_AFTER_DAYS = 30
#: An offer older than this many days is still usable but no longer fresh.
AGING_AFTER_DAYS = 7
#: A refresh re-verifies the source URL only when it is explicitly forced.
REFRESH_INTERVAL_HOURS = 24

#: The HTTP statuses that prove the offer page is gone.
GONE_STATUSES = frozenset({404, 410})

#: The source tiers, from the most official to the least trustworthy.
SOURCE_TIERS: dict[str, int] = {
    # 1 -- official employer page.
    "companycareer": 1,
    "employer": 1,
    "employersites": 1,
    "employerofficial": 1,
    "careerspage": 1,
    # 2 -- official ATS.
    "greenhouse": 2,
    "lever": 2,
    "ashby": 2,
    "smartrecruiters": 2,
    # 3 -- partner platform.
    "welcometothejungle": 3,
    "jobteaser": 3,
    "talentcom": 3,
    "apec": 3,
    # 4 -- aggregator.
    "indeed": 4,
    "linkedin": 4,
    "glassdoor": 4,
    "monster": 4,
    "aggregator": 4,
    # 5 -- manual entry.
    "manual": 5,
    "import": 5,
    "importmanuel": 5,
    "unknown": 5,
}

#: The human readable label of every tier.
TIER_LABELS: dict[int, str] = {
    1: "Page officielle entreprise",
    2: "ATS officiel",
    3: "Plateforme partenaire",
    4: "Agrégateur",
    5: "Saisie manuelle",
}

#: The fields read to compute the completeness score.  The weights sum to
#: 100, so the score is a percentage of the facts a targeted CV needs.
COMPLETENESS_FIELDS: tuple[tuple[str, int, tuple[str, ...]], ...] = (
    ("title", 10, ("title",)),
    ("company", 10, ("company",)),
    ("description", 12, ("description_original", "description")),
    ("requirements", 12, ("requirements", "requirements_text")),
    ("location", 8, ("city", "country", "location")),
    ("dates", 14, ("posted_date", "deadline_date", "start_date", "end_date")),
    ("duration_months", 8, ("duration_months",)),
    ("salary_range", 8, ("salary_range", "salary", "salary_min", "salary_max")),
    ("employment_type", 6, ("employment_type", "contract_type")),
    ("official_url", 12, ("official_url",)),
)

#: The fields watched between two checks to detect a change of the offer.
TRACKED_FIELDS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("title", ("title",)),
    ("company", ("company",)),
    ("official_url", ("official_url",)),
    ("posted_date", ("posted_date",)),
    ("deadline_date", ("deadline_date",)),
    ("start_date", ("start_date",)),
    ("end_date", ("end_date",)),
    ("duration_months", ("duration_months",)),
    ("employment_type", ("employment_type",)),
    ("location", ("city", "country")),
    ("requirements", ("requirements",)),
    ("source_status", ("source_status",)),
)

#: The ATS providers whose declared name is compared to the observed host.
ATS_PROVIDERS = frozenset({"greenhouse", "lever", "ashby", "smartrecruiters"})

#: The top-level keys of the contract returned by the interface.
OFFER_QUALITY_FIELDS: tuple[str, ...] = (
    "offer_id",
    "freshness",
    "completeness",
    "source_trust",
    "deduplication",
)


class OfferCatalog(Protocol):
    """The read-only view of the offers the assessment needs."""

    def offer(self, offer_id: str) -> Mapping[str, Any]: ...

    def offers(self) -> Sequence[Mapping[str, Any]]: ...


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(moment: datetime) -> str:
    """Return the UTC ISO-8601 form used by the contract (``...Z``)."""

    return (
        moment.astimezone(timezone.utc)
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z")
    )


def _parse_moment(value: Any) -> Optional[datetime]:
    """Parse an ISO-8601 timestamp; return ``None`` when unreadable."""

    text = clean_text(value, limit=40)
    if not text:
        return None
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _parse_date(value: Any) -> Optional[date]:
    """Parse an ``YYYY-MM-DD`` date; return ``None`` when unreadable."""

    text = clean_text(value, limit=32)
    if not text:
        return None
    try:
        return date.fromisoformat(text)
    except ValueError:
        return None


def _source_key(provider: Any) -> str:
    """Return the comparable key of a source name."""

    return re.sub(r"[^a-z0-9]", "", clean_text(provider, limit=80).lower())


def source_tier(provider: Any) -> int:
    """Return the tier of a source (1 = official employer page).

    The table of the mission is applied: employer page, official ATS,
    partner platform, aggregator, manual entry.  An unknown source is
    treated as an aggregator: it is never promoted to an official source.
    """

    key = _source_key(provider)
    if not key:
        return 5
    if key in SOURCE_TIERS:
        return SOURCE_TIERS[key]
    for known in sorted(SOURCE_TIERS, key=len, reverse=True):
        if key.startswith(known):
            return SOURCE_TIERS[known]
    return 4


def tier_label(tier: int) -> str:
    """Return the human readable label of a source tier."""

    return TIER_LABELS.get(tier, TIER_LABELS[4])


@dataclass(frozen=True)
class OfferChange:
    """One fact that changed between two checks of an offer."""

    field: str
    old: Any
    new: Any
    detected_at: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "field": self.field,
            "old": self.old,
            "new": self.new,
            "detected_at": self.detected_at,
        }


@dataclass(frozen=True)
class Freshness:
    """How recent and how reachable an offer is."""

    last_verified_at: Optional[str]
    source_url_status: Optional[int]
    source_url: str
    is_active: bool
    deadline_date: Optional[str]
    days_until_deadline: Optional[int]
    changes_since_last_check: list[OfferChange] = field(default_factory=list)
    status: str = "unknown"
    age_days: Optional[int] = None
    reasons: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "last_verified_at": self.last_verified_at,
            "source_url_status": self.source_url_status,
            "source_url": self.source_url,
            "is_active": self.is_active,
            "deadline_date": self.deadline_date,
            "days_until_deadline": self.days_until_deadline,
            "changes_since_last_check": [change.to_dict() for change in self.changes_since_last_check],
            "status": self.status,
            "age_days": self.age_days,
            "reasons": list(self.reasons),
        }


@dataclass(frozen=True)
class Completeness:
    """The facts a targeted CV needs, and the ones that are missing."""

    score: int
    missing_fields: list[str] = field(default_factory=list)
    present_fields: list[str] = field(default_factory=list)
    has_requirements: bool = False
    has_location: bool = False
    has_dates: bool = False
    reasons: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "score": self.score,
            "missing_fields": list(self.missing_fields),
            "present_fields": list(self.present_fields),
            "has_requirements": self.has_requirements,
            "has_location": self.has_location,
            "has_dates": self.has_dates,
            "reasons": list(self.reasons),
        }


@dataclass(frozen=True)
class SourceTrustView:
    """The trust of the official link of an offer (SPEC-SK-01)."""

    status: str
    provider: Optional[str]
    canonical_host: Optional[str]
    employer_match: str
    registry_evidence: Optional[str] = None
    checked_at: Optional[str] = None
    tier: int = 0
    reasons: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "provider": self.provider,
            "canonical_host": self.canonical_host,
            "employer_match": self.employer_match,
            "registry_evidence": self.registry_evidence,
            "checked_at": self.checked_at,
            "tier": self.tier,
            "tier_label": tier_label(self.tier),
            "reasons": list(self.reasons),
        }


@dataclass(frozen=True)
class SourceRef:
    """One source of a (possibly merged) offer."""

    provider: str
    url: str
    trust: str
    raw_id: Optional[str]
    tier: int
    is_primary: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "provider": self.provider,
            "url": self.url,
            "trust": self.trust,
            "raw_id": self.raw_id,
            "tier": self.tier,
            "tier_label": tier_label(self.tier),
            "is_primary": self.is_primary,
        }


@dataclass(frozen=True)
class Deduplication:
    """The identity of an offer once its duplicates are merged."""

    canonical_id: str
    sources: list[SourceRef] = field(default_factory=list)
    merged_from: list[str] = field(default_factory=list)
    contradictions: list[str] = field(default_factory=list)
    primary_provider: str = ""
    duplicate_count: int = 0
    reasons: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "canonical_id": self.canonical_id,
            "sources": [source.to_dict() for source in self.sources],
            "merged_from": list(self.merged_from),
            "contradictions": list(self.contradictions),
            "primary_provider": self.primary_provider,
            "duplicate_count": self.duplicate_count,
            "reasons": list(self.reasons),
        }


@dataclass(frozen=True)
class OfferQuality:
    """The complete verdict of SPEC-006 for one offer."""

    offer_id: str
    freshness: Freshness
    completeness: Completeness
    source_trust: SourceTrustView
    deduplication: Deduplication
    assessed_at: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "offer_id": self.offer_id,
            "assessed_at": self.assessed_at,
            "freshness": self.freshness.to_dict(),
            "completeness": self.completeness.to_dict(),
            "source_trust": self.source_trust.to_dict(),
            "deduplication": self.deduplication.to_dict(),
        }


# ---------------------------------------------------------------------------
# 1. The facts of an offer
# ---------------------------------------------------------------------------

def offer_facts(offer: Mapping[str, Any]) -> dict[str, Any]:
    """Return the watched facts of an offer, ready to be compared.

    The values are bounded and normalised so that two checks of the same
    offer always produce the same facts, whatever the storage order or the
    surrounding whitespace.
    """

    if not isinstance(offer, Mapping):
        raise TypeError("offer must be a mapping")
    facts: dict[str, Any] = {}
    for name, aliases in TRACKED_FIELDS:
        facts[name] = _fact_value(offer, aliases)
    return facts


def _fact_value(offer: Mapping[str, Any], aliases: tuple[str, ...]) -> Any:
    """Return the value of the first alias that carries a fact."""

    for alias in aliases:
        raw = offer.get(alias)
        if alias == "duration_months":
            if isinstance(raw, bool):
                continue
            if isinstance(raw, int) and raw > 0:
                return raw
            if isinstance(raw, str) and raw.strip().isdigit() and int(raw.strip()) > 0:
                return int(raw.strip())
            continue
        if isinstance(raw, (list, tuple, dict)):
            continue
        text = clean_text(raw, limit=2_000)
        if not text:
            continue
        if alias in {"city", "country"}:
            return text
        return text
    return None


def detect_changes(
    previous: Optional[Mapping[str, Any]],
    current: Mapping[str, Any],
    detected_at: str,
) -> list[OfferChange]:
    """Return the facts that changed between two checks of an offer.

    ``previous`` is the ``facts`` mapping of the last snapshot.  A fact that
    appears, disappears or changes value produces one change; an unchanged
    fact produces none.  The order of the changes follows the watched
    fields, so the history is replayable.

    Without a previous snapshot there is nothing to compare: the first
    check of an offer never invents a change.
    """

    if not isinstance(current, Mapping):
        raise TypeError("current facts must be a mapping")
    if previous is None:
        return []
    old_facts = dict(previous)
    changes: list[OfferChange] = []
    for name, _aliases in TRACKED_FIELDS:
        old = old_facts.get(name)
        new = current.get(name)
        if old == new:
            continue
        changes.append(OfferChange(field=name, old=old, new=new, detected_at=detected_at))
    return changes


# ---------------------------------------------------------------------------
# 2. Freshness
# ---------------------------------------------------------------------------

def assess_freshness(
    offer: Mapping[str, Any],
    *,
    now: Optional[datetime] = None,
    verified_at: Optional[str] = None,
    source_url_status: Optional[int] = None,
    previous: Optional[Mapping[str, Any]] = None,
    deadline_hint: Optional[str] = None,
) -> Freshness:
    """Return the freshness of an offer.

    The function is pure: the caller provides the moment, the moment of the
    last verification and the observed HTTP status of the source URL.
    """

    moment = (now or _utc_now()).astimezone(timezone.utc)
    reasons: list[str] = []
    source_url = clean_text(offer.get("official_url"), limit=2_000)
    last_verified = clean_text(verified_at, limit=40) or clean_text(offer.get("last_verified_at"), limit=40)
    status = source_url_status if isinstance(source_url_status, int) else None

    deadline = _parse_date(offer.get("deadline_date")) or _parse_date(deadline_hint)
    deadline_text = deadline.isoformat() if deadline else None
    days_until_deadline: Optional[int] = None
    if deadline is not None:
        days_until_deadline = (deadline - moment.date()).days
    else:
        reasons.append("Aucune date limite connue : l'activité de l'offre reste indéterminée.")

    age_days: Optional[int] = None
    verified_moment = _parse_moment(last_verified)
    if verified_moment is not None:
        age_days = max(0, (moment - verified_moment).days)
        if age_days > STALE_AFTER_DAYS:
            reasons.append(
                f"Dernière vérification il y a {age_days} jours : les informations peuvent être périmées."
            )
        elif age_days > AGING_AFTER_DAYS:
            reasons.append(f"Dernière vérification il y a {age_days} jours : une revérification est conseillée.")
    else:
        reasons.append("Offre jamais vérifiée : sa fraîcheur est inconnue.")

    if status is None:
        if source_url:
            reasons.append("L'URL de la source n'a pas été contrôlée : sa disponibilité est inconnue.")
    elif status in GONE_STATUSES:
        reasons.append(f"La page source répond {status} : l'offre n'est plus publiée.")
    elif status >= 500:
        reasons.append(f"La page source répond {status} : l'erreur du serveur ne prouve pas que l'offre a disparu.")
    elif 200 <= status < 300:
        reasons.append(f"La page source répond {status} : l'offre est toujours publiée.")

    source_status = clean_text(offer.get("source_status"), limit=40).lower()
    is_active = True
    if source_status == "closed":
        is_active = False
        reasons.append("La source déclare l'offre fermée.")
    elif deadline is not None and days_until_deadline is not None and days_until_deadline < 0:
        is_active = False
        reasons.append(f"La date limite ({deadline_text}) est dépassée : l'offre est expirée.")
    elif status in GONE_STATUSES:
        is_active = False

    if not source_url:
        reasons.append("Aucune URL officielle : l'offre n'est rattachée à aucune source.")

    if source_status == "closed" or (days_until_deadline is not None and days_until_deadline < 0) or status in GONE_STATUSES:
        freshness_status = "expired"
    elif verified_moment is None and status is None:
        freshness_status = "unknown"
    elif age_days is not None and age_days > STALE_AFTER_DAYS:
        freshness_status = "stale"
    elif age_days is not None and age_days > AGING_AFTER_DAYS:
        freshness_status = "aging"
    elif age_days is not None or status is not None:
        freshness_status = "fresh"
    else:
        freshness_status = "unknown"

    changes = detect_changes(previous, offer_facts(offer), _iso(moment))
    if changes:
        reasons.append(f"{len(changes)} information(s) de l'offre ont changé depuis la dernière vérification.")

    return Freshness(
        last_verified_at=last_verified or None,
        source_url_status=status,
        source_url=source_url,
        is_active=is_active,
        deadline_date=deadline_text,
        days_until_deadline=days_until_deadline,
        changes_since_last_check=changes,
        status=freshness_status,
        age_days=age_days,
        reasons=reasons,
    )


# ---------------------------------------------------------------------------
# 3. Completeness
# ---------------------------------------------------------------------------

def assess_completeness(offer: Mapping[str, Any]) -> Completeness:
    """Return the completeness of an offer (0-100).

    The score is the sum of the weights of the facts that are present; the
    missing facts are listed so that the interface can tell what is still
    unknown instead of hiding it behind a number.
    """

    if not isinstance(offer, Mapping):
        raise TypeError("offer must be a mapping")
    missing: list[str] = []
    present: list[str] = []
    score = 0
    for name, weight, aliases in COMPLETENESS_FIELDS:
        if _has_fact(offer, aliases):
            score += weight
            present.append(name)
        else:
            missing.append(name)
    reasons: list[str] = []
    if missing:
        reasons.append("Informations manquantes : " + ", ".join(missing) + ".")
    else:
        reasons.append("Toutes les informations attendues sont présentes.")
    return Completeness(
        score=score,
        missing_fields=missing,
        present_fields=present,
        has_requirements="requirements" in present,
        has_location="location" in present,
        has_dates="dates" in present,
        reasons=reasons,
    )


def _has_fact(offer: Mapping[str, Any], aliases: tuple[str, ...]) -> bool:
    """Return whether the offer carries one of the given facts."""

    for alias in aliases:
        raw = offer.get(alias)
        if alias == "duration_months":
            if isinstance(raw, bool):
                continue
            if isinstance(raw, int) and raw > 0:
                return True
            if isinstance(raw, str) and raw.strip().isdigit() and int(raw.strip()) > 0:
                return True
            continue
        if isinstance(raw, (list, tuple, dict)):
            continue
        if clean_text(raw, limit=2_000):
            return True
    return False


# ---------------------------------------------------------------------------
# 4. Source trust (SPEC-SK-01)
# ---------------------------------------------------------------------------

def assess_source_trust(
    offer: Mapping[str, Any],
    *,
    url: Optional[str] = None,
    checked_at: Optional[str] = None,
    provider: Optional[str] = None,
    tier: Optional[int] = None,
) -> SourceTrustView:
    """Return the trust of the official link of an offer.

    The decision is the one of SPEC-SK-01: this module never re-decides it.
    A link that belongs to a partner platform is not an official link: it is
    reported as missing rather than as contradictory, because the offer is
    not lying -- it simply has no official source yet.
    """

    if not isinstance(offer, Mapping):
        raise TypeError("offer must be a mapping")
    company = clean_text(offer.get("company"), limit=240)
    source = clean_text(provider if provider is not None else offer.get("source_name"), limit=120)
    link = clean_text(url if url is not None else offer.get("official_url"), limit=2_000)
    source_level = source_tier(source) if tier is None else int(tier)
    moment = clean_text(checked_at, limit=40) or None

    if not link:
        return SourceTrustView(
            status="missing",
            provider=source or None,
            canonical_host=None,
            employer_match="unknown",
            registry_evidence=None,
            checked_at=moment,
            tier=source_level,
            reasons=["Aucune URL officielle : l'offre n'est rattachée à aucune source vérifiable."],
        )

    if source_level > 2:
        return SourceTrustView(
            status="missing",
            provider=source or None,
            canonical_host=_host_of(link),
            employer_match="unknown",
            registry_evidence=None,
            checked_at=moment,
            tier=source_level,
            reasons=[
                f"La source « {source or 'inconnue'} » est une {tier_label(source_level).lower()} : "
                "elle n'est pas une source officielle de l'employeur."
            ],
        )

    declared = source.lower() if source.lower() in ATS_PROVIDERS else None
    result = check_trust(
        link,
        employer_hint=company or None,
        declared_provider=declared,
        clock=(lambda: moment) if moment else None,
    )
    return SourceTrustView(
        status=result.status,
        provider=result.provider,
        canonical_host=result.canonical_host,
        employer_match=result.employer_match,
        registry_evidence=result.registry_evidence,
        checked_at=result.checked_at,
        tier=source_level,
        reasons=list(result.reasons),
    )


def _host_of(url: str) -> Optional[str]:
    """Return the host of a URL without any network access."""

    import urllib.parse

    parsed = urllib.parse.urlsplit(url)
    host = (parsed.hostname or "").lower()
    return host[4:] if host.startswith("www.") else host or None


# ---------------------------------------------------------------------------
# 5. Deduplication (SPEC-SK-06)
# ---------------------------------------------------------------------------

def assess_deduplication(
    offer: Mapping[str, Any],
    duplicates: Sequence[Mapping[str, Any]] = (),
    *,
    checked_at: Optional[str] = None,
) -> Deduplication:
    """Return the identity of an offer once its duplicates are merged.

    The grouping is the one of SPEC-SK-06: this module never merges two
    offers by itself.  Every source stays visible in ``sources`` and every
    contradiction between the sources stays readable in ``contradictions``.
    """

    if not isinstance(offer, Mapping):
        raise TypeError("offer must be a mapping")
    records: list[Mapping[str, Any]] = [offer]
    for candidate in duplicates:
        if isinstance(candidate, Mapping):
            records.append(candidate)
    groups = deduplicate_jobs(records)
    group = next((item for item in groups if 0 in item["member_indexes"]), None)
    reasons: list[str] = []
    if group is None:  # pragma: no cover - deduplicate_jobs always returns the group of a record
        return Deduplication(
            canonical_id=_canonical_id(offer, []),
            sources=[],
            merged_from=[],
            contradictions=[],
            primary_provider=clean_text(offer.get("source_name"), limit=120),
            duplicate_count=0,
            reasons=["Aucun groupe de déduplication n'a pu être construit pour cette offre."],
        )

    provenances = list(group["provenances"])
    sources: list[SourceRef] = []
    for view in provenances:
        record = view.get("record") or {}
        provider = clean_text(view.get("source_name"), limit=120)
        url = clean_text(view.get("official_url"), limit=2_000)
        raw_id = clean_text(view.get("source_id"), limit=240) or None
        tier = source_tier(provider)
        trust = _trust_of_source(record, provider, url, tier, checked_at)
        sources.append(
            SourceRef(
                provider=provider,
                url=url,
                trust=trust,
                raw_id=raw_id,
                tier=tier,
            )
        )

    primary = _primary_source(sources)
    sources = [
        SourceRef(
            provider=source.provider,
            url=source.url,
            trust=source.trust,
            raw_id=source.raw_id,
            tier=source.tier,
            is_primary=primary is not None and source.provider == primary.provider and source.url == primary.url,
        )
        for source in sources
    ]

    merged_from = [_source_key_of(source) for source in sources]
    contradictions = _contradictions(group.get("conflicts") or {})
    if contradictions:
        reasons.append("Les sources se contredisent : " + " ; ".join(contradictions))
    if len(sources) > 1:
        reasons.append(
            f"{len(sources)} sources publications décrivent cette offre : la source prioritaire est "
            f"« {primary.provider if primary else 'inconnue'} »."
        )
    else:
        reasons.append("Cette offre n'est connue que d'une seule source.")

    return Deduplication(
        canonical_id=_canonical_id(offer, sources),
        sources=sources,
        merged_from=merged_from,
        contradictions=contradictions,
        primary_provider=primary.provider if primary else clean_text(offer.get("source_name"), limit=120),
        duplicate_count=max(0, len(sources) - 1),
        reasons=reasons,
    )


def _trust_of_source(
    record: Mapping[str, Any],
    provider: str,
    url: str,
    tier: int,
    checked_at: Optional[str],
) -> str:
    """Return the trust of one source of a merged offer."""

    if not url:
        return "missing"
    if tier > 2:
        return "unverified"
    company = clean_text(record.get("company"), limit=240)
    declared = provider.lower() if provider.lower() in ATS_PROVIDERS else None
    result = check_trust(
        url,
        employer_hint=company or None,
        declared_provider=declared,
        clock=(lambda: checked_at) if checked_at else None,
    )
    return result.status


def _primary_source(sources: Sequence[SourceRef]) -> Optional[SourceRef]:
    """Return the source that must be displayed for a merged offer.

    The tier of the mission decides: an employer page first, then an
    official ATS, then a partner platform, an aggregator and finally a
    manual entry.  The trust breaks the ties.
    """

    if not sources:
        return None
    order = {"verified": 0, "unverified": 1, "contradictory": 2, "missing": 3}
    return min(sources, key=lambda source: (source.tier, order.get(source.trust, 4), source.provider))


def _source_key_of(source: SourceRef) -> str:
    """Return the ``provider:raw_id`` key of a source."""

    if source.raw_id:
        return f"{source.provider}:{source.raw_id}"
    if source.url:
        return f"{source.provider}:{source.url}"
    return f"{source.provider}:unknown"


def _contradictions(conflicts: Mapping[str, Any]) -> list[str]:
    """Return the readable contradictions between the sources of an offer."""

    readable: list[str] = []
    for field_name, values in sorted(conflicts.items()):
        if not isinstance(values, Mapping):
            continue
        details = " / ".join(f"{key}={value}" for key, value in sorted(values.items()))
        readable.append(f"{field_name} : {details}")
    return readable


def _canonical_id(offer: Mapping[str, Any], sources: Sequence[SourceRef]) -> str:
    """Return the stable identity of a merged offer.

    The anchor is the most official source of the group: adding a partner
    platform never changes the identity, but discovering the official
    employer page does -- and the change stays visible in the history.
    """

    if sources:
        anchor = _primary_source(sources)
        company = canonical_company(offer.get("company"))
        concept = title_concept(offer.get("title"))
        city = canonical_city(offer.get("city"))
        payload = f"{anchor.provider}|{anchor.url}|{company}|{concept}|{city}" if anchor else f"{company}|{concept}|{city}"
    else:
        payload = "|".join(
            (
                canonical_company(offer.get("company")),
                title_concept(offer.get("title")),
                canonical_city(offer.get("city")),
            )
        )
    digest = hashlib.sha1(payload.encode("utf-8")).hexdigest()[:10]
    return f"canon_{digest}"


# ---------------------------------------------------------------------------
# 6. The assessment
# ---------------------------------------------------------------------------

def assess_offer(
    offer: Mapping[str, Any],
    *,
    offer_id: str = "",
    now: Optional[datetime] = None,
    verified_at: Optional[str] = None,
    source_url_status: Optional[int] = None,
    previous: Optional[Mapping[str, Any]] = None,
    duplicates: Sequence[Mapping[str, Any]] = (),
    deadline_hint: Optional[str] = None,
) -> OfferQuality:
    """Return the complete quality verdict of one offer.

    ``previous`` is the ``facts`` mapping of the last snapshot: the changes
    detected since that check are reported in the freshness.
    """

    if not isinstance(offer, Mapping):
        raise TypeError("offer must be a mapping")
    moment = (now or _utc_now()).astimezone(timezone.utc)
    identifier = clean_text(offer_id or offer.get("id"), limit=120)
    freshness = assess_freshness(
        offer,
        now=moment,
        verified_at=verified_at,
        source_url_status=source_url_status,
        previous=previous,
        deadline_hint=deadline_hint,
    )
    completeness = assess_completeness(offer)
    deduplication = assess_deduplication(offer, duplicates, checked_at=_iso(moment))
    primary = next((source for source in deduplication.sources if source.is_primary), None)
    source_trust = assess_source_trust(
        offer,
        url=primary.url if primary is not None else None,
        provider=primary.provider if primary is not None else None,
        tier=primary.tier if primary is not None else None,
        checked_at=_iso(moment),
    )
    return OfferQuality(
        offer_id=identifier,
        freshness=freshness,
        completeness=completeness,
        source_trust=source_trust,
        deduplication=deduplication,
        assessed_at=_iso(moment),
    )


def assess(
    offer_id: str,
    catalog: OfferCatalog,
    *,
    now: Optional[datetime] = None,
    verified_at: Optional[str] = None,
    source_url_status: Optional[int] = None,
    previous: Optional[Mapping[str, Any]] = None,
) -> OfferQuality:
    """Return the quality of one offer of a catalog.

    The function is pure: the catalog is only read, the moment and the
    observed URL status are injected by the caller, and nothing is written
    anywhere.
    """

    offer = catalog.offer(offer_id)
    duplicates = [candidate for candidate in catalog.offers() if _identity(candidate) != _identity(offer)]
    return assess_offer(
        offer,
        offer_id=offer_id,
        now=now,
        verified_at=verified_at,
        source_url_status=source_url_status,
        previous=previous,
        duplicates=duplicates,
    )


def _identity(offer: Mapping[str, Any]) -> str:
    """Return the identity of an offer inside a catalog."""

    identifier = clean_text(offer.get("id"), limit=120)
    if identifier:
        return f"id:{identifier}"
    source = clean_text(offer.get("source_name"), limit=120)
    source_id = clean_text(offer.get("source_id"), limit=240)
    if source_id:
        return f"source:{source}:{source_id}"
    return f"url:{clean_text(offer.get('official_url'), limit=2_000)}"


def deadline_hint_from_text(offer: Mapping[str, Any]) -> Optional[str]:
    """Return the deadline written in the description of an offer.

    SPEC-SK-02 reads the dates of the offer text.  A deadline is only
    returned when the text names a full day: a month is never completed by
    an invented first day.  The language of the text is not always detected
    on a short description, so the reader tries the supported languages and
    keeps the one that actually reads dates.
    """

    try:
        from .offer_dates import extract_offer_dates, facts_by_type
    except ImportError:  # pragma: no cover - the dependency is merged in the same branch
        return None
    best: list[Any] = []
    for language in ("auto", "fr", "en"):
        facts = extract_offer_dates(dict(offer), lang=language)
        if len(facts) > len(best):
            best = facts
    if not best:
        return None
    for fact in facts_by_type(best).get("deadline", []):
        value = fact.value
        day = value.get("day")
        month = value.get("month")
        year = value.get("year")
        if day and month and year:
            try:
                return date(int(year), int(month), int(day)).isoformat()
            except ValueError:
                continue
    return None


def is_refresh_due(last_verified_at: Optional[str], *, now: Optional[datetime] = None) -> bool:
    """Return whether a verification is old enough to be repeated."""

    moment = (now or _utc_now()).astimezone(timezone.utc)
    verified = _parse_moment(last_verified_at)
    if verified is None:
        return True
    return moment - verified >= timedelta(hours=REFRESH_INTERVAL_HOURS)
