#!/usr/bin/env python3
"""Read one real CV locally and print the facts the pipeline would propose.

This script is the *manual* counterpart of the automated tests: it works on a
document the person owns, outside the repository, so that no real document and
no personal data ever reaches the Git fixtures.

It never writes anything, never sends anything over the network and never
approves a fact: it only shows what the local pipeline would propose, with the
exact passage (page, offsets, quote) each fact comes from.

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

from career.cv_quality.parser import extract_pages_from_bytes  # noqa: E402
from career.profile_builder import build_fact_proposals  # noqa: E402


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


def _read_pages(path: Path) -> tuple[str, list[str] | None]:
    """Read one local document and return its text and its pages."""
    suffix = path.suffix.lower()
    if suffix == ".txt":
        text = path.read_text(encoding="utf-8", errors="replace")
        return text, None
    if suffix in {".pdf", ".docx"}:
        filetype = suffix.lstrip(".")
        pages = extract_pages_from_bytes(path.read_bytes(), filetype)
        return "\n\n".join(pages), pages
    raise SystemExit(f"Format non pris en charge : {suffix} (PDF, DOCX ou TXT).")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("document", nargs="?", help="Chemin d'un CV PDF, DOCX ou TXT.")
    parser.add_argument(
        "--text-file",
        help="Lire le document comme du texte brut au lieu d'un format binaire.",
    )
    arguments = parser.parse_args()

    source = arguments.text_file or arguments.document
    if not source:
        parser.error("Indique un document (ou --text-file).")

    path = Path(source).expanduser()
    if not path.is_file():
        raise SystemExit(f"Le fichier n’existe pas : {path}")
    _refuse_repository_files(path)

    text, pages = _read_pages(path)
    facts = build_fact_proposals(text, filename=path.name, pages=pages)

    print(f"Document : {path.name}")
    print(f"Faits proposés : {len(facts)}")
    print("Aucun fait n'est approuvé ici : tout passe par la relecture de l'interface.\n")
    for fact in facts:
        evidence = fact.evidence
        page = f"page {evidence.page}" if evidence.page else "page inconnue"
        if evidence.page_confidence != "exact":
            page += " (estimée)"
        print(f"- [{fact.kind}] {fact.label}" + (f" — {fact.value}" if fact.value else ""))
        print(f"    {page} · caractères {evidence.start_offset}–{evidence.end_offset}")
        print(f"    « {evidence.quote} »")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
