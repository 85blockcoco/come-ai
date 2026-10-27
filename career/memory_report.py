"""Read-only dashboard and Markdown export for personal style memory (SPEC-023).

The report is derived entirely from :class:`career.personal_memory.StyleMemoryStore`.
It never writes to the store, calls a model, or reaches the network.
"""

from __future__ import annotations

from typing import Any

from .memory_types import SOURCE_LABELS
from .personal_memory import MemoryStoreError, StyleMemoryStore


def build_report(store: StyleMemoryStore) -> dict[str, Any]:
    """Build the JSON payload used by ``GET /memory/report`` and the UI."""
    try:
        preferences = [item.to_dict() for item in store.list_preferences()]
        choices = [item.to_dict() for item in store.list_choices()]
        glossary = [item.to_dict() for item in store.glossary()]
        stats = store.stats()
        top_constraints = store.constraints(5)
        degraded = False
        warning = None
    except MemoryStoreError as error:
        preferences = []
        choices = []
        glossary = []
        top_constraints = []
        degraded = True
        warning = str(error)
        stats = {
            "preferences_count": 0,
            "auto_applied_count": 0,
            "glossary_count": 0,
            "choices_count": 0,
            "undone_choices_count": 0,
            "path_is_private": True,
        }
    return {
        "degraded": degraded,
        "warning": warning,
        "generation_allowed": not degraded,
        "stats": stats,
        "preferences": preferences,
        "top_constraints": top_constraints,
        "auto_applied": [item for item in preferences if item["auto_applied"]],
        "glossary": glossary,
        "choices": choices,
        "sources": SOURCE_LABELS,
    }


def render_markdown(report: dict[str, Any]) -> str:
    """Human-readable summary suitable for a local report or an agent note."""
    lines = ["# Mémoire personnelle de style", ""]
    if report.get("degraded"):
        lines.extend(
            [
                "> **Mémoire dégradée.** Aucune préférence n’est appliquée et aucune génération ne doit être lancée.",
                f"> {report.get('warning') or 'Fichier illisible.'}",
                "",
            ]
        )
    stats = report.get("stats", {})
    lines.extend(
        [
            "## Synthèse",
            "",
            f"- Préférences : {stats.get('preferences_count', 0)}",
            f"- Appliquées automatiquement : {stats.get('auto_applied_count', 0)}",
            f"- Entrées de glossaire : {stats.get('glossary_count', 0)}",
            f"- Choix enregistrés : {stats.get('choices_count', 0)}",
            f"- Choix annulés : {stats.get('undone_choices_count', 0)}",
            "",
            "## Préférences",
            "",
        ]
    )
    preferences = report.get("preferences", [])
    if not preferences:
        lines.append("_Aucune préférence enregistrée._")
    else:
        lines.extend(["| Clé | Valeur | Confiance | Source | Auto |", "| --- | --- | --- | --- | --- |"])
        for item in preferences:
            lines.append(
                "| {key} | {value} | {confidence:.0%} | {source} | {auto} |".format(
                    key=item["key"],
                    value=str(item["value"]).replace("|", "\\|"),
                    confidence=float(item["confidence"]),
                    source=item.get("source_label", item["source"]),
                    auto="oui" if item.get("auto_applied") else "non",
                )
            )
    lines.extend(["", "## Glossaire", ""])
    glossary = report.get("glossary", [])
    if not glossary:
        lines.append("_Aucun terme de glossaire._")
    else:
        for entry in glossary:
            lines.append(f"- **{entry['term']}** — {entry['definition']}")
    lines.extend(["", "## Historique récent", ""])
    choices = report.get("choices", [])[:10]
    if not choices:
        lines.append("_Aucun choix enregistré._")
    else:
        for choice in choices:
            state = "annulé" if choice.get("undone") else "actif"
            lines.append(f"- {choice['created_at']} — {choice['context']} ({state})")
    lines.append("")
    return "\n".join(lines)
