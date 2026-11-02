"""Propositions de cartes à partir de notes locales, avec citation obligatoire."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
from pathlib import Path

from .models import Card


@dataclass(frozen=True)
class NoteProposal:
    proposal_id: str
    topic: str
    front: str
    back: str
    citation: str
    status: str = "à approuver"


def propose_cards(text: str, *, source_name: str = "notes.txt", topic: str = "VC") -> list[NoteProposal]:
    if not isinstance(text, str) or len(text) > 2_000_000:
        raise ValueError("Les notes doivent être du texte UTF-8 borné.")
    proposals: list[NoteProposal] = []
    for line_number, raw in enumerate(text.splitlines(), start=1):
        line = raw.strip()
        if not line or ":" not in line:
            continue
        front, back = (part.strip() for part in line.split(":", 1))
        if len(front) < 3 or len(back) < 3:
            continue
        citation = f"{source_name}:ligne {line_number} — {line}"
        identifier = hashlib.sha256(citation.encode("utf-8")).hexdigest()[:16]
        proposals.append(NoteProposal(identifier, topic, front, back, citation))
    return proposals


def approve_proposal(proposal: NoteProposal) -> Card:
    if proposal.status != "à approuver" or not proposal.citation.strip():
        raise ValueError("La proposition doit être approuvée une seule fois avec une citation.")
    return Card(proposal.proposal_id, proposal.topic, proposal.front, proposal.back, proposal.citation, approved=True)


def extract_note_lines(path: str | Path) -> list[tuple[str, str]]:
    """Extrait des lignes citables depuis TXT/MD/PDF/DOCX, localement."""
    source = Path(path).expanduser().absolute()
    if source.is_symlink() or not source.is_file() or source.stat().st_size > 20_000_000:
        raise ValueError("Le support doit être un fichier local réel et inférieur à 20 Mo.")
    suffix = source.suffix.casefold()
    if suffix in {".txt", ".md"}:
        return [(f"{source.name}:ligne {number}", line.strip()) for number, line in enumerate(source.read_text(encoding="utf-8").splitlines(), 1) if line.strip()]
    if suffix == ".pdf":
        try:
            from pypdf import PdfReader
            pages = PdfReader(str(source)).pages
        except (ImportError, OSError, ValueError) as error:
            raise ValueError("Le PDF n'a pas pu être lu localement.") from error
        return [(f"{source.name}:page {page_number}:ligne {line_number}", line.strip())
                for page_number, page in enumerate(pages, 1)
                for line_number, line in enumerate((page.extract_text() or "").splitlines(), 1) if line.strip()]
    if suffix == ".docx":
        try:
            from docx import Document
            paragraphs = Document(str(source)).paragraphs
        except (ImportError, OSError, ValueError) as error:
            raise ValueError("Le DOCX n'a pas pu être lu localement.") from error
        return [(f"{source.name}:paragraphe {number}", paragraph.text.strip())
                for number, paragraph in enumerate(paragraphs, 1) if paragraph.text.strip()]
    raise ValueError("Format de cours non supporté : TXT, MD, PDF ou DOCX attendu.")


def propose_cards_from_file(path: str | Path, *, topic: str = "VC") -> list[NoteProposal]:
    """Ne propose que des définitions contenant ``:`` et conserve la citation."""
    proposals: list[NoteProposal] = []
    for citation, line in extract_note_lines(path):
        if ":" not in line:
            continue
        front, back = (part.strip() for part in line.split(":", 1))
        if len(front) < 3 or len(back) < 3:
            continue
        proposal_id = hashlib.sha256(f"{citation} — {line}".encode("utf-8")).hexdigest()[:16]
        proposals.append(NoteProposal(proposal_id, topic, front, back, f"{citation} — {line}"))
    return proposals
