"""Extension point for an AI reviewer that can only submit a staged proposal.

No provider is enabled here. A future Gemini/Ollama adapter receives a bounded
copy of selected source, returns inert text, and cannot call an apply method.
The main application and its documents are never exposed through this contract.
"""

from __future__ import annotations

import json
import uuid
import zipfile
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import Mapping, Protocol

from devkit.exporting import KitError, build_issue_bundle
from devkit.patching import PatchWorkspace


@dataclass(frozen=True)
class ProposalContext:
    issue: Mapping[str, object]
    sources: Mapping[str, str]


@dataclass(frozen=True)
class CodeProposal:
    patch: str | None = None
    files: Mapping[str, str] | None = None


class CorrectionProvider(Protocol):
    """An adapter implements generation only, never file changes or execution."""

    is_remote: bool

    def propose(self, context: ProposalContext) -> CodeProposal: ...


def propose_in_isolation(
    project_root: Path,
    storage_root: Path,
    provider: CorrectionProvider,
    *,
    title: str,
    description: str,
    selected_files: list[str],
    allow_external: bool = False,
) -> dict:
    """Generate then stage an inert proposal; validation/application stay separate.

    Calling this function is an explicit generation action. It is not wired to
    app startup, diagnostics, a scheduler or the workshop's export button.
    A production cloud adapter must additionally enforce the free-price policy.
    """
    if provider.is_remote and not allow_external:
        raise KitError("Un adaptateur distant nécessite une action externe explicitement autorisée.")
    directory = Path(storage_root) / "proposals"
    if directory.is_symlink():
        raise KitError("Le dossier de propositions doit être un dossier local réel.")
    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    archive_path = directory / f"{uuid.uuid4().hex}.zip"
    build_issue_bundle(project_root, archive_path, title=title, description=description, selected_files=selected_files)
    with zipfile.ZipFile(archive_path) as archive:
        issue = json.loads(archive.read("ISSUE.json"))
        sources = {path: archive.read("source/" + path).decode("utf-8") for path in issue["selected_files"]}
    context = ProposalContext(MappingProxyType(issue), MappingProxyType(sources))
    proposal = provider.propose(context)
    if not isinstance(proposal, CodeProposal) or bool(proposal.patch) == bool(proposal.files):
        raise KitError("L’IA doit retourner un patch ou une liste de fichiers, exclusivement.")
    workspace = PatchWorkspace(project_root, storage_root)
    if proposal.patch:
        staged = workspace.stage_patch(proposal.patch, allowed_paths=selected_files)
    else:
        staged = workspace.stage_files(dict(proposal.files or {}), allowed_paths=selected_files)
    return staged
