"""Local persistence of the CV review workspace and of its decision history.

Two artefacts live under the private Career directory (``career_data/cv_review``) :

* ``<application_id>/workspace.json`` — the current state of the review
  (blocks, statuses, user wording). It is rewritten atomically at every
  change and always mirrors the workspace rebuilt from the local facts ;
* ``<application_id>/history.jsonl`` — the **immutable** decision log. The
  file is only ever appended to: no decision is rewritten nor removed, so the
  trail of what was accepted, refused or modified is preserved.

Nothing here talks to the network, and the files stay private (0600) inside the
private Career directory.
"""

from __future__ import annotations

import json
import os
import re
import tempfile
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from .cv_review import EvidenceRef, ReviewBlock, ReviewWorkspace


APPLICATION_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,119}$")

EVENT_TYPE_DECISION = "decision"


class ReviewStoreError(ValueError):
    """An unusable application identifier or an unreadable review artefact."""


@dataclass(frozen=True, slots=True)
class ReviewEvent:
    """One immutable decision recorded in the review history."""

    event_id: str
    sequence: int
    application_id: str
    block_id: str
    section: str
    from_status: str
    to_status: str
    decided_at: str
    decided_by: str = "user"
    user_text: str | None = None
    event_type: str = EVENT_TYPE_DECISION

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ReviewEvent":
        return cls(
            event_id=str(data.get("event_id") or ""),
            sequence=int(data.get("sequence") or 0),
            application_id=str(data.get("application_id") or ""),
            block_id=str(data.get("block_id") or ""),
            section=str(data.get("section") or ""),
            from_status=str(data.get("from_status") or ""),
            to_status=str(data.get("to_status") or ""),
            decided_at=str(data.get("decided_at") or ""),
            decided_by=str(data.get("decided_by") or "user"),
            user_text=data.get("user_text"),
            event_type=str(data.get("event_type") or EVENT_TYPE_DECISION),
        )


@dataclass
class ReviewHistory:
    """The append-only decision log of one application."""

    application_id: str
    events: list[ReviewEvent] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "application_id": self.application_id,
            "events": [event.to_dict() for event in self.events],
            "count": len(self.events),
            "immutable": True,
        }


def safe_application_id(value: Any) -> str:
    """Return a storage-safe application identifier.

    The identifier comes from an URL path: anything that could escape the
    private directory is rejected instead of being sanitized silently.
    """

    identifier = str(value or "").strip()
    if not identifier or not APPLICATION_ID_PATTERN.match(identifier):
        raise ReviewStoreError("Identifiant de candidature invalide.")
    if ".." in identifier:
        raise ReviewStoreError("Identifiant de candidature invalide.")
    return identifier


def _block_to_state(block: ReviewBlock) -> dict[str, Any]:
    return {
        "block_id": block.block_id,
        "section": block.section,
        "source_text": block.source_text,
        "proposed_text": block.proposed_text,
        "status": block.status,
        "evidence": [item.to_dict() for item in block.evidence] if block.evidence else None,
        "placeholder_reason": block.placeholder_reason,
        "user_text": block.user_text,
        "decided_at": block.decided_at,
        "decided_by": block.decided_by,
    }


def _block_from_state(data: dict[str, Any]) -> ReviewBlock:
    evidence_payload = data.get("evidence")
    evidence = None
    if isinstance(evidence_payload, list):
        evidence = [
            EvidenceRef(
                source=str(item.get("source") or "profile"),
                quote=str(item.get("quote") or ""),
                start_offset=int(item.get("start_offset") or 0),
                end_offset=int(item.get("end_offset") or 0),
            )
            for item in evidence_payload
            if isinstance(item, dict)
        ]
    return ReviewBlock(
        block_id=str(data.get("block_id") or ""),
        section=str(data.get("section") or "experiences"),  # type: ignore[arg-type]
        source_text=str(data.get("source_text") or ""),
        proposed_text=str(data.get("proposed_text") or ""),
        status=str(data.get("status") or "pending"),  # type: ignore[arg-type]
        evidence=evidence,
        placeholder_reason=data.get("placeholder_reason"),
        user_text=data.get("user_text"),
        decided_at=data.get("decided_at"),
        decided_by=str(data.get("decided_by") or "user"),
    )


def workspace_to_state(workspace: ReviewWorkspace) -> dict[str, Any]:
    """Lean, JSON-ready state of a workspace (without computed views)."""

    return {
        "application_id": workspace.application_id,
        "job_id": workspace.job_id,
        "variant_id": workspace.variant_id,
        "language": workspace.language,
        "created_at": workspace.created_at,
        "updated_at": workspace.updated_at,
        "section_headings": dict(workspace.section_headings),
        "blocks": [_block_to_state(block) for block in workspace.blocks],
    }


def workspace_from_state(data: dict[str, Any]) -> ReviewWorkspace:
    """Rebuild a workspace from its stored state."""

    blocks_payload = data.get("blocks")
    blocks = [
        _block_from_state(item)
        for item in (blocks_payload if isinstance(blocks_payload, list) else [])
        if isinstance(item, dict)
    ]
    headings = data.get("section_headings")
    return ReviewWorkspace(
        application_id=str(data.get("application_id") or ""),
        job_id=str(data.get("job_id") or ""),
        variant_id=str(data.get("variant_id") or ""),
        language=str(data.get("language") or "fr"),
        blocks=blocks,
        section_headings=dict(headings) if isinstance(headings, dict) else {},
        created_at=str(data.get("created_at") or ""),
        updated_at=str(data.get("updated_at") or ""),
    )


class ReviewStore:
    """Append-only local storage for the CV review workspaces."""

    def __init__(self, data_dir: Path):
        self.data_dir = Path(data_dir)
        self.root = self.data_dir / "cv_review"
        self.root.mkdir(parents=True, exist_ok=True)
        try:
            os.chmod(self.root, 0o700)
        except OSError:
            pass

    # -- paths ---------------------------------------------------------
    def application_dir(self, application_id: str) -> Path:
        identifier = safe_application_id(application_id)
        return self.root / identifier

    def workspace_path(self, application_id: str) -> Path:
        return self.application_dir(application_id) / "workspace.json"

    def history_path(self, application_id: str) -> Path:
        return self.application_dir(application_id) / "history.jsonl"

    # -- workspace -----------------------------------------------------
    def save_workspace(self, workspace: ReviewWorkspace) -> Path:
        """Write the current review state atomically and privately."""

        target = self.workspace_path(workspace.application_id)
        target.parent.mkdir(parents=True, exist_ok=True)
        payload = json.dumps(workspace_to_state(workspace), ensure_ascii=False, indent=2)
        descriptor, raw = tempfile.mkstemp(prefix=".workspace-", suffix=".json", dir=target.parent)
        temporary = Path(raw)
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
                handle.write(payload)
            os.chmod(temporary, 0o600)
            os.replace(temporary, target)
            os.chmod(target, 0o600)
        except Exception:
            temporary.unlink(missing_ok=True)
            raise
        return target

    def load_workspace(self, application_id: str) -> ReviewWorkspace | None:
        """Read the stored review state, or ``None`` when there is none."""

        path = self.workspace_path(application_id)
        if not path.is_file():
            return None
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None
        if not isinstance(data, dict):
            return None
        return workspace_from_state(data)

    # -- history -------------------------------------------------------
    def append_event(self, event: ReviewEvent) -> ReviewEvent:
        """Append one decision to the immutable history."""

        path = self.history_path(event.application_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        line = json.dumps(event.to_dict(), ensure_ascii=False, sort_keys=True)
        descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
        try:
            os.write(descriptor, f"{line}\n".encode("utf-8"))
        finally:
            os.close(descriptor)
        try:
            os.chmod(path, 0o600)
        except OSError:
            pass
        return event

    def load_history(self, application_id: str) -> ReviewHistory:
        """Read the immutable decision log in order."""

        path = self.history_path(application_id)
        events: list[ReviewEvent] = []
        if path.is_file():
            try:
                raw = path.read_text(encoding="utf-8")
            except OSError:
                raw = ""
            for line in raw.splitlines():
                line = line.strip()
                if not line:
                    continue
                try:
                    payload = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if isinstance(payload, dict):
                    events.append(ReviewEvent.from_dict(payload))
        return ReviewHistory(application_id=safe_application_id(application_id), events=events)

    def next_sequence(self, application_id: str) -> int:
        """The next sequence number of the immutable history."""

        history = self.load_history(application_id)
        return len(history.events) + 1

    def new_event(
        self,
        *,
        application_id: str,
        block_id: str,
        section: str,
        from_status: str,
        to_status: str,
        decided_at: str,
        user_text: str | None = None,
        decided_by: str = "user",
    ) -> ReviewEvent:
        """Build the next immutable decision event for one application."""

        return ReviewEvent(
            event_id=uuid.uuid4().hex,
            sequence=self.next_sequence(application_id),
            application_id=safe_application_id(application_id),
            block_id=block_id,
            section=section,
            from_status=from_status,
            to_status=to_status,
            decided_at=decided_at,
            decided_by=decided_by,
            user_text=user_text,
        )
