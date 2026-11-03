"""Bridge between the VC revision coach and the Côme AI Study Coach.

The bridge is deliberately one-way and read-only: it exports VC progress
(drills, cases, past papers, radar) as a JSON payload that the Study Coach
engine can consume through its ``InMemoryDocumentSource`` / ``document_from_text``
contract.  It never writes to the Study Coach store and never imports it at
module import time, so the VC coach stays usable without it.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .content import load_content
from .mastery import mastery_radar
from .storage import VcStore


def build_study_coach_payload(store: VcStore, *, today: str | None = None) -> dict[str, Any]:
    """Build a Study Coach-compatible payload from VC data."""

    from .dates import today_iso

    day = today or today_iso()
    content = load_content()
    records = mastery_radar(
        content,
        store.load_reviews(),
        today=day,
        case_attempts=store.load_case_attempts(),
        exam_results=store.load_exam_history(),
        drill_attempts=store.load_drill_attempts(),
        paper_attempts=store.load_paper_attempts(),
        progress=store.load_progress(),
    )
    documents = []
    for topic in content.topics:
        record = next((r for r in records if r.topic_id == topic.id), None)
        documents.append(
            {
                "document_id": f"vc_{topic.id}",
                "title": topic.title_en,
                "text": topic.description or topic.title_en,
                "source_id": f"vc:{topic.id}",
                "metadata": {
                    "topic_id": topic.id,
                    "status": record.status if record else "untested",
                    "attempts": record.attempts if record else 0,
                    "accuracy": record.accuracy if record else None,
                },
            }
        )
    return {
        "schema_version": 1,
        "source": "nage-vc",
        "generated_at": day,
        "exam_date": store.load_settings().get("exam_date"),
        "documents": documents,
        "stats": {
            "topics": len(content.topics),
            "drills": len(content.drills),
            "cases": len(content.cases),
            "drill_attempts": len(store.load_drill_attempts()),
            "paper_attempts": len(store.load_paper_attempts()),
            "case_attempts": len(store.load_case_attempts()),
        },
        "radar": [r.to_dict() for r in records],
    }


def write_study_coach_payload(store: VcStore, destination: Path, *, today: str | None = None) -> Path:
    destination = Path(destination).expanduser()
    destination.parent.mkdir(parents=True, exist_ok=True)
    payload = build_study_coach_payload(store, today=today)
    destination.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return destination