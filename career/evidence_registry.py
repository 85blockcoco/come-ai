"""Append-only evidence registry (N100-D04).

Stores approved evidence items (facts, numbers, experiences) that back up
claims in CV/letters.  Append-only, hash-chained, no update/delete.
"""

from __future__ import annotations

import hashlib
import json
import uuid
from dataclasses import asdict, dataclass
from pathlib import Path


@dataclass
class Evidence:
    evidence_id: str
    claim: str
    source: str
    approved: bool = False
    approved_at: str | None = None
    prev_hash: str = ""
    entry_hash: str = ""


class EvidenceRegistry:
    def __init__(self, path: str | Path | None = None) -> None:
        if path is None:
            path = Path(".") / "evidence_registry.jsonl"
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def add(self, claim: str, source: str, approved: bool = False, approved_at: str | None = None) -> Evidence:
        ev = Evidence(
            evidence_id=uuid.uuid4().hex[:12],
            claim=claim,
            source=source,
            approved=approved,
            approved_at=approved_at,
            prev_hash=self._last_hash(),
        )
        ev.entry_hash = self._hash(ev)
        with self.path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(asdict(ev), ensure_ascii=False) + "\n")
        return ev

    def list(self, approved_only: bool = False) -> list[Evidence]:
        out: list[Evidence] = []
        if not self.path.exists():
            return out
        for line in self.path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            obj = json.loads(line)
            ev = Evidence(**{k: obj.get(k) for k in Evidence.__dataclass_fields__})
            if approved_only and not ev.approved:
                continue
            out.append(ev)
        return out

    def get(self, evidence_id: str) -> Evidence | None:
        for ev in self.list():
            if ev.evidence_id == evidence_id:
                return ev
        return None

    def verify_chain(self) -> tuple[bool, str | None]:
        if not self.path.exists():
            return True, None
        prev = ""
        for i, line in enumerate(self.path.read_text(encoding="utf-8").splitlines(), 1):
            if not line.strip():
                continue
            obj = json.loads(line)
            ev = Evidence(**{k: obj.get(k) for k in Evidence.__dataclass_fields__})
            if ev.prev_hash != prev:
                return False, f"ligne {i}: prev_hash incohérent"
            if ev.entry_hash != self._hash(ev):
                return False, f"ligne {i}: entry_hash incohérent"
            prev = ev.entry_hash
        return True, None

    def _last_hash(self) -> str:
        last = ""
        if not self.path.exists():
            return last
        for line in self.path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            try:
                obj = json.loads(line)
                last = str(obj.get("entry_hash") or "")
            except json.JSONDecodeError:
                continue
        return last

    @staticmethod
    def _hash(ev: Evidence) -> str:
        payload = json.dumps({
            "evidence_id": ev.evidence_id,
            "claim": ev.claim,
            "source": ev.source,
            "approved": ev.approved,
            "approved_at": ev.approved_at,
            "prev_hash": ev.prev_hash,
        }, sort_keys=True, ensure_ascii=False)
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()