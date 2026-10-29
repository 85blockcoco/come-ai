"""Synthetic fixture loading and small parsing helpers for the E2E suite."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import yaml

FIXTURES = Path(__file__).resolve().parent / "fixtures"
_COVERAGE = re.compile(r"Couverture obligatoire\s*:\s*([0-9.]+)\s*%")


def load_offer(name: str) -> dict[str, Any]:
    return json.loads((FIXTURES / "offers" / name).read_text(encoding="utf-8"))


def load_profile(name: str) -> dict[str, Any]:
    return yaml.safe_load((FIXTURES / "profiles" / name).read_text(encoding="utf-8"))


def mandatory_coverage(text: str) -> float:
    match = _COVERAGE.search(text)
    assert match, f"Couverture obligatoire absente de: {text!r}"
    return float(match.group(1))


def artifact_paths(texts: list[str]) -> dict[str, str]:
    """Parse the ``Label — /path`` lines rendered for targeted kit artifacts."""
    paths: dict[str, str] = {}
    for line in texts:
        label, separator, path = line.partition(" — ")
        if separator and path.strip().startswith("/"):
            paths[label.strip()] = path.strip()
    return paths
