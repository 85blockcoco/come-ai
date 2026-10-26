"""Contrôle de déterminisme des exports DOCX (job ``deterministic-docx``).

Deux exports du même contenu doivent être octet pour octet identiques : sans
cela, chaque génération crée un faux diff, casse les empreintes et empêche de
prouver qu'un document n'a pas été modifié après validation.
"""

from __future__ import annotations

import hashlib
import sys
import tempfile
from pathlib import Path

from career.document_export import write_docx

_DEMO_MARKDOWN = """# Dossier de démonstration

## Profil

- Donnée synthétique A
- Donnée synthétique B

## Motivation

Texte de démonstration, sans donnée personnelle réelle.
"""


def docx_sha256(*, markdown: str = _DEMO_MARKDOWN, title: str = "Démonstration") -> str:
    with tempfile.TemporaryDirectory(prefix="career-docx-") as directory:
        target = Path(directory) / "export.docx"
        write_docx(markdown=markdown, title=title, language="fr", target=target)
        return hashlib.sha256(target.read_bytes()).hexdigest()


def check_deterministic() -> int:
    first = docx_sha256()
    second = docx_sha256()
    if first != second:
        print(f"deterministic-docx : ÉCHEC ({first[:12]}… != {second[:12]}…)")
        return 1
    print(f"deterministic-docx : OK ({first[:12]}…)")
    return 0


def main(argv: list[str] | None = None) -> int:
    arguments = list(sys.argv[1:] if argv is None else argv)
    if arguments and arguments[0] == "check-deterministic":
        return check_deterministic()
    print("Usage : python -m career.docx check-deterministic")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
