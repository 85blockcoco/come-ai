"""Exhaustiveness score per offer (SK-20).

Aggregates the evidence produced by the local extractors (salary SK-16,
conditions SK-17, missions SK-18, education SK-19, dates SK-02) into a single
0-100 score shown as a badge in Stage Hunter.

The score only counts evidence that already exists in
``job["qualification"]["provenance"]`` (or equivalent source fields). It never
extracts new facts, never calls the network and never invents a value: a
missing component is reported as missing, with the weight it would carry.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Literal

_EXHAUSTIVENESS_GREEN = 70
_EXHAUSTIVENESS_ORANGE = 40
_EXHAUSTIVENESS_RED = 1

WEIGHTS: dict[str, int] = {
    "missions": 30,
    "salary": 25,
    "conditions": 20,
    "education": 15,
    "dates": 10,
}

# One component may be published under several provenance keys, because the
# extractor missions (SK-16..SK-19) each own their naming. Aliases keep the
# scorer stable regardless of which extractor produced the evidence.
_FACTOR_KEYS: dict[str, tuple[str, ...]] = {
    "missions": ("missions", "missions_fact", "missions_extracted"),
    "salary": ("salary", "salary_fact"),
    "conditions": ("conditions", "conditions_fact"),
    "education": ("education_required", "education_fact", "education"),
}

# date/duration sources: start_date OR duration_min OR deadline (SK-02) —
# a published ceiling ("up to 6 months") alone never credits a real duration.
_DATE_TOP_KEYS = ("start_date", "start_month", "deadline_date", "deadline")
_DATE_PROVENANCE_KEYS = ("start_date", "start_month", "start_year", "deadline",
                         "deadline_date", "duration_min_months")


@dataclass(frozen=True)
class ExhaustivenessScore:
    """Single offer exhaustiveness result, ready for the badge UI."""

    overall_score: int              # 0-100
    breakdown: dict[str, int]       # {"salary": 25, "conditions": 20, "missions": 30, "education": 15, "dates": 10}
    missing: list[str]              # ["salary", "conditions", "education"]
    present: list[str]              # ["missions", "dates"]
    badge_label: str                # "Exhaustivité 85%" / "… | Rémunération : non communiquée"
    badge_color: Literal["green", "orange", "red", "gray"]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _evidence_value(entry: Any) -> Any:
    """Uniform access to a FactEvidence serialized as dict, or as object."""
    if isinstance(entry, dict):
        return entry.get("value")
    return getattr(entry, "value", None)


def _truthy(value: Any) -> bool:
    if value is None:
        return False
    if isinstance(value, str):
        return bool(value.strip())
    if isinstance(value, (list, tuple, dict, set, frozenset)):
        return len(value) > 0
    return bool(value)


def _component_present(job: dict[str, Any], keys: tuple[str, ...]) -> bool:
    provenance = _provenance(job)
    for key in keys:
        evidence = provenance.get(key)
        if evidence is None:
            evidence = job.get(key) if isinstance(job, dict) else None
        if _truthy(_evidence_value(evidence) if evidence is not None else None):
            return True
    return False


def _provenance(job: dict[str, Any]) -> dict[str, Any]:
    qualification = job.get("qualification") if isinstance(job, dict) else None
    provenance = qualification.get("provenance") if isinstance(qualification, dict) else None
    return provenance if isinstance(provenance, dict) else {}


def _dates_present(job: dict[str, Any]) -> bool:
    """start_date OU start_month OU deadline OU duration minimale, avec preuve."""
    if isinstance(job, dict):
        for key in _DATE_TOP_KEYS:
            if _truthy(job.get(key)):
                return True
        provenance = _provenance(job)
        for key in _DATE_PROVENANCE_KEYS:
            if _truthy(_evidence_value(provenance.get(key))):
                return True
        qualification = job.get("qualification")
        if isinstance(qualification, dict) and type(qualification.get("duration_min_months")) is int:
            return True
    return False


def _badge(score: int, salary_missing: bool) -> tuple[str, Literal["green", "orange", "red", "gray"]]:
    if score >= _EXHAUSTIVENESS_GREEN:
        color: Literal["green", "orange", "red", "gray"] = "green"
    elif score >= _EXHAUSTIVENESS_ORANGE:
        color = "orange"
    elif score >= _EXHAUSTIVENESS_RED:
        color = "red"
    else:
        label = "Exhaustivité 0% — offre vide"
        if salary_missing:
            label += " | Rémunération : non communiquée"
        return label, "gray"
    label = f"Exhaustivité {score}%"
    if salary_missing:
        label += " | Rémunération : non communiquée"
    return label, color


def compute_exhaustiveness(job: dict[str, Any]) -> ExhaustivenessScore:
    """Score an already-qualified offer dict without extracting anything.

    ``job`` is either a ``QualifiedOffer.to_dict()`` payload nested under
    ``"qualification"``, or a plain dict carrying its own evidence.
    """
    if not isinstance(job, dict):
        raise TypeError("job must be an object")

    breakdown: dict[str, int] = {}
    missing: list[str] = []
    present: list[str] = []

    for component, keys in _FACTOR_KEYS.items():
        if _component_present(job, keys):
            breakdown[component] = WEIGHTS[component]
            present.append(component)
        else:
            breakdown[component] = 0
            missing.append(component)

    if _dates_present(job):
        breakdown["dates"] = WEIGHTS["dates"]
        present.append("dates")
    else:
        breakdown["dates"] = 0
        missing.append("dates")

    overall = sum(breakdown.values())
    label, color = _badge(overall, breakdown["salary"] == 0)
    return ExhaustivenessScore(
        overall_score=overall,
        breakdown=breakdown,
        missing=missing,
        present=present,
        badge_label=label,
        badge_color=color,
    )


def measure_corpus_exhaustiveness(jobs: list[dict[str, Any]]) -> float:
    """Retourne le score moyen d'exhaustivité sur un corpus d'offres."""
    if not jobs:
        return 0.0
    return sum(compute_exhaustiveness(j).overall_score for j in jobs) / len(jobs)
