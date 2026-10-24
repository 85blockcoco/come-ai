"""Deterministic checklist of administrative documents for an internship abroad.

This module is local-first and factual: it lists the documents that are
usually required for a given destination country, tracks their status, and
reports which required items are still missing.  It never infers a
candidate's eligibility, never calls a network service, and never stores
personal data beyond what the caller provides.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Iterable, Literal

AdminStatus = Literal["missing", "in_progress", "ok", "not_applicable"]
_VALID_STATUSES = {"missing", "in_progress", "ok", "not_applicable"}


@dataclass
class AdminItem:
    """One administrative document in a country checklist."""

    key: str
    label_fr: str
    required: bool
    status: AdminStatus = "missing"
    proof_refs: list[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        if self.status not in _VALID_STATUSES:
            raise ValueError(f"Statut administratif inconnu : {self.status!r}")
        self.key = str(self.key or "").strip()
        self.label_fr = str(self.label_fr or "").strip()
        self.proof_refs = [str(ref) for ref in (self.proof_refs or []) if str(ref).strip()]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class AdminChecklist:
    """Country-level administrative checklist with its blocking items."""

    country: str
    items: list[AdminItem] = field(default_factory=list)
    blocking_missing: list[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        self.country = _normalize_country(self.country)
        self.items = list(self.items or [])
        self.blocking_missing = _blocking_missing(self.items)

    def completeness(self) -> float:
        """Return the share of items that are ``ok`` or ``not_applicable``."""
        if not self.items:
            return 1.0
        done = sum(1 for item in self.items if item.status in {"ok", "not_applicable"})
        return round(done / len(self.items), 6)

    def completeness_percent(self) -> int:
        return int(round(self.completeness() * 100))

    def refresh(self) -> "AdminChecklist":
        self.blocking_missing = _blocking_missing(self.items)
        return self

    def to_dict(self) -> dict[str, Any]:
        return {
            "country": self.country,
            "items": [item.to_dict() for item in self.items],
            "blocking_missing": list(self.blocking_missing),
            "completeness": self.completeness(),
            "completeness_percent": self.completeness_percent(),
        }

    @classmethod
    def from_country(
        cls,
        country: Any,
        *,
        statuses: Any = None,
        proof_refs: dict[str, list[str]] | None = None,
    ) -> "AdminChecklist":
        return build_checklist(country, statuses=statuses, proof_refs=proof_refs)


def _normalize_country(value: Any) -> str:
    text = str(value or "").strip()
    if not text:
        return "FR"
    lowered = text.casefold()
    alias = _COUNTRY_ALIASES.get(lowered)
    if alias:
        return alias
    upper = text.upper()
    if len(upper) == 2 and upper.isalpha():
        return upper
    # Accept common full names that are not aliased by upper-casing the
    # first two letters as a best-effort code; callers should prefer ISO codes.
    return upper[:2] if len(upper) >= 2 else "FR"


_COUNTRY_ALIASES: dict[str, str] = {
    "france": "FR",
    "fr": "FR",
    "francia": "FR",
    "united kingdom": "GB",
    "uk": "GB",
    "gb": "GB",
    "great britain": "GB",
    "angleterre": "GB",
    "germany": "DE",
    "de": "DE",
    "allemagne": "DE",
    "deutschland": "DE",
    "netherlands": "NL",
    "nl": "NL",
    "pays-bas": "NL",
    "holland": "NL",
    "hollande": "NL",
    "spain": "ES",
    "es": "ES",
    "espagne": "ES",
    "espana": "ES",
    "belgium": "BE",
    "be": "BE",
    "belgique": "BE",
    "switzerland": "CH",
    "ch": "CH",
    "suisse": "CH",
    "schweiz": "CH",
    "italy": "IT",
    "it": "IT",
    "italie": "IT",
    "italia": "IT",
    "luxembourg": "LU",
    "lu": "LU",
    "portugal": "PT",
    "pt": "PT",
    "ireland": "IE",
    "ie": "IE",
    "irlande": "IE",
    "austria": "AT",
    "at": "AT",
    "autriche": "AT",
    "poland": "PL",
    "pl": "PL",
    "pologne": "PL",
    "sweden": "SE",
    "se": "SE",
    "suede": "SE",
    "norway": "NO",
    "no": "NO",
    "norvege": "NO",
    "denmark": "DK",
    "dk": "DK",
    "danemark": "DK",
    "finland": "FI",
    "fi": "FI",
    "finlande": "FI",
    "international": "INTL",
    "intl": "INTL",
    "abroad": "INTL",
    "etranger": "INTL",
}


def _blocking_missing(items: Iterable[AdminItem]) -> list[str]:
    return [item.key for item in items if item.required and item.status == "missing"]


def _template_item(template: dict[str, Any]) -> AdminItem:
    return AdminItem(
        key=str(template["key"]),
        label_fr=str(template["label_fr"]),
        required=bool(template.get("required", False)),
        status=template.get("status", "missing"),
        proof_refs=list(template.get("proof_refs", []) or []),
    )


# Base document templates.  ``required`` reflects whether the document is
# normally mandatory for a candidate coming from France.
_BASE_FR: list[dict[str, Any]] = [
    {"key": "convention", "label_fr": "Convention de stage tripartite signée", "required": True},
    {"key": "identity", "label_fr": "Pièce d'identité / passeport en cours de validité", "required": True},
    {"key": "enrollment", "label_fr": "Certificat de scolarité", "required": True},
    {"key": "insurance", "label_fr": "Attestation d'assurance responsabilité civile (stage)", "required": True},
    {"key": "health_insurance", "label_fr": "Couverture santé / mutuelle pour la période", "required": True},
    {"key": "bank_details", "label_fr": "Coordonnées bancaires (RIB/IBAN)", "required": False},
    {"key": "housing_proof", "label_fr": "Justificatif de domicile / hébergement", "required": False},
    {"key": "photo", "label_fr": "Photo d'identité", "required": False},
]

_INTL_EXTRA: list[dict[str, Any]] = [
    {"key": "visa", "label_fr": "Visa / titre de séjour pour la période", "required": True},
    {"key": "work_permit", "label_fr": "Autorisation de travail (si applicable)", "required": True},
    {"key": "tax_number", "label_fr": "Numéro fiscal / d'identification local", "required": False},
    {"key": "cv_translated", "label_fr": "CV traduit dans la langue locale", "required": False},
]

# Countries that do not require a visa/work permit for an EU citizen (France).
_EU_LIKE = {"FR", "DE", "NL", "BE", "ES", "IT", "PT", "IE", "LU", "AT", "PL", "SE", "NO", "DK", "FI"}


def _country_requirements(country_code: str) -> list[dict[str, Any]]:
    code = country_code.upper()
    if code == "FR":
        return [dict(item) for item in _BASE_FR]
    items = [dict(item) for item in _BASE_FR]
    # Non-FR EU destinations: no visa/work permit for an EU citizen, but
    # identity, insurance and local registration still matter.
    if code not in _EU_LIKE:
        items = items + [dict(item) for item in _INTL_EXTRA]
    else:
        # EU but non-FR: light-touch additions (registration + local tax id).
        items = items + [
            {"key": "residence_registration", "label_fr": "Enregistrement de résidence local", "required": False},
            {"key": "tax_number", "label_fr": "Numéro fiscal / d'identification local", "required": False},
            {"key": "cv_translated", "label_fr": "CV traduit dans la langue locale", "required": False},
        ]
    # Country-specific tweaks.
    if code == "GB":
        # Post-Brexit: visa/work permit required for most non-UK nationals.
        items = [dict(item) for item in _BASE_FR] + [dict(item) for item in _INTL_EXTRA]
    if code == "CH":
        items = items + [
            {"key": "work_permit", "label_fr": "Autorisation de travail (permis)", "required": True},
        ]
    # Deduplicate by key (keep first).
    seen: set[str] = set()
    unique: list[dict[str, Any]] = []
    for item in items:
        if item["key"] in seen:
            continue
        seen.add(item["key"])
        unique.append(item)
    return unique


REQUIREMENTS_BY_COUNTRY: dict[str, list[dict[str, Any]]] = {}
# France + the countries most often covered by the international connectors.
for _code in ("FR", "GB", "DE", "NL", "BE", "LU", "CH", "IT", "ES", "PT", "IE", "AT"):
    REQUIREMENTS_BY_COUNTRY[_code] = _country_requirements(_code)
# Generic international fallback.
REQUIREMENTS_BY_COUNTRY["INTL"] = _country_requirements("INTL") if "INTL" in _COUNTRY_ALIASES else (
    [dict(item) for item in _BASE_FR] + [dict(item) for item in _INTL_EXTRA]
)
# Ensure INTL key exists with full international set.
REQUIREMENTS_BY_COUNTRY["INTL"] = [dict(item) for item in _BASE_FR] + [dict(item) for item in _INTL_EXTRA]


def get_requirements(country: Any) -> list[dict[str, Any]]:
    """Return the raw requirement templates for a country (with fallback)."""
    code = _normalize_country(country)
    if code in REQUIREMENTS_BY_COUNTRY:
        return [dict(item) for item in REQUIREMENTS_BY_COUNTRY[code]]
    return [dict(item) for item in REQUIREMENTS_BY_COUNTRY["INTL"]]


def build_checklist(
    country: Any,
    *,
    statuses: Any = None,
    proof_refs: dict[str, list[str]] | None = None,
) -> AdminChecklist:
    """Build an :class:`AdminChecklist` for ``country``.

    ``statuses`` may be a mapping ``{key: status}`` or an iterable of
    ``(key, status)`` pairs.  Unknown keys are ignored.
    """
    code = _normalize_country(country)
    status_map: dict[str, str] = {}
    if isinstance(statuses, dict):
        status_map = {str(k): str(v) for k, v in statuses.items()}
    elif statuses is not None:
        try:
            for pair in statuses:
                if isinstance(pair, (tuple, list)) and len(pair) >= 2:
                    status_map[str(pair[0])] = str(pair[1])
        except TypeError:
            pass

    items: list[AdminItem] = []
    for template in get_requirements(code):
        key = str(template["key"])
        status = status_map.get(key, template.get("status", "missing"))
        refs = list((proof_refs or {}).get(key, template.get("proof_refs", [])) or [])
        items.append(
            AdminItem(
                key=key,
                label_fr=str(template["label_fr"]),
                required=bool(template.get("required", False)),
                status=status,  # validated in AdminItem.__post_init__
                proof_refs=refs,
            )
        )
    return AdminChecklist(country=code, items=items, blocking_missing=[])


def completeness(checklist: Any) -> float:
    """Return the completion ratio (0.0–1.0) of a checklist or item list."""
    items: list[Any]
    if isinstance(checklist, dict):
        items = list(checklist.get("items") or [])
    elif hasattr(checklist, "items") and not callable(getattr(checklist, "items", None)):
        items = list(checklist.items or [])
    elif isinstance(checklist, (list, tuple)):
        items = list(checklist)
    else:
        items = []
    if not items:
        return 1.0
    done = 0
    for item in items:
        status = getattr(item, "status", None)
        if status is None and isinstance(item, dict):
            status = item.get("status")
        if status in {"ok", "not_applicable"}:
            done += 1
    return round(done / len(items), 6)


# Aliases for discoverability.
def build_admin_checklist(*args: Any, **kwargs: Any) -> AdminChecklist:
    return build_checklist(*args, **kwargs)


def create_checklist(*args: Any, **kwargs: Any) -> AdminChecklist:
    return build_checklist(*args, **kwargs)


def get_checklist(*args: Any, **kwargs: Any) -> AdminChecklist:
    return build_checklist(*args, **kwargs)


def admin_checklist(*args: Any, **kwargs: Any) -> AdminChecklist:
    return build_checklist(*args, **kwargs)


def requirements_for_country(country: Any) -> list[dict[str, Any]]:
    return get_requirements(country)


def update_item(
    checklist: AdminChecklist,
    key: str,
    *,
    status: str | None = None,
    proof_refs: list[str] | None = None,
) -> AdminChecklist:
    """Mutate an item's status/proofs in place and refresh blocking items."""
    for item in checklist.items:
        if item.key == key:
            if status is not None:
                if status not in _VALID_STATUSES:
                    raise ValueError(f"Statut administratif inconnu : {status!r}")
                item.status = status  # type: ignore[assignment]
            if proof_refs is not None:
                item.proof_refs = [str(ref) for ref in proof_refs]
            break
    checklist.refresh()
    return checklist


__all__ = [
    "AdminItem",
    "AdminChecklist",
    "REQUIREMENTS_BY_COUNTRY",
    "AdminStatus",
    "build_checklist",
    "build_admin_checklist",
    "create_checklist",
    "get_checklist",
    "admin_checklist",
    "get_requirements",
    "requirements_for_country",
    "completeness",
    "update_item",
]
