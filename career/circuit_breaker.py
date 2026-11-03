"""Circuit breaker for external providers (N100-I03)."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any, Callable


class CircuitState(str, Enum):
    CLOSED = "closed"
    OPEN = "open"
    HALF_OPEN = "half_open"


@dataclass
class CircuitBreaker:
    threshold: int = 5
    reset_after_sec: float = 60.0
    _failures: int = 0
    _state: CircuitState = CircuitState.CLOSED
    _opened_at: float | None = None

    def state(self) -> CircuitState:
        if self._state == CircuitState.OPEN and self._opened_at is not None:
            import time
            if time.time() - self._opened_at >= self.reset_after_sec:
                self._state = CircuitState.HALF_OPEN
        return self._state

    def record_success(self) -> None:
        self._failures = 0
        self._state = CircuitState.CLOSED
        self._opened_at = None

    def record_failure(self) -> None:
        import time
        self._failures += 1
        if self._failures >= self.threshold:
            self._state = CircuitState.OPEN
            self._opened_at = time.time()

    def allow(self) -> bool:
        s = self.state()
        return s in (CircuitState.CLOSED, CircuitState.HALF_OPEN)

    def call(self, fn: Callable[[], Any]) -> Any:
        if not self.allow():
            raise RuntimeError("circuit open")
        try:
            result = fn()
            self.record_success()
            return result
        except Exception:
            self.record_failure()
            raise

    def to_dict(self) -> dict[str, Any]:
        return {"state": self.state().value, "failures": self._failures, "threshold": self.threshold}