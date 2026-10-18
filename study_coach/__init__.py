"""Local-first Study Coach engine for Côme AI.

The module turns a course into a revision programme, questions the learner,
corrects the answers against the course wording and keeps a local progress log.
It never invents course content, never grades what it cannot verify, and never
calls a network without an explicit opt-in.

Quick start::

    from study_coach import StudyCoach

    with StudyCoach.open("./study_data") as coach:
        syllabus = coach.ingest_course(text, title="Comptabilité générale")
        session = coach.start_session(syllabus.id, size=8)
        question = coach.next_question(session.id)
        correction = coach.submit_answer(session.id, question["id"], "ma réponse")
"""

from .engine import StudyCoach
from .errors import (
    GradingError,
    OfflineViolation,
    QuestionError,
    SessionError,
    SourceError,
    StoreError,
    StudyCoachError,
    SyllabusError,
)
from .grading import grade_answer
from .models import (
    AnswerRecord,
    Correction,
    Gap,
    Notion,
    NumericAnswer,
    Question,
    ReviewSession,
    ScheduleEntry,
    SourceRef,
    StudyDocument,
    Syllabus,
)
from .questions import QUESTION_FAMILIES, build_questions_for_notion, build_session_questions
from .scheduler import plan_due, recommend_from_answers, update_entry
from .sources import (
    DocumentSource,
    InMemoryDocumentSource,
    PersonalMemorySourceAdapter,
    document_from_text,
)
from .store import StudyCoachStore
from .syllabus import build_program, build_syllabus, syllabus_to_markdown

__version__ = "1.0.0"

__all__ = [
    "AnswerRecord",
    "Correction",
    "DocumentSource",
    "Gap",
    "GradingError",
    "InMemoryDocumentSource",
    "Notion",
    "NumericAnswer",
    "OfflineViolation",
    "PersonalMemorySourceAdapter",
    "QUESTION_FAMILIES",
    "Question",
    "QuestionError",
    "ReviewSession",
    "ScheduleEntry",
    "SessionError",
    "SourceError",
    "SourceRef",
    "StoreError",
    "StudyCoach",
    "StudyCoachError",
    "StudyCoachStore",
    "StudyDocument",
    "Syllabus",
    "SyllabusError",
    "__version__",
    "build_program",
    "build_questions_for_notion",
    "build_session_questions",
    "build_syllabus",
    "document_from_text",
    "grade_answer",
    "plan_due",
    "recommend_from_answers",
    "syllabus_to_markdown",
    "update_entry",
]
