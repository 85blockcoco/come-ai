"""Explicit, user-facing errors for the Study Coach engine.

The engine refuses rather than guesses.  Every refusal raises one of these
errors instead of silently producing a notion, a question or a grade that the
course does not actually support.
"""

from __future__ import annotations


class StudyCoachError(Exception):
    """Base class for every Study Coach error."""


class SourceError(StudyCoachError):
    """A course document is missing, empty or cannot be cited."""


class SyllabusError(StudyCoachError):
    """A revision programme cannot be built from the given document."""


class QuestionError(StudyCoachError):
    """A question cannot be generated (most often: a missing source reference)."""


class GradingError(StudyCoachError):
    """An answer cannot be corrected without inventing a result."""


class SessionError(StudyCoachError):
    """A review session is unknown, finished or inconsistent."""


class StoreError(StudyCoachError):
    """The local Study Coach store is unusable."""


class OfflineViolation(StudyCoachError):
    """A network call was attempted while the engine was running offline."""
