"""AI output guardrails (N100-I04)."""

from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass
class GuardrailResult:
    ok: bool
    violations: list[str]
    sanitized: str


FORBIDDEN_PATTERNS = [
    r"\binvent(ed)?\b",
    r"\bfabricat",
]


def check_output(text: str, *, max_length: int = 10000) -> GuardrailResult:
    violations: list[str] = []
    if len(text or "") > max_length:
        violations.append("too_long")
    for pat in FORBIDDEN_PATTERNS:
        if re.search(pat, (text or "").lower()):
            violations.append(f"forbidden:{pat}")
    sanitized = (text or "")[:max_length]
    return GuardrailResult(ok=not violations, violations=violations, sanitized=sanitized)