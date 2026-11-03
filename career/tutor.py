"""Source-grounded, deterministic course tutor.

This tutor intentionally does not call an LLM.  It composes an answer from
retrieved corpus excerpts and always returns citations.  A question with no
local evidence is an explicit refusal, never a best-effort general answer.
"""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass
from typing import Any

from .ingest import CorpusIndex, SourceChunk

MIN_EVIDENCE_SCORE = 0.08
_SENTENCE_RE = re.compile(r"(?<=[.!?])\s+|\n+")


@dataclass(frozen=True)
class Citation:
    source: str
    page: int | str
    section: str
    excerpt: str
    chunk_id: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class TutorResponse:
    question: str
    mode: str
    answer: str
    citations: list[Citation]
    refused: bool
    refusal_reason: str = ""
    local_only: bool = True
    steps: list[str] | None = None
    understanding_check: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "question": self.question,
            "mode": self.mode,
            "answer": self.answer,
            "citations": [item.to_dict() for item in self.citations],
            "refused": self.refused,
            "refusal_reason": self.refusal_reason,
            "local_only": self.local_only,
            "steps": self.steps or [],
            "understanding_check": self.understanding_check,
        }


class TutorEngine:
    MODES = {"explanation", "reformulation", "example", "beginner", "conversation", "did_not_understand", "je_n_ai_pas_compris"}

    def __init__(self, index: CorpusIndex):
        self.index = index

    @staticmethod
    def _relevant_sentences(question: str, chunks: list[SourceChunk]) -> list[str]:
        terms = {item.lower() for item in re.findall(r"[\wÀ-ÿ]+", question) if len(item) > 2}
        candidates: list[tuple[int, str]] = []
        for chunk in chunks:
            for sentence in _SENTENCE_RE.split(chunk.text):
                sentence = sentence.strip()
                if not sentence:
                    continue
                score = sum(1 for term in terms if term in sentence.lower())
                candidates.append((score, sentence))
        candidates.sort(key=lambda item: (-item[0], len(item[1])))
        answer: list[str] = []
        seen: set[str] = set()
        for _, sentence in candidates:
            key = sentence.lower()
            if key in seen:
                continue
            seen.add(key)
            answer.append(sentence)
            if len(answer) >= 4:
                break
        return answer

    def ask(self, question: str, *, mode: str = "explanation", limit: int = 3) -> TutorResponse:
        normalized = str(question or "").strip()
        mode = str(mode or "explanation").strip().lower()
        if not normalized:
            return TutorResponse(normalized, mode, "", [], True, "La question est vide.")
        if mode not in self.MODES:
            return TutorResponse(normalized, mode, "", [], True, "Mode de tutorat inconnu.")
        chunks = self.index.search(normalized, limit=max(2, min(limit, 5)))
        if not chunks or chunks[0].score < MIN_EVIDENCE_SCORE:
            return TutorResponse(
                normalized,
                mode,
                "Je ne peux pas répondre à partir du corpus de cours autorisé.",
                [],
                True,
                "Aucune preuve locale suffisante dans le corpus.",
            )
        sentences = self._relevant_sentences(normalized, chunks)
        if not sentences:
            return TutorResponse(normalized, mode, "", [], True, "Le corpus ne contient pas d'extrait exploitable.")
        lead = {
            "explanation": "D’après le cours :",
            "reformulation": "Reformulation fidèle du cours :",
            "example": "Exemple présent dans le corpus ou directement illustré par celui-ci :",
            "beginner": "Version débutant, sans ajouter d’information extérieure :",
            "conversation": "On avance pas à pas à partir du cours :",
            "did_not_understand": "Reprenons plus simplement, sans ajouter d’information extérieure :",
            "je_n_ai_pas_compris": "Reprenons plus simplement, sans ajouter d’information extérieure :",
        }[mode]
        if mode in {"beginner", "did_not_understand", "je_n_ai_pas_compris"}:
            body = " ".join(sentences[:2])
        elif mode == "example":
            body = " ".join(sentences)
        else:
            body = " ".join(sentences[:3])
        citations = [
            Citation(PathName(chunk.source_path), chunk.page_start if chunk.page_start == chunk.page_end else f"{chunk.page_start}-{chunk.page_end}", chunk.section, chunk.text[:500].strip(), chunk.chunk_id)
            for chunk in chunks
        ]
        steps = [f"Étape {number} : {sentence}" for number, sentence in enumerate(sentences[:3], start=1)] if mode in {"conversation", "did_not_understand", "je_n_ai_pas_compris"} else None
        check = "Peux-tu reformuler cette idée avec les termes du cours ?" if mode in {"conversation", "did_not_understand", "je_n_ai_pas_compris"} else ""
        return TutorResponse(normalized, mode, f"{lead} {body}", citations, False, steps=steps, understanding_check=check)


def PathName(path: str) -> str:
    """Return only a corpus-relative file name, never a private absolute path."""
    return path.replace("\\", "/").rsplit("/", 1)[-1]


def ask_tutor(index: CorpusIndex, question: str, *, mode: str = "explanation") -> dict[str, Any]:
    return TutorEngine(index).ask(question, mode=mode).to_dict()


__all__ = ["Citation", "TutorEngine", "TutorResponse", "ask_tutor"]
