"""Importeur borné du backlog NAGe vers la file persistante du Dev Kit.

Le backlog Markdown reste la source lisible par l'humain. Ce module ne lance
aucune mission et ne lit aucun document personnel : il transforme uniquement
les 200 lignes FINAL-* en tâches locales, dédupliquées par ``EvolutionStore``.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from devkit.evolution_store import EvolutionStore, EvolutionStoreError

_ENTRY = re.compile(
    r"^-\s+(FINAL-(?P<number>\d{3}))\s+—\s+(?P<title>.+?)\s+—\s+dépend de\s+(?P<dependency>.+?)\s+—\s+preuve\s*:\s+(?P<proof>.+?)\s*$"
)


@dataclass(frozen=True)
class BacklogEntry:
    mission_id: str
    title: str
    dependency: str
    proof: str

    @property
    def description(self) -> str:
        return f"Mission {self.mission_id}. {self.title}. Dépendance : {self.dependency}."

    @property
    def acceptance(self) -> str:
        return f"Preuve attendue : {self.proof}. Commit, test ciblé et rapport obligatoires."


def _read_backlog(path: Path) -> str:
    path = Path(path)
    if path.is_symlink() or not path.is_file() or path.stat().st_size > 1_000_000:
        raise EvolutionStoreError("Le backlog doit être un fichier Markdown local, réel et borné.")
    try:
        return path.read_text(encoding="utf-8")
    except (OSError, UnicodeError):
        raise EvolutionStoreError("Le backlog n’est pas lisible en UTF-8.") from None


def parse_backlog(path: Path) -> list[BacklogEntry]:
    """Parse les entrées FINAL-* et refuse les trous ou doublons silencieux."""
    entries: list[BacklogEntry] = []
    seen: set[str] = set()
    for line in _read_backlog(path).splitlines():
        match = _ENTRY.match(line.strip())
        if not match:
            continue
        mission_id = match.group(1)
        if mission_id in seen:
            raise EvolutionStoreError(f"Mission dupliquée dans le backlog : {mission_id}.")
        seen.add(mission_id)
        entries.append(BacklogEntry(mission_id, match.group("title"), match.group("dependency"), match.group("proof")))
    expected = {f"FINAL-{number:03d}" for number in range(1, 201)}
    if {entry.mission_id for entry in entries} != expected:
        missing = sorted(expected - {entry.mission_id for entry in entries})
        raise EvolutionStoreError(f"Le backlog doit contenir FINAL-001 à FINAL-200; manquantes : {', '.join(missing[:5])}.")
    return sorted(entries, key=lambda entry: entry.mission_id)


def _files_for(entry: BacklogEntry, project_root: Path) -> list[str]:
    """Choisit des sources existantes et autorisées selon le lot fonctionnel."""
    number = int(entry.mission_id[-3:])
    candidates = {
        "A": ["devkit/service.py", "devkit/router.py"],
        "B": ["career/router.py", "career/service.py"],
        "C": ["career/requirements_fit.py", "career/education_access.py", "career/service.py"],
        "D": ["career/cv_variants.py", "career/cv_fit.py", "career/service.py"],
        "E": ["career/letter_approval.py", "career/router.py", "career/service.py"],
        "F": ["career/dossier_checklist.py", "career/router.py", "career/service.py"],
        "G": ["career/source_trust.py", "career/offer_dates.py", "career/service.py"],
        "H": ["study_coach/engine.py", "study_coach/sources.py", "study_coach/store.py"],
        "I": ["devkit/evolution.py", "devkit/service.py", "devkit/evolution_store.py"],
        "J": ["devkit/diagnostics.py", "devkit/service.py", "devkit/evolution_store.py"],
    }
    lot = "ABCDEFGHIJ"[(number - 1) // 20]
    return [relative for relative in candidates[lot] if (project_root / relative).is_file()]


def import_backlog(project_root: Path, store: EvolutionStore, backlog_path: Path, *, limit: int = 200, dry_run: bool = False) -> dict[str, Any]:
    """Queue au plus ``limit`` missions; ne démarre jamais le moteur."""
    if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 200:
        raise EvolutionStoreError("La limite d’import doit être comprise entre 1 et 200.")
    entries = parse_backlog(backlog_path)[:limit]
    preview: list[dict[str, Any]] = []
    queued = 0
    for entry in entries:
        files = _files_for(entry, Path(project_root).resolve())
        if not files:
            raise EvolutionStoreError(f"Aucun fichier source existant pour {entry.mission_id}.")
        item = {"mission_id": entry.mission_id, "title": entry.title, "selected_files": files,
                "dependency": entry.dependency, "acceptance": entry.acceptance}
        preview.append(item)
        if not dry_run:
            store.add_task(entry.mission_id + " — " + entry.title, entry.description, files, entry.acceptance,
                           priority=max(1, 101 - int(entry.mission_id[-3:])))
            queued += 1
    return {"status": "preview" if dry_run else "queued", "count": len(preview), "queued": queued,
            "automatic_run": False, "entries": preview}
