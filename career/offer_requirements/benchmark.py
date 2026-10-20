"""Short deterministic benchmark over the bundled synthetic offers.

Run with:  ``PYTHONPATH=. python -m career.offer_requirements.benchmark``

The benchmark measures what the contract promises, not a vague score: per
fixture it reports how many requirements were extracted and how each field
of the contract was used, plus the wall-clock cost of ``analyze_offer`` (no
network, no model — timings only reflect pure Python parsing).  Timing lines
are informative; the counts must be stable because the package is
deterministic.
"""

from __future__ import annotations

import time
from typing import Any

from .extract import analyze_offer
from .fixtures import load_fixtures


def run_benchmark() -> dict[str, Any]:
    """Analyze every bundled fixture once and aggregate contract usage."""
    fixtures = load_fixtures()
    per_offer: list[dict[str, Any]] = []
    totals = {
        "offers": 0,
        "requirements": 0,
        "required": 0,
        "preferred": 0,
        "contextual": 0,
        "unknown": 0,
        "categories": 0,
        "duplicates": 0,
        "contradictions": 0,
        "deadlines": 0,
        "injection_suspects": 0,
        "locators_resolved": 0,
    }
    started = time.perf_counter()
    for offer in fixtures:
        began = time.perf_counter()
        analysis = analyze_offer(offer)
        elapsed_ms = (time.perf_counter() - began) * 1000
        requirements = analysis["requirements"]
        by_modality = analysis["stats"]["by_modality"]
        by_category = analysis["stats"]["by_category"]
        per_offer.append(
            {
                "offer_id": offer.get("id", ""),
                "language": offer.get("language", ""),
                "requirements": len(requirements),
                "by_modality": by_modality,
                "categories": by_category,
                "duplicates": len(analysis["duplicates"]),
                "contradictions": len(analysis["contradictions"]),
                "injection_suspects": len(analysis["injection_suspects"]),
                "truncated": analysis["truncated"],
                "deadline_iso": (analysis["application_deadline"] or {}).get("date_iso"),
                "elapsed_ms": round(elapsed_ms, 3),
            }
        )
        totals["offers"] += 1
        totals["requirements"] += len(requirements)
        totals["required"] += by_modality.get("required", 0)
        totals["preferred"] += by_modality.get("preferred", 0)
        totals["contextual"] += by_modality.get("contextual", 0)
        totals["unknown"] += by_modality.get("unknown", 0)
        totals["duplicates"] += len(analysis["duplicates"])
        totals["contradictions"] += len(analysis["contradictions"])
        totals["injection_suspects"] += len(analysis["injection_suspects"])
        totals["deadlines"] += 1 if analysis["application_deadline"] else 0
        if (analysis["application_deadline"] or {}).get("date_iso"):
            totals["locators_resolved"] += 1
    total_ms = (time.perf_counter() - started) * 1000
    return {
        "summary": totals,
        "categories_used": sorted(
            {
                category
                for entry in per_offer
                for category in entry["categories"]
            }
        ),
        "max_single_analysis_ms": round(
            max(entry["elapsed_ms"] for entry in per_offer), 3
        ) if per_offer else 0.0,
        "total_ms": round(total_ms, 3),
        "per_offer": per_offer,
    }


def main() -> None:  # pragma: no cover - human-facing entry point
    report = run_benchmark()
    summary = report["summary"]
    print("career.offer_requirements benchmark")
    print(
        f"  offers={summary['offers']} requirements={summary['requirements']}"
        f" (required={summary['required']}, preferred={summary['preferred']},"
        f" contextual={summary['contextual']}, unknown={summary['unknown']})"
    )
    print(
        f"  duplicates={summary['duplicates']} contradictions={summary['contradictions']}"
        f" deadlines={summary['deadlines']} injection_suspects={summary['injection_suspects']}"
    )
    print(f"  categories used: {', '.join(report['categories_used'])}")
    print(
        f"  timing: total={report['total_ms']}ms, worst single analysis="
        f"{report['max_single_analysis_ms']}ms (pure local parsing, no network)"
    )


if __name__ == "__main__":  # pragma: no cover
    main()
