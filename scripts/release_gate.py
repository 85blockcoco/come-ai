#!/usr/bin/env python3
"""Run the Career end-to-end release gate and print a deterministic report.

Usage:
    python scripts/release_gate.py [--base-dir DIR] [--no-browser] [--live]
                                   [--json] [--output PATH]

The default is fully local: no public source is contacted, no application is
submitted and no cloud provider is called.
"""

from __future__ import annotations

import argparse
import sys
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from career.release_gate import render_report, run_release_gate  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Career end-to-end release gate")
    parser.add_argument(
        "--base-dir",
        type=Path,
        default=None,
        help="Répertoire de données (défaut : dossier temporaire jetable).",
    )
    parser.add_argument(
        "--no-browser",
        action="store_true",
        help="Ne pas revendiquer de preuve navigateur (le check est alors SKIP).",
    )
    parser.add_argument(
        "--live",
        action="store_true",
        help="Autoriser une mesure live d'une source publique (désactivé par défaut).",
    )
    parser.add_argument("--json", action="store_true", help="Sortie JSON au lieu du markdown.")
    parser.add_argument("--output", type=Path, default=None, help="Écrire le rapport dans ce fichier.")
    args = parser.parse_args(argv)

    temporary: tempfile.TemporaryDirectory[str] | None = None
    base_dir = args.base_dir
    if base_dir is None:
        temporary = tempfile.TemporaryDirectory(prefix="career-release-gate-")
        base_dir = Path(temporary.name)

    try:
        report = run_release_gate(base_dir, browser=not args.no_browser, live=args.live)
        rendered = render_report(report, as_json=args.json)
        if args.output is not None:
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_text(rendered, encoding="utf-8")
        sys.stdout.write(rendered)
        if not rendered.endswith("\n"):
            sys.stdout.write("\n")
        return 0 if report.ok else 1
    finally:
        if temporary is not None:
            temporary.cleanup()


if __name__ == "__main__":
    raise SystemExit(main())
