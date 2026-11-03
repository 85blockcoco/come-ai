"""Profile validation (N100-D03)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


REQUIRED_FIELDS = ("display_name", "contact_email", "education", "experience")


@dataclass
class ValidationResult:
    ok: bool
    missing: list[str]
    errors: list[str]


def validate_profile(profile: dict[str, Any]) -> ValidationResult:
    missing = [f for f in REQUIRED_FIELDS if not str(profile.get(f, "")).strip()]
    errors: list[str] = []
    email = str(profile.get("contact_email", "")).strip()
    if email and "@" not in email:
        errors.append("contact_email: format invalide")
    return ValidationResult(ok=not missing and not errors, missing=missing, errors=errors)