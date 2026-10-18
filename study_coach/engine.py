"""``StudyCoach``: the one object Codex needs to plug a Révisions mode into Côme AI.

The complete journey is six calls::

    syllabus   = coach.ingest_course(text, title="…")
    session    = coach.start_session(syllabus.id, size=8)
    question   = coach.next_question(session.id)
    correction = coach.submit_answer(session.id, question["id"], value)
    report     = coach.complete_session(session.id)
    progress   = coach.progress()

Everything is local, deterministic and inspectable: a correction can always be
explained by the passage of the course it came from, and a session interrupted
half-way can be resumed exactly where it stopped.
"""

from __future__ import annotations

import uuid
from datetime import date
from pathlib import Path
from typing import Any, Iterable

from .errors import SessionError, StudyCoachError, SyllabusError
from .grading import grade_answer
from .llm import ensure_model_calls_allowed
from .models import (
    AnswerRecord,
    Correction,
    DifficultNotion,
    ReviewSession,
    ScheduleEntry,
    StudyDocument,
    Syllabus,
    clean_text,
    utc_now,
)
from .questions import DEFAULT_FAMILIES, build_session_questions
from .scheduler import new_entry, plan_due, recommend_from_answers, update_entry
from .sources import DocumentSource, document_from_text
from .store import StudyCoachStore
from .syllabus import build_syllabus


def _new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:12]}"


class StudyCoach:
    """Engine of the Study Coach module (offline by default)."""

    def __init__(
        self,
        store: StudyCoachStore,
        *,
        generator: Any = None,
        allow_model_calls: bool = False,
        today: date | None = None,
    ) -> None:
        self.store = store
        self.generator = generator
        self.allow_model_calls = bool(allow_model_calls)
        self.today = today

    # ------------------------------------------------------------------ #
    # Construction
    # ------------------------------------------------------------------ #

    @classmethod
    def open(
        cls,
        base_dir: str | Path,
        *,
        generator: Any = None,
        allow_model_calls: bool = False,
        today: date | None = None,
    ) -> "StudyCoach":
        return cls(
            StudyCoachStore(base_dir),
            generator=generator,
            allow_model_calls=allow_model_calls,
            today=today,
        )

    def close(self) -> None:
        self.store.close()

    def __enter__(self) -> "StudyCoach":
        return self

    def __exit__(self, *exc_info: Any) -> None:
        self.close()

    # ------------------------------------------------------------------ #
    # 1. Course -> revision programme
    # ------------------------------------------------------------------ #

    def ingest_course(
        self,
        text: str | None = None,
        *,
        document: StudyDocument | None = None,
        title: str = "",
        source_id: str = "",
        requested_topics: Iterable[str] = (),
        max_notions: int = 24,
        notions_per_session: int = 5,
        save: bool = True,
    ) -> Syllabus:
        """Build (and store) the revision programme of one course.

        Either ``text`` or an already-built ``document`` is expected.  A source
        identifier may be supplied to keep the citation of the Côme AI document
        store; otherwise a stable content-based one is computed.
        """

        if document is None:
            document = document_from_text(text or "", title=title, source_id=source_id)
        elif source_id:
            document.source_id = source_id

        syllabus = build_syllabus(
            document,
            max_notions=max_notions,
            notions_per_session=notions_per_session,
            requested_topics=requested_topics,
        )
        if save:
            self.store.save_syllabus(syllabus)
        return syllabus

    def ingest_source(
        self,
        document_id: str,
        source: DocumentSource,
        **kwargs: Any,
    ) -> Syllabus:
        """Ingest a course coming from any :class:`DocumentSource` adapter."""

        document = source.load_document(document_id)
        return self.ingest_course(document=document, **kwargs)

    def get_syllabus(self, syllabus_id: str) -> Syllabus:
        syllabus = self.store.get_syllabus(syllabus_id)
        if syllabus is None:
            raise SyllabusError(f"Programme de révision inconnu : {syllabus_id}.")
        return syllabus

    def list_courses(self) -> list[dict[str, Any]]:
        return self.store.list_syllabi()

    # ------------------------------------------------------------------ #
    # 2. Questions & sessions
    # ------------------------------------------------------------------ #

    def start_session(
        self,
        syllabus_id: str,
        *,
        size: int = 8,
        program_index: int | None = None,
        due_only: bool = False,
        mode: str = "revision_initiale",
        per_notion: int = 2,
        families: Iterable[str] = DEFAULT_FAMILIES,
        distractors: int = 3,
    ) -> ReviewSession:
        """Create a persisted review session from a programme of revision."""

        syllabus = self.get_syllabus(syllabus_id)
        if not syllabus.notions:
            raise SyllabusError(
                f"Le cours « {syllabus.title} » ne contient aucune notion exploitable : "
                "ajoute le passage manquant avant de réviser."
            )
        notion_ids = self._select_notions(syllabus, program_index=program_index, due_only=due_only)
        questions = build_session_questions(
            syllabus,
            notion_ids,
            target_size=size,
            per_notion=per_notion,
            families=families,
            distractors=distractors,
        )
        moment = utc_now()
        session = ReviewSession(
            id=_new_id("sess"),
            syllabus_id=syllabus.id,
            title=f"{syllabus.title} — {mode.replace('_', ' ')}",
            mode=clean_text(mode, limit=40) or "revision_initiale",
            status="preparee",
            questions=questions,
            current_index=0,
            created_at=moment,
            updated_at=moment,
        )
        self.store.save_session(session)
        return session

    def _select_notions(
        self,
        syllabus: Syllabus,
        *,
        program_index: int | None,
        due_only: bool,
    ) -> list[str]:
        priorities = {notion.id: notion.importance for notion in syllabus.notions}
        if due_only:
            due = plan_due(self.store.list_schedule(), today=self.today, limit=50, priorities=priorities)
            due_ids = [item["item_key"] for item in due if item["kind"] == "notion"]
            selected = [notion_id for notion_id in due_ids if syllabus.notion(notion_id) is not None]
            if selected:
                return selected
        if program_index is not None:
            for step in syllabus.program:
                if step.get("index") == int(program_index):
                    return list(step.get("notion_ids") or [])
            raise SyllabusError(f"Séance de programme inconnue : {program_index}.")
        if syllabus.program:
            return list(syllabus.program[0].get("notion_ids") or [])
        return [notion.id for notion in syllabus.notions]

    def resume_session(self, session_id: str) -> ReviewSession:
        """Reload a session exactly as it was left, questions included."""

        return self._require_session(session_id)

    def next_question(self, session_id: str) -> dict[str, Any] | None:
        """The next question to answer, as shown to the learner (no answer key)."""

        session = self._require_session(session_id)
        if session.status == "terminee":
            return None
        pending = session.pending_questions()
        if not pending:
            return None
        return pending[0].to_public_dict()

    def _require_session(self, session_id: str) -> ReviewSession:
        session = self.store.get_session(session_id)
        if session is None:
            raise SessionError(f"Séance de révision inconnue : {session_id}.")
        return session

    # ------------------------------------------------------------------ #
    # 3. Answers & corrections
    # ------------------------------------------------------------------ #

    def submit_answer(
        self,
        session_id: str,
        question_id: str,
        value: Any,
        *,
        replace: bool = False,
    ) -> Correction:
        """Record one answer and return its verifiable correction."""

        session = self._require_session(session_id)
        if session.status == "terminee":
            raise SessionError("Cette séance est terminée : Démarrer une nouvelle séance pour continuer.")
        question = session.question(question_id)
        if question is None:
            raise SessionError(f"Question inconnue pour cette séance : {question_id}.")
        existing = self.store.find_answer(session_id, question_id)
        if existing is not None and not replace:
            raise SessionError(
                f"Une réponse est déjà enregistrée pour {question_id} : utilise replace=True pour la corriger."
            )

        correction = grade_answer(question, value)
        moment = utc_now()
        self.store.record_answer(
            AnswerRecord(
                id=existing.id if existing else _new_id("ans"),
                session_id=session_id,
                question_id=question_id,
                notion_id=question.notion_id,
                value=value,
                answered_at=moment,
                status=correction.status,
                score=correction.score,
                validation=correction.validation,
                syllabus_id=session.syllabus_id,
            )
        )

        index = session.question_ids.index(question_id)
        session.current_index = max(session.current_index, index + 1)
        session.status = "en_cours"
        session.updated_at = moment
        if not session.pending_questions():
            session.status = "terminee"
            session.completed_at = moment
        self.store.save_session(session)

        self._update_schedule(question.notion_id, correction.status)
        return correction

    def _update_schedule(self, notion_id: str, status: str) -> None:
        if not notion_id:
            return
        entry = self.store.get_schedule(notion_id) or new_entry(notion_id, kind="notion")
        self.store.upsert_schedule(update_entry(entry, status, today=self.today))

    def complete_session(self, session_id: str) -> dict[str, Any]:
        """Close a session and summarise what must be revised next."""

        session = self._require_session(session_id)
        pending = session.pending_questions()
        if pending:
            raise SessionError(
                f"Il reste {len(pending)} question(s) sans réponse : réponds-les avant de clore la séance."
            )
        session.status = "terminee"
        session.completed_at = session.completed_at or utc_now()
        session.updated_at = utc_now()
        self.store.save_session(session)
        return self.session_report(session_id)

    def session_report(self, session_id: str) -> dict[str, Any]:
        session = self._require_session(session_id)
        answers = self.store.list_answers(session_id=session_id)
        by_status: dict[str, int] = {}
        for answer in answers:
            by_status[answer["status"]] = by_status.get(answer["status"], 0) + 1
        to_review = [
            answer["notion_id"] for answer in answers if answer["status"] in {"incorrect", "partiel", "non_evaluable"}
        ]
        return {
            "session_id": session.id,
            "title": session.title,
            "status": session.status,
            "answered": session.current_index,
            "total": len(session.questions),
            "by_status": by_status,
            "notions_to_review": sorted(set(to_review)),
            "completed_at": session.completed_at,
        }

    # ------------------------------------------------------------------ #
    # 4. Progress & active revision
    # ------------------------------------------------------------------ #

    def progress(self, *, syllabus_id: str = "", limit: int = 5) -> dict[str, Any]:
        """Local progress: sessions, questions, accuracy, weak notions, next steps."""

        stats = self.store.stats()
        answers = self.store.list_answers(syllabus_id=syllabus_id or "", limit=100_000)
        difficult = self.difficult_notions(answers, limit=limit)
        recommendation = self.recommended_review(syllabus_id=syllabus_id, limit=limit)
        return {
            "stats": stats,
            "notions_to_review": difficult,
            "recommended_revision": recommendation,
            "sessions": self.store.list_sessions(syllabus_id=syllabus_id, limit=20),
        }

    def difficult_notions(self, answers: Iterable[dict[str, Any]], *, limit: int = 5) -> list[dict[str, Any]]:
        ranked = recommend_from_answers(answers, limit=limit)
        result: list[dict[str, Any]] = []
        for item in ranked:
            title = item["notion_id"]
            syllabus_id = item.get("syllabus_id") or self._syllabus_of(item["notion_id"])
            syllabus = self.store.get_syllabus(syllabus_id) if syllabus_id else None
            if syllabus is not None:
                notion = syllabus.notion(item["notion_id"])
                if notion is not None:
                    title = notion.title
            result.append(
                DifficultNotion(
                    notion_id=item["notion_id"],
                    title=title,
                    seen=item["seen"],
                    correct=item["correct"],
                    incorrect=item["incorrect"],
                    accuracy=item["accuracy"],
                    last_seen_at=item["last_failure_at"],
                ).to_dict()
            )
        return result

    def _syllabus_of(self, notion_id: str) -> str:
        for row in self.store.list_syllabi(limit=100_000):
            syllabus = self.store.get_syllabus(row["id"])
            if syllabus is not None and syllabus.notion(notion_id) is not None:
                return syllabus.id
        return ""

    def recommended_review(self, *, syllabus_id: str = "", limit: int = 10) -> list[dict[str, Any]]:
        """Notions to revise today, ranked by overdue days then importance."""

        priorities: dict[str, int] = {}
        rows = self.store.list_syllabi(limit=100_000) if not syllabus_id else [{"id": syllabus_id}]
        for row in rows:
            syllabus = self.store.get_syllabus(row["id"])
            if syllabus is None:
                continue
            for notion in syllabus.notions:
                priorities[notion.id] = notion.importance
        return plan_due(self.store.list_schedule(), today=self.today, limit=limit, priorities=priorities)

    def schedule_entry(self, notion_id: str) -> ScheduleEntry | None:
        return self.store.get_schedule(notion_id)

    # ------------------------------------------------------------------ #
    # 5. Data lifecycle
    # ------------------------------------------------------------------ #

    def export_data(self) -> dict[str, Any]:
        return self.store.export_data()

    def export_for_anki(self, *, syllabus_id: str = "") -> list[dict[str, str]]:
        """Export notions as Anki-compatible cards (CSV rows).

        Each card contains:
        - front: the question prompt (definition or concept)
        - back: the answer from the course (statement + source citation)
        - tags: syllabus title + notion tags
        """
        rows: list[dict[str, str]] = []
        syllabi = (
            [self.store.get_syllabus(syllabus_id)]
            if syllabus_id
            else [s for r in self.store.list_syllabi(limit=100_000) if (s := self.store.get_syllabus(r["id"]))]
        )
        for syllabus in syllabi:
            if syllabus is None:
                continue
            for notion in syllabus.notions:
                front = f"Définis : {notion.title}"
                back_parts = [notion.statement]
                if notion.source_refs:
                    ref = notion.source_refs[0]
                    back_parts.append(f"\n\n📖 Source : {ref.citation_label}")
                back = "".join(back_parts)
                tags = f"study-coach::{syllabus.title.replace(' ', '_').lower()}::{notion.title.replace(' ', '_')}"
                rows.append({"Front": front, "Back": back, "Tags": tags})
        return rows

    def export_progress_csv(self, *, syllabus_id: str = "") -> list[dict[str, Any]]:
        """Export progress as CSV rows for analysis."""
        answers = self.store.list_answers(syllabus_id=syllabus_id or "", limit=100_000)
        syllabus_map = {}
        for ans in answers:
            sid = ans.get("syllabus_id") or self._syllabus_of(ans["notion_id"])
            if sid not in syllabus_map:
                syllabus_map[sid] = self.store.get_syllabus(sid)
        rows = []
        for ans in answers:
            syllabus = syllabus_map.get(ans.get("syllabus_id") or "")
            notion_title = ans["notion_id"]
            if syllabus:
                notion = syllabus.notion(ans["notion_id"])
                if notion:
                    notion_title = notion.title
            rows.append(
                {
                    "notion_id": ans["notion_id"],
                    "notion_title": notion_title,
                    "question_type": ans.get("question_type", ""),
                    "status": ans.get("status", ""),
                    "score": ans.get("score", ""),
                    "answered_at": ans.get("answered_at", ""),
                    "syllabus_id": ans.get("syllabus_id", ""),
                }
            )
        return rows

    def delete_data(self, *, scope: str = "all", syllabus_id: str = "") -> dict[str, Any]:
        return self.store.delete_data(scope=scope, syllabus_id=syllabus_id)

    # ------------------------------------------------------------------ #
    # 6. Optional model seam
    # ------------------------------------------------------------------ #

    def generate_with_model(self, notion_id: str, syllabus_id: str, **kwargs: Any) -> list[dict[str, Any]]:
        """Optional: ask an external (free) model for extra questions.

        Disabled unless a generator was supplied **and** model calls were
        explicitly authorised.  Every returned payload must carry the source
        excerpt, otherwise it is refused.
        """

        ensure_model_calls_allowed(self.generator, self.allow_model_calls)
        syllabus = self.get_syllabus(syllabus_id)
        notion = syllabus.notion(notion_id)
        if notion is None:
            raise StudyCoachError(f"Notion inconnue : {notion_id}.")
        from .llm import GenerationRequest  # imported lazily: the offline path never needs it

        request = GenerationRequest(
            course_title=syllabus.title,
            notion_title=notion.title,
            notion_statement=notion.statement,
            source_excerpt=notion.source_refs[0].excerpt if notion.source_refs else "",
            max_questions=int(kwargs.get("max_questions") or 3),
        )
        payloads = self.generator.generate_questions(request) or []
        validated: list[dict[str, Any]] = []
        for payload in payloads:
            excerpt = clean_text((payload or {}).get("source_excerpt"), limit=2_000)
            if not excerpt:
                raise StudyCoachError(
                    "Question générée par modèle sans extrait de source : elle est refusée."
                )
            validated.append({**dict(payload), "source_excerpt": excerpt})
        return validated
