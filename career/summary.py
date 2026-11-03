"""Corpus-grounded chapter fiches and local PDF export."""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from .ingest import CorpusIndex, SourceChunk


@dataclass(frozen=True)
class ChapterSummary:
    chapter: str
    definitions: list[str]
    formulas: list[str]
    key_points: list[str]
    citations: list[dict[str, Any]]
    local_only: bool = True

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


_DEFINITION_RE = re.compile(r"(?:\bis\b|\bmeans\b|\brefers to\b|\bcorrespond à\b|\bdésigne\b|:)" , re.IGNORECASE)
_FORMULA_RE = re.compile(r"(?:=|\bIRR\b|\bMOIC\b|\bpre-money\b|\bpost-money\b|\bownership\b|\bdilution\b|\bVAN\b)", re.IGNORECASE)


def _sentences(chunks: list[SourceChunk]) -> list[tuple[str, SourceChunk]]:
    items: list[tuple[str, SourceChunk]] = []
    for chunk in chunks:
        for part in re.split(r"(?<=[.!?])\s+|\n+", chunk.text):
            clean = re.sub(r"\s+", " ", part).strip(" -•\t")
            if len(clean) >= 20:
                items.append((clean, chunk))
    return items


def build_summary(index: CorpusIndex, chapter: str, *, limit: int = 20) -> ChapterSummary:
    chunks = index.chunks_for_section(chapter)
    if not chunks:
        chunks = index.search(chapter, limit=limit)
    sentences = _sentences(chunks)
    definitions: list[str] = []
    formulas: list[str] = []
    key_points: list[str] = []
    for sentence, _ in sentences:
        if _DEFINITION_RE.search(sentence) and len(definitions) < 8:
            definitions.append(sentence)
        if _FORMULA_RE.search(sentence) and len(formulas) < 8:
            formulas.append(sentence)
        if sentence not in definitions and sentence not in formulas and len(key_points) < 10:
            key_points.append(sentence)
    citations = []
    seen: set[str] = set()
    for chunk in chunks:
        if chunk.chunk_id in seen:
            continue
        seen.add(chunk.chunk_id)
        citations.append(chunk.citation())
        if len(citations) >= 8:
            break
    return ChapterSummary(chapter, definitions, formulas, key_points, citations)


def export_summary_pdf(summary: ChapterSummary, destination: str | Path) -> Path:
    """Export a summary using reportlab, with no network or document upload."""
    try:
        from reportlab.lib.pagesizes import A4
        from reportlab.lib.styles import getSampleStyleSheet
        from reportlab.lib.units import cm
        from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer
    except ImportError as error:  # pragma: no cover - packaging failure
        raise RuntimeError("L’export PDF nécessite reportlab localement.") from error
    path = Path(destination)
    path.parent.mkdir(parents=True, exist_ok=True)
    styles = getSampleStyleSheet()
    story: list[Any] = [Paragraph(f"Fiche — {summary.chapter}", styles["Title"]), Spacer(1, 0.35 * cm)]
    for title, values in (("Définitions", summary.definitions), ("Formules", summary.formulas), ("Points clés", summary.key_points)):
        story.append(Paragraph(title, styles["Heading2"]))
        for value in values or ["Aucun élément retrouvé dans le corpus pour cette rubrique."]:
            story.append(Paragraph(f"• {value}", styles["BodyText"]))
            story.append(Spacer(1, 0.12 * cm))
    story.append(Paragraph("Sources locales : " + "; ".join(f"{item['source']} p.{item['page']}" for item in summary.citations), styles["BodyText"]))
    SimpleDocTemplate(str(path), pagesize=A4, rightMargin=1.7 * cm, leftMargin=1.7 * cm, topMargin=1.5 * cm, bottomMargin=1.5 * cm).build(story)
    return path


def export_plan_pdf(plan: dict[str, Any], destination: str | Path) -> Path:
    """Export the current mastery-based revision plan as a local PDF."""
    try:
        from reportlab.lib.pagesizes import A4
        from reportlab.lib.styles import getSampleStyleSheet
        from reportlab.lib.units import cm
        from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer
        from xml.sax.saxutils import escape
    except ImportError as error:  # pragma: no cover - packaging failure
        raise RuntimeError("L’export PDF nécessite reportlab localement.") from error
    path = Path(destination)
    path.parent.mkdir(parents=True, exist_ok=True)
    styles = getSampleStyleSheet()
    sessions = plan.get("sessions", [])
    story: list[Any] = [
        Paragraph("Plan de révision Venture Capital", styles["Title"]),
        Paragraph(f"Du {escape(str(plan.get('start', '—')))} au {escape(str(plan.get('until', '—')))}", styles["BodyText"]),
        Spacer(1, 0.35 * cm),
    ]
    for session in sessions:
        story.append(Paragraph(f"{escape(str(session.get('date', '')))} — {escape(str(session.get('chapter', 'Chapitre')))}", styles["Heading2"]))
        story.append(Paragraph(escape(str(session.get("phase", "Révision"))).replace("_", " "), styles["BodyText"]))
        activities = session.get("activities", [])
        for activity in activities:
            story.append(Paragraph(f"• {escape(str(activity))}", styles["BodyText"]))
        story.append(Spacer(1, 0.2 * cm))
    if not sessions:
        story.append(Paragraph("Aucune session n’est planifiée.", styles["BodyText"]))
    SimpleDocTemplate(str(path), pagesize=A4, rightMargin=1.7 * cm, leftMargin=1.7 * cm, topMargin=1.5 * cm, bottomMargin=1.5 * cm).build(story)
    return path


__all__ = ["ChapterSummary", "build_summary", "export_plan_pdf", "export_summary_pdf"]
