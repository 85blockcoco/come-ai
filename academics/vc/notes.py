"""Turn local course notes into cited cards that require explicit approval."""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

from .cases import normalize_text
from .dates import now_iso, stable_id
from .errors import InputError
from .models import Flashcard, NoteSource, ProposedCard
from .storage import SCHEMA_VERSION, VcStore

MAX_NOTE_BYTES = 2 * 1024 * 1024
NOTICE = "Aucune carte n'est active avant une approbation explicite."
SUPPORTED_KINDS = {".txt": "txt", ".md": "md", ".markdown": "md", ".pdf": "pdf"}
STOP_TERMS = {
    "attention",
    "bareme",
    "chapitre",
    "date",
    "duree",
    "exemple",
    "exemples",
    "exercice",
    "exercices",
    "note",
    "notes",
    "objectif",
    "objectifs",
    "q",
    "question",
    "r",
    "rappel",
    "reference",
    "remarque",
    "reponse",
    "section",
    "source",
}

_HEADING = re.compile(r"^\s{0,3}#{1,6}\s+(?P<title>.+?)\s*#*\s*$")
_BULLET = re.compile(r"^\s*[-*•]\s+(?P<body>.+?)\s*$")
_BOLD = re.compile(r"\*\*(?P<text>.+?)\*\*")
_BOLD_DEFINITION = re.compile(
    r"^\s*(?:[-*•]\s*)?\*\*(?P<term>.+?)\*\*\s*(?::|—|–)\s*(?P<definition>.+?)\s*$"
)
_COLON_DEFINITION = re.compile(
    r"^\s*(?:[-*•]\s*)?(?P<term>[^:：]{2,90})\s*[:：]\s*(?P<definition>.{8,})$"
)
_DASH_DEFINITION = re.compile(
    r"^\s*(?:[-*•]\s*)?(?P<term>[^—–]{2,90})\s*[—–]\s*(?P<definition>.{8,})$"
)
_QUESTION = re.compile(
    r"^\s*(?:[-*•]\s*)?(?:Q|Question)\s*[:：]\s*(?P<text>.+?)\s*$", re.IGNORECASE
)
_ANSWER = re.compile(
    r"^\s*(?:[-*•]\s*)?(?:R|Réponse|Reponse|A|Answer)\s*[:：]\s*(?P<text>.*?)\s*$",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class _Candidate:
    question: str
    answer: str | None
    locator: str
    quote: str


def _normalize_source(text: str) -> str:
    return text.replace("\r\n", "\n").replace("\r", "\n").lstrip("\ufeff")


def _clean(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip()


def _clean_term(value: str) -> str:
    return _clean(value.strip(" \t*_`“”\"'"))


def _kind(filename: str) -> str:
    suffix = Path(filename).suffix.lower()
    kind = SUPPORTED_KINDS.get(suffix)
    if kind is None:
        raise InputError("Unsupported notes format: use .txt, .md or .pdf.")
    return kind


def _locator(line_number: int, page: int, *, pdf: bool, end: int | None = None) -> str:
    prefix = f"p. {page}, " if pdf else ""
    if end is None or end == line_number:
        return f"{prefix}ligne {line_number}"
    return f"{prefix}lignes {line_number}-{end}"


def _valid_term(term: str) -> bool:
    if not 2 <= len(term) <= 90:
        return False
    if "?" in term or "=" in term or "://" in term:
        return False
    if term.lower() in STOP_TERMS:
        return False
    if re.fullmatch(r"[\d\s.,%€$]+", term):
        return False
    return True


def _valid_definition(definition: str) -> bool:
    return len(definition) >= 8 and not definition.lower().startswith(("http://", "https://"))


def _add(
    candidates: list[_Candidate],
    *,
    question: str,
    answer: str | None,
    locator: str,
    quote: str,
) -> None:
    question = _clean(question)
    if len(question) < 8:
        return
    candidates.append(
        _Candidate(
            question=question,
            answer=_clean(answer) if answer and answer.strip() else None,
            locator=locator,
            quote=quote.strip(),
        )
    )


def _extract_candidates(text: str, *, pdf: bool = False) -> list[_Candidate]:
    """Extract only patterns whose answer is explicitly present in the notes."""
    lines = text.split("\n")
    candidates: list[_Candidate] = []
    heading = ""
    page = 1
    index = 0
    while index < len(lines):
        raw = lines[index]
        if raw.strip() == "\f":
            page += 1
            index += 1
            continue
        line = raw.strip()
        if not line:
            index += 1
            continue

        heading_match = _HEADING.match(raw)
        if heading_match:
            heading = _clean_term(heading_match.group("title"))
            index += 1
            continue

        question_match = _QUESTION.match(line)
        if question_match:
            question = _clean(question_match.group("text"))
            answer: str | None = None
            end = index
            for lookahead in range(index + 1, min(index + 3, len(lines))):
                candidate_line = lines[lookahead].strip()
                if not candidate_line or candidate_line == "\f":
                    continue
                answer_match = _ANSWER.match(candidate_line)
                if answer_match:
                    answer = answer_match.group("text")
                    end = lookahead
                break
            quote = "\n".join(lines[item] for item in range(index, end + 1)).strip()
            _add(
                candidates,
                question=question,
                answer=answer,
                locator=_locator(index + 1, page, pdf=pdf, end=end + 1),
                quote=quote,
            )
            index = end + 1
            continue

        bullet_match = _BULLET.match(line)
        body = bullet_match.group("body").strip() if bullet_match else ""
        bold = _BOLD.search(body) if body else None
        if bullet_match and bold and body[: bold.start()].strip():
            term = _clean_term(bold.group("text"))
            if _valid_term(term):
                blanked = f"{body[: bold.start()]}_____{body[bold.end() :]}"
                _add(
                    candidates,
                    question=f"Complete: {blanked}",
                    answer=term if heading else None,
                    locator=_locator(index + 1, page, pdf=pdf),
                    quote=line,
                )
                index += 1
                continue

        definition_match = (
            _BOLD_DEFINITION.match(line)
            or _COLON_DEFINITION.match(line)
            or _DASH_DEFINITION.match(line)
        )
        if definition_match:
            term = _clean_term(definition_match.group("term"))
            definition = _clean(definition_match.group("definition"))
            if _valid_term(term) and _valid_definition(definition):
                _add(
                    candidates,
                    question=f"Que signifie « {term} » ?",
                    answer=definition,
                    locator=_locator(index + 1, page, pdf=pdf),
                    quote=line,
                )
                index += 1
                continue

        if bullet_match and heading:
            pattern = re.compile(re.escape(heading), re.IGNORECASE)
            found = pattern.search(body)
            if found:
                blanked = f"{body[: found.start()]}_____{body[found.end() :]}"
                _add(
                    candidates,
                    question=f"Complete: {blanked}",
                    answer=found.group(0),
                    locator=_locator(index + 1, page, pdf=pdf),
                    quote=line,
                )
        index += 1
    return candidates


def _read_text_file(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except UnicodeDecodeError as error:
        raise InputError("Notes must be a UTF-8 text file.") from error
    except OSError as error:
        raise InputError(f"Lecture impossible : {path.name}") from error


def _read_pdf_file(path: Path) -> str:
    try:
        from pypdf import PdfReader
    except ImportError as error:  # pragma: no cover - dependency is pinned
        raise InputError("Reading PDF requires pypdf.") from error
    try:
        reader = PdfReader(str(path))
        pages = [page.extract_text() or "" for page in reader.pages]
    except Exception as error:  # pypdf raises several concrete error types
        raise InputError(f"PDF illisible : {path.name}") from error
    text = "\n\f\n".join(pages)
    if not text.replace("\f", "").strip():
        raise InputError(
            "PDF sans texte extractible (scan ?). Importez une version texte ou OCR."
        )
    return text


def read_note_file(path: Path) -> tuple[str, str]:
    """Read a supported note file and return its normalized text and kind."""
    path = Path(path).expanduser()
    try:
        size = path.stat().st_size
    except FileNotFoundError as error:
        raise InputError(f"File not found: {path}") from error
    except OSError as error:
        raise InputError(f"Lecture impossible : {path.name}") from error
    if size > MAX_NOTE_BYTES:
        raise InputError("Notes trop volumineuses : limite de 2 Mo par fichier.")
    kind = _kind(path.name)
    text = _read_pdf_file(path) if kind == "pdf" else _read_text_file(path)
    normalized = _normalize_source(text)
    if not normalized.strip():
        raise InputError("Le fichier de notes est vide.")
    return normalized, kind


def _signature(topic_id: str, question: str) -> str:
    return stable_id("sig", topic_id, normalize_text(question))


def _load_index(
    store: VcStore,
) -> tuple[dict[str, NoteSource], dict[str, ProposedCard], set[str]]:
    raw = store.load_note_index()
    sources: dict[str, NoteSource] = {}
    for key, item in raw["sources"].items():
        if not isinstance(item, dict):
            continue
        try:
            sources[str(key)] = NoteSource.from_dict(item)
        except (TypeError, ValueError):
            store.warnings.append("Unreadable notes source ignored.")
    proposals: dict[str, ProposedCard] = {}
    for key, item in raw["proposals"].items():
        if not isinstance(item, dict):
            continue
        try:
            proposals[str(key)] = ProposedCard.from_dict(item)
        except (TypeError, ValueError):
            store.warnings.append("Unreadable local proposal ignored.")
    return sources, proposals, set(raw["rejected_signatures"])


def _save_index(
    store: VcStore,
    sources: dict[str, NoteSource],
    proposals: dict[str, ProposedCard],
    rejected: Iterable[str],
) -> None:
    store.save_note_index(
        {
            "schema_version": SCHEMA_VERSION,
            "sources": {
                source_id: source.to_dict()
                for source_id, source in sorted(sources.items())
            },
            "proposals": {
                proposal_id: proposal.to_dict()
                for proposal_id, proposal in sorted(proposals.items())
            },
            "rejected_signatures": sorted(set(rejected)),
        }
    )


def _refresh_source_status(
    source: NoteSource | None, proposals: Iterable[ProposedCard]
) -> None:
    if source is None or source.status == "superseded":
        return
    statuses = {
        proposal.status
        for proposal in proposals
        if proposal.source_id == source.source_id
    }
    if statuses and statuses <= {"approved", "rejected"}:
        source.status = "reviewed"


def ingest_notes(
    store: VcStore,
    text: str,
    *,
    filename: str,
    topic_id: str,
    replace: bool = False,
) -> dict[str, Any]:
    """Extract cited proposals and store the source snapshot locally."""
    if not re.fullmatch(r"VC\d{2}", topic_id):
        raise InputError("Topic attendu au format VCxx.")
    name = Path(filename).name
    if not name:
        raise InputError("Nom de fichier de notes manquant.")
    kind = _kind(name)
    normalized = _normalize_source(text)
    if not normalized.strip():
        raise InputError("Le fichier de notes est vide.")
    if len(normalized.encode("utf-8")) > MAX_NOTE_BYTES:
        raise InputError("Notes trop volumineuses : limite de 2 Mo par fichier.")

    digest = hashlib.sha256(normalized.encode("utf-8")).hexdigest()
    sources, proposals, rejected = _load_index(store)
    existing = next(
        (
            source
            for source in sources.values()
            if source.filename == name and source.status != "superseded"
        ),
        None,
    )
    if existing is not None and existing.sha256 != digest:
        if not replace:
            raise InputError(
                f'The source "{name}" has changed since the last import; '
                "rerun with --replace to re-import it."
            )
        existing.status = "superseded"
        for proposal_id, proposal in list(proposals.items()):
            if proposal.source_id == existing.source_id and proposal.status in {
                "proposed",
                "a_completer",
            }:
                del proposals[proposal_id]
        store.remove_note_text(existing.source_id)

    source = sources.get(digest)
    if source is None:
        source = NoteSource(
            source_id=digest,
            filename=name,
            kind=kind,
            imported_at=now_iso(),
            sha256=digest,
            line_count=len(normalized.splitlines()),
            status="imported",
        )
        sources[digest] = source
    elif source.status == "superseded":
        source.status = "imported"

    source_proposals = {
        proposal_id: proposal
        for proposal_id, proposal in proposals.items()
        if proposal.source_id == source.source_id
    }
    seen_questions = {
        normalize_text(proposal.question) for proposal in source_proposals.values()
    }
    deck_questions = {
        normalize_text(card.question) for card in store.load_deck()
    }
    created = 0
    duplicates = 0
    rejected_skipped = 0
    for candidate in _extract_candidates(normalized, pdf=kind == "pdf"):
        question_key = normalize_text(candidate.question)
        signature = _signature(topic_id, candidate.question)
        if signature in rejected:
            rejected_skipped += 1
            continue
        if question_key in seen_questions or question_key in deck_questions:
            duplicates += 1
            continue
        proposal_id = stable_id(
            "prop", source.source_id, candidate.locator, question_key
        )
        proposal = ProposedCard(
            proposal_id=proposal_id,
            source_id=source.source_id,
            topic_id=topic_id,
            question=candidate.question,
            answer=candidate.answer,
            citation={
                "source_id": source.source_id,
                "locator": candidate.locator,
                "quote": candidate.quote,
            },
            status="a_completer" if candidate.answer is None else "proposed",
        )
        proposals[proposal_id] = proposal
        source_proposals[proposal_id] = proposal
        seen_questions.add(question_key)
        created += 1

    store.save_note_text(source.source_id, normalized)
    _save_index(store, sources, proposals, rejected)
    ordered = [
        proposal.to_dict()
        for proposal in sorted(
            source_proposals.values(), key=lambda item: item.proposal_id
        )
    ]
    return {
        "source": source.to_dict(),
        "proposals": ordered,
        "created": created,
        "duplicates": duplicates,
        "rejected_skipped": rejected_skipped,
        "notice": NOTICE,
    }


def ingest_file(
    store: VcStore,
    path: Path,
    *,
    topic_id: str,
    replace: bool = False,
) -> dict[str, Any]:
    text, _ = read_note_file(path)
    return ingest_notes(
        store,
        text,
        filename=Path(path).name,
        topic_id=topic_id,
        replace=replace,
    )


def list_notes(store: VcStore) -> dict[str, Any]:
    sources, proposals, _ = _load_index(store)
    ordered_sources = sorted(
        sources.values(), key=lambda source: (source.imported_at, source.filename)
    )
    items: list[dict[str, Any]] = []
    counts = {"proposed": 0, "a_completer": 0, "approved": 0, "rejected": 0}
    for proposal in sorted(proposals.values(), key=lambda item: item.proposal_id):
        item = proposal.to_dict()
        source = sources.get(proposal.source_id)
        item["filename"] = source.filename if source else ""
        items.append(item)
        if proposal.status in counts:
            counts[proposal.status] += 1
    return {
        "sources": [source.to_dict() for source in ordered_sources],
        "proposals": items,
        "counts": counts,
        "notice": NOTICE,
    }


def approve_proposal(
    store: VcStore, proposal_id: str, *, answer: str | None = None
) -> Flashcard:
    """Approve one proposal and add the resulting card to the active deck."""
    sources, proposals, rejected = _load_index(store)
    proposal = proposals.get(proposal_id)
    if proposal is None:
        raise InputError(f"Proposal not found: {proposal_id}")
    if proposal.status == "rejected":
        raise InputError("This proposal was rejected; it cannot be approved.")
    card_id = stable_id("vcnote", proposal.proposal_id)
    deck = {card.id: card for card in store.load_deck()}
    if proposal.status == "approved" and card_id in deck:
        return deck[card_id]
    final_answer = _clean(answer if answer is not None else proposal.answer or "")
    if not final_answer:
        raise InputError(
            'Missing answer: this proposal is "to be completed". '
            "Rerun with --answer to complete it."
        )
    citation = {
        key: str(proposal.citation.get(key, ""))
        for key in ("source_id", "locator", "quote")
    }
    if not all(citation.values()):
        raise InputError("Incomplete source citation; proposal cannot be approved.")
    card = Flashcard(
        id=card_id,
        topic_id=proposal.topic_id,
        question=proposal.question,
        answer=final_answer,
        source_type="user_note",
        citation=citation,
        status="active",
        tags=("notes",),
    )
    deck[card.id] = card
    store.save_deck(list(deck.values()))
    proposal.status = "approved"
    proposal.answer = final_answer
    _refresh_source_status(sources.get(proposal.source_id), proposals.values())
    _save_index(store, sources, proposals, rejected)
    return card


def reject_proposal(store: VcStore, proposal_id: str) -> None:
    """Record a rejection so the same question is not proposed again."""
    sources, proposals, rejected = _load_index(store)
    proposal = proposals.get(proposal_id)
    if proposal is None:
        raise InputError(f"Proposal not found: {proposal_id}")
    if proposal.status == "approved":
        raise InputError(
            "Proposal already approved; the active card cannot be rejected here."
        )
    proposal.status = "rejected"
    rejected.add(_signature(proposal.topic_id, proposal.question))
    _refresh_source_status(sources.get(proposal.source_id), proposals.values())
    _save_index(store, sources, proposals, rejected)
