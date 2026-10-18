"""Deterministic readiness of the local Career profile.

This is deliberately not a recruitment score.  It only reports whether the
local facts needed to compare offers and prepare factual documents are present.
Missing values never become inferred candidate facts.
"""

from __future__ import annotations

from typing import Any

from .models import clean_text


_FIELDS: tuple[tuple[str, str, int], ...] = (
    ("education", "Formation et niveau d’étude", 4),
    ("experience", "Expériences factuelles", 4),
    ("skills", "Compétences factuelles", 4),
    ("languages", "Langues et niveaux", 2),
    ("eligibility", "Éligibilité / autorisation de travail", 2),
    ("display_name", "Nom d’affichage", 1),
    ("contact", "E-mail ou téléphone", 1),
    ("linkedin_url", "Profil LinkedIn public", 1),
    ("target_companies", "Entreprises ou cibles préférées", 1),
)


def _present(profile: dict[str, Any], field: str) -> bool:
    if field == "contact":
        return bool(clean_text(profile.get("contact_email")) or clean_text(profile.get("contact_phone")))
    if field == "eligibility":
        return clean_text(profile.get(field), limit=40) in {"compatible", "incompatible"}
    return bool(clean_text(profile.get(field), limit=8_000))


def assess_profile_readiness(profile: dict[str, Any] | None) -> dict[str, Any]:
    """Return a transparent 0–20 readiness note from explicitly stored facts."""
    facts = profile if isinstance(profile, dict) else {}
    components: list[dict[str, Any]] = []
    known_fields: list[str] = []
    missing_fields: list[dict[str, Any]] = []
    for field, label, weight in _FIELDS:
        present = _present(facts, field)
        components.append({
            "field": field,
            "label": label,
            "points": weight if present else 0,
            "maximum": weight,
            "status": "known" if present else "missing",
        })
        if present:
            known_fields.append(field)
        else:
            missing_fields.append({"field": field, "label": label, "points_available": weight})
    score = sum(int(item["points"]) for item in components)
    if score >= 16:
        label = "Profil prêt pour personnaliser les candidatures"
    elif score >= 10:
        label = "Profil utilisable, encore améliorable"
    elif score:
        label = "Profil partiel"
    else:
        label = "Profil à compléter"
    next_actions = [
        f"Ajouter : {item['label']} (+{item['points_available']} point{'s' if item['points_available'] > 1 else ''})."
        for item in missing_fields[:4]
    ]
    return {
        "score_out_of_20": score,
        "maximum_score": 20,
        "label": label,
        "components": components,
        "known_fields": known_fields,
        "missing_fields": missing_fields,
        "next_actions": next_actions,
        "disclaimer": (
            "Cette note mesure uniquement la complétude des faits locaux utiles. "
            "Ce n’est ni une probabilité d’embauche, ni une évaluation de ta valeur."
        ),
    }

