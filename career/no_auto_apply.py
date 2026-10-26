"""Point d'entrée CI du contrôle « aucune candidature automatique » (job ``no-auto-apply``)."""

from __future__ import annotations

import sys

from career.ci_guards import no_auto_apply_problems, report


def check() -> int:
    return report("no-auto-apply", no_auto_apply_problems())


def main(argv: list[str] | None = None) -> int:
    arguments = list(sys.argv[1:] if argv is None else argv)
    if arguments and arguments[0] == "check":
        return check()
    print("Usage : python -m career.no_auto_apply check")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
