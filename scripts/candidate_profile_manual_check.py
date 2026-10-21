#!/usr/bin/env python3
"""Read one real CV locally and print the facts the pipeline would propose.

This script is the *manual* counterpart of the automated tests.  It works on
a document the person owns, outside the repository, so no real document and
no real personal data ever reaches the Git fixtures.

It never writes anything, never sends anything over the network and never
approves a fact: it only shows what the local pipeline would propose, with
the exact passage each fact comes from.

Usage::

    python scripts/candidate_profile_manual_check.py ~/Documents/mon-cv.pdf
    python scripts/candidate_profile_manual_check.py --text-file ~/cv.txt
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from career.profile_builder import propose_profile_facts  # noqa: E402


def _refuse_repository_files(path: Path) -> None:
    """Refuse to read a file stored inside the repository.

    A real CV must never end up in the Git history, not even by accident.
    """
    try:
        path.resolve().relative_to(ROOT.resolve())
    except ValueError:
        return
    raise SystemExit(
        "Ce fichier est dans le dépôt : un document réel ne doit jamais y entrer. "
        "Copie-le hors du dépôt et relance le script."
    )


def _read_document(path: Path) -> tuple[str, list[str]]:
    """Read a local document and return its text and its pages."""
    from career.cv_quality.parser import extract_pages_from_bytes

    suffix = path.suffix.lower()
    filetype = {".pdf": "pdf", ".docx": "docx", ".txt": "txt", ".md": "txt"}.get(suffix)
    if filetype is None:
        raise SystemExit("Format non pris en charge : utilise un PDF, DOCX, TXT ou MD.")
    pages = extract_pages_from_bytes(path.read_bytes(), filetype)
    return "\n\n".join(page.text for page in pages), [page.text for page in pages]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("document", nargs="?", help="Path of a PDF, DOCX or TXT CV.")
    parser.add_argument(
        "--text-file",
        help="Read the document as plain text instead of parsing a binary format.",
    )
    arguments = parser.parse_args()

    source = arguments.text_file or arguments.document
    if not source:
        parser.error("Indique un document (ou --text-file).")

    path = Path(source).expanduser()
    if not path.is_file():
        raise SystemExit(f"Fichier introuvable : {path}")
    _refuse_repository_files(path)

    if arguments.text_file:
        text = path.read_text(encoding="utf-8", errors="replace")
        pages = [text]
    else:
        text, pages = _read_document(path)

    facts = propose_profile_facts(text, pages=pages, source_name=path.name)
    if not facts:
        print("Aucune proposition n’a pu être lue dans ce document.")
        return 0

    print(f"{len(facts)} proposition(s) — aucune n’est approuvée.\n")
    for fact in facts:
        provenance = fact.provenance
        page = provenance.page if provenance and provenance.page else "?"
        start = provenance.start_offset if provenance else 0
        end = provenance.end_offset if provenance else 0
        print(f"[{fact.kind_label}] {fact.label}")
        print(f"    page {page} · caractères {start}–{end}")
        if provenance and provenance.quote:
            print(f"    source : {provenance.quote}")
        print()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
