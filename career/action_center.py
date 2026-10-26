"""Truthful next-action projection for the local Career pipeline.

This module does not write state, call a model, refresh a source or submit an
application.  It turns already persisted workflow evidence into one bounded,
human-readable next action per offer.
"""

from __future__ import annotations

from datetime import date
from typing import Any

from .models import clean_text


STAGE_PRESENTATION: dict[str, tuple[str, int]] = {
    "discovered": ("Offre découverte", 10),
    "qualified": ("Offre qualifiée", 25),
    "sprint_queued": ("Dans la liste express", 35),
    "prep_analyzed": ("Analyse CV terminée", 50),
    "variant_selected": ("Variante CV choisie", 60),
    "kit_generated": ("Kit local généré", 75),
    "tracking_created": ("Kit et suivi créés", 85),
}

_CLOSED_TRACKING = frozenset({"rejected", "refused", "withdrawn"})
_SUBMITTED_TRACKING = frozenset({"submitted", "submitted_confirmed"})
_PASSIVE_ACTIONS = frozenset({"closed", "deadline_passed", "monitor_response"})
_POST_SUBMISSION_TRACKING = frozenset(
    {
        "submitted",
        "submitted_confirmed",
        "receipt_unknown",
        "response_received",
        "interview",
        "offer_received",
        "rejected",
        "refused",
        "withdrawn",
    }
)
_ACTION_EFFORT_MINUTES: dict[str, int] = {
    "prepare_interview": 25,
    "review_offer": 20,
    "review_response": 10,
    "confirm_receipt": 10,
    "locate_official_source": 15,
    "verify_official_source": 15,
    "manual_submit": 10,
    "final_review": 15,
    "review_kit": 20,
    "create_kit": 30,
    "verify_offer": 20,
    "complete_profile": 25,
    "analyze_offer": 25,
}
_DEFAULT_FOCUS_BUDGET_MINUTES = 60


def _action(
    code: str,
    label: str,
    detail: str,
    priority: int,
) -> tuple[str, str, str, int]:
    return code, label, detail, priority


def project_pipeline_item(
    raw: dict[str, Any],
    *,
    today: date | None = None,
) -> dict[str, Any]:
    """Add a single honest next action to one serialized pipeline item."""

    item = dict(raw)
    stage = clean_text(item.get("stage"), limit=40) or "discovered"
    tracking = clean_text(item.get("tracking_stage"), limit=80)
    readiness = clean_text(item.get("readiness"), limit=80)
    stage_label, progress = STAGE_PRESENTATION.get(stage, ("État à vérifier", 0))
    kit_ready = bool(item.get("kit_generated_at"))
    tracking_exists = bool(item.get("application_id") or tracking)
    can_open_official_source = bool(clean_text(item.get("official_url"), limit=2_000))
    source_verified = bool(item.get("source_verified"))
    source_trust_status = (
        "missing"
        if not can_open_official_source
        else "verified"
        if source_verified
        else "to_verify"
    )
    deadline_date = clean_text(item.get("deadline_date"), limit=32)
    deadline_status = "unknown"
    days_until_deadline: int | None = None
    if deadline_date:
        try:
            parsed_deadline = date.fromisoformat(deadline_date[:10])
        except ValueError:
            parsed_deadline = None
        if parsed_deadline is not None:
            days_until_deadline = (parsed_deadline - (today or date.today())).days
            if days_until_deadline < 0:
                deadline_status = "passed"
            elif days_until_deadline <= 3:
                deadline_status = "urgent"
            else:
                deadline_status = "upcoming"
    blockers: list[str] = []

    if readiness == "offer_to_verify":
        blockers.append("Des faits de l’offre restent à vérifier sur la source officielle.")
    elif readiness == "candidate_to_verify":
        blockers.append("L’éligibilité du profil doit être confirmée avant de préparer le dossier.")
    elif readiness == "profile_to_complete":
        blockers.append("Le profil approuvé ne contient pas encore toutes les preuves nécessaires.")

    if tracking in _CLOSED_TRACKING:
        selected = _action(
            "closed",
            "Aucune action urgente",
            "Cette candidature est clôturée localement ; son historique reste consultable.",
            90,
        )
        progress = 100
    elif tracking == "interview":
        selected = _action(
            "prepare_interview",
            "Préparer l’entretien",
            "Relis l’offre, prépare tes preuves et lance une séance d’entraînement locale.",
            0,
        )
        progress = max(progress, 95)
    elif tracking == "offer_received":
        selected = _action(
            "review_offer",
            "Examiner la proposition",
            "Compare les conditions et conserve ta décision dans le suivi local.",
            5,
        )
        progress = 100
    elif tracking == "response_received":
        selected = _action(
            "review_response",
            "Traiter la réponse reçue",
            "Mets à jour le statut et prépare l’étape suivante sans réponse automatique.",
            10,
        )
        progress = max(progress, 90)
    elif tracking == "receipt_unknown":
        selected = _action(
            "confirm_receipt",
            "Vérifier la réception",
            "Contrôle manuellement le portail ou l’accusé de réception avant toute relance.",
            15,
        )
        progress = max(progress, 85)
    elif tracking in _SUBMITTED_TRACKING:
        selected = _action(
            "monitor_response",
            "Suivre la réponse",
            "La candidature a été déclarée envoyée manuellement ; surveille les réponses et les échéances.",
            70,
        )
        progress = max(progress, 90)
    elif tracking in {"approved_for_manual_submission", "ready_to_apply"} and not can_open_official_source:
        blockers.append("Le lien vers la source officielle manque ; aucun dépôt manuel ne doit commencer sans destination vérifiée.")
        selected = _action(
            "locate_official_source",
            "Retrouver la source officielle",
            "Confirme l’annonce sur le portail officiel avant toute relecture finale ou dépôt manuel.",
            5,
        )
    elif tracking in {"approved_for_manual_submission", "ready_to_apply"} and not source_verified:
        blockers.append(
            "Un lien est présent, mais sa provenance officielle n’est pas encore vérifiée."
        )
        selected = _action(
            "verify_official_source",
            "Vérifier la source officielle",
            "Confirme le domaine et l’annonce d’origine avant toute relecture finale ou dépôt manuel.",
            5,
        )
    elif tracking == "approved_for_manual_submission":
        selected = _action(
            "manual_submit",
            "Déposer manuellement",
            "Le dossier a été approuvé localement. Ouvre la source officielle et effectue toi-même le dépôt.",
            5,
        )
        progress = max(progress, 90)
    elif tracking == "ready_to_apply":
        selected = _action(
            "final_review",
            "Faire la relecture finale",
            "Vérifie les faits, les PDF et la langue avant d’autoriser un dépôt manuel.",
            20,
        )
        progress = max(progress, 80)
    elif kit_ready:
        selected = _action(
            "review_kit",
            "Relire le kit local",
            "Vérifie le CV, la lettre, les marqueurs ouverts et la fiche de préparation.",
            30,
        )
    elif stage in {"prep_analyzed", "variant_selected"} or tracking_exists:
        selected = _action(
            "create_kit",
            "Créer le kit ciblé",
            "Confirme la variante et la langue, puis génère localement le CV et la lettre.",
            40,
        )
    elif readiness in {"offer_to_verify", "candidate_to_verify"}:
        selected = _action(
            "verify_offer",
            "Vérifier l’offre",
            "Confirme les faits manquants sur la page officielle avant de personnaliser le dossier.",
            50,
        )
    elif readiness == "profile_to_complete":
        selected = _action(
            "complete_profile",
            "Compléter les preuves du profil",
            "Ajoute uniquement des faits vérifiables, puis relance l’analyse de correspondance.",
            45,
        )
    else:
        selected = _action(
            "analyze_offer",
            "Analyser l’offre et le CV",
            "Ouvre la préparation pour comparer les exigences au profil approuvé.",
            60,
        )

    code, label, detail, priority = selected
    if deadline_status == "passed" and tracking not in _POST_SUBMISSION_TRACKING:
        blockers.append(
            "La date limite connue est dépassée ; vérifie manuellement si l’annonce accepte encore des candidatures."
        )
        code, label, detail, priority = _action(
            "deadline_passed",
            "Échéance dépassée",
            "Ne prépare aucun dépôt avant d’avoir confirmé que l’offre est toujours ouverte.",
            95,
        )
    elif deadline_status == "urgent" and code not in _PASSIVE_ACTIONS:
        priority = min(priority, 1)
    item.update(
        {
            "stage_label": stage_label,
            "progress_percent": progress,
            "next_action_code": code,
            "next_action_label": label,
            "next_action_detail": detail,
            "action_priority": priority,
            "blockers": blockers,
            "tracking_exists": tracking_exists,
            "kit_ready": kit_ready,
            "can_open_official_source": can_open_official_source,
            "source_trust_status": source_trust_status,
            "deadline_date": deadline_date,
            "deadline_status": deadline_status,
            "days_until_deadline": days_until_deadline,
        }
    )
    return item


def _build_focus_plan(
    projected: list[dict[str, Any]],
    *,
    budget_minutes: int = _DEFAULT_FOCUS_BUDGET_MINUTES,
) -> dict[str, Any]:
    """Select a bounded, deterministic sequence of active local actions."""

    bounded_budget = max(15, min(240, int(budget_minutes)))
    selected: list[dict[str, Any]] = []
    planned_minutes = 0
    active_count = 0
    for item in projected:
        action_code = clean_text(item.get("next_action_code"), limit=80)
        if action_code in _PASSIVE_ACTIONS:
            continue
        active_count += 1
        effort = _ACTION_EFFORT_MINUTES.get(action_code, 20)
        if planned_minutes + effort > bounded_budget:
            continue
        selected.append(
            {
                "job_id": item.get("job_id"),
                "company": item.get("company"),
                "title": item.get("title"),
                "action_code": action_code,
                "action_label": item.get("next_action_label"),
                "estimated_minutes": effort,
                "official_url": item.get("official_url"),
            }
        )
        planned_minutes += effort

    return {
        "budget_minutes": bounded_budget,
        "planned_minutes": planned_minutes,
        "remaining_minutes": bounded_budget - planned_minutes,
        "items": selected,
        "deferred_count": max(0, active_count - len(selected)),
        "automatic_submission": False,
    }


def build_application_action_center(
    items: list[dict[str, Any]],
    *,
    today: date | None = None,
) -> dict[str, Any]:
    """Project, sort and summarize pipeline rows without side effects."""

    projected = [project_pipeline_item(item, today=today) for item in items]
    projected.sort(
        key=lambda item: (
            int(item["action_priority"]),
            -int(item.get("match_score") or 0),
            clean_text(item.get("company"), limit=240).casefold(),
            clean_text(item.get("title"), limit=300).casefold(),
        )
    )
    action_codes = {item["next_action_code"] for item in projected}
    return {
        "pipeline": projected,
        "focus_plan": _build_focus_plan(projected),
        "summary": {
            "total": len(projected),
            "actions_now": sum(item["next_action_code"] not in _PASSIVE_ACTIONS for item in projected),
            "facts_to_verify": sum(item["next_action_code"] == "verify_offer" for item in projected),
            "kits_ready": sum(bool(item["kit_ready"]) for item in projected),
            "tracked": sum(bool(item["tracking_exists"]) for item in projected),
            "interviews": sum(item["next_action_code"] == "prepare_interview" for item in projected),
            "urgent_deadlines": sum(item["deadline_status"] == "urgent" for item in projected),
            "passed_deadlines": sum(item["deadline_status"] == "passed" for item in projected),
            "sources_to_verify": sum(item["source_trust_status"] != "verified" for item in projected),
        },
        "available_actions": sorted(action_codes),
        "automatic_submission": False,
        "disclaimer": (
            "Ce centre organise uniquement des actions locales et manuelles. "
            "Côme AI ne dépose jamais de candidature, n’envoie jamais d’e-mail et ne transforme jamais une inconnue en fait."
        ),
    }
