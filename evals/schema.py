"""Chargement et validation du schéma des cas d'évaluation.

Un cas est un dictionnaire JSON validé ici. Aucune dépendance externe :
stdlib uniquement. Les cas sont des données synthétiques ; jamais de
données personnelles, de secrets ou de contenus réels d'utilisateurs.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .checks import criterion_error

CASES_DIR = Path(__file__).parent / "cases"

REQUIRED_FIELDS = (
    "id",
    "category",
    "title",
    "objective",
    "status",
    "required_features",
    "severity",
    "input",
    "expected",
    "acceptance",
    "failure_conditions",
)

VALID_STATUS = {"supported", "future"}
VALID_SEVERITY = {"critical", "major", "minor"}
VALID_CATEGORIES = {"memoire", "documents", "finance", "conversation"}

# Répartition contractuelle de la suite de 60 cas.
EXPECTED_COUNTS = {
    "memoire": 20,   # mémoire, recherche, citations, documents textuels
    "documents": 15,  # analyse PDF et Excel
    "finance": 15,    # calculs, hypothèses, cohérence, erreurs
    "conversation": 10,  # conversation, routage, outils
}


class CaseError(ValueError):
    """Un cas est invalide : le laboratoire s'arrête plutôt que de mesurer faux."""


@dataclass
class Case:
    id: str
    category: str
    title: str
    objective: str
    status: str
    required_features: list[str]
    severity: str
    input: dict[str, Any]
    expected: dict[str, Any]
    acceptance: list[dict[str, Any]]
    failure_conditions: list[str]
    notes: str = ""
    raw: dict[str, Any] = field(default_factory=dict, repr=False)
    application_verified: bool = False


def _validate_case(raw: Any, source: str) -> Case:
    if not isinstance(raw, dict):
        raise CaseError(f"{source} : un cas doit être un objet JSON")
    missing = [f for f in REQUIRED_FIELDS if f not in raw]
    if missing:
        raise CaseError(f"{source} : champs manquants {missing}")
    for name in ("id", "title", "objective", "category", "status", "severity"):
        if not isinstance(raw[name], str) or not raw[name].strip():
            raise CaseError(f"{source} : {name} doit être un texte non vide")
    if raw["status"] not in VALID_STATUS:
        raise CaseError(f"{source} : status invalide {raw['status']!r}")
    if raw["severity"] not in VALID_SEVERITY:
        raise CaseError(f"{source} : severity invalide {raw['severity']!r}")
    if raw["category"] not in VALID_CATEGORIES:
        raise CaseError(f"{source} : category invalide {raw['category']!r}")
    if not isinstance(raw["required_features"], list) or not raw["required_features"]:
        raise CaseError(f"{source} : required_features doit être une liste non vide")
    if any(not isinstance(v, str) or not v.strip() for v in raw["required_features"]):
        raise CaseError(f"{source} : required_features contient un nom invalide")
    for name in ("input", "expected"):
        if not isinstance(raw[name], dict):
            raise CaseError(f"{source} : {name} doit être un objet JSON")
    if not isinstance(raw["acceptance"], list) or not raw["acceptance"]:
        raise CaseError(f"{source} : acceptance doit contenir au moins un critère")
    for crit in raw["acceptance"]:
        problem = criterion_error(crit)
        if problem:
            raise CaseError(f"{source} : {problem}")
    if not isinstance(raw["failure_conditions"], list) or not raw["failure_conditions"]:
        raise CaseError(f"{source} : failure_conditions doit être une liste non vide")
    if any(not isinstance(v, str) or not v.strip() for v in raw["failure_conditions"]):
        raise CaseError(f"{source} : failure_conditions contient un texte invalide")
    if "application_verified" in raw and type(raw["application_verified"]) is not bool:
        raise CaseError(f"{source} : application_verified doit être un booléen")
    return Case(
        id=str(raw["id"]),
        category=raw["category"],
        title=raw["title"],
        objective=raw["objective"],
        status=raw["status"],
        required_features=list(raw["required_features"]),
        severity=raw["severity"],
        input=raw["input"],
        expected=raw["expected"],
        acceptance=list(raw["acceptance"]),
        failure_conditions=list(raw["failure_conditions"]),
        notes=str(raw.get("notes", "")),
        raw=raw,
        application_verified=raw.get("application_verified", False),
    )


def load_cases(cases_dir: Path | str | None = None, *, validate_shape: bool | None = None) -> list[Case]:
    """Load the core suite, or an explicit independent JSON suite.

    The default uses the four contractual files only; adapter-specific suites
    can coexist in the directory without changing the 60-case laboratory.
    Explicit files are validated case by case without enforcing core counts.
    """
    directory = Path(cases_dir) if cases_dir else CASES_DIR
    if not directory.is_dir() and not directory.is_file():
        raise CaseError(f"dossier de cas introuvable : {directory}")
    if directory.is_file():
        paths = [directory]
    elif cases_dir is None:
        paths = [directory / f"{category}.json" for category in sorted(EXPECTED_COUNTS)]
    else:
        paths = sorted(directory.glob("*.json"))
    enforce_shape = directory.is_dir() if validate_shape is None else validate_shape
    cases: list[Case] = []
    seen: set[str] = set()
    for path in paths:
        try:
            payload = json.loads(path.read_text(encoding="utf-8"), parse_constant=_reject_constant)
        except json.JSONDecodeError as exc:
            raise CaseError(f"{path.name} : JSON invalide ({exc})") from exc
        except (OSError, ValueError) as exc:
            raise CaseError(f"{path.name} : cas illisibles ou JSON non fini ({type(exc).__name__})") from exc
        if not isinstance(payload, list):
            raise CaseError(f"{path.name} : le fichier doit contenir une liste de cas")
        for index, raw in enumerate(payload):
            case = _validate_case(raw, f"{path.name}[{index}]")
            if case.id in seen:
                raise CaseError(f"identifiant dupliqué : {case.id}")
            seen.add(case.id)
            cases.append(case)
    if not cases:
        raise CaseError("la suite ne contient aucun cas")
    if enforce_shape:
        _validate_suite_shape(cases)
    return cases


def _reject_constant(value: str) -> None:
    raise ValueError("nombre JSON non fini")


def _validate_suite_shape(cases: list[Case]) -> None:
    counts: dict[str, int] = {}
    for case in cases:
        counts[case.category] = counts.get(case.category, 0) + 1
    if counts != EXPECTED_COUNTS:
        raise CaseError(
            f"répartition attendue {EXPECTED_COUNTS}, trouvée {counts}"
        )


def summarize_suite(cases: list[Case]) -> dict[str, Any]:
    supported = [c for c in cases if c.status == "supported"]
    return {
        "total": len(cases),
        "supported": len(supported),
        "future": len(cases) - len(supported),
        "application_verified": sum(c.application_verified for c in cases),
        "by_category": {
            cat: sum(1 for c in cases if c.category == cat) for cat in sorted(VALID_CATEGORIES)
        },
        "critical": sum(1 for c in cases if c.severity == "critical"),
    }
