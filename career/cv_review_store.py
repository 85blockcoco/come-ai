"""Local persistence of the CV review workspace (SPEC-004).

Two files per **review key** (one application and one CV variant), both inside
the private Career directory:

* ``<application_id>__<variant>.json`` — the current state of the workspace;
* ``<application_id>__<variant>.history.jsonl`` — the decision history,
  **append only**.

The variant is part of the key on purpose: two variants of the same offer
propose different wording, so a decision taken on one must never be replayed
on the other.

The history is never rewritten: each decision appends one JSON line and the
file only ever grows.  A decision therefore cannot be silently erased, and
the state file can always be rebuilt by replaying the history
(:func:`career.cv_review.replay_events`).

The identifiers come from a URL, so they are validated before touching the
filesystem: no path traversal, no surprise file names.
"""

from __future__ import annotations

import json
import os
import re
import tempfile
from pathlib import Path
from typing import Any

from .cv_review import EvidenceRef, ReviewBlock, ReviewEvent, ReviewHeader, ReviewWorkspace


#: Format marker of the stored workspace (not a database schema).
REVIEW_FORMAT = "career-cv-review/1"
#: Characters allowed in an application identifier used as a file name.
IDENTIFIER_PATTERN = re.compile(r"^[A-Za-z0-9_-]{1,80}$")
#: Separator between the application identifier and the variant in a file name.
#: A dot cannot appear in an identifier, so the key can always be read back.
KEY_SEPARATOR = "."
MAX_HISTORY_EVENTS = 5_000


def review_directory(base_dir: Path) -> Path:
    """Return the private directory holding the review workspaces."""

    return Path(base_dir) / "cv_review"


def _safe_identifier(application_id: str) -> str:
    identifier = str(application_id or "").strip()
    if not IDENTIFIER_PATTERN.match(identifier):
        raise ValueError("Identifiant de candidature invalide pour la revue CV.")
    return identifier


def review_key(application_id: str, variant_id: str = "") -> str:
    """File-name key of one review: an application and a CV variant."""

    identifier = _safe_identifier(application_id)
    variant = _safe_identifier(variant_id) if str(variant_id or "").strip() else "default"
    return f"{identifier}{KEY_SEPARATOR}{variant}"


def split_review_key(key: str) -> tuple[str, str]:
    """Read back an application identifier and a variant from a file key."""

    if KEY_SEPARATOR in key:
        identifier, _, variant = key.rpartition(KEY_SEPARATOR)
        return identifier, variant
    return key, "default"


def workspace_path(directory: Path, application_id: str, variant_id: str = "") -> Path:
    """Path of the stored workspace for one application and one variant."""

    return Path(directory) / f"{review_key(application_id, variant_id)}.json"


def history_path(directory: Path, application_id: str, variant_id: str = "") -> Path:
    """Path of the append-only decision history for one application."""

    return Path(directory) / f"{review_key(application_id, variant_id)}.history.jsonl"


def _atomic_write(path: Path, payload: str) -> None:
    """Write a private file atomically (no partial state on crash)."""

    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, raw = tempfile.mkstemp(prefix=f".{path.stem}-", suffix=path.suffix, dir=path.parent)
    temporary = Path(raw)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(temporary, 0o600)
        os.replace(temporary, path)
    except BaseException:
        temporary.unlink(missing_ok=True)
        raise


def serialize_workspace(workspace: ReviewWorkspace) -> dict[str, Any]:
    """JSON-ready view of a workspace, ready to be stored."""

    return {
        "format": REVIEW_FORMAT,
        "application_id": workspace.application_id,
        "job_id": workspace.job_id,
        "variant_id": workspace.variant_id,
        "language": workspace.language,
        "created_at": workspace.created_at,
        "updated_at": workspace.updated_at,
        "source_document": workspace.source_document,
        "invalidated_blocks": list(workspace.invalidated_blocks or []),
        "header": {
            "display_name": workspace.header.display_name,
            "contact_line": workspace.header.contact_line,
            "education_line": workspace.header.education_line,
        },
        "blocks": [
            {
                "block_id": block.block_id,
                "section": block.section,
                "heading": block.heading,
                "index": block.index,
                "source_text": block.source_text,
                "proposed_text": block.proposed_text,
                "status": block.status,
                "placeholder_reason": block.placeholder_reason,
                "user_text": block.user_text,
                "decided_at": block.decided_at,
                "decided_by": block.decided_by,
                "evidence": [item.to_dict() for item in block.evidence] if block.evidence else None,
            }
            for block in workspace.blocks
        ],
    }


def deserialize_workspace(payload: dict[str, Any]) -> ReviewWorkspace:
    """Rebuild a workspace from its stored form."""

    header = payload.get("header") if isinstance(payload.get("header"), dict) else {}
    blocks: list[ReviewBlock] = []
    for raw in payload.get("blocks") or []:
        if not isinstance(raw, dict):
            continue
        evidence_raw = raw.get("evidence")
        evidence: list[EvidenceRef] | None = None
        if isinstance(evidence_raw, list):
            evidence = [
                EvidenceRef(
                    source=str(item.get("source") or ""),
                    quote=str(item.get("quote") or ""),
                    offset=int(item.get("offset") or 0),
                )
                for item in evidence_raw
                if isinstance(item, dict)
            ]
        blocks.append(
            ReviewBlock(
                block_id=str(raw.get("block_id") or ""),
                section=str(raw.get("section") or "experiences"),  # type: ignore[arg-type]
                source_text=str(raw.get("source_text") or ""),
                proposed_text=str(raw.get("proposed_text") or ""),
                status=str(raw.get("status") or "pending"),  # type: ignore[arg-type]
                evidence=evidence,
                placeholder_reason=raw.get("placeholder_reason"),
                user_text=raw.get("user_text"),
                decided_at=raw.get("decided_at"),
                decided_by=str(raw.get("decided_by") or ""),
                heading=str(raw.get("heading") or ""),
                index=int(raw.get("index") or 0),
            )
        )
    return ReviewWorkspace(
        application_id=str(payload.get("application_id") or ""),
        job_id=str(payload.get("job_id") or ""),
        variant_id=str(payload.get("variant_id") or ""),
        language=str(payload.get("language") or "fr"),
        blocks=blocks,
        created_at=str(payload.get("created_at") or ""),
        updated_at=str(payload.get("updated_at") or ""),
        header=ReviewHeader(
            display_name=str(header.get("display_name") or ""),
            contact_line=str(header.get("contact_line") or ""),
            education_line=str(header.get("education_line") or ""),
        ),
        source_document=str(payload.get("source_document") or ""),
        invalidated_blocks=list(payload.get("invalidated_blocks") or []),
    )


def save_workspace(directory: Path, workspace: ReviewWorkspace) -> None:
    """Store the current state of one workspace."""

    payload = json.dumps(serialize_workspace(workspace), ensure_ascii=False, indent=2)
    _atomic_write(
        workspace_path(directory, workspace.application_id, workspace.variant_id),
        payload + "\n",
    )


def load_workspace(
    directory: Path, application_id: str, variant_id: str = ""
) -> ReviewWorkspace | None:
    """Read the stored workspace, or ``None`` when it does not exist yet.

    A missing or unreadable file is not an error: the caller then rebuilds
    the decisions from the immutable history.
    """

    return load_workspace_file(workspace_path(directory, application_id, variant_id))


def load_workspace_file(path: Path) -> ReviewWorkspace | None:
    """Read one workspace file, whatever its name."""

    try:
        raw = Path(path).read_text(encoding="utf-8")
    except (FileNotFoundError, OSError):
        return None
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        return None
    if not isinstance(payload, dict) or payload.get("format") != REVIEW_FORMAT:
        return None
    return deserialize_workspace(payload)


def append_event(directory: Path, event: ReviewEvent) -> None:
    """Append one decision to the immutable history.

    The file is only ever appended to: an earlier decision can never be
    rewritten or removed, so the trail of what was accepted, refused or
    rewritten stays complete.
    """

    path = history_path(directory, event.application_id, event.variant_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    line = json.dumps(event.to_dict(), ensure_ascii=False, sort_keys=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(line + "\n")
        handle.flush()
        os.fsync(handle.fileno())
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass


def read_events(
    directory: Path, application_id: str, variant_id: str = ""
) -> list[ReviewEvent]:
    """Read the whole decision history, oldest first."""

    path = history_path(directory, application_id, variant_id)
    try:
        raw = path.read_text(encoding="utf-8")
    except (FileNotFoundError, OSError):
        return []
    events: list[ReviewEvent] = []
    for line in raw.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            payload = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(payload, dict):
            continue
        events.append(
            ReviewEvent(
                event_id=str(payload.get("event_id") or ""),
                application_id=str(payload.get("application_id") or application_id),
                block_id=str(payload.get("block_id") or ""),
                from_status=str(payload.get("from_status") or ""),
                to_status=str(payload.get("to_status") or ""),
                user_text=str(payload.get("user_text") or ""),
                decided_at=str(payload.get("decided_at") or ""),
                decided_by=str(payload.get("decided_by") or "user"),
                sequence=int(payload.get("sequence") or 0),
                variant_id=str(payload.get("variant_id") or variant_id),
                proposed_text=str(payload.get("proposed_text") or ""),
            )
        )
    return events


def clear_workspace(directory: Path, application_id: str, variant_id: str = "") -> None:
    """Remove the workspace and its history for one application."""

    workspace_path(directory, application_id, variant_id).unlink(missing_ok=True)
    history_path(directory, application_id, variant_id).unlink(missing_ok=True)


def list_workspaces(directory: Path) -> list[dict[str, Any]]:
    """Return every stored workspace with its history, for the privacy export.

    Files that are not a readable workspace (a leftover temporary file, an
    unrelated file) are skipped instead of breaking the export.
    """

    root = Path(directory)
    if not root.is_dir():
        return []
    exported: list[dict[str, Any]] = []
    for path in sorted(root.glob("*.json")):
        if path.name.startswith("."):
            continue
        identifier, variant = split_review_key(path.stem)
        if not IDENTIFIER_PATTERN.match(identifier):
            continue
        workspace = load_workspace_file(path)
        if workspace is None:
            continue
        try:
            events = read_events(root, identifier, variant)
        except ValueError:
            events = []
        exported.append(
            {
                **serialize_workspace(workspace),
                "history": [event.to_dict() for event in events],
            }
        )
    return exported
