"""Performance profiling helper (N100-J08)."""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any, Callable


@dataclass
class ProfileResult:
    name: str
    duration_sec: float
    ok: bool
    error: str | None = None


def profile(name: str, fn: Callable[[], Any]) -> ProfileResult:
    start = time.time()
    try:
        fn()
        return ProfileResult(name=name, duration_sec=round(time.time() - start, 6), ok=True)
    except Exception as exc:
        return ProfileResult(name=name, duration_sec=round(time.time() - start, 6), ok=False, error=str(exc))


def profile_many(tasks: dict[str, Callable[[], Any]]) -> list[ProfileResult]:
    return [profile(name, fn) for name, fn in tasks.items()]