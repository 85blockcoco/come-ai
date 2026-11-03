"""Recovery after error with exponential backoff (N100-I02)."""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any, Callable


@dataclass
class RetryResult:
    ok: bool
    attempts: int
    last_error: str | None = None
    result: Any = None


def retry_with_backoff(
    fn: Callable[[], Any],
    *,
    max_attempts: int = 3,
    base_delay: float = 0.01,
    max_delay: float = 1.0,
    sleep: Callable[[float], None] = time.sleep,
) -> RetryResult:
    last_err = None
    for attempt in range(1, max_attempts + 1):
        try:
            return RetryResult(ok=True, attempts=attempt, result=fn())
        except Exception as exc:
            last_err = str(exc)
            if attempt < max_attempts:
                delay = min(max_delay, base_delay * (2 ** (attempt - 1)))
                sleep(delay)
    return RetryResult(ok=False, attempts=max_attempts, last_error=last_err)