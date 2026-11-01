"""Text dashboard for the shortlist (N100-C10).

Renders a fixed-width, plain-text table of offers with scores and urgency.
Deterministic, no HTML, suitable for terminal/desktop copy.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Iterable

from career.urgency_ranking import classify_urgency


@dataclass
class Dashboard:
    text: str
    rows: int
    avg_score: float


def render_dashboard(
    offers: Iterable[dict[str, Any]],
    *,
    today: str | None = None,
    width: int = 80,
    max_rows: int = 50,
) -> Dashboard:
    rows = [o for o in offers if isinstance(o, dict)][:max_rows]
    lines = [f"{'ID':<8} {'TITRE':<26} {'DEADLINE':<12} {'SCORE':>6}  URGENCE"]
    lines.append("-" * min(width, 80))
    scores: list[float] = []
    for o in rows:
        oid = str(o.get("id") or o.get("job_id") or "")[:7]
        title = str(o.get("title") or "")[:25]
        deadline = str(o.get("deadline") or "—")[:11]
        try:
            score = float(o.get("score") or 0.0)
        except (TypeError, ValueError):
            score = 0.0
        scores.append(score)
        urg = classify_urgency(str(o.get("deadline") or ""), today=today)
        lines.append(f"{oid:<8} {title:<26} {deadline:<12} {score:>6.1f}  {urg}")
    avg = round(sum(scores) / len(scores), 1) if scores else 0.0
    header = f"SHORTLIST — {len(rows)} offre(s), score moyen {avg}"
    return Dashboard(text=f"{header}\n\n" + "\n".join(lines) + "\n", rows=len(rows), avg_score=avg)


def to_dict(d: Dashboard) -> dict[str, Any]:
    return asdict(d)
