"""Local, private storage for the VC revision coach.

Everything lives under ``~/.nage/vc`` (override: ``NAGE_VC_HOME``).  The
repository never receives learner notes or answers.
"""

from __future__ import annotations

import json
import os
import shutil
from datetime import datetime
from pathlib import Path
from typing import Any

from .errors import InputError, StorageError
from .models import (
    CardProgress,
    CaseAttempt,
    DrillAttempt,
    ExamSession,
    Flashcard,
    PaperAttempt,
    ReviewEvent,
    ReviewSession,
)

SCHEMA_VERSION = 1
CONFIRMATION_PHRASE = "SUPPRIMER MES DONNEES VC"
MARKER = ".nage-vc"
DEFAULT_SETTINGS = {
    "language": "fr",
    "exam_date": "2026-11-06",
    "exam_time": "16:00",
    "exam_duration_minutes": 90,
    "daily_capacity": 60,
}


def default_vc_home() -> Path:
    raw = os.environ.get("NAGE_VC_HOME")
    if raw:
        path = Path(raw).expanduser()
        if not path.is_absolute():
            raise StorageError("NAGE_VC_HOME must be an absolute path.")
        return path
    return Path.home() / ".nage" / "vc"


class VcStore:
    def __init__(self, home: Path | None = None) -> None:
        self._home = Path(home).expanduser() if home is not None else default_vc_home()
        if self._home.is_symlink():
            raise StorageError("The VC folder must not be a symlink.")
        self.warnings: list[str] = []
        self._ensure()

    @property
    def home(self) -> Path:
        return self._home

    @property
    def reports_dir(self) -> Path:
        return self._home / "reports"

    def _ensure(self) -> None:
        try:
            self._home.mkdir(parents=True, exist_ok=True, mode=0o700)
            os.chmod(self._home, 0o700)
            for name in ("sessions", "notes", "exams", "reports", "cases"):
                directory = self._home / name
                directory.mkdir(exist_ok=True, mode=0o700)
                os.chmod(directory, 0o700)
            marker = self._home / MARKER
            if not marker.exists():
                marker.write_text("NAGE VC local storage\n", encoding="utf-8")
            os.chmod(marker, 0o600)
        except OSError as error:
            raise StorageError("Unable to prepare local VC storage.") from error

    def path(self, *parts: str) -> Path:
        return self._home.joinpath(*parts)

    # ------------------------------------------------------------------ JSON
    def _read_json(self, path: Path, default: Any) -> Any:
        if not path.exists():
            return default
        try:
            with path.open("r", encoding="utf-8") as handle:
                return json.load(handle)
        except (OSError, json.JSONDecodeError):
            backup = path.with_name(f"{path.name}.corrupt-{datetime.now():%Y%m%d%H%M%S}")
            try:
                if path.exists():
                    shutil.copy2(path, backup)
            except OSError:
                pass
            self.warnings.append(f"Unreadable local file saved: {path.name}")
            return default

    def _write_json(self, path: Path, payload: Any) -> None:
        path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        temporary = path.with_name(f"{path.name}.tmp")
        try:
            with temporary.open("w", encoding="utf-8") as handle:
                json.dump(payload, handle, ensure_ascii=False, indent=2, sort_keys=True)
                handle.write("\n")
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, path)
            os.chmod(path, 0o600)
        except OSError as error:
            try:
                temporary.unlink(missing_ok=True)
            except OSError:
                pass
            raise StorageError(f"Écriture locale impossible : {path.name}") from error

    def _write_text(self, path: Path, text: str) -> None:
        path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        temporary = path.with_name(f"{path.name}.tmp")
        try:
            with temporary.open("w", encoding="utf-8") as handle:
                handle.write(text)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, path)
            os.chmod(path, 0o600)
        except OSError as error:
            try:
                temporary.unlink(missing_ok=True)
            except OSError:
                pass
            raise StorageError(f"Écriture locale impossible : {path.name}") from error

    # -------------------------------------------------------------- progress
    def load_progress(self) -> dict[str, CardProgress]:
        payload = self._read_json(self.path("progress.json"), {})
        cards = payload.get("cards", {}) if isinstance(payload, dict) else {}
        result: dict[str, CardProgress] = {}
        for card_id, item in cards.items():
            if isinstance(item, dict):
                result[str(card_id)] = CardProgress.from_dict(item)
        return result

    def save_progress(self, progress: dict[str, CardProgress]) -> None:
        payload = {
            "schema_version": SCHEMA_VERSION,
            "cards": {card_id: item.to_dict() for card_id, item in sorted(progress.items())},
        }
        self._write_json(self.path("progress.json"), payload)

    # ---------------------------------------------------------------- reviews
    def append_review(self, event: ReviewEvent) -> None:
        self._append_jsonl(self.path("reviews.jsonl"), event.to_dict())

    def load_reviews(self) -> list[ReviewEvent]:
        return [ReviewEvent.from_dict(item) for item in self._read_jsonl(self.path("reviews.jsonl"))]

    # --------------------------------------------------------------- sessions
    def load_active_session(self) -> ReviewSession | None:
        payload = self._read_json(self.path("sessions", "active.json"), None)
        if not isinstance(payload, dict):
            return None
        try:
            return ReviewSession.from_dict(payload)
        except (TypeError, ValueError):
            self.warnings.append("Unreadable active session ignored.")
            return None

    def save_active_session(self, session: ReviewSession) -> None:
        self._write_json(self.path("sessions", "active.json"), session.to_dict())

    def clear_active_session(self) -> None:
        try:
            self.path("sessions", "active.json").unlink(missing_ok=True)
        except OSError as error:
            raise StorageError("Impossible de fermer la session active.") from error

    def append_session_history(self, summary: dict[str, Any]) -> None:
        self._append_jsonl(self.path("sessions", "history.jsonl"), summary)

    # ------------------------------------------------------------------ exams
    def load_active_exam(self) -> ExamSession | None:
        payload = self._read_json(self.path("exams", "active.json"), None)
        if not isinstance(payload, dict):
            return None
        try:
            return ExamSession.from_dict(payload)
        except (TypeError, ValueError):
            self.warnings.append("Unreadable active exam ignored.")
            return None

    def save_active_exam(self, exam: ExamSession) -> None:
        self._write_json(self.path("exams", "active.json"), exam.to_dict())

    def clear_active_exam(self) -> None:
        try:
            self.path("exams", "active.json").unlink(missing_ok=True)
        except OSError as error:
            raise StorageError("Impossible de fermer l'examen actif.") from error

    def append_exam_history(self, summary: dict[str, Any]) -> None:
        self._append_jsonl(self.path("exams", "history.jsonl"), summary)

    def load_exam_history(self) -> list[dict[str, Any]]:
        return self._read_jsonl(self.path("exams", "history.jsonl"))

    # ------------------------------------------------------------------ notes
    def load_note_index(self) -> dict[str, Any]:
        payload = self._read_json(self.path("notes", "index.json"), {})
        if not isinstance(payload, dict):
            payload = {}
        sources = payload.get("sources")
        proposals = payload.get("proposals")
        rejected = payload.get("rejected_signatures")
        return {
            "schema_version": SCHEMA_VERSION,
            "sources": sources if isinstance(sources, dict) else {},
            "proposals": proposals if isinstance(proposals, dict) else {},
            "rejected_signatures": [
                str(item) for item in rejected if isinstance(item, str)
            ]
            if isinstance(rejected, list)
            else [],
        }

    def save_note_index(self, index: dict[str, Any]) -> None:
        self._write_json(self.path("notes", "index.json"), index)

    def load_note_text(self, source_id: str) -> str | None:
        path = self.path("notes", f"{source_id}.txt")
        if not path.exists():
            return None
        try:
            return path.read_text(encoding="utf-8")
        except OSError as error:
            raise StorageError("Lecture des notes locales impossible.") from error

    def save_note_text(self, source_id: str, text: str) -> None:
        self._write_text(self.path("notes", f"{source_id}.txt"), text)

    def remove_note_text(self, source_id: str) -> None:
        try:
            self.path("notes", f"{source_id}.txt").unlink(missing_ok=True)
        except OSError as error:
            raise StorageError("Suppression de la copie locale impossible.") from error

    # ------------------------------------------------------------------- deck
    def load_deck(self) -> list[Flashcard]:
        payload = self._read_json(self.path("deck.json"), {})
        raw = payload.get("cards", []) if isinstance(payload, dict) else []
        cards: list[Flashcard] = []
        for item in raw if isinstance(raw, list) else []:
            if not isinstance(item, dict):
                continue
            try:
                cards.append(Flashcard.from_dict(item))
            except (TypeError, ValueError):
                self.warnings.append("Unreadable imported card ignored.")
        return sorted(cards, key=lambda card: card.id)

    def save_deck(self, cards: list[Flashcard]) -> None:
        payload = {
            "schema_version": SCHEMA_VERSION,
            "cards": [card.to_dict() for card in sorted(cards, key=lambda item: item.id)],
        }
        self._write_json(self.path("deck.json"), payload)

    # ------------------------------------------------------------ case attempts
    def append_case_attempt(self, attempt: CaseAttempt) -> None:
        self._append_jsonl(self.path("cases", "attempts.jsonl"), attempt.to_dict())

    def load_case_attempts(self) -> list[CaseAttempt]:
        return [
            CaseAttempt.from_dict(item)
            for item in self._read_jsonl(self.path("cases", "attempts.jsonl"))
        ]

    # ----------------------------------------------------------- drill attempts
    def append_drill_attempt(self, attempt: DrillAttempt) -> None:
        self._append_jsonl(self.path("drills", "attempts.jsonl"), attempt.to_dict())

    def load_drill_attempts(self) -> list[DrillAttempt]:
        return [
            DrillAttempt.from_dict(item)
            for item in self._read_jsonl(self.path("drills", "attempts.jsonl"))
        ]

    # ----------------------------------------------------------- paper attempts
    def append_paper_attempt(self, attempt: PaperAttempt) -> None:
        self._append_jsonl(self.path("papers", "attempts.jsonl"), attempt.to_dict())

    def load_paper_attempts(self) -> list[PaperAttempt]:
        return [
            PaperAttempt.from_dict(item)
            for item in self._read_jsonl(self.path("papers", "attempts.jsonl"))
        ]

    # ----------------------------------------------------------- time tracking
    def append_time_entry(self, entry: dict[str, Any]) -> None:
        self._append_jsonl(self.path("time.jsonl"), entry)

    def load_time_entries(self) -> list[dict[str, Any]]:
        return self._read_jsonl(self.path("time.jsonl"))

    # --------------------------------------------------------------- settings
    def load_settings(self) -> dict[str, Any]:
        payload = self._read_json(self.path("settings.json"), {})
        settings = dict(DEFAULT_SETTINGS)
        if isinstance(payload, dict):
            settings.update(payload)
        return settings

    def save_settings(self, settings: dict[str, Any]) -> None:
        merged = dict(DEFAULT_SETTINGS)
        merged.update(settings)
        self._write_json(self.path("settings.json"), merged)

    # ---------------------------------------------------------------- export
    def export_progress(self, destination: Path) -> Path:
        destination = Path(destination).expanduser()
        payload = {
            "schema_version": SCHEMA_VERSION,
            "progress": {
                card_id: item.to_dict() for card_id, item in self.load_progress().items()
            },
            "settings": self.load_settings(),
        }
        self._write_json(destination, payload)
        return destination

    def import_progress(self, source: Path) -> int:
        payload = self._read_json(Path(source).expanduser(), {})
        if not isinstance(payload, dict):
            raise StorageError("Fichier d'import invalide.")
        raw_cards = payload.get("progress") or payload.get("cards") or {}
        if not isinstance(raw_cards, dict):
            raise StorageError("Fichier d'import invalide.")
        progress = self.load_progress()
        imported = 0
        for card_id, item in raw_cards.items():
            if isinstance(item, dict):
                progress[str(card_id)] = CardProgress.from_dict(item)
                imported += 1
        self.save_progress(progress)
        return imported

    # ----------------------------------------------------------------- delete
    def delete_all(self, confirmation: str) -> bool:
        if confirmation != CONFIRMATION_PHRASE:
            raise InputError("Incorrect confirmation phrase; no data deleted.")
        marker = self._home / MARKER
        if not marker.exists():
            raise StorageError("VC folder not recognised; no data deleted.")
        try:
            shutil.rmtree(self._home)
        except OSError as error:
            raise StorageError("Suppression locale impossible.") from error
        return True

    # ---------------------------------------------------------------- helpers
    def _append_jsonl(self, path: Path, payload: dict[str, Any]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        try:
            with path.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(payload, ensure_ascii=False, sort_keys=True))
                handle.write("\n")
                handle.flush()
                os.fsync(handle.fileno())
            os.chmod(path, 0o600)
        except OSError as error:
            raise StorageError(f"Écriture locale impossible : {path.name}") from error

    def _read_jsonl(self, path: Path) -> list[dict[str, Any]]:
        if not path.exists():
            return []
        result: list[dict[str, Any]] = []
        try:
            with path.open("r", encoding="utf-8") as handle:
                for line_number, line in enumerate(handle, 1):
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        item = json.loads(line)
                    except json.JSONDecodeError:
                        self.warnings.append(
                            f"Line ignored in {path.name} (line {line_number})."
                        )
                        continue
                    if isinstance(item, dict):
                        result.append(item)
        except OSError as error:
            raise StorageError(f"Lecture locale impossible : {path.name}") from error
        return result
