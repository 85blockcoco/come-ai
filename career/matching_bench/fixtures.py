"""Loading and validation of the synthetic CV/offer couples (CVBOOST-08).

The fixtures are synthetic by construction: fake companies, fake offers, fake
profiles, reserved example domains.  The loader refuses a fixture set that is
too small, malformed, duplicated or that leaks real-looking contact data —
a benchmark that measures garbage is worse than no benchmark.

A loader failure raises :class:`FixtureError` instead of returning a partial
suite: a truncated fixture set would silently understate coverage.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from . import contracts

DATA_PATH = Path(__file__).resolve().parent / "fixtures" / "cv_offer_pairs.json"

PROFILE_FIELDS = ("skills", "experience", "education", "languages", "eligibility")
CONTACT_FIELDS = ("email", "phone", "linkedin")

_EMAIL = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
_PHONE = re.compile(r"(?<![\d.])(?:\+33\s?[1-9]|0[1-9])(?:[ .-]?\d{2}){4}(?![\d.])")
_LINKEDIN = re.compile(r"linkedin\.com/in/[A-Za-z0-9_-]+", re.IGNORECASE)


class FixtureError(ValueError):
    """The fixture set is invalid: the bench stops rather than measure wrong."""


@dataclass(frozen=True)
class RequirementOracle:
    """Ground truth about one requirement of one synthetic offer."""

    ref: str
    should_be_requirement: bool
    supported: bool
    reason: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "ref": self.ref,
            "should_be_requirement": self.should_be_requirement,
            "supported": self.supported,
            "reason": self.reason,
        }


@dataclass(frozen=True)
class Case:
    """One synthetic CV/offer couple with its hand-written ground truth."""

    id: str
    family: str
    axis: str
    title: str
    severity: str
    profile: dict[str, Any]
    offer: dict[str, Any]
    criteria: dict[str, Any]
    brief: dict[str, Any]
    oracle: dict[str, Any]
    notes: str = ""
    raw: dict[str, Any] = field(default_factory=dict, repr=False)

    @property
    def profile_fields(self) -> dict[str, str]:
        fields = self.profile.get("fields") or {}
        return {name: str(fields.get(name) or "") for name in PROFILE_FIELDS}

    @property
    def contact(self) -> dict[str, str]:
        contact = self.profile.get("contact") or {}
        return {name: str(contact.get(name) or "") for name in CONTACT_FIELDS}

    @property
    def offer_fields(self) -> dict[str, Any]:
        return dict(self.offer.get("fields") or {})

    @property
    def requirement_oracles(self) -> list[RequirementOracle]:
        return [
            RequirementOracle(
                ref=str(item["ref"]),
                should_be_requirement=bool(item["should_be_requirement"]),
                supported=bool(item["supported"]),
                reason=str(item["reason"]),
            )
            for item in self.oracle.get("requirements") or []
        ]


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise FixtureError(message)


def _validate_contact(case_id: str, contact: dict[str, Any], source: str) -> None:
    email = str(contact.get("email") or "")
    if email:
        _require(
            bool(_EMAIL.fullmatch(email)),
            f"{case_id} ({source}) : e-mail de contact synthétique mal formé.",
        )
        domain = email.rsplit("@", 1)[-1].lower()
        _require(
            domain in contracts.ALLOWED_EMAIL_DOMAINS,
            f"{case_id} ({source}) : le domaine de contact {domain!r} n'est pas un domaine d'exemple réservé.",
        )
    phone = str(contact.get("phone") or "")
    if phone:
        _require(
            bool(_PHONE.fullmatch(phone.strip())),
            f"{case_id} ({source}) : numéro de contact synthétique mal formé.",
        )
    linkedin = str(contact.get("linkedin") or "")
    if linkedin:
        _require(
            bool(_LINKEDIN.search(linkedin)),
            f"{case_id} ({source}) : URL de contact synthétique mal formée.",
        )
        _require(
            linkedin.lower().startswith("https://www.linkedin.com/in/"),
            f"{case_id} ({source}) : URL LinkedIn hors gabarit d'exemple.",
        )


def _validate_case(raw: Any, source: str) -> Case:
    _require(isinstance(raw, dict), f"{source} : un cas doit être un objet JSON")
    for name in ("id", "family", "axis", "title", "severity", "profile", "offer", "oracle"):
        _require(name in raw, f"{source} : champ manquant {name!r}")
    case_id = str(raw["id"])
    _require(case_id.strip() != "", f"{source} : id vide")
    _require(raw["family"] in contracts.FAMILIES, f"{case_id} : famille inconnue {raw['family']!r}")
    _require(raw["axis"] in contracts.AXES, f"{case_id} : axe inconnu {raw['axis']!r}")
    _require(raw["severity"] in {"critical", "major", "minor"}, f"{case_id} : sévérité invalide")

    profile = raw["profile"]
    _require(isinstance(profile, dict), f"{case_id} : profile doit être un objet")
    profile_fields = profile.get("fields")
    _require(isinstance(profile_fields, dict), f"{case_id} : profile.fields doit être un objet")
    for name in PROFILE_FIELDS:
        _require(name in profile_fields, f"{case_id} : profile.fields.{name} manquant")
        _require(
            isinstance(profile_fields[name], str),
            f"{case_id} : profile.fields.{name} doit être un texte",
        )
    _validate_contact(case_id, profile.get("contact") or {}, "profile")

    offer = raw["offer"]
    _require(isinstance(offer, dict), f"{case_id} : offer doit être un objet")
    offer_fields = offer.get("fields")
    _require(isinstance(offer_fields, dict), f"{case_id} : offer.fields doit être un objet")
    for name in ("id", "title", "company", "description_original"):
        _require(name in offer_fields, f"{case_id} : offer.fields.{name} manquant")
        _require(isinstance(offer_fields[name], str), f"{case_id} : offer.fields.{name} doit être un texte")
    _validate_contact(case_id, offer.get("contact") or {}, "offer")

    oracle = raw["oracle"]
    _require(isinstance(oracle, dict), f"{case_id} : oracle doit être un objet")
    requirements = oracle.get("requirements")
    _require(
        isinstance(requirements, list) and requirements,
        f"{case_id} : oracle.requirements doit contenir au moins une exigence de référence",
    )
    seen_refs: set[str] = set()
    for item in requirements:
        _require(isinstance(item, dict), f"{case_id} : oracle.requirements doit contenir des objets")
        for name in ("ref", "should_be_requirement", "supported", "reason"):
            _require(name in item, f"{case_id} : oracle.requirements[].{name} manquant")
        ref = str(item["ref"]).strip()
        _require(ref != "", f"{case_id} : oracle.requirements[].ref vide")
        _require(ref not in seen_refs, f"{case_id} : référence dupliquée {ref!r}")
        seen_refs.add(ref)
        _require(
            isinstance(item["should_be_requirement"], bool),
            f"{case_id} : should_be_requirement doit être un booléen",
        )
        _require(isinstance(item["supported"], bool), f"{case_id} : supported doit être un booléen")
        _require(str(item["reason"]).strip() != "", f"{case_id} : motif manquant pour {ref!r}")
    _require(
        oracle.get("eligibility") in {"eligible", "ineligible", "unknown"},
        f"{case_id} : oracle.eligibility invalide",
    )
    _require(
        oracle.get("education_status") in set(contracts.EDUCATION_STATUSES),
        f"{case_id} : oracle.education_status invalide",
    )
    for dimension in oracle.get("unknown_dimensions") or []:
        _require(
            dimension in contracts.UNKNOWN_DIMENSIONS,
            f"{case_id} : dimension inconnue {dimension!r}",
        )
    relevance = oracle.get("relevance") or {}
    _require(isinstance(relevance, dict), f"{case_id} : oracle.relevance doit être un objet")
    for key, status in (relevance.get("components") or {}).items():
        _require(
            status in {"match", "no_match", "unknown"},
            f"{case_id} : composant de pertinence {key!r} invalide",
        )

    criteria = raw.get("criteria") or {}
    _require(isinstance(criteria, dict), f"{case_id} : criteria doit être un objet")
    brief = raw.get("brief") or {}
    _require(isinstance(brief, dict), f"{case_id} : brief doit être un objet")

    return Case(
        id=case_id,
        family=str(raw["family"]),
        axis=str(raw["axis"]),
        title=str(raw["title"]),
        severity=str(raw["severity"]),
        profile=profile,
        offer=offer,
        criteria=criteria,
        brief=brief,
        oracle=oracle,
        notes=str(raw.get("notes") or ""),
        raw=raw,
    )


def load_cases(path: Path | str | None = None) -> list[Case]:
    """Load the synthetic couples and refuse an invalid suite."""
    source_path = Path(path) if path else DATA_PATH
    if not source_path.is_file():
        raise FixtureError(f"jeu de fixtures introuvable : {source_path}")
    try:
        payload = json.loads(source_path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as error:
        raise FixtureError(f"{source_path.name} : JSON illisible ({type(error).__name__})") from error
    _require(isinstance(payload, dict), f"{source_path.name} : la racine doit être un objet")
    _require(
        payload.get("schema_version") == contracts.SCHEMA_VERSION,
        f"{source_path.name} : version de schéma inattendue {payload.get('schema_version')!r}",
    )
    raw_cases = payload.get("cases")
    _require(isinstance(raw_cases, list), f"{source_path.name} : 'cases' doit être une liste")
    _require(
        len(raw_cases) >= contracts.MIN_CASES,
        f"{source_path.name} : au moins {contracts.MIN_CASES} couples synthétiques sont requis "
        f"(lu : {len(raw_cases)}).",
    )
    cases: list[Case] = []
    seen: set[str] = set()
    for index, raw in enumerate(raw_cases):
        case = _validate_case(raw, f"{source_path.name}[{index}]")
        _require(case.id not in seen, f"{source_path.name} : identifiant dupliqué {case.id}")
        seen.add(case.id)
        cases.append(case)
    families = {case.family for case in cases}
    missing = sorted(set(contracts.FAMILIES) - families)
    _require(
        not missing,
        f"{source_path.name} : familles attendues mais absentes : {missing}",
    )
    return cases


def summarize_cases(cases: list[Case]) -> dict[str, Any]:
    """Counts used by the report and by the fixture integrity tests."""
    by_family: dict[str, int] = {family: 0 for family in contracts.FAMILIES}
    by_axis: dict[str, int] = {axis: 0 for axis in contracts.AXES}
    requirements = 0
    for case in cases:
        by_family[case.family] = by_family.get(case.family, 0) + 1
        by_axis[case.axis] = by_axis.get(case.axis, 0) + 1
        requirements += len(case.requirement_oracles)
    return {
        "cases": len(cases),
        "requirements": requirements,
        "by_family": by_family,
        "by_axis": by_axis,
        "contacts_present": sum(1 for case in cases if any(case.contact.values())),
    }
