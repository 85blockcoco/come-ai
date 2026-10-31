"""Learning loop: link application variants to observed outcomes (SPEC-045).

Descriptive only: records experiments {application, variants, context, outcome}
and produces per-variant-family response rates with simple intervals.  No ML
model is served before n>=30 observations.  Correlation is never presented as
causation.
"""

from __future__ import annotations

import json
import sqlite3
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

MIN_OBSERVATIONS_FOR_MODEL = 30


@dataclass
class Experience:
    application_id: str
    variants: dict[str, Any] = field(default_factory=dict)  # cv/letter keywords, tone
    context: dict[str, Any] = field(default_factory=dict)   # sector, location, source
    outcome: str = ""  # no_response | rejected | interview | assessment
    observed_at: str = ""
    manual: bool = False


@dataclass
class VariantStats:
    family: str
    n: int
    responses: int
    response_rate: float
    interval: tuple[float, float]


@dataclass
class LearningReport:
    n_total: int
    model_allowed: bool
    stats: list[VariantStats]
    recommendations: list[str]
    correlation_disclaimer: str


class LearningStore:
    """SQLite-backed experience registry."""

    def __init__(self, db_path: str | Path | None = None) -> None:
        if db_path is None:
            db_path = Path(".") / "career_learning.sqlite3"
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(self.db_path))
        self._conn.execute(
            """CREATE TABLE IF NOT EXISTS experiences (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                application_id TEXT NOT NULL,
                variants TEXT NOT NULL,
                context TEXT NOT NULL,
                outcome TEXT NOT NULL,
                observed_at TEXT NOT NULL,
                manual INTEGER NOT NULL
            )"""
        )
        self._conn.commit()

    def record(self, exp: Experience) -> int:
        cur = self._conn.execute(
            "INSERT INTO experiences (application_id, variants, context, outcome, observed_at, manual) VALUES (?,?,?,?,?,?)",
            (exp.application_id, json.dumps(exp.variants), json.dumps(exp.context),
             exp.outcome, exp.observed_at, 1 if exp.manual else 0),
        )
        self._conn.commit()
        return int(cur.lastrowid)

    def all(self) -> list[Experience]:
        rows = self._conn.execute(
            "SELECT application_id, variants, context, outcome, observed_at, manual FROM experiences"
        ).fetchall()
        out = []
        for r in rows:
            out.append(Experience(
                application_id=r[0],
                variants=json.loads(r[1] or "{}"),
                context=json.loads(r[2] or "{}"),
                outcome=r[3],
                observed_at=r[4],
                manual=bool(r[5]),
            ))
        return out

    def count(self) -> int:
        return int(self._conn.execute("SELECT COUNT(*) FROM experiences").fetchone()[0])

    def close(self) -> None:
        self._conn.close()


def _variant_family(exp: Experience) -> str:
    v = exp.variants or {}
    parts = []
    if v.get("cv"):
        parts.append(f"cv:{v['cv']}")
    if v.get("letter"):
        parts.append(f"letter:{v['letter']}")
    if v.get("tone"):
        parts.append(f"tone:{v['tone']}")
    if not parts:
        parts.append("default")
    return " | ".join(parts)


def _is_response(outcome: str) -> bool:
    return str(outcome).lower() in {"interview", "assessment", "response", "replied", "entretien"}


def _simple_interval(k: int, n: int) -> tuple[float, float]:
    # Wald interval (simple, indicative).
    if n == 0:
        return (0.0, 0.0)
    p = k / n
    margin = 1.96 * (p * (1 - p) / n) ** 0.5 if n > 0 else 0.0
    return (max(0.0, p - margin), min(1.0, p + margin))


def analyze(store: LearningStore) -> LearningReport:
    exps = store.all()
    n_total = len(exps)
    model_allowed = n_total >= MIN_OBSERVATIONS_FOR_MODEL

    # Group by variant family.
    groups: dict[str, list[Experience]] = {}
    for e in exps:
        groups.setdefault(_variant_family(e), []).append(e)

    stats: list[VariantStats] = []
    for family, items in groups.items():
        n = len(items)
        resp = sum(1 for e in items if _is_response(e.outcome))
        rate = (resp / n) if n else 0.0
        lo, hi = _simple_interval(resp, n)
        stats.append(VariantStats(family=family, n=n, responses=resp,
                                 response_rate=round(rate, 4), interval=(round(lo, 4), round(hi, 4))))
    stats.sort(key=lambda s: s.response_rate, reverse=True)

    recommendations: list[str] = []
    if n_total == 0:
        recommendations.append("Aucune expérience enregistrée : saisir les résultats observés.")
    elif not model_allowed:
        recommendations.append(
            f"n={n_total} < {MIN_OBSERVATIONS_FOR_MODEL} : conclusions indicatives uniquement, "
            "pas de modèle appris."
        )
    if stats:
        best = stats[0]
        recommendations.append(
            f"Variante la plus performante (indicatif) : {best.family} "
            f"({best.responses}/{best.n} réponses, taux {best.response_rate})."
        )
        if len(stats) > 1:
            worst = stats[-1]
            recommendations.append(
                f"Variante la moins performante : {worst.family} "
                f"({worst.responses}/{worst.n})."
            )
    if len(recommendations) > 3:
        recommendations = recommendations[:3]

    disclaimer = (
        "Analyse descriptive uniquement — corrélation, pas causalité. "
        "Un modèle appris ne remplace jamais le verdict d'éligibilité ni l'audit qualité."
    )
    return LearningReport(
        n_total=n_total,
        model_allowed=model_allowed,
        stats=stats,
        recommendations=recommendations,
        correlation_disclaimer=disclaimer,
    )


def to_dict(report: LearningReport) -> dict[str, Any]:
    return {
        "n_total": report.n_total,
        "model_allowed": report.model_allowed,
        "stats": [asdict(s) for s in report.stats],
        "recommendations": report.recommendations,
        "correlation_disclaimer": report.correlation_disclaimer,
    }