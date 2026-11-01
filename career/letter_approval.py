"""Human approval gate for cover letters (N100-F09).

A letter cannot be exported/sent until a human explicitly approves the
content for the given version.  No auto-approval, no auto-send.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any


@dataclass
class ApprovalDecision:
    letter_id: str
    version: int
    approved: bool
    approver: str = "human"
    note: str = ""


_REGISTRY: dict[str, ApprovalDecision] = {}
_REGISTRY_PATH: Path | None = None


def set_registry_path(path: str | Path) -> None:
    """Point the gate at a persistent JSONL file (tests pass tmp_path)."""
    global _REGISTRY_PATH  # noqa: PLW0603
    _REGISTRY_PATH = Path(path)
    _REGISTRY.clear()
    if _REGISTRY_PATH.exists():
        import json

        for line in _REGISTRY_PATH.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            try:
                d = json.loads(line)
                _REGISTRY[d["letter_id"]] = ApprovalDecision(**d)
            except (json.JSONDecodeError, TypeError, KeyError):
                continue


def _persist(dec: ApprovalDecision) -> None:
    if _REGISTRY_PATH is None:
        return
    import json

    _REGISTRY_PATH.parent.mkdir(parents=True, exist_ok=True)
    with _REGISTRY_PATH.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(asdict(dec), ensure_ascii=False) + "\n")


def decide(letter_id: str, approved: bool, *, version: int = 1, note: str = "") -> ApprovalDecision:
    dec = ApprovalDecision(letter_id=letter_id, version=version, approved=approved, note=note)
    _REGISTRY[letter_id] = dec
    _persist(dec)
    return dec


def is_approved(letter_id: str) -> bool:
    dec = _REGISTRY.get(letter_id)
    return bool(dec and dec.approved)


def get_decision(letter_id: str) -> ApprovalDecision | None:
    return _REGISTRY.get(letter_id)


def to_dict(dec: ApprovalDecision) -> dict[str, Any]:
    return asdict(dec)
