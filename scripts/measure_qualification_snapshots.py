#!/usr/bin/env python3
"""Measure and optionally rebuild derived qualification on a copied Career DB.

The command reports aggregate counts only: it never prints company names,
titles, descriptions or profile data.  Use ``--refresh-derived`` only on an
isolated copy because opening an older database performs the normal additive
schema migration and creates a backup beside that copy.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from career.application_prep import summarize_offer  # noqa: E402
from career.offer_qualification import qualify_offer  # noqa: E402
from career.service import CareerService  # noqa: E402


def aggregate(service: CareerService) -> dict:
    jobs = service.list_jobs()
    counts = {
        "offers": len(jobs),
        "snapshots": 0,
        "contract_type": 0,
        "start_month": 0,
        "duration_min_months": 0,
    }
    summary_slots = 0
    for job in jobs:
        summary = summarize_offer(job)
        facts = job.get("qualification_facts") or {}
        counts["snapshots"] += int(bool(facts))
        for field in ("contract_type", "start_month", "duration_min_months"):
            value = summary.get(field)
            present = value not in (None, "", "unknown", "ambiguous")
            counts[field] += int(present)
            summary_slots += int(present)
    denominator = 3 * len(jobs)
    return {
        **counts,
        "qualification_summary_pct": round(100 * summary_slots / denominator, 1) if denominator else 0.0,
    }


def refresh(service: CareerService) -> int:
    jobs = service.list_jobs()
    for job in jobs:
        qualification = qualify_offer(
            job,
            allowed_contract_types=["stage", "cdd", "cdi", "vie"],
            allowed_start_months=[1, 2, 3],
            minimum_stage_duration_months=6,
        ).to_dict()
        service.import_job(
            {**job, "qualification": qualification},
            preserve_unknown_source_fields=True,
        )
    return len(jobs)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-dir", type=Path, required=True)
    parser.add_argument("--refresh-derived", action="store_true")
    args = parser.parse_args()
    service = CareerService(args.base_dir)
    before = aggregate(service)
    refreshed = refresh(service) if args.refresh_derived else 0
    after = aggregate(service)
    print(json.dumps({"before": before, "refreshed": refreshed, "after": after}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
