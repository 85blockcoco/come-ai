#!/usr/bin/env python3
"""Read one real CV locally and print the facts it would propose.

This script is the *manual* counterpart of the automated tests: it works on
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

from career.profile_builder import build_source_document, propose_facts  # noqa: E402
from career.candidate_profile import verify_profile, CandidateProfile  # noqa: E402


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
        raise SystemExit(f"Le fichier n’existe pas : {path}")
    _refuse_repository_files(path)

    if arguments.text_file:
        document, spans = build_source_document(
            filename=path.name,
            filetype="txt",
            text=path.read_text(encoding="utf-8", errors="replace"),
            created_at="",
        )
    else:
        suffix = path.suffix.lower()
        filetype = {".pdf": "pdf", ".docx": "docx", ".txt": "txt"}.get(suffix)
        if filetype is None:
            raise SystemExit("Format accepté : PDF, DOCX ou TXT.")
        document, spans = build_source_document(
            filename=path.name,
            filetype=filetype,
            data=path.read_bytes(),
            created_at="",
        )

    facts = propose_facts(document, spans, created_at="")
    profile = CandidateProfile(document=document, facts=facts)

    print(f"Document      : {document.filename} ({document.filetype})")
    print(f"Extraction    : {document.extraction}")
    print(f"Pages         : {document.page_count}")
    print(f"Faits proposés: {len(facts)} (aucun n'est approuvé)")
    print()
    for fact in facts:
        page = fact.provenance.page or "?"
        print(f"- [{fact.kind}] {fact.label}")
        print(f"    valeur : {fact.value}")
        print(f"    source : page {page} · « {fact.provenance.quote} »")
        if fact.attributes:
            print(f"    détail : {fact.attributes}")
    print()

    problems = verify_profile(profile)
    if problems:
        print("Anomalies de provenance :")
        for problem in problems:
            print(f"  ! {problem}")
        return 1
    print("Toutes les sources citées correspondent exactement au document lu.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
