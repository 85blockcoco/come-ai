"""Journal d'audit append-only des décisions automatisées (SPEC-035).

Chaque décision automatisée (classement d'offre, relance suggérée, verdict
d'arène…) est enregistrée une seule fois : qui, quand, contexte, résultat.
Le journal est en ordre d'ajout uniquement — il n'existe ni API de
modification ni API de suppression — et chaque ligne est chaînée par empreinte
sha256 (``prev_hash``) afin que toute altération, suppression ou
réordonnancement soit détectable via ``AuditJournal.verify()``.

Stockage : fichier JSON Lines local, un objet par ligne, dérivé du dossier de
données Career et surchargeable par la variable d'environnement
``AUDIT_JOURNAL_PATH``. Aucun appel réseau, aucun secret en dur.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import re
import threading
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

JOURNAL_SCHEMA_VERSION = 1
GENESIS_HASH = "0" * 64
MAX_PAYLOAD_CHARS = 60_000
MAX_FACTORS = 10
MAX_LIMIT = 200

_DECISION_TYPE_RE = re.compile(r"[a-z][a-z0-9_.-]{0,79}")
_DECISION_ID_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:-]{2,119}")
_ACTOR_RE = re.compile(r"[^\s].{0,119}", re.DOTALL)
_FRENCH_MONTHS = (
    "janvier",
    "février",
    "mars",
    "avril",
    "mai",
    "juin",
    "juillet",
    "août",
    "septembre",
    "octobre",
    "novembre",
    "décembre",
)

_LOCKS_GUARD = threading.Lock()
_LOCKS: dict[str, threading.Lock] = {}


class AuditJournalError(ValueError):
    """Erreur de base du journal d'audit."""


class InvalidEntryError(AuditJournalError, ValueError):
    """Entrée refusée : formats, tailles ou journal illisible."""


class DuplicateDecisionError(AuditJournalError, ValueError):
    """Une décision du même identifiant existe déjà (append-only)."""


class UnknownDecisionError(AuditJournalError, KeyError):
    """Aucune décision ne porte cet identifiant."""


class AuditEntryNotFoundError(AuditJournalError):
    """Aucune décision ne porte cet identifiant."""


@dataclass
class AuditEntry:
    """Une décision enregistrée : contract public SPEC-035."""

    decision_id: str
    decision_type: str
    context: dict[str, Any]
    outcome: dict[str, Any]
    at: str

    def as_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["actor"] = getattr(self, "actor", "systeme")
        payload["seq"] = getattr(self, "seq", 0)
        payload["sequence"] = getattr(self, "seq", 0)
        payload["prev_hash"] = getattr(self, "prev_hash", GENESIS_HASH)
        payload["hash"] = getattr(self, "hash", getattr(self, "entry_hash", ""))
        payload["entry_hash"] = getattr(self, "entry_hash", getattr(self, "hash", ""))
        return payload

    def to_dict(self) -> dict[str, Any]:
        return self.as_dict()

    @property
    def entry(self) -> "AuditEntry":
        return self

    @classmethod
    def from_record(cls, record: dict[str, Any]) -> "AuditEntry":
        entry = cls(
            decision_id=str(record.get("decision_id", "")),
            decision_type=str(record.get("decision_type", "")),
            context=record.get("context") if isinstance(record.get("context"), dict) else {},
            outcome=record.get("outcome") if isinstance(record.get("outcome"), dict) else {},
            at=str(record.get("at", "")),
        )
        entry.actor = str(record.get("actor", "systeme"))
        entry.seq = int(record.get("sequence", record.get("seq", 0)) or 0)
        entry.sequence = entry.seq
        entry.prev_hash = str(record.get("prev_hash", GENESIS_HASH) or GENESIS_HASH)
        entry_hash = str(record.get("hash", record.get("entry_hash", "")) or "")
        entry.hash = entry_hash
        entry.entry_hash = entry_hash
        return entry


@dataclass(frozen=True)
class AuditExplanation:
    """Rapport d'explication lisible d'une décision."""

    entry: AuditEntry
    narrative: str
    contributing_factors: list[tuple[str, float]]


def _lock_for(path: Path) -> threading.Lock:
    key = str(path)
    with _LOCKS_GUARD:
        return _LOCKS.setdefault(key, threading.Lock())


def _chain_payload(record: dict[str, Any]) -> str:
    payload = {key: value for key, value in record.items() if key not in {"hash", "entry_hash"}}
    payload.setdefault("schema_version", JOURNAL_SCHEMA_VERSION)
    return json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _chain_hash(record: dict[str, Any]) -> str:
    material = f"{record.get('prev_hash') or GENESIS_HASH}|{_chain_payload(record)}"
    return hashlib.sha256(material.encode("utf-8")).hexdigest()


def _validate_choice(name: str, value: Any, pattern: re.Pattern[str]) -> str:
    if not isinstance(value, str):
        raise InvalidEntryError(f"{name} doit être une chaîne.")
    text = value.strip()
    if not pattern.fullmatch(text):
        raise InvalidEntryError(f"{name} invalide : {text[:80]!r} (attendu {pattern.pattern}).")
    return text


def _validate_mapping(name: str, value: Any) -> dict[str, Any]:
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise InvalidEntryError(f"{name} doit être un objet JSON.")
    try:
        text = json.dumps(value, ensure_ascii=False)
    except (TypeError, ValueError) as error:
        raise InvalidEntryError(f"{name} doit être JSON-sérialisable.") from error
    if len(text) > MAX_PAYLOAD_CHARS:
        raise InvalidEntryError(f"{name} dépasse {MAX_PAYLOAD_CHARS} caractères.")
    normalized = json.loads(text)
    if not isinstance(normalized, dict):  # pragma: no cover - json.dumps(dict) revient en dict
        raise InvalidEntryError(f"{name} doit être un objet JSON.")
    return normalized


def _normalize_at(value: str | None) -> str:
    if value is None or not str(value).strip():
        return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")
    text = str(value).strip()
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError as error:
        raise InvalidEntryError("Horodatage ISO 8601 attendu (ex. 2026-10-26T09:00:00Z).") from error
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _generate_id(decision_type: str) -> str:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
    return f"{decision_type}-{stamp}-{os.urandom(4).hex()}"


def _flatten_numbers(prefix: str, value: Any, out: list[tuple[str, float]]) -> None:
    if isinstance(value, bool):
        return
    if isinstance(value, (int, float)):
        number = float(value)
        if math.isfinite(number):
            out.append((prefix, number))
        return
    if isinstance(value, dict):
        for key, item in value.items():
            _flatten_numbers(f"{prefix}.{key}", item, out)
        return
    if isinstance(value, (list, tuple)):
        for index, item in enumerate(value):
            _flatten_numbers(f"{prefix}[{index}]", item, out)


def _is_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _c_style_factors(entry: AuditEntry) -> list[tuple[str, float]]:
    """Factor extraction aligned with the SPEC-035 contract fixtures."""

    factors: list[tuple[str, float]] = []
    seen: set[str] = set()

    def add(name: str, weight: float) -> None:
        key = " ".join(str(name).split())[:80]
        folded = key.casefold()
        if not key or folded in seen:
            return
        if not _is_number(weight):
            return
        number = float(weight)
        if not math.isfinite(number):
            return
        if abs(number) > 1:
            number = number / 100.0
        seen.add(folded)
        factors.append((key, round(max(-1.0, min(1.0, number)), 4)))

    has_explicit = False
    for source in (entry.context, entry.outcome):
        for key_name in ("factors", "contributing_factors", "scores"):
            nested = source.get(key_name) if isinstance(source, dict) else None
            if isinstance(nested, dict):
                has_explicit = True
                for name, weight in sorted(nested.items(), key=lambda item: str(item[0])):
                    if _is_number(weight):
                        add(str(name), float(weight))

    has_reasons = False
    for source in (entry.outcome, entry.context):
        if not isinstance(source, dict):
            continue
        for key_name in ("reasons", "justifications", "rationale_items"):
            value = source.get(key_name)
            if isinstance(value, list):
                has_reasons = True

    if not (has_explicit or has_reasons):
        return []

    # Score global (premier trouvé, outcome puis contexte).
    for key in ("match_score", "score", "coverage_percent", "exhaustiveness_score"):
        for source in (entry.outcome, entry.context):
            if isinstance(source, dict) and key in source and _is_number(source.get(key)):
                add(key.replace("_", " "), float(source.get(key)))
                break

    # Raisons textuelles (poids unitaire).
    for key in ("reasons", "justifications", "rationale_items"):
        for source in (entry.outcome, entry.context):
            if not isinstance(source, dict):
                continue
            value = source.get(key)
            if isinstance(value, list):
                for reason in value:
                    if isinstance(reason, str) and reason.strip():
                        add(" ".join(reason.split()), 1.0)
            if value is not None:
                break

    factors.sort(key=lambda item: (-abs(item[1]), item[0]))
    return factors[:MAX_FACTORS]


def _contributing_factors(entry: AuditEntry) -> list[tuple[str, float]]:
    c_factors = _c_style_factors(entry)
    if c_factors:
        return c_factors

    numbers: list[tuple[str, float]] = []
    _flatten_numbers("context", entry.context, numbers)
    _flatten_numbers("outcome", entry.outcome, numbers)
    if not numbers:
        return []
    total = sum(abs(value) for _, value in numbers)
    if total > 0:
        weighted = [(key, value / total) for key, value in numbers]
    else:
        weighted = [(key, 1.0 / len(numbers)) for key, _ in numbers]
    weighted = [(key, round(weight, 4)) for key, weight in weighted]
    weighted.sort(key=lambda item: (-abs(item[1]), item[0]))
    return weighted[:MAX_FACTORS]


def _scalar_text(value: Any, limit: int = 80) -> str:
    if isinstance(value, bool):
        return "oui" if value else "non"
    if value is None:
        return "non renseigné"
    if isinstance(value, float):
        text = f"{value:.4f}".rstrip("0").rstrip(".")
        return text.replace(".", ",")
    text = str(value).replace("\n", " ").strip()
    return text if len(text) <= limit else f"{text[: limit - 1]}…"


def _summarise(mapping: dict[str, Any], limit: int = 4) -> str:
    if not mapping:
        return ""
    parts = []
    for key, value in list(mapping.items())[:limit]:
        if isinstance(value, (dict, list, tuple)):
            preview = json.dumps(value, ensure_ascii=False)
            rendered = preview if len(preview) <= 80 else f"{preview[:79]}…"
        else:
            rendered = _scalar_text(value)
        parts.append(f"{key} = {rendered}")
    if len(mapping) > limit:
        parts.append(f"… {len(mapping)} éléments au total")
    return ", ".join(parts)


def _format_at(at: str) -> str:
    try:
        moment = datetime.fromisoformat(at.replace("Z", "+00:00"))
    except ValueError:
        return at
    month = _FRENCH_MONTHS[moment.month - 1] if 1 <= moment.month <= 12 else ""
    return f"{moment.day} {month} {moment.year} à {moment:%H:%M} (UTC)"


def _narrative(entry: AuditEntry, factors: list[tuple[str, float]]) -> str:
    actor = getattr(entry, "actor", "systeme")
    seq = getattr(entry, "seq", 0)
    context_summary = _summarise(entry.context)
    outcome_summary = _summarise(entry.outcome)
    c_summary = context_summary or "détails du contexte enregistrés dans le journal"
    sentences = [
        f"Décision « {entry.decision_type} » enregistrée le {entry.at} ({entry.decision_id}) : {c_summary}.",
        f"Le {_format_at(entry.at)}, l'agent « {actor} » a enregistré la décision {entry.decision_id} "
        f"(type {entry.decision_type}, entrée n°{seq}).",
    ]
    if context_summary:
        sentences.append(f"Éléments de contexte : {context_summary}.")
    else:
        sentences.append("Aucun élément de contexte n'a été fourni.")
    if outcome_summary:
        sentences.append(f"Résultat obtenu : {outcome_summary}.")
    else:
        sentences.append("Aucun résultat explicite n'a été produit.")
    if factors:
        ranked_parts = []
        for key, weight in factors[:5]:
            label = key if len(key) <= 48 else f"{key[:47]}…"
            percent = f"{weight * 100:.1f}".replace(".", ",")
            ranked_parts.append(f"{label} ({percent} %)")
        described = ", ".join(f"{name} (poids {weight:.2f})" for name, weight in factors)
        sentences.append(f"Facteurs déterminants : {', '.join(ranked_parts)}.")
        sentences.append(f"Facteurs contributifs principaux : {described}.")
    else:
        sentences.append("Décision qualitative : aucun facteur chiffré n'a été pondéré.")
        sentences.append("Aucun facteur chiffré n'a été enregistré avec cette décision.")
    return " ".join(sentences)


class AuditJournal:
    """Journal append-only, chaîné par empreinte, lecture + écriture seule."""

    def __init__(self, path: str | Path, *, journal_name: str = "audit_journal.jsonl", base_dir: str | Path | None = None):
        if base_dir is not None:
            path = Path(base_dir)
        path = Path(path).expanduser()
        if path.suffix.lower() not in {".jsonl", ".json", ".log"} or path.is_dir():
            # Traité comme un dossier de données.
            path.mkdir(parents=True, exist_ok=True)
            path = path / journal_name
        self.path = path

    @classmethod
    def for_base_dir(cls, base_dir: str | Path) -> AuditJournal:
        override = os.environ.get("AUDIT_JOURNAL_PATH", "").strip()
        if override:
            return cls(override)
        return cls(Path(base_dir) / "career_data" / "audit")

    # --- lecture ------------------------------------------------------------

    def _raw_lines(self) -> list[str]:
        if not self.path.exists():
            return []
        return self.path.read_text(encoding="utf-8").splitlines()

    def _records(self) -> list[dict[str, Any]]:
        records: list[dict[str, Any]] = []
        for number, raw in enumerate(self._raw_lines(), start=1):
            line = raw.strip()
            if not line:
                continue
            try:
                record = json.loads(line)
            except ValueError as error:
                raise InvalidEntryError(f"Journal corrompu : ligne {number} illisible.") from error
            if not isinstance(record, dict):
                raise InvalidEntryError(f"Journal corrompu : ligne {number} non objet.")
            records.append(record)
        return records

    def count(self) -> int:
        return len(self._records())

    def entries(
        self,
        *,
        decision_type: str | None = None,
        query: str | None = None,
        actor: str | None = None,
        since: str | None = None,
        until: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[AuditEntry]:
        """Recherche/filtre sur le journal, du plus ancien au plus récent."""
        if not isinstance(limit, int) or not 1 <= limit <= MAX_LIMIT:
            raise InvalidEntryError(f"limit doit être compris entre 1 et {MAX_LIMIT}.")
        if not isinstance(offset, int) or offset < 0:
            raise InvalidEntryError("offset doit être positif.")
        since_at = _normalize_at(since) if since else None
        until_at = _normalize_at(until) if until else None
        needle = (query or "").strip().casefold()

        selected: list[AuditEntry] = []
        for record in self._records():
            entry = AuditEntry.from_record(record)
            if decision_type and entry.decision_type != decision_type:
                continue
            if actor and entry.actor != actor:
                continue
            if since_at and entry.at < since_at:
                continue
            if until_at and entry.at > until_at:
                continue
            if needle:
                haystack = " ".join(
                    [entry.decision_id, entry.decision_type, entry.actor, json.dumps(entry.context, ensure_ascii=False), json.dumps(entry.outcome, ensure_ascii=False)]
                ).casefold()
                if needle not in haystack:
                    continue
            selected.append(entry)
        return selected[offset : offset + limit]

    def list(
        self,
        *,
        decision_type: str = "",
        query: str = "",
        limit: int = 50,
        offset: int = 0,
    ) -> list[AuditEntry]:
        type_filter = str(decision_type or "").strip()
        needle = str(query or "").strip().casefold()
        bounded_limit = max(1, min(int(limit or 50), MAX_LIMIT))
        bounded_offset = max(0, int(offset or 0))
        selected: list[AuditEntry] = []
        for record in reversed(self._records()):
            entry = AuditEntry.from_record(record)
            if type_filter and entry.decision_type != type_filter:
                continue
            if needle:
                haystack = " ".join(
                    [entry.decision_id, entry.decision_type, getattr(entry, "actor", ""), json.dumps(entry.context, ensure_ascii=False), json.dumps(entry.outcome, ensure_ascii=False)]
                ).casefold()
                if needle not in haystack:
                    continue
            selected.append(entry)
        return selected[bounded_offset : bounded_offset + bounded_limit]

    def search(
        self,
        query: str = "",
        decision_type: str = "",
        *,
        limit: int = 50,
        offset: int = 0,
    ) -> dict[str, Any]:
        type_filter = str(decision_type or "").strip()
        needle = str(query or "").strip().casefold()
        bounded_limit = max(0, min(int(limit or 50), MAX_LIMIT))
        bounded_offset = max(0, int(offset or 0))
        matches: list[AuditEntry] = []
        for record in reversed(self._records()):
            entry = AuditEntry.from_record(record)
            if type_filter and entry.decision_type != type_filter:
                continue
            if needle:
                haystack = " ".join(
                    [entry.decision_id, entry.decision_type, getattr(entry, "actor", ""), json.dumps(entry.context, ensure_ascii=False), json.dumps(entry.outcome, ensure_ascii=False)]
                ).casefold()
                if needle not in haystack:
                    continue
            matches.append(entry)
        page = matches[bounded_offset : bounded_offset + bounded_limit]
        return {
            "total": len(matches),
            "offset": bounded_offset,
            "limit": bounded_limit,
            "entries": [{"entry": entry.as_dict()} for entry in page],
        }

    def stats(self) -> dict[str, Any]:
        records = self._records()
        by_type: dict[str, int] = {}
        for record in records:
            entry = AuditEntry.from_record(record)
            by_type[entry.decision_type] = by_type.get(entry.decision_type, 0) + 1
        integrity = self.verify_integrity()
        return {
            "schema_version": JOURNAL_SCHEMA_VERSION,
            "entries": len(records),
            "by_decision_type": dict(sorted(by_type.items())),
            "integrity": {"valid": integrity["valid"]},
        }

    def get(self, decision_id: str) -> AuditEntry:
        wanted = str(decision_id or "").strip()
        for record in self._records():
            if str(record.get("decision_id")) == wanted:
                return AuditEntry.from_record(record)
        raise AuditEntryNotFoundError(f"Décision introuvable : {decision_id}")

    def explain(self, decision_id: str) -> AuditExplanation:
        entry = self.get(decision_id)
        factors = _contributing_factors(entry)
        return AuditExplanation(entry=entry, narrative=_narrative(entry, factors), contributing_factors=factors)

    def verify(self) -> dict[str, Any]:
        """Contrôle l'intégrité de la chaîne : contenu, ordre et liens prev_hash."""
        report: dict[str, Any] = {
            "schema_version": JOURNAL_SCHEMA_VERSION,
            "path": str(self.path),
            "entries": 0,
            "valid": True,
            "broken_at": None,
            "chain_digest": GENESIS_HASH,
            "problems": [],
            "first_broken_sequence": None,
            "first_invalid_id": "",
            "reason": None,
        }
        if not self.path.exists():
            report["reason"] = None
            return report

        previous_hash = GENESIS_HASH
        seen: set[str] = set()

        def broken(reason: str, line: int, record: dict[str, Any] | None = None) -> dict[str, Any]:
            report["valid"] = False
            report["broken_at"] = {
                "line": line,
                "seq": (record or {}).get("seq"),
                "decision_id": (record or {}).get("decision_id"),
                "reason": reason,
            }
            report["problems"] = [f"ligne {line} : {reason}"]
            report["first_broken_sequence"] = (record or {}).get("sequence", (record or {}).get("seq", line))
            report["first_invalid_id"] = (record or {}).get("decision_id", "")
            report["reason"] = reason
            return report

        for number, raw in enumerate(self._raw_lines(), start=1):
            line = raw.strip()
            if not line:
                continue
            try:
                record = json.loads(line)
            except ValueError:
                return broken("ligne malformée (JSON illisible)", number)
            if not isinstance(record, dict):
                return broken("ligne non objet", number)
            if record.get("schema_version") != JOURNAL_SCHEMA_VERSION:
                return broken("version de schéma inattendue", number, record)
            seq_value = record.get("sequence", record.get("seq"))
            if seq_value != report["entries"] + 1:
                return broken("numérotation incohérente (entrée manquante)", number, record)
            decision_id = record.get("decision_id")
            if not isinstance(decision_id, str) or not decision_id:
                return broken("identifiant de décision manquant", number, record)
            if decision_id in seen:
                return broken("identifiant de décision dupliqué", number, record)
            if record.get("prev_hash") != previous_hash:
                return broken("prev_hash incohérent (entrée réordonnée ou supprimée)", number, record)
            computed = _chain_hash(record)
            stored_hash = record.get("hash", record.get("entry_hash"))
            if stored_hash != computed:
                return broken("hash d'entrée invalide (contenu modifié)", number, record)
            seen.add(decision_id)
            previous_hash = computed
            report["entries"] += 1

        report["chain_digest"] = previous_hash
        report["problems"] = []
        report["first_broken_sequence"] = None
        report["first_invalid_id"] = ""
        report["reason"] = None
        return report

    def verify_integrity(self) -> dict[str, Any]:
        return self.verify()

    # --- écriture -----------------------------------------------------------

    def record(
        self,
        decision_type: str,
        context: dict[str, Any] | None = None,
        outcome: dict[str, Any] | None = None,
        *,
        actor: str = "systeme",
        decision_id: str | None = None,
        at: str | None = None,
    ) -> AuditEntry:
        """Ajoute une décision. Aucune mise à jour ni suppression possible."""
        if isinstance(decision_type, AuditEntry):
            _entry = decision_type
            decision_type = _entry.decision_type
            context = _entry.context
            outcome = _entry.outcome
            if not actor:
                actor = getattr(_entry, "actor", "") or ""
            if decision_id is None:
                decision_id = _entry.decision_id
            if at is None:
                at = _entry.at
        clean_type = _validate_choice("decision_type", decision_type, _DECISION_TYPE_RE)
        clean_actor = str(actor or "systeme").strip() or "systeme"
        if not _ACTOR_RE.fullmatch(clean_actor):
            raise InvalidEntryError("actor invalide (1 à 120 caractères).")
        clean_context = _validate_mapping("context", context)
        clean_outcome = _validate_mapping("outcome", outcome)
        clean_at = _normalize_at(at)
        if decision_id is None:
            clean_id = _generate_id(clean_type)
        else:
            clean_id = _validate_choice("decision_id", decision_id, _DECISION_ID_RE)

        with _lock_for(self.path):
            records = self._records()
            if any(str(record.get("decision_id")) == clean_id for record in records):
                raise DuplicateDecisionError(f"Décision déjà enregistrée : {clean_id} (append-only).")
            previous_hash = str(records[-1].get("hash") or GENESIS_HASH) if records else GENESIS_HASH
            record: dict[str, Any] = {
                "schema_version": JOURNAL_SCHEMA_VERSION,
                "sequence": len(records) + 1,
                "seq": len(records) + 1,
                "decision_id": clean_id,
                "decision_type": clean_type,
                "actor": clean_actor,
                "context": clean_context,
                "outcome": clean_outcome,
                "at": clean_at,
                "prev_hash": previous_hash,
            }
            record["hash"] = _chain_hash(record)
            record["entry_hash"] = record["hash"]
            self._append(record)
        return AuditEntry.from_record(record)

    def _append(self, record: dict[str, Any]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        created = not self.path.exists()
        line = json.dumps(record, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(line + "\n")
            handle.flush()
            os.fsync(handle.fileno())
        if created:
            try:
                os.chmod(self.path, 0o600)
            except OSError:  # pragma: no cover - permission best effort
                pass
