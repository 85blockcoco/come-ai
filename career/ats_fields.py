"""ATS form fields per platform (N100-G06).

Field schemas for the common graduate-recruiting ATS.  Fields map profile
keys; nothing is submitted automatically.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Iterable

PLATFORMS = ("workday", "greenhouse", "icims", "taleo", "smartrecruiters", "generic")


@dataclass
class AtsField:
    name: str
    label: str
    ftype: str  # text | email | select | file | textarea
    required: bool
    profile_key: str  # key in the user profile that pre-fills it
    value: Any = None


_SCHEMAS: dict[str, list[tuple[str, str, str, bool, str]]] = {
    "generic": [
        ("full_name", "Nom complet", "text", True, "display_name"),
        ("email", "Email", "email", True, "contact_email"),
        ("cv", "CV", "file", True, "cv_path"),
        ("cover_letter", "Lettre de motivation", "file", False, "letter_path"),
        ("start_date", "Date de début souhaitée", "text", False, "start_date"),
        ("location", "Localisation", "text", False, "location"),
        ("work_authorization", "Autorisation de travail", "select", False, "work_authorization"),
        ("linkedin", "LinkedIn", "text", False, "linkedin_url"),
    ],
}
_SCHEMAS["workday"] = _SCHEMAS["generic"]
_SCHEMAS["greenhouse"] = _SCHEMAS["generic"]
_SCHEMAS["icims"] = _SCHEMAS["generic"]
_SCHEMAS["taleo"] = _SCHEMAS["generic"]
_SCHEMAS["smartrecruiters"] = _SCHEMAS["generic"]


def fields_for_platform(platform: str) -> list[AtsField]:
    key = (platform or "generic").lower()
    if key not in PLATFORMS:
        key = "generic"
    return [AtsField(name=n, label=l, ftype=t, required=r, profile_key=pk) for (n, l, t, r, pk) in _SCHEMAS[key]]


def prefill_fields(platform: str, profile: dict[str, Any]) -> list[AtsField]:
    fields = fields_for_platform(platform)
    for f in fields:
        f.value = profile.get(f.profile_key)
    return fields


def missing_required(fields: Iterable[AtsField]) -> list[str]:
    return [f.name for f in fields if f.required and f.value in (None, "")]


def to_dict(f: AtsField) -> dict[str, Any]:
    return asdict(f)
