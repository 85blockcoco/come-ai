"""Local, append-only personal style memory for Career reformulations.

SPEC-023 asks the résumé-reformulation workflow to remember which verbs, tone,
bullet length, glossary entries and past decisions a person prefers, then to
inject those preferences as explicit constraints in later generations.

Design rules implemented here:

* one local JSON file per Career workspace, private permissions (``0600``);
* an append-only event log with a closed format version and a SHA-256
  integrity digest — a damaged file is reported, never silently reset;
* every preference and every choice can be traced back to the events that
  produced it, and choices can be undone without deleting history;
* three identical observations raise ``confidence`` to at least ``0.8`` and
  mark the preference as automatically applied;
* export/import are lossless, idempotent JSON round-trips;
* a read failure degrades to *no generation* rather than an unconstrained
  generation (see :func:`inject_constraints`).

No network, provider, model or filesystem scan is performed by this module.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import threading
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Sequence

from .memory_types import Glossary, PastChoice, PreferenceSource, StylePreference

MEMORY_FORMAT = "come-ai.career.style-memory"
MEMORY_FORMAT_VERSION = 1
DEFAULT_FILENAME = "style_memory.json"
DEFAULT_MAX_FILE_BYTES = 8 * 1024 * 1024
DEFAULT_MAX_EVENTS = 50_000
AUTO_APPLY_THRESHOLD = 0.8
AUTO_APPLY_OCCURRENCES = 3
MAX_KEY_LENGTH = 80
MAX_VALUE_LENGTH = 300
MAX_CONTEXT_LENGTH = 240
MAX_EVIDENCE_REFS = 20
MAX_REJECTED_OPTIONS = 20
MAX_CHOICE_JSON_BYTES = 24_000
MAX_IMPORT_EVENTS = 100_000

SOURCE_PRIORITY: dict[str, int] = {"auto_infer": 0, "user_pick": 1, "manual": 2}
EVENT_TYPES = frozenset(
    {"preference_observed", "preference_purged", "choice_recorded", "choice_undone"}
)
_KEY_PATTERN = re.compile(r"^[^\W_][\w.:-]{0,79}$", re.UNICODE)
_ID_PATTERN = re.compile(r"^[A-Za-z0-9_-]{8,64}$")
_CONTROL_PATTERN = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")

# Fields from a reformulation option that are meaningful style signals.  Any
# identifier, score, label or evidence field is intentionally ignored: it must
# never become a "preference".
_INFERENCE_FIELDS: tuple[tuple[str, str], ...] = (
    ("action_verb", "js-action-verb"),
    ("verb", "js-action-verb"),
    ("js_action_verb", "js-action-verb"),
    ("tone", "tone"),
    ("bullet_length", "bullet-length"),
    ("length", "bullet-length"),
    ("language", "language"),
    ("formality", "formality"),
)
_IGNORED_CHOICE_FIELDS = frozenset(
    {
        "id",
        "variant_id",
        "option_id",
        "label",
        "text",
        "body",
        "score",
        "confidence",
        "created_at",
        "updated_at",
        "job_id",
        "offer_id",
        "application_id",
        "evidence_refs",
        "rejected",
    }
)


class MemoryStoreError(Exception):
    """Raised when the style memory cannot be read or safely written."""


class MemoryCorruptionError(MemoryStoreError):
    """Raised when the stored file is damaged or has an unsupported format."""


@dataclass(frozen=True, slots=True)
class _PreferenceState:
    value: str
    count: int
    source: PreferenceSource
    updated_at: str


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _clean_text(value: Any, *, field: str, limit: int, allow_empty: bool = False) -> str:
    if not isinstance(value, str):
        raise MemoryStoreError(f"Le champ « {field} » doit être un texte.")
    text = value.strip()
    if _CONTROL_PATTERN.search(text):
        raise MemoryStoreError(f"Le champ « {field} » contient des caractères non autorisés.")
    if not text and not allow_empty:
        raise MemoryStoreError(f"Le champ « {field} » ne peut pas être vide.")
    if len(text) > limit:
        raise MemoryStoreError(f"Le champ « {field} » dépasse {limit} caractères.")
    return text


def _clean_key(value: Any) -> str:
    key = _clean_text(value, field="key", limit=MAX_KEY_LENGTH)
    if not _KEY_PATTERN.fullmatch(key):
        raise MemoryStoreError(
            "La clé de préférence doit commencer par une lettre ou un chiffre et ne contenir que lettres, chiffres, « . : _ - »."
        )
    return key


def _clean_value(value: Any) -> str:
    return _clean_text(value, field="value", limit=MAX_VALUE_LENGTH)


def _clean_source(value: Any) -> PreferenceSource:
    if not isinstance(value, str) or value not in SOURCE_PRIORITY:
        raise MemoryStoreError("La source de préférence est inconnue.")
    return value  # type: ignore[return-value]


def _confidence_for(count: int, source: PreferenceSource) -> float:
    """Deterministic confidence curve.

    Three identical observations always reach at least ``0.8`` so the
    automatic-application rule is visible and testable.
    """
    if source == "manual":
        return 0.95
    if count >= AUTO_APPLY_OCCURRENCES:
        return round(min(0.98, AUTO_APPLY_THRESHOLD + 0.05 * (count - AUTO_APPLY_OCCURRENCES)), 3)
    if count == 2:
        return 0.75 if source == "user_pick" else 0.6
    return 0.5 if source == "user_pick" else 0.35


def _canonical_json(payload: Any) -> bytes:
    return json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _digest(events: Sequence[dict[str, Any]]) -> str:
    return hashlib.sha256(_canonical_json(list(events))).hexdigest()


def _json_copy(value: Any, *, field: str, max_bytes: int) -> Any:
    try:
        encoded = json.dumps(value, ensure_ascii=False)
    except (TypeError, ValueError) as error:
        raise MemoryStoreError(f"Le champ « {field} » doit être sérialisable en JSON.") from error
    if len(encoded.encode("utf-8")) > max_bytes:
        raise MemoryStoreError(f"Le champ « {field} » est trop volumineux.")
    return json.loads(encoded)


def _clean_mapping(value: Any, *, field: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise MemoryStoreError(f"Le champ « {field} » doit être un objet JSON.")
    copied = _json_copy(value, field=field, max_bytes=MAX_CHOICE_JSON_BYTES)
    if not isinstance(copied, dict):
        raise MemoryStoreError(f"Le champ « {field} » doit être un objet JSON.")
    return copied


def _clean_rejected(value: Any) -> list[dict[str, Any]]:
    if value is None:
        return []
    if not isinstance(value, list):
        raise MemoryStoreError("Le champ « rejected » doit être une liste.")
    if len(value) > MAX_REJECTED_OPTIONS:
        raise MemoryStoreError(f"Le champ « rejected » dépasse {MAX_REJECTED_OPTIONS} entrées.")
    return [_clean_mapping(item, field="rejected") for item in value]


def _clean_evidence_refs(value: Any) -> list[str]:
    if value is None:
        return []
    if not isinstance(value, list):
        raise MemoryStoreError("Le champ « evidence_refs » doit être une liste.")
    if len(value) > MAX_EVIDENCE_REFS:
        raise MemoryStoreError(f"Le champ « evidence_refs » dépasse {MAX_EVIDENCE_REFS} entrées.")
    return [_clean_text(item, field="evidence_refs", limit=300) for item in value]


def _glossary_slug(term: str) -> str:
    slug = re.sub(r"[^\w.:-]+", "_", term.strip(), flags=re.UNICODE).strip("._:-")
    return (slug or "terme")[:MAX_KEY_LENGTH - len("glossary:")]


def _infer_preferences(chosen: dict[str, Any]) -> list[tuple[str, str]]:
    """Derive stable preference pairs from the chosen option's style fields."""
    inferred: dict[str, str] = {}

    explicit = chosen.get("preferences")
    if isinstance(explicit, dict):
        for key, value in list(explicit.items())[:20]:
            if isinstance(value, (str, int, float, bool)):
                try:
                    inferred[_clean_key(key)] = _clean_value(str(value))
                except MemoryStoreError:
                    continue

    scalars: dict[str, str] = {}
    for field, preference_key in _INFERENCE_FIELDS:
        if field in _IGNORED_CHOICE_FIELDS:
            continue
        value = chosen.get(field)
        if isinstance(value, (str, int, float, bool)) and str(value).strip():
            try:
                cleaned = _clean_value(str(value))
            except MemoryStoreError:
                continue
            scalars[preference_key] = cleaned
            inferred[preference_key] = cleaned

    tone = scalars.get("tone")
    length = scalars.get("bullet-length")
    if tone and length:
        inferred["tone-length"] = f"{tone} / {length}"

    glossary = chosen.get("glossary")
    entries: list[tuple[str, str]] = []
    if isinstance(glossary, dict):
        entries = [(str(term), str(definition)) for term, definition in glossary.items()]
    elif isinstance(glossary, list):
        for item in glossary[:20]:
            if isinstance(item, dict):
                term = item.get("term") or item.get("key")
                definition = item.get("definition") or item.get("value") or item.get("meaning") or term
                if term:
                    entries.append((str(term), str(definition)))
            elif isinstance(item, str) and item.strip():
                entries.append((item, item))
    for term, definition in entries[:20]:
        try:
            cleaned_term = _clean_text(term, field="glossary term", limit=60)
            cleaned_definition = _clean_value(definition or cleaned_term)
        except MemoryStoreError:
            continue
        inferred[f"glossary:{_glossary_slug(cleaned_term)}"] = cleaned_definition

    return list(inferred.items())


class StyleMemoryStore:
    """Append-only store for personal style preferences and past choices."""

    def __init__(
        self,
        data_dir: Path,
        *,
        filename: str = DEFAULT_FILENAME,
        max_file_bytes: int = DEFAULT_MAX_FILE_BYTES,
        max_events: int = DEFAULT_MAX_EVENTS,
    ):
        self.data_dir = Path(data_dir)
        self.path = self.data_dir / filename
        self.max_file_bytes = int(max_file_bytes)
        self.max_events = int(max_events)
        self._lock = threading.RLock()
        self.data_dir.mkdir(parents=True, exist_ok=True)
        try:
            os.chmod(self.data_dir, 0o700)
        except OSError:
            pass

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------
    def _envelope(self, events: Sequence[dict[str, Any]], *, exported: bool) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "schema": MEMORY_FORMAT,
            "version": MEMORY_FORMAT_VERSION,
            "updated_at": _utc_now(),
            "events": list(events),
            "integrity": _digest(events),
        }
        if exported:
            payload["exported_at"] = payload["updated_at"]
        return payload

    def _read_events(self) -> list[dict[str, Any]]:
        if not self.path.exists():
            return []
        try:
            size = self.path.stat().st_size
        except OSError as error:
            raise MemoryCorruptionError("La mémoire de style locale est illisible.") from error
        if size > self.max_file_bytes:
            raise MemoryCorruptionError("La mémoire de style locale dépasse la taille autorisée.")
        try:
            raw = self.path.read_text(encoding="utf-8")
        except (OSError, UnicodeError) as error:
            raise MemoryCorruptionError("La mémoire de style locale est illisible.") from error
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError as error:
            raise MemoryCorruptionError(
                "La mémoire de style locale est corrompue. Aucune préférence n’est appliquée ; réimporte un export valide."
            ) from error
        try:
            self._validate_envelope(payload, require_integrity=True)
        except MemoryStoreError as error:
            raise MemoryCorruptionError(str(error)) from error
        events = payload["events"]
        if len(events) > self.max_events:
            raise MemoryCorruptionError("La mémoire de style locale contient trop d’événements.")
        return [dict(event) for event in events]

    def _write_events(self, events: Sequence[dict[str, Any]]) -> None:
        if len(events) > self.max_events:
            raise MemoryStoreError("La mémoire de style locale contient trop d’événements.")
        payload = self._envelope(events, exported=False)
        data = json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True).encode("utf-8")
        if len(data) > self.max_file_bytes:
            raise MemoryStoreError("La mémoire de style locale dépasserait la taille autorisée.")
        temporary = self.data_dir / f".{self.path.name}.{uuid.uuid4().hex}.tmp"
        try:
            with open(temporary, "wb") as handle:
                handle.write(data)
                handle.flush()
                os.fsync(handle.fileno())
            os.chmod(temporary, 0o600)
            os.replace(temporary, self.path)
        except OSError as error:
            try:
                temporary.unlink(missing_ok=True)
            except OSError:
                pass
            raise MemoryStoreError("Impossible d’enregistrer la mémoire de style locale.") from error

    def _append(self, new_events: Sequence[dict[str, Any]]) -> list[dict[str, Any]]:
        for event in new_events:
            self._validate_event(event)
        with self._lock:
            events = self._read_events()
            known = {event["id"] for event in events}
            for event in new_events:
                if event["id"] in known:
                    raise MemoryStoreError("Un événement identique existe déjà dans la mémoire.")
                known.add(event["id"])
                events.append(dict(event))
            self._write_events(events)
            return events

    # ------------------------------------------------------------------
    # Validation
    # ------------------------------------------------------------------
    def _validate_envelope(self, payload: Any, *, require_integrity: bool) -> None:
        if not isinstance(payload, dict):
            raise MemoryStoreError("La mémoire de style locale n’a pas le format attendu.")
        if payload.get("schema") != MEMORY_FORMAT:
            raise MemoryStoreError("Ce fichier n’est pas une mémoire de style Côme AI.")
        version = payload.get("version")
        if version != MEMORY_FORMAT_VERSION:
            raise MemoryStoreError(
                "La version de cette mémoire de style n’est pas prise en charge. Aucune donnée n’a été modifiée."
            )
        events = payload.get("events")
        if not isinstance(events, list):
            raise MemoryStoreError("La mémoire de style locale n’a pas le format attendu.")
        if len(events) > MAX_IMPORT_EVENTS:
            raise MemoryStoreError("La mémoire de style locale contient trop d’événements.")
        integrity = payload.get("integrity")
        if require_integrity:
            if not isinstance(integrity, str) or not integrity:
                raise MemoryStoreError("La mémoire de style locale n’a pas d’empreinte d’intégrité.")
            if not hmac_compare(integrity, _digest(events)):
                raise MemoryStoreError(
                    "L’empreinte de la mémoire de style locale ne correspond pas. Aucune préférence n’est appliquée."
                )
        seen: set[str] = set()
        for event in events:
            self._validate_event(event)
            if event["id"] in seen:
                raise MemoryStoreError("La mémoire de style locale contient un événement dupliqué.")
            seen.add(event["id"])
        # Every observation/undo must point to a recorded choice event.
        choice_ids = {event["choice_id"] for event in events if event["type"] == "choice_recorded"}
        for event in events:
            reference = event.get("choice_id")
            if event["type"] in {"choice_undone"} and reference not in choice_ids:
                raise MemoryStoreError("La mémoire de style locale référence un choix inconnu.")
            if event["type"] == "preference_observed" and reference and reference not in choice_ids:
                raise MemoryStoreError("La mémoire de style locale référence un choix inconnu.")

    def _validate_event(self, event: Any) -> None:
        if not isinstance(event, dict):
            raise MemoryStoreError("Un événement de la mémoire de style est invalide.")
        event_id = event.get("id")
        if not isinstance(event_id, str) or not _ID_PATTERN.fullmatch(event_id):
            raise MemoryStoreError("Un événement de la mémoire de style a un identifiant invalide.")
        event_type = event.get("type")
        if event_type not in EVENT_TYPES:
            raise MemoryStoreError("Un événement de la mémoire de style a un type inconnu.")
        if not isinstance(event.get("at"), str) or not event["at"]:
            raise MemoryStoreError("Un événement de la mémoire de style n’a pas d’horodatage.")
        if event_type == "preference_observed":
            _clean_key(event.get("key"))
            _clean_value(event.get("value"))
            _clean_source(event.get("source"))
            choice_id = event.get("choice_id")
            if choice_id is not None and (not isinstance(choice_id, str) or not _ID_PATTERN.fullmatch(choice_id)):
                raise MemoryStoreError("Un événement de préférence référence un choix invalide.")
        elif event_type == "preference_purged":
            _clean_key(event.get("key"))
            if not isinstance(event.get("reason"), str):
                raise MemoryStoreError("Une purge de mémoire doit indiquer sa raison.")
        elif event_type == "choice_recorded":
            _clean_text(event.get("context"), field="context", limit=MAX_CONTEXT_LENGTH)
            _clean_mapping(event.get("chosen"), field="chosen")
            _clean_rejected(event.get("rejected"))
            _clean_evidence_refs(event.get("evidence_refs"))
            choice_id = event.get("choice_id")
            if not isinstance(choice_id, str) or not _ID_PATTERN.fullmatch(choice_id):
                raise MemoryStoreError("Un choix de mémoire a un identifiant invalide.")
        elif event_type == "choice_undone":
            choice_id = event.get("choice_id")
            if not isinstance(choice_id, str) or not _ID_PATTERN.fullmatch(choice_id):
                raise MemoryStoreError("Une annulation de choix a un identifiant invalide.")

    # ------------------------------------------------------------------
    # Replay / materialised views
    # ------------------------------------------------------------------
    def _replay(
        self, events: Sequence[dict[str, Any]]
    ) -> tuple[list[StylePreference], list[PastChoice]]:
        undone_at = {
            event["choice_id"]: event["at"]
            for event in events
            if event["type"] == "choice_undone"
        }
        choices: dict[str, PastChoice] = {}
        order: list[str] = []
        states: dict[str, _PreferenceState] = {}

        for event in events:
            event_type = event["type"]
            if event_type == "choice_recorded":
                choice_id = event["choice_id"]
                choices[choice_id] = PastChoice(
                    id=choice_id,
                    context=event["context"],
                    chosen=dict(event["chosen"]),
                    rejected=[dict(item) for item in event["rejected"]],
                    evidence_refs=list(event["evidence_refs"]),
                    created_at=event["at"],
                    undone_at=undone_at.get(choice_id),
                )
                order.append(choice_id)
            elif event_type == "choice_undone":
                existing = choices.get(event["choice_id"])
                if existing is not None:
                    choices[event["choice_id"]] = PastChoice(
                        id=existing.id,
                        context=existing.context,
                        chosen=existing.chosen,
                        rejected=existing.rejected,
                        evidence_refs=existing.evidence_refs,
                        created_at=existing.created_at,
                        undone_at=event["at"],
                    )
            elif event_type == "preference_purged":
                states.pop(event["key"], None)
            elif event_type == "preference_observed":
                choice_id = event.get("choice_id")
                if choice_id and choice_id in undone_at:
                    continue
                key = event["key"]
                value = event["value"]
                source = event["source"]
                current = states.get(key)
                if current is not None:
                    priority = SOURCE_PRIORITY[source]
                    current_priority = SOURCE_PRIORITY[current.source]
                    if priority < current_priority:
                        continue
                    if current.value == value:
                        states[key] = _PreferenceState(
                            value=value,
                            count=current.count + 1,
                            source=source if priority >= current_priority else current.source,
                            updated_at=event["at"],
                        )
                        continue
                states[key] = _PreferenceState(
                    value=value,
                    count=1,
                    source=source,
                    updated_at=event["at"],
                )

        preferences: list[StylePreference] = []
        for key, state in states.items():
            confidence = _confidence_for(state.count, state.source)
            preferences.append(
                StylePreference(
                    key=key,
                    value=state.value,
                    confidence=confidence,
                    source=state.source,
                    updated_at=state.updated_at,
                    occurrences=state.count,
                    auto_applied=confidence >= AUTO_APPLY_THRESHOLD,
                )
            )
        preferences.sort(
            key=lambda item: (
                not item.auto_applied,
                -item.confidence,
                _reverse_timestamp(item.updated_at),
                item.key,
            )
        )
        past_choices = [choices[choice_id] for choice_id in reversed(order)]
        return preferences, past_choices

    # ------------------------------------------------------------------
    # Public reads
    # ------------------------------------------------------------------
    def list_preferences(self) -> list[StylePreference]:
        with self._lock:
            return self._replay(self._read_events())[0]

    def list_choices(self) -> list[PastChoice]:
        with self._lock:
            return self._replay(self._read_events())[1]

    def get_choice(self, choice_id: str) -> PastChoice:
        wanted = _clean_text(choice_id, field="choice_id", limit=64)
        for choice in self.list_choices():
            if choice.id == wanted:
                return choice
        raise MemoryStoreError("Ce choix est introuvable dans l’historique.")

    def glossary(self) -> list[Glossary]:
        entries: list[Glossary] = []
        for preference in self.list_preferences():
            if not preference.key.startswith("glossary:"):
                continue
            term = preference.key.split(":", 1)[1].replace("_", " ").strip() or preference.key
            entries.append(
                Glossary(
                    term=term,
                    definition=preference.value,
                    key=preference.key,
                    source=preference.source,
                    updated_at=preference.updated_at,
                )
            )
        return entries

    def constraints(self, limit: int = 5, *, only_auto: bool = False) -> list[dict[str, Any]]:
        """Return the top preferences to inject into a reformulation prompt."""
        if not isinstance(limit, int) or not 1 <= limit <= 20:
            raise MemoryStoreError("La limite de contraintes doit être comprise entre 1 et 20.")
        preferences = self.list_preferences()
        if only_auto:
            preferences = [item for item in preferences if item.auto_applied]
        return [
            {
                "key": item.key,
                "value": item.value,
                "confidence": item.confidence,
                "source": item.source,
                "auto_applied": item.auto_applied,
                "constraint": f"{item.key} = {item.value}",
            }
            for item in preferences[:limit]
        ]

    def format_constraints(self, limit: int = 5, *, only_auto: bool = False) -> list[str]:
        return [item["constraint"] for item in self.constraints(limit, only_auto=only_auto)]

    # ------------------------------------------------------------------
    # Public writes
    # ------------------------------------------------------------------
    def record_preference(self, key: str, value: str, *, source: PreferenceSource = "manual") -> StylePreference:
        clean_key = _clean_key(key)
        clean_value = _clean_value(value)
        clean_source = _clean_source(source)
        event = {
            "id": uuid.uuid4().hex,
            "type": "preference_observed",
            "at": _utc_now(),
            "key": clean_key,
            "value": clean_value,
            "source": clean_source,
            "choice_id": None,
        }
        events = self._append([event])
        preferences = {item.key: item for item in self._replay(events)[0]}
        return preferences[clean_key]

    def record_choice(
        self,
        context: str,
        chosen: dict[str, Any],
        rejected: Iterable[dict[str, Any]] | None = None,
        evidence_refs: Iterable[str] | None = None,
    ) -> dict[str, Any]:
        """Post-choice hook: record the decision and learn from its style."""
        clean_context = _clean_text(context, field="context", limit=MAX_CONTEXT_LENGTH)
        clean_chosen = _clean_mapping(chosen, field="chosen")
        clean_rejected = _clean_rejected(list(rejected or []))
        clean_refs = _clean_evidence_refs(list(evidence_refs or []))
        choice_id = uuid.uuid4().hex
        at = _utc_now()

        events: list[dict[str, Any]] = [
            {
                "id": uuid.uuid4().hex,
                "type": "choice_recorded",
                "at": at,
                "choice_id": choice_id,
                "context": clean_context,
                "chosen": clean_chosen,
                "rejected": clean_rejected,
                "evidence_refs": clean_refs,
            }
        ]
        learned: list[tuple[str, str]] = []
        for key, value in _infer_preferences(clean_chosen):
            learned.append((key, value))
            events.append(
                {
                    "id": uuid.uuid4().hex,
                    "type": "preference_observed",
                    "at": at,
                    "key": key,
                    "value": value,
                    "source": "user_pick",
                    "choice_id": choice_id,
                }
            )

        stored = self._append(events)
        preferences = {item.key: item for item in self._replay(stored)[0]}
        choice = self.get_choice(choice_id)
        return {
            "choice": choice.to_dict(),
            "learned": [
                preferences[key].to_dict()
                for key, _ in learned
                if key in preferences
            ],
        }

    def undo_choice(self, choice_id: str) -> dict[str, Any]:
        """Undo one choice without deleting its audit trail."""
        wanted = _clean_text(choice_id, field="choice_id", limit=64)
        choice = self.get_choice(wanted)
        if choice.undone:
            raise MemoryStoreError("Ce choix est déjà annulé.")
        event = {
            "id": uuid.uuid4().hex,
            "type": "choice_undone",
            "at": _utc_now(),
            "choice_id": wanted,
        }
        stored = self._append([event])
        preferences = self._replay(stored)[0]
        updated = self.get_choice(wanted)
        return {
            "choice": updated.to_dict(),
            "preferences": [item.to_dict() for item in preferences],
        }

    def purge_preference(self, key: str, *, reason: str = "Demande de l’utilisateur") -> bool:
        """Purge a preference with an explicit, auditable tombstone event."""
        clean_key = _clean_key(key)
        clean_reason = _clean_text(reason, field="reason", limit=240)
        existing = {item.key for item in self.list_preferences()}
        if clean_key not in existing:
            return False
        event = {
            "id": uuid.uuid4().hex,
            "type": "preference_purged",
            "at": _utc_now(),
            "key": clean_key,
            "reason": clean_reason,
        }
        self._append([event])
        return True

    # ------------------------------------------------------------------
    # Export / import
    # ------------------------------------------------------------------
    def export_envelope(self) -> dict[str, Any]:
        with self._lock:
            events = self._read_events()
            return self._envelope(events, exported=True)

    def import_envelope(self, payload: Any) -> dict[str, Any]:
        """Merge a previously exported memory, idempotently and atomically."""
        if not isinstance(payload, dict):
            raise MemoryStoreError("Le fichier importé n’est pas une mémoire de style Côme AI.")
        if "export" in payload and "events" not in payload:
            payload = payload["export"]
        if not isinstance(payload, dict):
            raise MemoryStoreError("Le fichier importé n’est pas une mémoire de style Côme AI.")
        self._validate_envelope(payload, require_integrity=True)
        incoming = [dict(event) for event in payload["events"]]
        with self._lock:
            events = self._read_events()
            by_id = {event["id"]: event for event in events}
            added = 0
            skipped = 0
            for event in incoming:
                current = by_id.get(event["id"])
                if current is not None:
                    if _canonical_json(current) != _canonical_json(event):
                        raise MemoryStoreError(
                            "Deux événements différents partagent le même identifiant. Aucune donnée n’a été modifiée."
                        )
                    skipped += 1
                    continue
                by_id[event["id"]] = event
                events.append(event)
                added += 1
            if added:
                self._write_events(events)
            preferences, choices = self._replay(events)
            return {
                "imported": added,
                "skipped": skipped,
                "preferences_count": len(preferences),
                "choices_count": len(choices),
            }

    def stats(self) -> dict[str, Any]:
        preferences, choices = self._replay(self._read_events())
        return {
            "preferences_count": len(preferences),
            "auto_applied_count": sum(1 for item in preferences if item.auto_applied),
            "glossary_count": sum(1 for item in preferences if item.key.startswith("glossary:")),
            "choices_count": len(choices),
            "undone_choices_count": sum(1 for item in choices if item.undone),
            "path_is_private": _is_private(self.path),
        }


def hmac_compare(left: str, right: str) -> bool:
    """Constant-time digest comparison without importing a networking stack."""
    import hmac

    return hmac.compare_digest(left, right)


def _is_private(path: Path) -> bool:
    try:
        return (path.stat().st_mode & 0o077) == 0
    except OSError:
        # A missing file will be created with private permissions on write.
        return True


def _reverse_timestamp(value: str) -> float:
    """Sort most-recent timestamps first without parsing every value."""
    try:
        return -datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp()
    except ValueError:
        return 0.0


def inject_constraints(store: StyleMemoryStore, limit: int = 5) -> dict[str, Any]:
    """Fail-closed helper for the reformulation/arena generators.

    If the memory can be read, the caller receives the top constraints and may
    generate.  If it is corrupted, the caller receives ``generation_allowed``
    ``False`` and must not generate an unconstrained variant.
    """
    try:
        return {
            "constraints": store.constraints(limit),
            "degraded": False,
            "generation_allowed": True,
        }
    except MemoryStoreError as error:
        return {
            "constraints": [],
            "degraded": True,
            "generation_allowed": False,
            "reason": str(error),
        }


# ---------------------------------------------------------------------------
# N100-I01 personal memory (kept alongside the SPEC-023 style memory store)
# ---------------------------------------------------------------------------
from dataclasses import asdict  # noqa: E402  (N100 MemoryEntry serialization)

import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any


@dataclass
class MemoryEntry:
    key: str
    value: Any
    source: str = "user"
    approved: bool = False


class PersonalMemory:
    def __init__(self, path: str | Path | None = None) -> None:
        if path is None:
            path = Path(".") / "personal_memory.json"
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._data: dict[str, MemoryEntry] = {}
        self._load()

    def _load(self) -> None:
        if self.path.exists():
            try:
                raw = json.loads(self.path.read_text(encoding="utf-8"))
                for k, v in raw.items():
                    v = {kk: vv for kk, vv in v.items() if kk != "key"}
                    self._data[k] = MemoryEntry(key=k, **v)
            except (json.JSONDecodeError, TypeError):
                self._data = {}

    def _save(self) -> None:
        self.path.write_text(json.dumps({k: asdict(v) for k, v in self._data.items()}, ensure_ascii=False, indent=2), encoding="utf-8")

    def set(self, key: str, value: Any, source: str = "user", approved: bool = False) -> MemoryEntry:
        entry = MemoryEntry(key=key, value=value, source=source, approved=approved)
        self._data[key] = entry
        self._save()
        return entry

    def get(self, key: str) -> MemoryEntry | None:
        return self._data.get(key)

    def all(self) -> list[MemoryEntry]:
        return list(self._data.values())

    def delete(self, key: str) -> bool:
        if key in self._data:
            del self._data[key]
            self._save()
            return True
        return False
