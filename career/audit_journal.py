"""Append-only audit journal for Career decisions.

Every automated decision (offer ranked, follow-up scheduled, arena verdict, …)
is recorded with its context, outcome, timestamp and a hash chain so that any
later alteration is detectable.  The journal is **append-only**: there is no
update or delete API.

Storage is a single JSONL file (one JSON object per line) so it stays readable,
diffable and easy to inspect.  A SHA-256 chain (``prev_hash`` → ``entry_hash``)
links consecutive entries; ``verify_chain()`` detects tampering.
"""

from __future__ import annotations

import hashlib
import json
import os
import threading
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable


@dataclass
class AuditEntry:
    decision_id: str
    decision_type: str
    context: dict[str, Any]
    outcome: dict[str, Any]
    at: str
    prev_hash: str = ""
    entry_hash: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class AuditExplanation:
    entry: AuditEntry
    narrative: str
    contributing_factors: list[tuple[str, float]] = field(default_factory=list)


# French narratives per decision type.  Unknown types fall back to a generic
# template so the journal never crashes on a new decision type.
_NARRATIVES: dict[str, Callable[[AuditEntry], str]] = {}


def _narrative_for(entry: AuditEntry) -> str:
    fn = _NARRATIVES.get(entry.decision_type)
    if fn is not None:
        try:
            return fn(entry)
        except Exception:
            pass
    return (
        f"Décision « {entry.decision_type} » (id={entry.decision_id}) enregistrée "
        f"le {entry.at}. Contexte : {entry.context}. Résultat : {entry.outcome}."
    )


def _factorize(entry: AuditEntry) -> list[tuple[str, float]]:
    """Extract numeric contributing factors from context/outcome."""
    factors: list[tuple[str, float]] = []
    for source in (entry.context, entry.outcome):
        if not isinstance(source, dict):
            continue
        for key, value in source.items():
            if isinstance(value, bool):
                factors.append((key, 1.0 if value else 0.0))
            elif isinstance(value, (int, float)) and not isinstance(value, bool):
                factors.append((key, float(value)))
    # Deduplicate by name, keep last.
    seen: dict[str, float] = {}
    for name, val in factors:
        seen[name] = val
    return list(seen.items())


def _hash_entry(entry: AuditEntry) -> str:
    payload = json.dumps(
        {
            "decision_id": entry.decision_id,
            "decision_type": entry.decision_type,
            "context": entry.context,
            "outcome": entry.outcome,
            "at": entry.at,
            "prev_hash": entry.prev_hash,
        },
        sort_keys=True,
        ensure_ascii=False,
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


class AuditJournal:
    """Append-only, hash-chained audit journal backed by a JSONL file."""

    def __init__(self, path: str | Path | None = None) -> None:
        if path is None:
            path = os.environ.get("CAREER_AUDIT_JOURNAL_PATH", "")
        if not path:
            path = Path(os.environ.get("CAREER_DATA_DIR", ".")) / "audit_journal.jsonl"
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()

    # ---------- write ----------

    def record(
        self,
        decision_type: str,
        context: dict[str, Any] | None = None,
        outcome: dict[str, Any] | None = None,
        *,
        decision_id: str | None = None,
        at: str | None = None,
    ) -> AuditEntry:
        context = dict(context or {})
        outcome = dict(outcome or {})
        if at is None:
            at = datetime.now(timezone.utc).isoformat()
        if decision_id is None:
            decision_id = uuid.uuid4().hex
        with self._lock:
            prev_hash = self._last_hash()
            entry = AuditEntry(
                decision_id=decision_id,
                decision_type=decision_type,
                context=context,
                outcome=outcome,
                at=at,
                prev_hash=prev_hash,
            )
            entry.entry_hash = _hash_entry(entry)
            with self.path.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(entry.to_dict(), ensure_ascii=False) + "\n")
            return entry

    # ---------- read ----------

    def entries(
        self,
        *,
        decision_type: str | None = None,
        decision_id: str | None = None,
        since: str | None = None,
        limit: int | None = None,
    ) -> list[AuditEntry]:
        out: list[AuditEntry] = []
        with self._lock:
            if not self.path.exists():
                return out
            with self.path.open("r", encoding="utf-8") as fh:
                for line in fh:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        obj = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    entry = _entry_from_dict(obj)
                    if decision_type is not None and entry.decision_type != decision_type:
                        continue
                    if decision_id is not None and entry.decision_id != decision_id:
                        continue
                    if since is not None and entry.at < since:
                        continue
                    out.append(entry)
        if limit is not None:
            out = out[-limit:]
        return out

    def explain(self, decision_id: str) -> AuditExplanation | None:
        matches = self.entries(decision_id=decision_id)
        if not matches:
            return None
        entry = matches[-1]
        return AuditExplanation(
            entry=entry,
            narrative=_narrative_for(entry),
            contributing_factors=_factorize(entry),
        )

    def verify_chain(self) -> tuple[bool, str | None]:
        """Return (ok, error_message). Detects tampering / reordering."""
        with self._lock:
            if not self.path.exists():
                return True, None
            prev = ""
            line_no = 0
            with self.path.open("r", encoding="utf-8") as fh:
                for raw in fh:
                    raw = raw.strip()
                    if not raw:
                        continue
                    line_no += 1
                    try:
                        obj = json.loads(raw)
                    except json.JSONDecodeError as exc:
                        return False, f"ligne {line_no}: JSON invalide ({exc})"
                    entry = _entry_from_dict(obj)
                    if entry.prev_hash != prev:
                        return False, f"ligne {line_no}: prev_hash incohérent"
                    if entry.entry_hash != _hash_entry(entry):
                        return False, f"ligne {line_no}: entry_hash incohérent (altération)"
                    prev = entry.entry_hash
            return True, None

    def count(self) -> int:
        return len(self.entries())

    # ---------- internals ----------

    def _last_hash(self) -> str:
        last = ""
        if not self.path.exists():
            return last
        with self.path.open("r", encoding="utf-8") as fh:
            for raw in fh:
                raw = raw.strip()
                if not raw:
                    continue
                try:
                    obj = json.loads(raw)
                except json.JSONDecodeError:
                    continue
                last = str(obj.get("entry_hash") or "")
        return last


def _entry_from_dict(obj: dict[str, Any]) -> AuditEntry:
    return AuditEntry(
        decision_id=str(obj.get("decision_id", "")),
        decision_type=str(obj.get("decision_type", "")),
        context=dict(obj.get("context") or {}),
        outcome=dict(obj.get("outcome") or {}),
        at=str(obj.get("at", "")),
        prev_hash=str(obj.get("prev_hash", "")),
        entry_hash=str(obj.get("entry_hash", "")),
    )


def register_narrative(decision_type: str, fn: Callable[[AuditEntry], str]) -> None:
    """Register a French narrative generator for a decision type."""
    _NARRATIVES[decision_type] = fn


# Default narratives for the known decision types.
def _narr_followup(e: AuditEntry) -> str:
    return (
        f"Relance planifiée pour l'offre {e.context.get('job_id', '?')} "
        f"le {e.outcome.get('scheduled_at', e.at)} "
        f"(motif : {e.context.get('reason', 'n/a')})."
    )


def _narr_ranked(e: AuditEntry) -> str:
    score = e.outcome.get("score", e.context.get("score"))
    return (
        f"Offre {e.context.get('job_id', '?')} classée avec un score de {score}. "
        f"Facteurs : {e.context.get('factors', [])}."
    )


def _narr_arena(e: AuditEntry) -> str:
    return (
        f"Verdict arena pour {e.context.get('job_id', '?')} : "
        f"{e.outcome.get('verdict', 'n/a')} (confiance {e.outcome.get('confidence', 'n/a')})."
    )


register_narrative("followup_scheduled", _narr_followup)
register_narrative("offer_ranked", _narr_ranked)
register_narrative("arena_verdict", _narr_arena)