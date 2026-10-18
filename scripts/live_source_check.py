"""Run one bounded Career Explorer refresh against the curated public registry.

This maintenance command never reads the user's Career database or profile. It
creates disposable storage, uses the application's real connectors and default
search criteria, then emits a deliberately small report containing public job
facts only. No application, email or message is ever submitted.

Example:
    python -m scripts.live_source_check --json /tmp/come-live-sources.json
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import tempfile
from typing import Any

from career.service import CareerService
from career.source_registry import CURATED_SOURCES
from career.stage_search import STAGE_DOMAINS, default_brief


REPORT_SCHEMA = "come-career-live-source-check/1"


def live_finance_brief() -> dict[str, Any]:
    """Use every declared finance domain while preserving safe defaults."""
    brief = default_brief()
    brief["domains"] = list(STAGE_DOMAINS)
    return brief


def build_report(payload: dict[str, Any], *, source_count: int) -> dict[str, Any]:
    """Reduce an explorer result to public, reviewable evidence."""
    outcomes = []
    for item in payload.get("outcomes", []):
        if not isinstance(item, dict):
            continue
        outcomes.append({key: item.get(key) for key in (
            "source_id", "provider", "company", "status", "attempted", "error_code",
            "raw_count", "evaluated_count", "confirmed_count", "uncertain_count",
            "excluded_count", "relevant_count", "retained_count", "truncated", "verified_at",
        ) if item.get(key) is not None})
    matches = []
    for item in payload.get("matches", []):
        if not isinstance(item, dict) or not isinstance(item.get("job"), dict):
            continue
        job = item["job"]
        qualification = item.get("qualification") if isinstance(item.get("qualification"), dict) else {}
        matches.append({
            "company": job.get("company", ""),
            "title": job.get("title", ""),
            "location": job.get("location", ""),
            "official_url": job.get("official_url", ""),
            "source_name": job.get("source_name", ""),
            "source_id": job.get("source_id", ""),
            "contract_type": qualification.get("contract_type", "unknown"),
            "target_status": qualification.get("target_status", "to_verify"),
            "start_month": qualification.get("start_month"),
            "duration_min_months": qualification.get("duration_min_months"),
            "duration_max_months": qualification.get("duration_max_months"),
            "missing_fields": qualification.get("missing_fields", []),
        })
    return {
        "schema": REPORT_SCHEMA,
        "checked_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "criteria": payload.get("brief", {}),
        "registered_sources_checked": source_count,
        "summary": payload.get("summary", {}),
        "outcomes": outcomes,
        "matches": matches,
        "limitations": [
            "Public feed snapshot only; an employer can change or remove a posting afterwards.",
            "No personal profile was read, so this is criteria qualification, not personal fit.",
            "Missing dates, duration or contract facts remain unknown and are never invented.",
        ],
    }


def _write_new(path: Path, report: dict[str, Any]) -> None:
    path = path.expanduser().resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8") as handle:
        json.dump(report, handle, ensure_ascii=False, indent=2, sort_keys=True)
        handle.write("\n")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--limit", type=int, default=len(CURATED_SOURCES),
                        help="Maximum number of registry sources to consult (default: all curated sources).")
    parser.add_argument("--json", type=Path, help="Create a new JSON report; refuses to overwrite an existing file.")
    args = parser.parse_args()
    if not 1 <= args.limit <= len(CURATED_SOURCES):
        parser.error(f"--limit must be between 1 and {len(CURATED_SOURCES)}")
    sources = tuple(dict(source) for source in CURATED_SOURCES[:args.limit])
    with tempfile.TemporaryDirectory(prefix="come-live-source-check-") as directory:
        service = CareerService(Path(directory), curated_sources=sources)
        service.update_stage_search(live_finance_brief())
        payload = service.explore_internships(force=True)
    report = build_report(payload, source_count=len(sources))
    summary = report["summary"]
    print(
        "Career live source check: "
        f"{summary.get('sources_succeeded', 0)} succeeded, "
        f"{summary.get('sources_failed', 0)} failed, "
        f"{summary.get('sources_not_queried', 0)} not queried, "
        f"{summary.get('retained_count', 0)} retained offers."
    )
    for outcome in report["outcomes"]:
        print(
            f"- {outcome.get('company', outcome.get('source_id', 'unknown'))}: "
            f"{outcome.get('status', 'unknown')} raw={outcome.get('raw_count', 0)} "
            f"retained={outcome.get('retained_count', 0)}"
        )
    if args.json:
        _write_new(args.json, report)
        print(f"New report written to {args.json.expanduser().resolve()}")
    complete = (
        summary.get("sources_succeeded", 0) == len(sources)
        and summary.get("sources_failed", 0) == 0
        and summary.get("sources_not_queried", 0) == 0
    )
    return 0 if complete else 1


if __name__ == "__main__":
    raise SystemExit(main())
