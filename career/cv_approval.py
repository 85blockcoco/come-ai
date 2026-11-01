"""Human approval gate before CV export (N100-E09).

Same contract as ``letter_approval``: a variant cannot be exported until a
human approves a given version.  No auto-approval.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any


@dataclass
class CvApproval:
    cv_id: str
    version_id: str
    approved: bool
    approver: str = "human"
    note: str = ""


_REGISTRY: dict[tuple[str, str], CvApproval] = {}
_REGISTRY_PATH: Path | None = None


def set_registry_path(path: str | Path) -> None:
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
                _REGISTRY[(d["cv_id"], d["version_id"])] = CvApproval(**d)
            except (json.JSONDecodeError, TypeError, KeyError):
                continue


def _persist(dec: CvApproval) -> None:
    if _REGISTRY_PATH is None:
        return
    import json

    _REGISTRY_PATH.parent.mkdir(parents=True, exist_ok=True)
    with _REGISTRY_PATH.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(asdict(dec), ensure_ascii=False) + "\n")


def decide(cv_id: str, version_id: str, approved: bool, *, note: str = "") -> CvApproval:
    dec = CvApproval(cv_id=cv_id, version_id=version_id, approved=approved, note=note)
    _REGISTRY[(cv_id, version_id)] = dec
    _persist(dec)
    return dec


def is_approved(cv_id: str, version_id: str) -> bool:
    dec = _REGISTRY.get((cv_id, version_id))
    return bool(dec and dec.approved)


def get_decision(cv_id: str, version_id: str) -> CvApproval | None:
    return _REGISTRY.get((cv_id, version_id))


def to_dict(dec: CvApproval) -> dict[str, Any]:
    return asdict(dec)
