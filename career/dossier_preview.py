"""Dossier preview (N100-G08).

Renders a read-only textual preview of an application kit: documents present,
order of documents, placeholders for missing items.  Nothing is exported or
sent here.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Iterable


@dataclass
class DossierPreview:
    dossier_id: str
    lines: list[str] = field(default_factory=list)
    document_count: int = 0
    warnings: list[str] = field(default_factory=list)


def build_preview(
    *,
    dossier_id: str,
    documents: Iterable[tuple[str, str]] = (),
    stage_summary: str = "",
    letter_summary: str = "",
) -> DossierPreview:
    prev = DossierPreview(dossier_id=dossier_id)
    docs = list(documents or [])
    prev.document_count = len(docs)
    prev.lines.append(f"DOSSIER {dossier_id}")
    prev.lines.append("Poste / offre résumé : " + (stage_summary or "(non fourni)"))
    prev.lines.append("Lettre : " + (letter_summary or "(non fournie)"))
    if not docs:
        prev.warnings.append("aucun document fourni")
    prev.lines.append("Documents :")
    for name, status in docs:
        mark = "OK " if str(status).lower() == "present" else "[MANQUANT]"
        prev.lines.append(f"  - {mark} {name}")
    missing_docs = [n for n, s in docs if str(s).lower() != "present"]
    if missing_docs:
        prev.warnings.append(f"{len(missing_docs)} document(s) manquant(s)")
    prev.lines.append("")
    return prev


def to_dict(p: DossierPreview) -> dict[str, Any]:
    return asdict(p)
