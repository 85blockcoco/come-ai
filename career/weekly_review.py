"""Weekly review aggregator for the Career pipeline (SPEC-036).

Pure, local, deterministic: takes a list of application events (synthetic or
real) and produces a :class:`WeeklySummary` with counts, response/interview
rates, objective check and up to 3 recommended actions for the next week.

No network, no secrets, no side effects.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import date, datetime
from typing import Any, Iterable, Literal

Metric = Literal["applications", "responses", "interviews"]


@dataclass
class Objective:
    metric: Metric
    target: int


@dataclass
class WeeklySummary:
    iso_week: str
    applications_sent: int
    responses: int
    interviews: int
    interview_rate: float
    objective_met: bool | None
    top_actions: list[str] = field(default_factory=list)


def _iso_week(d: date) -> str:
    return f"{d.isocalendar().year}-W{d.isocalendar().week:02d}"


def _parse_date(value: Any) -> date | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    s = str(value).strip()
    if not s:
        return None
    for fmt in ("%Y-%m-%d", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%dT%H:%M:%SZ", "%d/%m/%Y"):
        try:
            return datetime.strptime(s[:19], fmt[: len(fmt)] if "T" not in fmt else fmt).date()
        except ValueError:
            continue
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00")).date()
    except ValueError:
        return None


def _event_week(ev: dict[str, Any], week: str | None) -> bool:
    if week is None:
        return True
    d = _parse_date(ev.get("date") or ev.get("sent_at") or ev.get("created_at"))
    if d is None:
        return False
    return _iso_week(d) == week


def weekly_summary(
    events: Iterable[dict[str, Any]],
    *,
    week: str | None = None,
    objective: Objective | None = None,
) -> WeeklySummary:
    """Aggregate application events into a weekly summary.

    Each event is a dict that may contain: ``status`` (sent/responded/interview/
    rejected/ko), ``date``/``sent_at``, ``duration_minutes``.
    """
    events = [e for e in events if isinstance(e, dict)]
    if week is None:
        # Infer the most recent week present in the data.
        weeks = sorted({_iso_week(d) for e in events for d in [_parse_date(e.get("date") or e.get("sent_at") or e.get("created_at"))] if d})
        week = weeks[-1] if weeks else _iso_week(date.today())

    week_events = [e for e in events if _event_week(e, week)]

    def _is_status(ev: dict[str, Any], *names: str) -> bool:
        st = str(ev.get("status", "")).lower()
        return st in {n.lower() for n in names}

    applications_sent = sum(1 for e in week_events if _is_status(e, "sent", "applied", "submitted"))
    responses = sum(1 for e in week_events if _is_status(e, "responded", "response", "reply", "interview", "rejected", "ko"))
    interviews = sum(1 for e in week_events if _is_status(e, "interview", "entretien"))
    interview_rate = (interviews / applications_sent) if applications_sent else 0.0

    objective_met: bool | None = None
    if objective is not None:
        actual = {"applications": applications_sent, "responses": responses, "interviews": interviews}.get(objective.metric, 0)
        objective_met = actual >= objective.target

    actions = recommend_next(
        applications_sent=applications_sent,
        responses=responses,
        interviews=interviews,
        objective=objective,
        objective_met=objective_met,
    )

    return WeeklySummary(
        iso_week=week,
        applications_sent=applications_sent,
        responses=responses,
        interviews=interviews,
        interview_rate=round(interview_rate, 4),
        objective_met=objective_met,
        top_actions=actions,
    )


def objective_check(summary: WeeklySummary, objective: Objective | None) -> bool | None:
    if objective is None:
        return None
    actual = {
        "applications": summary.applications_sent,
        "responses": summary.responses,
        "interviews": summary.interviews,
    }.get(objective.metric, 0)
    return actual >= objective.target


def recommend_next(
    *,
    applications_sent: int = 0,
    responses: int = 0,
    interviews: int = 0,
    objective: Objective | None = None,
    objective_met: bool | None = None,
) -> list[str]:
    actions: list[str] = []
    if applications_sent == 0:
        actions.append("Envoyer au moins une candidature cette semaine.")
    if objective is not None and objective_met is False:
        metric = objective.metric
        if metric == "applications":
            actions.append(f"Atteindre l'objectif de {objective.target} candidatures (actuellement {applications_sent}).")
        elif metric == "responses":
            actions.append(f"Relancer les candidatures sans réponse pour viser {objective.target} réponses.")
        elif metric == "interviews":
            actions.append(f"Préparer les entretiens pour atteindre {objective.target} invitations.")
    if applications_sent > 0 and responses == 0:
        actions.append("Aucune réponse : vérifier le ciblage et la qualité du CV/lettre.")
    if interviews > 0:
        actions.append("Préparer le briefing J-1 pour les entretiens à venir.")
    # Cap at 3.
    # Deduplicate while preserving order.
    seen: set[str] = set()
    out: list[str] = []
    for a in actions:
        if a in seen:
            continue
        seen.add(a)
        out.append(a)
        if len(out) >= 3:
            break
    return out


def to_dict(summary: WeeklySummary) -> dict[str, Any]:
    return asdict(summary)