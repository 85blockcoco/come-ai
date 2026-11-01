"""Ordered model fallback (N100-I07)."""

from __future__ import annotations

from typing import Any, Callable, Iterable


def try_models(models: Iterable[str], call: Callable[[str], Any]) -> tuple[str | None, Any, list[str]]:
    """Try each model in order. Return (model_used, result, errors)."""
    errors: list[str] = []
    for m in models:
        try:
            return m, call(m), errors
        except Exception as exc:
            errors.append(f"{m}: {exc}")
    return None, None, errors