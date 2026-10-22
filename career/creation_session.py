"""State, persistence and preference learning for the creation assistant.

The module is deliberately local-first and deterministic.  It stores one JSON
document per Career data directory (never in the shared document workspace),
learns only from explicit user decisions, and keeps every applied suggestion
traceable through its rationale and evidence references.

Nothing here calls a model, the network, or a public service.
"""

from __future__ import annotations

import json
import os
import re
import tempfile
import threading
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

from .models import clean_text, normalized_text, utc_now
from workspace_core import UserFacingError


CreationType = Literal["cv", "cover_letter", "profile", "application", "interview_prep"]
SessionStatus = Literal["draft", "reviewing", "validating", "finalized", "exported"]
StepType = Literal["select", "write", "review", "validate", "attach", "choose"]
StepStatus = Literal["pending", "in_progress", "completed", "skipped"]
SuggestionType = Literal[
    "text", "structure", "proof", "reformulation", "addition", "removal", "reorder"
]
SuggestionAction = Literal["accept", "modify", "reject", "defer"]
Severity = Literal["blocking", "warning", "info"]
DetailLevel = Literal["synthetic", "balanced", "detailed"]
Tone = Literal["formal", "neutral", "direct"]

CREATION_TYPES: tuple[str, ...] = (
    "cv",
    "cover_letter",
    "profile",
    "application",
    "interview_prep",
)
SESSION_STATUSES: tuple[str, ...] = (
    "draft",
    "reviewing",
    "validating",
    "finalized",
    "exported",
)
STEP_TYPES: tuple[str, ...] = ("select", "write", "review", "validate", "attach", "choose")
STEP_STATUSES: tuple[str, ...] = ("pending", "in_progress", "completed", "skipped")
SUGGESTION_TYPES: tuple[str, ...] = (
    "text",
    "structure",
    "proof",
    "reformulation",
    "addition",
    "removal",
    "reorder",
)
SUGGESTION_ACTIONS: tuple[str, ...] = ("accept", "modify", "reject", "defer")

MAX_STEPS = 12
MAX_SESSIONS = 200
MAX_TEXT = 20_000
MAX_MAPPING_ENTRIES = 50
PREFERENCES_MIN_SESSIONS = 3
LEARNING_HISTORY_LIMIT = 50

CREATION_LABELS: dict[str, str] = {
    "cv": "CV ciblé",
    "cover_letter": "Lettre de motivation",
    "profile": "Profil candidat",
    "application": "Candidature complète",
    "interview_prep": "Préparation d’entretien",
}


def choice(value: Any, allowed: tuple[str, ...], label: str) -> str:
    """Validate a small enumerated value without silently guessing."""
    text = clean_text(value, limit=60)
    if text not in allowed:
        raise UserFacingError(f"{label} inconnu : choisissez une valeur proposée.")
    return text


def _bounded_text(value: Any, *, limit: int = 2_000) -> str:
    return clean_text(value, limit=min(limit, MAX_TEXT))


def _bounded_mapping(value: Any, label: str) -> dict[str, str]:
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise UserFacingError(f"{label} doit être un objet clé/valeur.")
    if len(value) > MAX_MAPPING_ENTRIES:
        raise UserFacingError(f"{label} contient trop d’entrées (maximum {MAX_MAPPING_ENTRIES}).")
    result: dict[str, str] = {}
    for raw_key, raw_value in value.items():
        key = _bounded_text(raw_key, limit=120)
        item = _bounded_text(raw_value, limit=120)
        if not key or not item:
            raise UserFacingError(f"{label} doit contenir des clés et des valeurs non vides.")
        result[key] = item
    return result


def _bounded_list(value: Any, label: str) -> list[str]:
    if value is None:
        return []
    if not isinstance(value, (list, tuple)):
        raise UserFacingError(f"{label} doit être une liste.")
    if len(value) > MAX_MAPPING_ENTRIES:
        raise UserFacingError(f"{label} contient trop d’entrées (maximum {MAX_MAPPING_ENTRIES}).")
    result: list[str] = []
    for item in value:
        text = _bounded_text(item, limit=160)
        if text and text not in result:
            result.append(text)
    return result


@dataclass(frozen=True)
class ValidationRule:
    """The rule attached to a wizard step, not a validation result."""

    rule_id: str
    label: str
    severity: Severity = "warning"
    check: str = "manual"
    params: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "rule_id": self.rule_id,
            "label": self.label,
            "severity": self.severity,
            "check": self.check,
            "params": dict(self.params),
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "ValidationRule":
        return cls(
            rule_id=_bounded_text(payload.get("rule_id"), limit=80),
            label=_bounded_text(payload.get("label"), limit=200),
            severity=payload.get("severity") if payload.get("severity") in {"blocking", "warning", "info"} else "warning",
            check=_bounded_text(payload.get("check"), limit=80) or "manual",
            params=dict(payload.get("params") or {}),
        )


@dataclass
class Suggestion:
    """A contextual proposal with an explicit, human-readable rationale."""

    suggestion_id: str
    type: SuggestionType
    content: str
    rationale: str
    evidence_refs: list[str] = field(default_factory=list)
    confidence: float = 0.0
    alternatives: list[str] = field(default_factory=list)
    action: SuggestionAction = "defer"
    applied_at: str | None = None
    applied_by: Literal["user", "auto"] | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
    score_components: dict[str, float] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "suggestion_id": self.suggestion_id,
            "type": self.type,
            "content": self.content,
            "rationale": self.rationale,
            "evidence_refs": list(self.evidence_refs),
            "confidence": round(float(self.confidence), 2),
            "alternatives": list(self.alternatives),
            "action": self.action,
            "applied_at": self.applied_at,
            "applied_by": self.applied_by,
            "metadata": dict(self.metadata),
            "score_components": {key: round(float(value), 3) for key, value in self.score_components.items()},
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "Suggestion":
        return cls(
            suggestion_id=_bounded_text(payload.get("suggestion_id"), limit=80),
            type=payload.get("type") if payload.get("type") in SUGGESTION_TYPES else "text",
            content=_bounded_text(payload.get("content"), limit=MAX_TEXT),
            rationale=_bounded_text(payload.get("rationale"), limit=4_000),
            evidence_refs=_bounded_list(payload.get("evidence_refs"), "Références de preuve"),
            confidence=max(0.0, min(1.0, float(payload.get("confidence") or 0.0))),
            alternatives=_bounded_list(payload.get("alternatives"), "Alternatives"),
            action=payload.get("action") if payload.get("action") in SUGGESTION_ACTIONS else "defer",
            applied_at=_bounded_text(payload.get("applied_at"), limit=40) or None,
            applied_by=payload.get("applied_by") if payload.get("applied_by") in {"user", "auto"} else None,
            metadata=dict(payload.get("metadata") or {}),
            score_components={
                str(key): float(value)
                for key, value in (payload.get("score_components") or {}).items()
            },
        )


@dataclass
class CreationStep:
    step_id: str
    step_number: int
    title: str
    description: str
    type: StepType
    content: dict[str, Any] = field(default_factory=dict)
    suggestions: list[Suggestion] = field(default_factory=list)
    validation: ValidationRule | None = None
    user_input: dict[str, Any] | None = None
    status: StepStatus = "pending"
    started_at: str | None = None
    completed_at: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "step_id": self.step_id,
            "step_number": self.step_number,
            "title": self.title,
            "description": self.description,
            "type": self.type,
            "content": dict(self.content),
            "suggestions": [suggestion.to_dict() for suggestion in self.suggestions],
            "validation": self.validation.to_dict() if self.validation else None,
            "user_input": dict(self.user_input) if self.user_input is not None else None,
            "status": self.status,
            "started_at": self.started_at,
            "completed_at": self.completed_at,
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "CreationStep":
        raw_validation = payload.get("validation")
        return cls(
            step_id=_bounded_text(payload.get("step_id"), limit=80),
            step_number=max(1, int(payload.get("step_number") or 1)),
            title=_bounded_text(payload.get("title"), limit=200),
            description=_bounded_text(payload.get("description"), limit=2_000),
            type=payload.get("type") if payload.get("type") in STEP_TYPES else "write",
            content=dict(payload.get("content") or {}),
            suggestions=[
                Suggestion.from_dict(item)
                for item in payload.get("suggestions") or []
                if isinstance(item, dict)
            ],
            validation=ValidationRule.from_dict(raw_validation) if isinstance(raw_validation, dict) else None,
            user_input=dict(payload.get("user_input")) if isinstance(payload.get("user_input"), dict) else None,
            status=payload.get("status") if payload.get("status") in STEP_STATUSES else "pending",
            started_at=_bounded_text(payload.get("started_at"), limit=40) or None,
            completed_at=_bounded_text(payload.get("completed_at"), limit=40) or None,
        )


@dataclass
class CreationSession:
    session_id: str
    user_id: str
    creation_type: CreationType
    target_offer_id: str | None
    status: SessionStatus
    current_step: int
    total_steps: int
    context: dict[str, Any]
    steps: list[CreationStep]
    created_at: str
    updated_at: str
    completed_at: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "session_id": self.session_id,
            "user_id": self.user_id,
            "creation_type": self.creation_type,
            "creation_label": CREATION_LABELS.get(self.creation_type, self.creation_type),
            "target_offer_id": self.target_offer_id,
            "status": self.status,
            "current_step": self.current_step,
            "total_steps": self.total_steps,
            "context": dict(self.context),
            "steps": [step.to_dict() for step in self.steps],
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "completed_at": self.completed_at,
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "CreationSession":
        steps = [
            CreationStep.from_dict(item)
            for item in payload.get("steps") or []
            if isinstance(item, dict)
        ]
        return cls(
            session_id=_bounded_text(payload.get("session_id"), limit=80),
            user_id=_bounded_text(payload.get("user_id"), limit=80) or "local-user",
            creation_type=payload.get("creation_type") if payload.get("creation_type") in CREATION_TYPES else "cv",
            target_offer_id=_bounded_text(payload.get("target_offer_id"), limit=80) or None,
            status=payload.get("status") if payload.get("status") in SESSION_STATUSES else "draft",
            current_step=max(1, int(payload.get("current_step") or 1)),
            total_steps=max(len(steps), int(payload.get("total_steps") or len(steps) or 1)),
            context=dict(payload.get("context") or {}),
            steps=steps,
            created_at=_bounded_text(payload.get("created_at"), limit=40),
            updated_at=_bounded_text(payload.get("updated_at"), limit=40),
            completed_at=_bounded_text(payload.get("completed_at"), limit=40) or None,
        )


@dataclass
class CreationPreferences:
    """Only explicit decisions are learned; nothing is inferred silently."""

    user_id: str
    preferred_verbs: dict[str, str] = field(default_factory=dict)
    avoided_terms: dict[str, str] = field(default_factory=dict)
    technical_terms: dict[str, str] = field(default_factory=dict)
    section_order: list[str] = field(default_factory=list)
    detail_level: DetailLevel = "balanced"
    tone: Tone = "neutral"
    explicit: bool = False
    decisions: dict[str, int] = field(default_factory=dict)
    seen_sessions: list[str] = field(default_factory=list)
    updated_at: str = field(default_factory=utc_now)

    @property
    def learned_from_sessions(self) -> int:
        return len(self.seen_sessions)

    @property
    def active(self) -> bool:
        return self.explicit or self.learned_from_sessions >= PREFERENCES_MIN_SESSIONS

    def to_dict(self) -> dict[str, Any]:
        return {
            "user_id": self.user_id,
            "preferred_verbs": dict(self.preferred_verbs),
            "avoided_terms": dict(self.avoided_terms),
            "technical_terms": dict(self.technical_terms),
            "section_order": list(self.section_order),
            "detail_level": self.detail_level,
            "tone": self.tone,
            "explicit": self.explicit,
            "decisions": dict(self.decisions),
            "seen_sessions": list(self.seen_sessions),
            "learned_from_sessions": self.learned_from_sessions,
            "activation_threshold": PREFERENCES_MIN_SESSIONS,
            "active": self.active,
            "updated_at": self.updated_at,
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "CreationPreferences":
        detail = payload.get("detail_level")
        tone = payload.get("tone")
        seen = _bounded_list(payload.get("seen_sessions"), "Sessions apprises")
        return cls(
            user_id=_bounded_text(payload.get("user_id"), limit=80) or "local-user",
            preferred_verbs=_bounded_mapping(payload.get("preferred_verbs"), "Verbes préférés"),
            avoided_terms=_bounded_mapping(payload.get("avoided_terms"), "Termes évités"),
            technical_terms=_bounded_mapping(payload.get("technical_terms"), "Termes techniques"),
            section_order=_bounded_list(payload.get("section_order"), "Ordre des sections"),
            detail_level=detail if detail in {"synthetic", "balanced", "detailed"} else "balanced",
            tone=tone if tone in {"formal", "neutral", "direct"} else "neutral",
            explicit=bool(payload.get("explicit")),
            decisions={
                str(key): int(value)
                for key, value in (payload.get("decisions") or {}).items()
                if isinstance(value, (int, float))
            },
            seen_sessions=seen[-LEARNING_HISTORY_LIMIT:],
            updated_at=_bounded_text(payload.get("updated_at"), limit=40) or utc_now(),
        )


def _atomic_write(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        os.chmod(path.parent, 0o700)
    except OSError:
        pass
    descriptor, temporary = tempfile.mkstemp(prefix=f".{path.stem}-", suffix=".tmp", dir=path.parent)
    temporary_path = Path(temporary)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        try:
            os.chmod(temporary_path, 0o600)
        except OSError:
            pass
        os.replace(temporary_path, path)
    finally:
        temporary_path.unlink(missing_ok=True)


def _read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as error:
        raise UserFacingError(
            "Les données locales de l’assistant de création sont illisibles. Sauvegardez puis réinitialisez-les."
        ) from error
    if not isinstance(payload, dict):
        raise UserFacingError("Les données locales de l’assistant de création ont un format inattendu.")
    return payload


class CreationStore:
    """Small JSON store scoped to one Career data directory."""

    def __init__(self, directory: Path) -> None:
        self.directory = Path(directory)
        self.sessions_path = self.directory / "sessions.json"
        self.preferences_path = self.directory / "preferences.json"
        self._lock = threading.RLock()
        self._sessions: dict[str, dict[str, Any]] | None = None
        self._preferences: dict[str, dict[str, Any]] | None = None

    def _load_sessions(self) -> dict[str, dict[str, Any]]:
        if self._sessions is None:
            raw = _read_json(self.sessions_path)
            sessions = raw.get("sessions")
            self._sessions = sessions if isinstance(sessions, dict) else {}
        return self._sessions

    def _load_preferences(self) -> dict[str, dict[str, Any]]:
        if self._preferences is None:
            raw = _read_json(self.preferences_path)
            preferences = raw.get("preferences")
            self._preferences = preferences if isinstance(preferences, dict) else {}
        return self._preferences

    def save_session(self, session: CreationSession) -> dict[str, Any]:
        payload = session.to_dict()
        with self._lock:
            sessions = self._load_sessions()
            sessions[session.session_id] = payload
            if len(sessions) > MAX_SESSIONS:
                oldest = min(
                    sessions.values(),
                    key=lambda item: (_bounded_text(item.get("updated_at"), limit=40), _bounded_text(item.get("session_id"), limit=80)),
                )
                sessions.pop(str(oldest.get("session_id")), None)
            _atomic_write(self.sessions_path, {"version": 1, "sessions": sessions})
        return payload

    def get_session(self, session_id: str) -> dict[str, Any]:
        identifier = _bounded_text(session_id, limit=80)
        with self._lock:
            payload = self._load_sessions().get(identifier)
        if payload is None:
            raise UserFacingError("Cette session de création n’existe pas ou a été supprimée.")
        return payload

    def list_sessions(self, *, user_id: str | None = None) -> list[dict[str, Any]]:
        with self._lock:
            values = list(self._load_sessions().values())
        if user_id:
            values = [value for value in values if value.get("user_id") == user_id]
        return sorted(
            values,
            key=lambda value: (_bounded_text(value.get("updated_at"), limit=40), _bounded_text(value.get("session_id"), limit=80)),
            reverse=True,
        )

    def delete_session(self, session_id: str) -> None:
        identifier = _bounded_text(session_id, limit=80)
        with self._lock:
            sessions = self._load_sessions()
            if identifier not in sessions:
                raise UserFacingError("Cette session de création n’existe pas ou a été supprimée.")
            sessions.pop(identifier)
            _atomic_write(self.sessions_path, {"version": 1, "sessions": sessions})

    def get_preferences(self, user_id: str) -> CreationPreferences:
        identifier = _bounded_text(user_id, limit=80) or "local-user"
        with self._lock:
            payload = self._load_preferences().get(identifier)
        if payload is None:
            return CreationPreferences(user_id=identifier)
        return CreationPreferences.from_dict(payload)

    def save_preferences(self, preferences: CreationPreferences) -> dict[str, Any]:
        payload = preferences.to_dict()
        with self._lock:
            values = self._load_preferences()
            values[preferences.user_id] = payload
            _atomic_write(self.preferences_path, {"version": 1, "preferences": values})
        return payload


def learn_from_decision(
    preferences: CreationPreferences,
    suggestion: Suggestion,
    decision: Literal["accept", "modify", "reject"],
    *,
    session_id: str,
    now: str,
) -> CreationPreferences:
    """Update preferences from one explicit decision, never from silence."""
    preferences.decisions[decision] = preferences.decisions.get(decision, 0) + 1
    typed_key = f"{decision}:{suggestion.type}"
    preferences.decisions[typed_key] = preferences.decisions.get(typed_key, 0) + 1
    identifier = _bounded_text(session_id, limit=80)
    if identifier and identifier not in preferences.seen_sessions:
        preferences.seen_sessions.append(identifier)
        preferences.seen_sessions = preferences.seen_sessions[-LEARNING_HISTORY_LIMIT:]

    metadata = suggestion.metadata or {}
    avoided = _bounded_text(metadata.get("avoided_term"), limit=120)
    preferred = _bounded_text(metadata.get("preferred_term"), limit=120)
    section = _bounded_text(metadata.get("section"), limit=120)
    section_before = _bounded_text(metadata.get("section_before"), limit=120)

    if decision in {"accept", "modify"}:
        if avoided and preferred:
            preferences.preferred_verbs[avoided] = preferred
            preferences.avoided_terms.pop(preferred, None)
        source_term = _bounded_text(metadata.get("technical_from"), limit=120)
        target_term = _bounded_text(metadata.get("technical_to"), limit=120)
        if source_term and target_term:
            preferences.technical_terms[source_term] = target_term
        if section:
            ordered = [section] + [item for item in preferences.section_order if item != section]
            preferences.section_order = ordered[:MAX_MAPPING_ENTRIES]
        if section_before and section:
            ordered = [item for item in preferences.section_order if item != section]
            insertion = 0
            for index, item in enumerate(ordered):
                if normalized_text(item) == normalized_text(section_before):
                    insertion = index
                    break
            ordered.insert(insertion, section)
            preferences.section_order = ordered[:MAX_MAPPING_ENTRIES]
        detail = metadata.get("detail_level")
        if detail in {"synthetic", "balanced", "detailed"}:
            preferences.detail_level = detail
        tone = metadata.get("tone")
        if tone in {"formal", "neutral", "direct"}:
            preferences.tone = tone
    elif avoided and preferred:
        # Rejecting "use X instead of Y" records the opposite preference.
        preferences.avoided_terms[preferred] = avoided
        if preferences.preferred_verbs.get(avoided) == preferred:
            preferences.preferred_verbs.pop(avoided, None)

    preferences.updated_at = now
    return preferences


def record_session_use(preferences: CreationPreferences, session_id: str, *, now: str) -> CreationPreferences:
    """Count a session once, even when it produced no suggestion decision."""
    identifier = _bounded_text(session_id, limit=80)
    if identifier and identifier not in preferences.seen_sessions:
        preferences.seen_sessions.append(identifier)
        preferences.seen_sessions = preferences.seen_sessions[-LEARNING_HISTORY_LIMIT:]
    preferences.updated_at = now
    return preferences


def preference_match_score(
    preferences: CreationPreferences,
    *,
    preferred_term: str = "",
    avoided_term: str = "",
    section: str = "",
) -> float:
    """Return the 0..1 preference component used by the suggestion formula."""
    if not preferences.active:
        return 0.5
    preferred = normalized_text(preferred_term)
    avoided = normalized_text(avoided_term)
    for source, target in preferences.preferred_verbs.items():
        source_key, target_key = normalized_text(source), normalized_text(target)
        if preferred and avoided and source_key == avoided and target_key == preferred:
            return 1.0
        if avoided and source_key == avoided:
            return 1.0
        if preferred and target_key == preferred:
            return 1.0
    for rejected in preferences.avoided_terms:
        if preferred and normalized_text(rejected) == preferred:
            return 0.1
    if section:
        ordered = [normalized_text(item) for item in preferences.section_order]
        target = normalized_text(section)
        if ordered and ordered[0] == target:
            return 1.0
        if target in ordered:
            return 0.8
    return 0.6


def apply_preferences(text: str, preferences: CreationPreferences) -> str:
    """Apply only learned, explicit wording preferences; never invent facts."""
    if not preferences.active or not text:
        return text
    result = _bounded_text(text, limit=MAX_TEXT)
    replacements: list[tuple[str, str]] = []
    replacements.extend(preferences.preferred_verbs.items())
    replacements.extend(preferences.technical_terms.items())
    for source, target in replacements:
        if not source or not target or source == target:
            continue
        pattern = re.compile(rf"(?<!\w){re.escape(source)}(?!\w)", re.IGNORECASE)
        result = pattern.sub(target, result)
    return result[:MAX_TEXT]


def new_session_id() -> str:
    return uuid.uuid4().hex
