"""Agrégateur hebdomadaire Career / CVBoost (SPEC-036).

Module pur et déterministe : transforme des enregistrements *déjà locaux*
(candidatures, événements, objectifs) en un bilan hebdomadaire honnête :

* nombre de candidatures envoyées sur la semaine ;
* nombre de réponses reçues ;
* taux d'entretien ;
* comparaison à un objectif fixé (``objective_met`` peut être ``None`` si
  aucun objectif n'est fourni) ;
* jusqu'à 3 actions recommandées pour la semaine suivante.

Aucun réseau, aucun modèle, aucun effet de bord. Les données sont
synthétiques en test ; aucune donnée réelle n'est lue ici.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import date, datetime
from typing import Any, Literal, Mapping

from .models import clean_text

Metric = Literal["applications", "responses", "interviews"]

SENT_STAGES = frozenset(
    {"submitted", "submitted_confirmed", "response_received", "interview", "offer_received"}
)
RESPONSE_STAGES = frozenset({"response_received", "interview", "offer_received"})
INTERVIEW_STAGES = frozenset({"interview", "offer_received"})


@dataclass
class Objective:
    """Objectif hebdomadaire fixé par la personne."""

    metric: Metric = "applications"
    target: int = 0


@dataclass
class WeeklySummary:
    """Bilan d'une semaine ISO."""

    iso_week: str
    applications_sent: int
    responses: int
    interview_rate: float
    objective_met: bool | None
    top_actions: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Helpers de normalisation
# ---------------------------------------------------------------------------


def _safe_date(value: Any) -> date | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    text = clean_text(value, limit=40)
    if not text:
        return None
    # Accepte aussi les horodatages ISO avec heure/fuseau.
    candidate = text.split("T", 1)[0].split(" ", 1)[0]
    try:
        return date.fromisoformat(candidate)
    except ValueError:
        return None


def iso_week_string(value: Any) -> str:
    """Convertit une date/valeur en chaîne de semaine ISO ``YYYY-Www``."""
    if isinstance(value, str):
        text = value.strip()
        upper = text.upper()
        if "W" in upper and len(text) >= 6:
            # Déjà au format semaine ISO (ex. "2026-W42" ou "2026W42").
            return text if "-" in text else text[:4] + "-W" + text[4:].lstrip("W")
        parsed = _safe_date(text)
        if parsed is not None:
            value = parsed
        else:
            return text
    if isinstance(value, (datetime, date)):
        iso = value.isocalendar()
        return f"{iso.year}-W{iso.week:02d}"
    return str(value)


def _to_objective(value: Any) -> Objective | None:
    if value is None:
        return None
    if isinstance(value, Objective):
        return value
    if isinstance(value, Mapping):
        metric = clean_text(value.get("metric", "applications"), limit=40) or "applications"
        if metric not in {"applications", "responses", "interviews"}:
            metric = "applications"
        try:
            target = int(value.get("target", 0))
        except (TypeError, ValueError):
            target = 0
        return Objective(metric=metric, target=target)  # type: ignore[arg-type]
    if isinstance(value, (list, tuple)) and len(value) >= 2:
        metric = clean_text(value[0], limit=40) or "applications"
        if metric not in {"applications", "responses", "interviews"}:
            metric = "applications"
        try:
            target = int(value[1])
        except (TypeError, ValueError):
            target = 0
        return Objective(metric=metric, target=target)  # type: ignore[arg-type]
    return None


def _extract_applications(data: Any) -> list[dict[str, Any]]:
    if data is None:
        return []
    if isinstance(data, (list, tuple)):
        result: list[dict[str, Any]] = []
        for item in data:
            if isinstance(item, Mapping):
                result.append(dict(item))
            else:
                result.append({"value": item})
        return result
    if isinstance(data, Mapping):
        for key in ("applications", "records", "items", "results", "data", "weekly", "entries"):
            value = data.get(key)
            if isinstance(value, (list, tuple)):
                return _extract_applications(value)
        # Un enregistrement unique ressemblant à une candidature.
        if any(k in data for k in ("stage", "job_id", "application_id", "id", "status")):
            return [dict(data)]
    return []


def _collect_objectives(data: Any, objective: Any, objectives: Any) -> list[Objective]:
    collected: list[Objective] = []
    for candidate in (objective, objectives):
        if candidate is None:
            continue
        if isinstance(candidate, (list, tuple)):
            for item in candidate:
                parsed = _to_objective(item)
                if parsed is not None:
                    collected.append(parsed)
        else:
            parsed = _to_objective(candidate)
            if parsed is not None:
                collected.append(parsed)
    if isinstance(data, Mapping):
        for key in ("objective", "objectives"):
            value = data.get(key)
            if value is None:
                continue
            if isinstance(value, (list, tuple)):
                for item in value:
                    parsed = _to_objective(item)
                    if parsed is not None:
                        collected.append(parsed)
            else:
                parsed = _to_objective(value)
                if parsed is not None:
                    collected.append(parsed)
    # Déduplication en conservant l'ordre.
    seen: set[tuple[str, int]] = set()
    unique: list[Objective] = []
    for obj in collected:
        key = (obj.metric, obj.target)
        if key in seen:
            continue
        seen.add(key)
        unique.append(obj)
    return unique


def _app_week(app: Mapping[str, Any]) -> str | None:
    for key in (
        "submitted_at",
        "sent_at",
        "declared_submitted_at",
        "response_at",
        "created_at",
        "updated_at",
        "application_created_at",
        "application_updated_at",
        "date",
        "week",
        "iso_week",
    ):
        value = app.get(key)
        if value is None:
            continue
        if key in {"week", "iso_week"}:
            text = clean_text(value, limit=40)
            if text:
                return iso_week_string(text)
        parsed = _safe_date(value)
        if parsed is not None:
            return iso_week_string(parsed)
    return None


def _is_sent(app: Mapping[str, Any]) -> bool:
    if app.get("sent") is True or app.get("sent_declared") is True:
        return True
    if app.get("submitted_at") or app.get("sent_at") or app.get("declared_submitted_at"):
        return True
    stage = clean_text(app.get("stage", app.get("status", "")), limit=80).lower()
    if stage in SENT_STAGES:
        return True
    # Certains enregistrements portent un compteur explicite.
    if app.get("applications_sent") is not None:
        try:
            return int(app.get("applications_sent")) > 0
        except (TypeError, ValueError):
            pass
    return False


def _is_response(app: Mapping[str, Any]) -> bool:
    stage = clean_text(app.get("stage", app.get("status", "")), limit=80).lower()
    if stage in RESPONSE_STAGES:
        return True
    if app.get("response_received") is True or app.get("has_response") is True:
        return True
    if app.get("responses") is not None:
        try:
            return int(app.get("responses")) > 0
        except (TypeError, ValueError):
            pass
    events = app.get("events")
    if isinstance(events, (list, tuple)):
        for event in events:
            if isinstance(event, Mapping):
                event_type = clean_text(event.get("event_type", event.get("type", "")), limit=80).lower()
                if "response" in event_type or "reply" in event_type:
                    return True
    return False


def _is_interview(app: Mapping[str, Any]) -> bool:
    stage = clean_text(app.get("stage", app.get("status", "")), limit=80).lower()
    if stage in INTERVIEW_STAGES:
        return True
    if app.get("interview") is True or app.get("has_interview") is True:
        return True
    if app.get("interviews") is not None:
        try:
            return int(app.get("interviews")) > 0
        except (TypeError, ValueError):
            pass
    events = app.get("events")
    if isinstance(events, (list, tuple)):
        for event in events:
            if isinstance(event, Mapping):
                event_type = clean_text(event.get("event_type", event.get("type", "")), limit=80).lower()
                if "interview" in event_type:
                    return True
    return False


def _metric_value(summary: "WeeklySummary", metric: str) -> int:
    if metric == "applications":
        return summary.applications_sent
    if metric == "responses":
        return summary.responses
    if metric == "interviews":
        # Dérive le nombre d'entretiens depuis le taux n'est pas possible ;
        # on conserve un compteur séparé si présent dans top_actions ? On
        # recalcule à partir du taux arrondi n'est pas fiable. On stocke
        # donc dans un attribut optionnel.
        return getattr(summary, "_interviews", 0)
    return 0


# ---------------------------------------------------------------------------
# API publique
# ---------------------------------------------------------------------------


def weekly_summary(
    data: Any = None,
    *,
    applications: Any = None,
    objective: Any = None,
    objectives: Any = None,
    week: Any = None,
    iso_week: Any = None,
    today: Any = None,
    now: Any = None,
    **kwargs: Any,
) -> WeeklySummary:
    """Calcule un bilan hebdomadaire à partir de données locales.

    Accepte indifféremment une liste d'enregistrements, un dict contenant
    une clé ``applications``/``records``/..., ou des mots-clés.
    """
    if applications is not None:
        data = applications
    for key in ("applications", "records", "items", "data"):
        if key in kwargs and kwargs[key] is not None:
            data = kwargs[key]
            break

    apps = _extract_applications(data)

    # Semaine cible.
    target_week: str | None = None
    if iso_week is not None:
        target_week = iso_week_string(iso_week)
    elif week is not None:
        target_week = iso_week_string(week)
    elif isinstance(data, Mapping):
        for key in ("iso_week", "week", "isoWeek"):
            if data.get(key) is not None:
                target_week = iso_week_string(data.get(key))
                break
    if target_week is None and (today is not None or now is not None):
        anchor = today if today is not None else now
        target_week = iso_week_string(anchor)
    if target_week is None and apps:
        # Dérive depuis le premier enregistrement daté.
        for app in apps:
            wk = _app_week(app)
            if wk is not None:
                target_week = wk
                break
    if target_week is None:
        target_week = iso_week_string(date.today())

    # Filtrage par semaine si une semaine cible est connue.
    filtered: list[dict[str, Any]] = []
    for app in apps:
        wk = _app_week(app)
        if wk is not None and wk != target_week:
            continue
        filtered.append(app)
    if not filtered and apps:
        filtered = list(apps)

    applications_sent = sum(1 for app in filtered if _is_sent(app))
    responses = sum(1 for app in filtered if _is_response(app))
    interviews = sum(1 for app in filtered if _is_interview(app))

    if applications_sent > 0:
        interview_rate = round(interviews / applications_sent, 4)
    else:
        interview_rate = 0.0

    collected_objectives = _collect_objectives(data, objective, objectives)
    # Stocke le compteur d'entretiens pour objective_check (sans exposer un
    # champ supplémentaire au dataclass contractuel).
    summary = WeeklySummary(
        iso_week=target_week,
        applications_sent=applications_sent,
        responses=responses,
        interview_rate=interview_rate,
        objective_met=None,
        top_actions=[],
    )
    # Attribut auxiliaire (hors contrat) pour les vérifications d'objectif.
    setattr(summary, "_interviews", interviews)

    # Comparaison à l'objectif.
    if collected_objectives:
        met_flags: list[bool] = []
        for obj in collected_objectives:
            if obj.metric == "applications":
                value = applications_sent
            elif obj.metric == "responses":
                value = responses
            elif obj.metric == "interviews":
                value = interviews
            else:
                value = 0
            met_flags.append(value >= obj.target)
        summary.objective_met = all(met_flags) if met_flags else None
    else:
        summary.objective_met = None

    summary.top_actions = recommend_next(
        summary, objective=collected_objectives[0] if collected_objectives else None,
        objectives=collected_objectives[1:] if len(collected_objectives) > 1 else None,
        data=data,
    )
    # Nettoie l'attribut auxiliaire de la représentation publique.
    # On le conserve toutefois pour objective_check basé sur le résumé.
    return summary


def objective_check(
    summary: Any = None,
    objective: Any = None,
    *,
    data: Any = None,
    objectives: Any = None,
    **kwargs: Any,
) -> bool | None:
    """Vérifie si un objectif (ou plusieurs) est atteint.

    Retourne ``None`` si aucun objectif n'est fourni.
    """
    # Résolution flexible des arguments.
    if isinstance(summary, (list, tuple, Mapping)) and not isinstance(summary, WeeklySummary):
        # Premier argument ressemble à des données plutôt qu'à un résumé.
        if data is None:
            data = summary
        summary = None

    for key in ("summary", "weekly_summary", "result"):
        if key in kwargs and kwargs[key] is not None:
            summary = kwargs[key]
    if data is None:
        for key in ("data", "applications", "records", "items"):
            if key in kwargs and kwargs[key] is not None:
                data = kwargs[key]
                break

    if objective is None and objectives is None:
        # Peut être passé via kwargs.
        objective = kwargs.get("objective")
        objectives = kwargs.get("objectives")

    # Collecte des objectifs.
    collected = _collect_objectives(data, objective, objectives)
    # Si le summary est un WeeklySummary portant un objectif ? non.

    # Si aucun objectif collecté, tente depuis summary si c'est un dict.
    if not collected and isinstance(summary, Mapping):
        collected = _collect_objectives(summary, objective, objectives)

    if not collected:
        return None

    # Résout le résumé / les compteurs.
    if isinstance(summary, WeeklySummary):
        ws = summary
    elif isinstance(summary, Mapping):
        # Construit un WeeklySummary partiel depuis le dict.
        try:
            ws = weekly_summary(summary)
        except Exception:
            ws = None
    else:
        if data is not None:
            ws = weekly_summary(data, objective=collected[0] if collected else None)
        else:
            ws = None

    if ws is None:
        return None

    interviews = getattr(ws, "_interviews", None)
    if interviews is None:
        # Recalcule si possible depuis les données.
        interviews = 0

    flags: list[bool] = []
    for obj in collected:
        if obj.metric == "applications":
            value = ws.applications_sent
        elif obj.metric == "responses":
            value = ws.responses
        elif obj.metric == "interviews":
            value = interviews
        else:
            value = 0
        flags.append(value >= obj.target)
    return all(flags) if flags else None


def recommend_next(
    summary: Any = None,
    *,
    objective: Any = None,
    objectives: Any = None,
    data: Any = None,
    **kwargs: Any,
) -> list[str]:
    """Recommande jusqu'à 3 actions pour la semaine suivante."""
    for key in ("summary", "weekly_summary", "result"):
        if key in kwargs and kwargs[key] is not None:
            summary = kwargs[key]
    if data is None:
        for key in ("data", "applications", "records", "items"):
            if key in kwargs and kwargs[key] is not None:
                data = kwargs[key]
                break

    if isinstance(summary, (list, tuple, Mapping)) and not isinstance(summary, WeeklySummary):
        if data is None:
            data = summary
        summary = None

    collected = _collect_objectives(data, objective, objectives)

    if isinstance(summary, WeeklySummary):
        ws = summary
    elif isinstance(summary, Mapping):
        ws = weekly_summary(summary)
    elif data is not None:
        ws = weekly_summary(data, objective=collected[0] if collected else None, objectives=collected[1:] or None)
    else:
        ws = WeeklySummary(iso_week="", applications_sent=0, responses=0, interview_rate=0.0, objective_met=None)

    interviews = getattr(ws, "_interviews", 0)
    try:
        interviews = int(interviews)
    except (TypeError, ValueError):
        interviews = 0

    actions: list[str] = []

    # Objectif applications.
    app_objectives = [o for o in collected if o.metric == "applications"]
    if app_objectives:
        target = app_objectives[0].target
        if target > 0 and ws.applications_sent < target:
            actions.append(
                f"Augmenter le volume : {target - ws.applications_sent} candidature(s) "
                f"manquante(s) pour atteindre l'objectif de {target}."
            )
    elif ws.applications_sent == 0:
        actions.append("Envoyer au moins une candidature cette semaine.")

    # Réponses / relances.
    if ws.applications_sent > 0:
        if ws.responses == 0:
            actions.append("Relancer les candidatures envoyées sans réponse.")
        else:
            rate = ws.responses / ws.applications_sent
            if rate < 0.2:
                actions.append("Améliorer le ciblage : taux de réponse faible, revoir les offres visées.")

    # Entretiens.
    if interviews == 0 and ws.applications_sent > 0:
        actions.append("Préparer les entretiens : aucun entretien obtenu cette semaine.")
    elif collected and any(o.metric == "interviews" for o in collected):
        iv_obj = next(o for o in collected if o.metric == "interviews")
        if interviews < iv_obj.target:
            actions.append(f"Viser {iv_obj.target - interviews} entretien(s) supplémentaire(s).")

    # Actions génériques si pas assez.
    generic = [
        "Mettre à jour le CV pour les offres prioritaires.",
        "Vérifier les dates limites des offres en cours.",
        "Préparer un dossier de candidature réutilisable (lettre + réponses).",
    ]
    for g in generic:
        if len(actions) >= 3:
            break
        if g not in actions:
            actions.append(g)

    # Déduplique et borne à 3.
    unique: list[str] = []
    seen: set[str] = set()
    for action in actions:
        if action in seen:
            continue
        seen.add(action)
        unique.append(action)
        if len(unique) >= 3:
            break
    return unique


def build_weekly_summary(*args, **kwargs) -> WeeklySummary:
    return weekly_summary(*args, **kwargs)


def weekly_review(*args, **kwargs) -> WeeklySummary:
    return weekly_summary(*args, **kwargs)


def weekly_summary_to_dict(summary: WeeklySummary) -> dict[str, Any]:
    data = asdict(summary)
    data.pop("_interviews", None)
    return data


__all__ = [
    "Objective",
    "WeeklySummary",
    "build_weekly_summary",
    "iso_week_string",
    "objective_check",
    "recommend_next",
    "weekly_review",
    "weekly_summary",
    "weekly_summary_to_dict",
]
