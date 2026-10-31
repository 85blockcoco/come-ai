"""End-to-end evaluation on real offers (SPEC-044).

Reads offer files from a local directory (``evals/real_offers/``), runs the
pipeline (timing + quality audit) and produces an aggregated report.  No cloud,
no personal data leaves the machine.  Confidence is reported as indicative
(n=10).
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from .dossier_quality import score_dossier
from .metrics import MetricsStore, StepTimer, new_run_id


@dataclass
class OfferResult:
    offer_id: str
    title: str = ""
    quality_score: float = 0.0
    errors_found: int = 0
    corrections: int = 0
    correction_duration_sec: float = 0.0
    total_duration_sec: float = 0.0
    steps: dict[str, float] = field(default_factory=dict)
    notes: str = ""


@dataclass
class AggregatedReport:
    n_offers: int
    avg_quality_score: float
    avg_total_duration_sec: float
    total_errors: int
    total_corrections: int
    confidence: str
    per_offer: list[dict[str, Any]] = field(default_factory=list)


def load_offers(offers_dir: str | Path) -> list[dict[str, Any]]:
    """Load offer files (JSON or text) from a directory."""
    d = Path(offers_dir)
    if not d.exists() or not d.is_dir():
        return []
    out: list[dict[str, Any]] = []
    for p in sorted(d.iterdir()):
        if p.name.startswith("."):
            continue
        if p.suffix.lower() == ".json":
            try:
                data = json.loads(p.read_text(encoding="utf-8"))
                if isinstance(data, dict):
                    data.setdefault("offer_id", p.stem)
                    out.append(data)
                elif isinstance(data, list):
                    for item in data:
                        if isinstance(item, dict):
                            item.setdefault("offer_id", p.stem)
                            out.append(item)
            except (json.JSONDecodeError, OSError):
                continue
        elif p.suffix.lower() in (".txt", ".md"):
            out.append({"offer_id": p.stem, "title": p.stem, "description": p.read_text(encoding="utf-8")})
    return out


def evaluate_offer(
    offer: dict[str, Any],
    *,
    dossier_text: str = "",
    evidence: list[str] | None = None,
    steps: dict[str, Callable[[], None]] | None = None,
    store: MetricsStore | None = None,
) -> OfferResult:
    evidence = evidence or []
    run_id = new_run_id()
    if store is None:
        store = MetricsStore(":memory:")
    result = OfferResult(offer_id=str(offer.get("offer_id", "unknown")), title=str(offer.get("title", "")))
    steps = steps or {}

    # Run each step with timing.
    for step_name, fn in steps.items():
        with StepTimer(store, run_id, step_name):
            try:
                fn()
            except Exception:
                pass

    # Quality audit.
    q = score_dossier(dossier_text, evidence)
    result.quality_score = q.score
    result.errors_found = sum(1 for c in q.claims if c["label"] != "supported")

    result.steps = store.aggregate(run_id)
    result.total_duration_sec = store.total_duration(run_id)
    return result


def aggregate(results: list[OfferResult]) -> AggregatedReport:
    n = len(results)
    if n == 0:
        return AggregatedReport(n_offers=0, avg_quality_score=0.0, avg_total_duration_sec=0.0,
                                total_errors=0, total_corrections=0, confidence="n=0 (aucune offre)")
    avg_q = sum(r.quality_score for r in results) / n
    avg_t = sum(r.total_duration_sec for r in results) / n
    total_err = sum(r.errors_found for r in results)
    total_corr = sum(r.corrections for r in results)
    if n < 10:
        conf = f"n={n} (indicatif, pas de conclusion forte)"
    else:
        conf = f"n={n} (tendances indicatives)"
    return AggregatedReport(
        n_offers=n,
        avg_quality_score=round(avg_q, 2),
        avg_total_duration_sec=round(avg_t, 2),
        total_errors=total_err,
        total_corrections=total_corr,
        confidence=conf,
        per_offer=[{"offer_id": r.offer_id, "quality_score": r.quality_score,
                    "errors_found": r.errors_found, "total_duration_sec": r.total_duration_sec} for r in results],
    )


def render_report(report: AggregatedReport) -> str:
    lines = [
        f"# Rapport E2E — {report.n_offers} offres",
        "",
        f"- Score qualité moyen : {report.avg_quality_score}/100",
        f"- Durée totale moyenne : {report.avg_total_duration_sec}s",
        f"- Erreurs détectées : {report.total_errors}",
        f"- Corrections utilisateur : {report.total_corrections}",
        f"- Confiance : {report.confidence}",
        "",
        "## Par offre",
    ]
    for o in report.per_offer:
        lines.append(f"- {o['offer_id']}: score={o['quality_score']}, erreurs={o['errors_found']}, durée={o['total_duration_sec']}s")
    return "\n".join(lines)