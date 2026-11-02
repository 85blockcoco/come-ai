"""Propositions de cartes à partir de notes locales, avec citation obligatoire."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib

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
