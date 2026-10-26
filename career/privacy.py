"""Point d'entrée CI du contrôle de confidentialité (job ``privacy-check``)."""

from __future__ import annotations

import sys

from career.ci_guards import privacy_problems, report


def check() -> int:
    return report("privacy-check", privacy_problems())


def main(argv: list[str] | None = None) -> int:
    arguments = list(sys.argv[1:] if argv is None else argv)
    if arguments and arguments[0] == "check":
        return check()
    print("Usage : python -m career.privacy check")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
