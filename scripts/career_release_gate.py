#!/usr/bin/env python3
"""Fail-closed, machine-readable Career release verification."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
REPORT = ROOT / "artifacts" / "career-release-gate.json"


def run(name: str, command: list[str]) -> dict[str, object]:
    started = datetime.now(timezone.utc)
    result = subprocess.run(command, cwd=ROOT, text=True, capture_output=True, check=False)
    output = (result.stdout + result.stderr).strip()
    return {
        "name": name,
        "status": "passed" if result.returncode == 0 else "failed",
        "returncode": result.returncode,
        "duration_seconds": round((datetime.now(timezone.utc) - started).total_seconds(), 3),
        "command": command,
        "output_tail": output[-8_000:],
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--quick", action="store_true", help="Skip the full suite; result cannot be PASS.")
    args = parser.parse_args()
    python = os.environ.get("CAREER_GATE_PYTHON", sys.executable)
    ruff = os.environ.get("CAREER_GATE_RUFF", "")
    if not ruff:
        candidates = [ROOT / ".venv/bin/ruff", ROOT.parent / "AI-Excel-Agent/.venv/bin/ruff"]
        ruff = next((str(path) for path in candidates if path.is_file()), "")

    checks = [
        run("tracked_diff", ["git", "diff", "--exit-code", "--", ".", ":(exclude)artifacts"]),
        run("staged_diff", ["git", "diff", "--cached", "--exit-code"]),
        run("compile", [python, "-m", "compileall", "-q", "career"]),
        run(
            "matching",
            [python, "-m", "pytest", "-q", "tests/test_cv_matching_actions.py", "tests/test_cv_matching_adversarial.py", "-p", "no:cacheprovider"],
        ),
        run(
            "release_contracts",
            [python, "-m", "pytest", "-q", "tests/test_dependencies.py", "tests/test_constitution.py", "tests/test_offer_intelligence_adversarial.py", "tests/test_cv_review.py", "-p", "no:cacheprovider"],
        ),
    ]
    if ruff:
        checks.append(run("ruff", [ruff, "check", "career", "tests", "scripts/career_release_gate.py"]))
    else:
        checks.append({"name": "ruff", "status": "failed", "reason": "ruff executable unavailable"})
    if args.quick:
        checks.append({"name": "full_suite", "status": "skipped", "reason": "--quick requested"})
    else:
        checks.append(run("full_suite", [python, "-m", "pytest", "-q", "-p", "no:cacheprovider"]))

    metadata = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "branch": subprocess.check_output(["git", "branch", "--show-current"], cwd=ROOT, text=True).strip(),
        "sha": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip(),
        "python": subprocess.check_output([python, "--version"], cwd=ROOT, text=True, stderr=subprocess.STDOUT).strip(),
        "quick": args.quick,
    }
    passed = all(check.get("status") == "passed" for check in checks)
    payload = {"verdict": "PASS" if passed else "FAIL", "metadata": metadata, "checks": checks}
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"Career release gate: {payload['verdict']}")
    for check in checks:
        print(f"- {check['name']}: {check['status']}")
    print(REPORT)
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
