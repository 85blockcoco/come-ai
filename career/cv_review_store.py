"""Local persistence of the CV review workspaces (SPEC-004).

Two files per application, both stored inside the local Career data folder:

* ``<application>.json`` — the current workspace (rewritten atomically).
* ``<application>.history.jsonl`` — the immutable decision journal.

The history is **append only**: a decision is never edited nor deleted, so the
audit trail of what the user accepted, modified or refused survives every
rebuild of the workspace.  No network, no telemetry, no personal data leaves
the machine.
"""

from __future__ import annotations

import json
import os
import re
import tempfile
from pathlib import Path
from typing import Any, Iterable

from career.cv_review import ReviewWorkspace, workspace_from_dict, workspace_to_dict


_UNSAFE = re.compile(r"[^A-Za-z0-9._-]+")


def _slug(application_id: str) -> str:
    """Return a safe file name for one application identifier."""

    cleaned = _UNSAFE.sub("-", (application_id or "").strip()).strip("-._")
    return cleaned or "application"


class CVReviewStore:
    """Read and write the review workspaces of one local Career workspace."""

    def __init__(self, root: Path) -> None:
        self.root = Path(root)

    # -- paths ---------------------------------------------------------- #

    def workspace_path(self, application_id: str) -> Path:
        return self.root / f"{_slug(application_id)}.json"

    def history_path(self, application_id: str) -> Path:
        return self.root / f"{_slug(application_id)}.history.jsonl"

    # -- workspace ------------------------------------------------------ #

    def load_workspace(self, application_id: str) -> ReviewWorkspace | None:
        """Return the saved workspace, or ``None`` when there is none."""

        path = self.workspace_path(application_id)
        if not path.is_file():
            return None
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None
        if not isinstance(payload, dict):
            return None
        return workspace_from_dict(payload)

    def save_workspace(self, workspace: ReviewWorkspace) -> Path:
        """Persist the workspace atomically and return its path."""

        path = self.workspace_path(workspace.application_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = json.dumps(workspace_to_dict(workspace), ensure_ascii=False, indent=2)
        _atomic_write(path, payload + "\n")
        return path

    # -- history -------------------------------------------------------- #

    def append_history(self, application_id: str, entry: dict[str, Any]) -> Path:
        """Append one immutable entry to the decision journal."""

        path = self.history_path(application_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        line = json.dumps(entry, ensure_ascii=False, sort_keys=True)
        with path.open("a", encoding="utf-8") as handle:
            handle.write(line + "\n")
        _restrict_permissions(path)
        return path

    def load_history(self, application_id: str) -> list[dict[str, Any]]:
        """Return every recorded decision, oldest first."""

        path = self.history_path(application_id)
        if not path.is_file():
            return []
        entries: list[dict[str, Any]] = []
        try:
            content = path.read_text(encoding="utf-8")
        except OSError:
            return []
        for line in content.splitlines():
            stripped = line.strip()
            if not stripped:
                continue
            try:
                payload = json.loads(stripped)
            except ValueError:
                continue
            if isinstance(payload, dict):
                entries.append(payload)
        return entries

    def append_history_entries(
        self, application_id: str, entries: Iterable[dict[str, Any]]
    ) -> None:
        """Append several entries at once, preserving their order."""

        for entry in entries:
            self.append_history(application_id, entry)


def _atomic_write(path: Path, content: str) -> None:
    """Write a file atomically so a crash never truncates the workspace."""

    descriptor, raw = tempfile.mkstemp(prefix=f".{path.stem}-", suffix=".tmp", dir=path.parent)
    temporary = Path(raw)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(temporary, 0o600)
        os.replace(temporary, path)
    except BaseException:
        temporary.unlink(missing_ok=True)
        raise


def _restrict_permissions(path: Path) -> None:
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass
