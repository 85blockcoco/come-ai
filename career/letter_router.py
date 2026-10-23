"""FastAPI router for cover letters (SPEC-022)."""

from __future__ import annotations

from career.letter_generator import create_letter_router, create_letter_generator_router, create_router

__all__ = ["create_letter_router", "create_letter_generator_router", "create_router"]

# module-level router for convenience
router = create_letter_router()
