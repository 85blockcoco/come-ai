"""Persistance locale et versionnée du graphe de dépendances (SPEC-013).

Le stockage est volontairement simple et inspectable : un fichier JSON pour le
graphe courant, un fichier JSON pour l'historique, et un fichier par snapshot.
Aucune base distante, aucun service, aucune écriture hors du répertoire privé
du Career.

Garanties :

* écriture atomique (fichier temporaire + ``os.replace``) ;
* permissions privées (``0o700`` pour les dossiers, ``0o600`` pour les
  fichiers) ;
* version monotone : chaque sauvegarde incrémente ``version`` et horodate
  ``updated_at`` ;
* rollback vers un snapshot antérieur, puis nouvelle version (jamais de
  réécriture silencieuse de l'historique) ;
* verrou en mémoire par répertoire pour les accès concurrents d'un même
  processus.
"""

from __future__ import annotations

import copy
import json
import os
import tempfile
import threading
from pathlib import Path
from typing import Any

from .dependencies import DependencyGraph, _clean, utc_now

GRAPH_FILENAME = "graph.json"
HISTORY_FILENAME = "history.json"
SNAPSHOTS_DIRNAME = "snapshots"
MAX_HISTORY_ENTRIES = 500
MAX_SNAPSHOTS = 50

_LOCKS: dict[str, threading.RLock] = {}
_LOCKS_GUARD = threading.Lock()


def _lock_for(root: Path) -> threading.RLock:
    key = str(root)
    with _LOCKS_GUARD:
        lock = _LOCKS.get(key)
        if lock is None:
            lock = threading.RLock()
            _LOCKS[key] = lock
        return lock


def _safe_label(value: Any) -> str:
    text = _clean(value, 160)
    return text or "snapshot"


def _atomic_write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        os.chmod(path.parent, 0o700)
    except OSError:
        pass
    serialized = json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.",
        suffix=".tmp",
        dir=str(path.parent),
    )
    temporary = Path(temporary_name)
    try:
        try:
            os.fchmod(descriptor, 0o600)
        except OSError:
            pass
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            handle.write(serialized)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def _read_json(path: Path, default: Any) -> Any:
    if not path.is_file():
        return copy.deepcopy(default)
    try:
        with path.open("r", encoding="utf-8") as handle:
            return json.load(handle)
    except (OSError, ValueError) as error:
        raise ValueError(f"Fichier de dépendances illisible : {path.name} ({error.__class__.__name__}).") from error


class DependencyStore:
    """Stockage local du graphe, de son historique et de ses snapshots."""

    def __init__(self, root: Path | str, *, max_snapshots: int = MAX_SNAPSHOTS):
        self.root = Path(root).expanduser()
        self.graph_path = self.root / GRAPH_FILENAME
        self.history_path = self.root / HISTORY_FILENAME
        self.snapshots_dir = self.root / SNAPSHOTS_DIRNAME
        self.max_snapshots = max(1, int(max_snapshots))
        self._lock = _lock_for(self.root.resolve())

    # -- lecture ---------------------------------------------------------
    def load(self) -> DependencyGraph:
        """Charge le graphe courant ; un stockage vide retourne un graphe vide."""
        with self._lock:
            payload = _read_json(self.graph_path, {})
        return DependencyGraph.from_dict(payload)

    def load_or_none(self) -> DependencyGraph | None:
        """Comme :meth:`load`, mais distingue l'absence de fichier d'un graphe vide."""
        with self._lock:
            if not self.graph_path.is_file():
                return None
            payload = _read_json(self.graph_path, {})
        return DependencyGraph.from_dict(payload)

    def exists(self) -> bool:
        return self.graph_path.is_file()

    # -- écriture --------------------------------------------------------
    def save(self, graph: DependencyGraph, *, action: str = "save", label: str = "") -> DependencyGraph:
        """Sauvegarde atomiquement et retourne le graphe avec sa nouvelle version.

        La version enregistrée est toujours strictement supérieure à la version
        précédente du stockage, même si l'appelant réutilise un vieil objet.
        """
        with self._lock:
            current = DependencyGraph.from_dict(_read_json(self.graph_path, {}))
            prepared = graph.copy()
            prepared.version = max(int(current.version), int(graph.version)) + 1
            prepared.updated_at = utc_now()
            self.root.mkdir(parents=True, exist_ok=True)
            try:
                os.chmod(self.root, 0o700)
            except OSError:
                pass
            _atomic_write_json(self.graph_path, prepared.to_dict())
            entry = {
                "version": prepared.version,
                "updated_at": prepared.updated_at,
                "action": _clean(action, 40) or "save",
                "label": _safe_label(label) if label else "",
                "node_count": len(prepared.nodes),
                "edge_count": len(prepared.edges),
            }
            self._append_history(entry)
            return prepared

    def snapshot(self, label: str = "") -> dict[str, Any]:
        """Écrit une copie versionnée du graphe courant (rollback possible)."""
        with self._lock:
            graph = DependencyGraph.from_dict(_read_json(self.graph_path, {}))
            if not graph.version:
                raise ValueError("Aucun graphe versionné à sauvegarder : construis d'abord le graphe.")
            self.snapshots_dir.mkdir(parents=True, exist_ok=True)
            try:
                os.chmod(self.snapshots_dir, 0o700)
            except OSError:
                pass
            path = self._snapshot_path(graph.version)
            _atomic_write_json(path, graph.to_dict())
            entry = {
                "version": graph.version,
                "updated_at": utc_now(),
                "action": "snapshot",
                "label": _safe_label(label),
                "node_count": len(graph.nodes),
                "edge_count": len(graph.edges),
                "path": f"{SNAPSHOTS_DIRNAME}/{path.name}",
            }
            self._append_history(entry)
            self._prune_snapshots()
            return entry

    def rollback(self, version: int) -> DependencyGraph:
        """Restaure un snapshot puis enregistre une **nouvelle** version."""
        try:
            version = int(version)
        except (TypeError, ValueError) as error:
            raise ValueError("La version de rollback doit être un entier.") from error
        with self._lock:
            path = self._snapshot_path(version)
            if not path.is_file():
                raise KeyError(f"Snapshot introuvable pour la version {version}.")
            payload = _read_json(path, {})
            graph = DependencyGraph.from_dict(payload)
            graph.version = version
            graph.updated_at = _clean(payload.get("updated_at"), 64)
            restored = self.save(
                graph,
                action="rollback",
                label=f"rollback depuis v{version}",
            )
            return restored

    # -- historique ------------------------------------------------------
    def history(self, *, limit: int = 100) -> list[dict[str, Any]]:
        entries = self._read_history().get("entries", [])
        try:
            limit = max(1, min(int(limit), MAX_HISTORY_ENTRIES))
        except (TypeError, ValueError):
            limit = 100
        return [copy.deepcopy(entry) for entry in entries[-limit:]][::-1]

    def snapshots(self) -> list[dict[str, Any]]:
        return [entry for entry in self.history(limit=MAX_HISTORY_ENTRIES) if entry.get("action") == "snapshot"]

    # -- maintenance -----------------------------------------------------
    def reset(self) -> None:
        """Supprime graphe, historique et snapshots (action locale explicite)."""
        with self._lock:
            for path in [self.graph_path, self.history_path, *sorted(self.snapshots_dir.glob("*.json"))]:
                path.unlink(missing_ok=True)
            try:
                self.snapshots_dir.rmdir()
            except OSError:
                pass

    # -- internes --------------------------------------------------------
    def _snapshot_path(self, version: int) -> Path:
        return self.snapshots_dir / f"v{max(0, int(version)):06d}.json"

    def _read_history(self) -> dict[str, Any]:
        payload = _read_json(self.history_path, {"entries": []})
        if not isinstance(payload, dict) or not isinstance(payload.get("entries"), list):
            return {"entries": []}
        return payload

    def _append_history(self, entry: dict[str, Any]) -> None:
        history = self._read_history()
        entries = [item for item in history["entries"] if isinstance(item, dict)]
        entries.append(entry)
        _atomic_write_json(self.history_path, {"entries": entries[-MAX_HISTORY_ENTRIES:]})

    def _prune_snapshots(self) -> None:
        files = sorted(self.snapshots_dir.glob("v*.json"))
        for path in files[: max(0, len(files) - self.max_snapshots)]:
            try:
                path.unlink()
            except OSError:
                pass


__all__ = ["DependencyStore", "GRAPH_FILENAME", "HISTORY_FILENAME", "SNAPSHOTS_DIRNAME"]
