"""Persistance, versionnage et signatures de la Constitution exécutable.

SPEC-014.  Le stockage est séparé de la base Career métier : une Constitution
est un document de gouvernance, pas une donnée de candidature.  Elle vit dans
``career_data/constitution.sqlite3`` avec une clé locale dédiée
(``career_data/constitution.key``, permissions 0600) qui sert à signer chaque
règle.

Garanties :

* une règle modifiée ne remplace jamais l'historique : chaque version est
  conservée et la version approuvée reste effective tant que la nouvelle
  version n'est pas approuvée ;
* l'approbation exige un approbateur distinct de l'auteur de la version ;
* chaque action de gouvernance est journalisée (audit trail) ;
* la signature d'une règle détecte toute modification hors du moteur.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import secrets
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator, Mapping, Sequence

from workspace_core import UserFacingError

from .constitution import (
    DEFAULT_RULES,
    DEFAULT_RULESETS,
    MAX_RULE_ID_LENGTH,
    Rule,
    RuleSet,
    normalize_rule_payload,
    validate_rule_payload,
)
from .models import clean_text, utc_now


CONSTITUTION_DB_NAME = "constitution.sqlite3"
CONSTITUTION_KEY_NAME = "constitution.key"
CONSTITUTION_SCHEMA_VERSION = 1

#: Statuts dans lesquels une version de règle reste applicable.
EFFECTIVE_STATUSES: tuple[str, ...] = ("active", "deprecated")


def canonical_json(payload: Mapping[str, Any]) -> str:
    """Sérialisation stable (triée) utilisée pour signer et comparer."""
    return json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


class ConstitutionStore:
    """Stockage local, versionné et signé de la Constitution."""

    def __init__(
        self,
        base_dir: Path | str,
        *,
        actor: str = "local",
        allow_self_approval: bool = False,
    ) -> None:
        self.base_dir = Path(base_dir).resolve()
        self.data_dir = self.base_dir / "career_data"
        self.db_path = self.data_dir / CONSTITUTION_DB_NAME
        self.key_path = self.data_dir / CONSTITUTION_KEY_NAME
        self.default_actor = clean_text(actor, limit=120) or "local"
        self.allow_self_approval = allow_self_approval
        self._ensure_storage()
        self._initialize()
        self._key = self._load_or_create_key()
        # La Constitution de référence est installée une fois : les règles
        # propositions restent en brouillon tant qu'elles ne sont pas
        # approuvées.
        self.seed_defaults()

    # -- stockage --------------------------------------------------------------

    def _ensure_storage(self) -> None:
        self.data_dir.mkdir(parents=True, exist_ok=True)
        for path in (self.data_dir, self.db_path):
            try:
                os.chmod(path, 0o700 if path.is_dir() else 0o600)
            except OSError:
                pass

    def _load_or_create_key(self) -> bytes:
        """Charge (ou crée) la clé locale de signature."""
        if self.key_path.exists():
            key = self.key_path.read_bytes()
            if len(key) >= 32:
                return key
        key = secrets.token_bytes(32)
        self.key_path.write_bytes(key)
        try:
            os.chmod(self.key_path, 0o600)
        except OSError:
            pass
        return key

    def _initialize(self) -> None:
        with self._connection() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS constitution_rules (
                    rule_id TEXT PRIMARY KEY,
                    version INTEGER NOT NULL,
                    status TEXT NOT NULL,
                    domain TEXT NOT NULL,
                    name TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    signature TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    created_by TEXT NOT NULL,
                    approved_by TEXT,
                    approved_at TEXT,
                    reviewed_at TEXT,
                    has_test INTEGER NOT NULL DEFAULT 0
                );
                CREATE TABLE IF NOT EXISTS constitution_rule_versions (
                    rule_id TEXT NOT NULL,
                    version INTEGER NOT NULL,
                    status TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    signature TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    created_by TEXT NOT NULL,
                    change_note TEXT NOT NULL DEFAULT '',
                    PRIMARY KEY (rule_id, version)
                );
                CREATE TABLE IF NOT EXISTS constitution_rulesets (
                    ruleset_id TEXT PRIMARY KEY,
                    version INTEGER NOT NULL,
                    name TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    signature TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    effective_from TEXT NOT NULL,
                    effective_until TEXT,
                    supersedes TEXT,
                    created_by TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS constitution_ruleset_versions (
                    ruleset_id TEXT NOT NULL,
                    version INTEGER NOT NULL,
                    payload_json TEXT NOT NULL,
                    signature TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    created_by TEXT NOT NULL,
                    change_note TEXT NOT NULL DEFAULT '',
                    PRIMARY KEY (ruleset_id, version)
                );
                CREATE TABLE IF NOT EXISTS constitution_audit_log (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    occurred_at TEXT NOT NULL,
                    actor TEXT NOT NULL,
                    action TEXT NOT NULL,
                    subject_type TEXT NOT NULL,
                    subject_id TEXT NOT NULL,
                    details_json TEXT NOT NULL,
                    signature TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS constitution_conformance (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    entity_id TEXT NOT NULL,
                    entity_type TEXT NOT NULL,
                    ruleset_id TEXT NOT NULL,
                    ruleset_version INTEGER NOT NULL,
                    checked_at TEXT NOT NULL,
                    compliance_score REAL NOT NULL,
                    passed INTEGER NOT NULL,
                    failed INTEGER NOT NULL,
                    warnings INTEGER NOT NULL,
                    errors INTEGER NOT NULL,
                    critical INTEGER NOT NULL,
                    report_json TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS constitution_audit_subject
                    ON constitution_audit_log (subject_type, subject_id);
                CREATE INDEX IF NOT EXISTS constitution_conformance_entity
                    ON constitution_conformance (entity_id, checked_at);
                """
            )
            connection.execute(f"PRAGMA user_version = {CONSTITUTION_SCHEMA_VERSION}")

    @contextmanager
    def _connection(self) -> Iterator[sqlite3.Connection]:
        connection = sqlite3.connect(self.db_path, timeout=5.0)
        connection.row_factory = sqlite3.Row
        try:
            connection.execute("PRAGMA busy_timeout = 5000")
            connection.execute("PRAGMA secure_delete = ON")
            yield connection
            connection.commit()
        except sqlite3.Error as error:
            connection.rollback()
            raise UserFacingError("Le stockage de la Constitution locale a rencontré un problème. Réessaie.") from error
        finally:
            connection.close()

    # -- signatures ------------------------------------------------------------

    def sign(self, payload: Mapping[str, Any]) -> str:
        """Signe un contenu avec la clé locale (HMAC-SHA256)."""
        return hmac.new(self._key, canonical_json(self._signable(payload)).encode("utf-8"), hashlib.sha256).hexdigest()

    @staticmethod
    def _signable(payload: Mapping[str, Any]) -> dict[str, Any]:
        """Contenu réellement signé : les métadonnées de stockage sont exclues."""
        return {
            key: value
            for key, value in payload.items()
            if key not in {"signature", "has_test", "change_note"}
        }

    def verify(self, payload: Mapping[str, Any], signature: str) -> bool:
        """Vérifie la signature d'un contenu."""
        if not signature:
            return False
        return hmac.compare_digest(self.sign(payload), str(signature))

    def verify_rule(self, payload: Mapping[str, Any]) -> bool:
        """Vérifie la signature d'une règle stockée."""
        return self.verify(payload, str(payload.get("signature", "")))

    # -- règles ----------------------------------------------------------------

    def _rule_row_to_dict(self, row: sqlite3.Row) -> dict[str, Any]:
        payload = json.loads(row["payload_json"])
        payload["signature"] = row["signature"]
        payload["has_test"] = bool(row["has_test"])
        return payload

    def create_rule(
        self,
        payload: Mapping[str, Any],
        *,
        actor: str | None = None,
        change_note: str = "",
    ) -> dict[str, Any]:
        """Crée une règle en version 1, statut ``draft``."""
        problems = validate_rule_payload(payload)
        if problems:
            raise UserFacingError("Règle invalide : " + " ".join(problems))
        author = clean_text(actor or payload.get("created_by") or self.default_actor, limit=120) or "local"
        rule = normalize_rule_payload(payload, version=1, status="draft", created_by=author)
        signature = self.sign(rule)
        with self._connection() as connection:
            existing = connection.execute(
                "SELECT rule_id FROM constitution_rules WHERE rule_id = ?", (rule["rule_id"],)
            ).fetchone()
            if existing is not None:
                raise UserFacingError(f"La règle « {rule['rule_id']} » existe déjà : modifiez-la pour créer une version.")
            connection.execute(
                """
                INSERT INTO constitution_rules (
                    rule_id, version, status, domain, name, payload_json, signature,
                    created_at, updated_at, created_by, approved_by, approved_at, reviewed_at, has_test
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, NULL, NULL, NULL, 0)
                """,
                (
                    rule["rule_id"],
                    rule["version"],
                    rule["status"],
                    rule["domain"],
                    rule["name"],
                    canonical_json(rule),
                    signature,
                    rule["created_at"],
                    rule["updated_at"],
                    rule["created_by"],
                ),
            )
            connection.execute(
                """
                INSERT INTO constitution_rule_versions (
                    rule_id, version, status, payload_json, signature, created_at, created_by, change_note
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    rule["rule_id"],
                    rule["version"],
                    rule["status"],
                    canonical_json(rule),
                    signature,
                    rule["created_at"],
                    rule["created_by"],
                    clean_text(change_note, limit=500),
                ),
            )
            self._audit(
                connection,
                actor=author,
                action="rule.created",
                subject_type="rule",
                subject_id=rule["rule_id"],
                details={"version": rule["version"], "domain": rule["domain"], "expression": rule["expression"]},
            )
        return {**rule, "signature": signature, "has_test": False}

    def get_rule(self, rule_id: str) -> dict[str, Any] | None:
        """Retourne la dernière version connue d'une règle."""
        with self._connection() as connection:
            row = connection.execute(
                "SELECT * FROM constitution_rules WHERE rule_id = ?", (rule_id,)
            ).fetchone()
        if row is None:
            return None
        return self._rule_row_to_dict(row)

    def get_rule_version(self, rule_id: str, version: int) -> dict[str, Any] | None:
        """Retourne une version précise de l'historique d'une règle."""
        with self._connection() as connection:
            row = connection.execute(
                "SELECT * FROM constitution_rule_versions WHERE rule_id = ? AND version = ?",
                (rule_id, int(version)),
            ).fetchone()
        if row is None:
            return None
        payload = json.loads(row["payload_json"])
        payload["signature"] = row["signature"]
        return payload

    def list_rule_versions(self, rule_id: str) -> list[dict[str, Any]]:
        """Historique complet des versions d'une règle (la plus récente d'abord)."""
        with self._connection() as connection:
            rows = connection.execute(
                "SELECT * FROM constitution_rule_versions WHERE rule_id = ? ORDER BY version DESC",
                (rule_id,),
            ).fetchall()
        versions: list[dict[str, Any]] = []
        for row in rows:
            payload = json.loads(row["payload_json"])
            payload["signature"] = row["signature"]
            payload["change_note"] = row["change_note"]
            versions.append(payload)
        return versions

    def list_rules(
        self,
        *,
        domain: str | None = None,
        status: str | None = None,
        query: str | None = None,
        scope: str | None = None,
    ) -> list[dict[str, Any]]:
        """Liste les règles avec filtres (domaine, statut, texte libre, périmètre)."""
        clauses: list[str] = []
        values: list[Any] = []
        if domain:
            clauses.append("domain = ?")
            values.append(domain)
        if status:
            clauses.append("status = ?")
            values.append(status)
        if query:
            clauses.append("(rule_id LIKE ? OR name LIKE ? OR description LIKE ?)")
            pattern = f"%{query}%"
            values.extend([pattern, pattern, pattern])
        where = f" WHERE {' AND '.join(clauses)}" if clauses else ""
        with self._connection() as connection:
            rows = connection.execute(
                f"SELECT * FROM constitution_rules{where} ORDER BY rule_id", values
            ).fetchall()
        rules = [self._rule_row_to_dict(row) for row in rows]
        if scope:
            rules = [rule for rule in rules if scope in rule.get("scope", [])]
        return rules

    def effective_rule(self, rule_id: str) -> dict[str, Any] | None:
        """Retourne la version effective (active ou dépréciée) d'une règle."""
        with self._connection() as connection:
            rows = connection.execute(
                """
                SELECT * FROM constitution_rule_versions
                WHERE rule_id = ? AND status IN ('active', 'deprecated')
                ORDER BY version DESC LIMIT 1
                """,
                (rule_id,),
            ).fetchall()
        if not rows:
            return None
        payload = json.loads(rows[0]["payload_json"])
        payload["signature"] = rows[0]["signature"]
        return payload

    def update_rule(
        self,
        rule_id: str,
        changes: Mapping[str, Any],
        *,
        actor: str | None = None,
        change_note: str = "",
    ) -> dict[str, Any]:
        """Crée une nouvelle version ``draft`` d'une règle (l'ancienne reste effective)."""
        current = self.get_rule(rule_id)
        if current is None:
            raise UserFacingError(f"La règle « {rule_id} » est introuvable.")
        merged = {**current, **dict(changes)}
        merged.pop("signature", None)
        merged.pop("has_test", None)
        problems = validate_rule_payload(merged)
        if problems:
            raise UserFacingError("Règle invalide : " + " ".join(problems))
        author = clean_text(actor or self.default_actor, limit=120) or "local"
        version = int(current.get("version", 1)) + 1
        rule = normalize_rule_payload(merged, version=version, status="draft", created_by=author)
        signature = self.sign(rule)
        with self._connection() as connection:
            connection.execute(
                """
                UPDATE constitution_rules
                SET version = ?, status = 'draft', domain = ?, name = ?, payload_json = ?, signature = ?,
                    updated_at = ?, created_by = ?, approved_by = NULL, approved_at = NULL, reviewed_at = NULL
                WHERE rule_id = ?
                """,
                (
                    version,
                    rule["domain"],
                    rule["name"],
                    canonical_json(rule),
                    signature,
                    rule["updated_at"],
                    rule["created_by"],
                    rule_id,
                ),
            )
            connection.execute(
                """
                INSERT INTO constitution_rule_versions (
                    rule_id, version, status, payload_json, signature, created_at, created_by, change_note
                ) VALUES (?, ?, 'draft', ?, ?, ?, ?, ?)
                """,
                (
                    rule_id,
                    version,
                    canonical_json(rule),
                    signature,
                    rule["created_at"],
                    rule["created_by"],
                    clean_text(change_note, limit=500),
                ),
            )
            self._audit(
                connection,
                actor=author,
                action="rule.updated",
                subject_type="rule",
                subject_id=rule_id,
                details={"version": version, "change_note": clean_text(change_note, limit=500)},
            )
        return {**rule, "signature": signature, "has_test": False}

    def approve_rule(
        self,
        rule_id: str,
        *,
        approver: str,
        note: str = "",
    ) -> dict[str, Any]:
        """Approuve la version courante : la règle devient effective."""
        current = self.get_rule(rule_id)
        if current is None:
            raise UserFacingError(f"La règle « {rule_id} » est introuvable.")
        if current.get("status") != "draft":
            raise UserFacingError(f"La règle « {rule_id} » n'est pas en brouillon : rien à approuver.")
        approver_name = clean_text(approver, limit=120)
        if not approver_name:
            raise UserFacingError("L'approbateur est obligatoire.")
        if not self.allow_self_approval and approver_name == current.get("created_by"):
            raise UserFacingError(
                "L'approbateur doit être différent de l'auteur de la version : la relecture par un tiers est obligatoire."
            )
        now = utc_now()
        approved = {
            **current,
            "status": "active",
            "approved_by": approver_name,
            "approved_at": now,
            "updated_at": now,
        }
        approved.pop("signature", None)
        approved.pop("has_test", None)
        signature = self.sign(approved)
        with self._connection() as connection:
            previous = connection.execute(
                """
                SELECT version, payload_json, signature FROM constitution_rule_versions
                WHERE rule_id = ? AND status = 'active' ORDER BY version DESC LIMIT 1
                """,
                (rule_id,),
            ).fetchone()
            if previous is not None:
                deprecated_payload = json.loads(previous["payload_json"])
                deprecated_payload["status"] = "deprecated"
                deprecated_payload["updated_at"] = now
                connection.execute(
                    "UPDATE constitution_rule_versions SET status = 'deprecated', payload_json = ?, signature = ? WHERE rule_id = ? AND version = ?",
                    (
                        canonical_json(deprecated_payload),
                        self.sign(deprecated_payload),
                        rule_id,
                        previous["version"],
                    ),
                )
            connection.execute(
                """
                UPDATE constitution_rules
                SET status = 'active', payload_json = ?, signature = ?, updated_at = ?, approved_by = ?, approved_at = ?, reviewed_at = ?
                WHERE rule_id = ?
                """,
                (
                    canonical_json(approved),
                    signature,
                    now,
                    approver_name,
                    now,
                    now,
                    rule_id,
                ),
            )
            connection.execute(
                """
                UPDATE constitution_rule_versions
                SET status = 'active', payload_json = ?, signature = ?
                WHERE rule_id = ? AND version = ?
                """,
                (canonical_json(approved), signature, rule_id, approved["version"]),
            )
            self._audit(
                connection,
                actor=approver_name,
                action="rule.approved",
                subject_type="rule",
                subject_id=rule_id,
                details={"version": approved["version"], "note": clean_text(note, limit=500)},
            )
        return {**approved, "signature": signature, "has_test": bool(current.get("has_test"))}

    def deprecate_rule(self, rule_id: str, *, actor: str | None = None, reason: str = "") -> dict[str, Any]:
        """Déprécie la version courante (elle reste applicable pendant la transition)."""
        return self._set_rule_status(rule_id, "deprecated", actor=actor, reason=reason, action="rule.deprecated")

    def archive_rule(self, rule_id: str, *, actor: str | None = None, reason: str = "") -> dict[str, Any]:
        """Archive la version courante : la règle n'est plus applicable."""
        return self._set_rule_status(rule_id, "archived", actor=actor, reason=reason, action="rule.archived")

    def _set_rule_status(
        self,
        rule_id: str,
        status: str,
        *,
        actor: str | None = None,
        reason: str = "",
        action: str,
    ) -> dict[str, Any]:
        current = self.get_rule(rule_id)
        if current is None:
            raise UserFacingError(f"La règle « {rule_id} » est introuvable.")
        if current.get("status") == "archived" and status == "archived":
            raise UserFacingError(f"La règle « {rule_id} » est déjà archivée.")
        author = clean_text(actor or self.default_actor, limit=120) or "local"
        now = utc_now()
        updated = {**current, "status": status, "updated_at": now}
        updated.pop("signature", None)
        updated.pop("has_test", None)
        signature = self.sign(updated)
        with self._connection() as connection:
            connection.execute(
                "UPDATE constitution_rules SET status = ?, payload_json = ?, signature = ?, updated_at = ? WHERE rule_id = ?",
                (status, canonical_json(updated), signature, now, rule_id),
            )
            connection.execute(
                "UPDATE constitution_rule_versions SET status = ?, payload_json = ?, signature = ? WHERE rule_id = ? AND version = ?",
                (status, canonical_json(updated), signature, rule_id, updated["version"]),
            )
            self._audit(
                connection,
                actor=author,
                action=action,
                subject_type="rule",
                subject_id=rule_id,
                details={"version": updated["version"], "reason": clean_text(reason, limit=500)},
            )
        return {**updated, "signature": signature, "has_test": bool(current.get("has_test"))}

    def rollback_rule(
        self,
        rule_id: str,
        *,
        target_version: int,
        actor: str | None = None,
        reason: str = "",
    ) -> dict[str, Any]:
        """Restaure instantanément une version antérieure (nouvelle version active)."""
        target = self.get_rule_version(rule_id, int(target_version))
        if target is None:
            raise UserFacingError(f"La version {target_version} de la règle « {rule_id} » est introuvable.")
        current = self.get_rule(rule_id)
        if current is None:
            raise UserFacingError(f"La règle « {rule_id} » est introuvable.")
        author = clean_text(actor or self.default_actor, limit=120) or "local"
        now = utc_now()
        version = int(current.get("version", 1)) + 1
        restored = {
            **target,
            "version": version,
            "status": "active",
            "updated_at": now,
            "created_at": now,
            "created_by": author,
            "approved_by": author,
            "approved_at": now,
        }
        restored.pop("signature", None)
        restored.pop("has_test", None)
        signature = self.sign(restored)
        with self._connection() as connection:
            previous = connection.execute(
                """
                SELECT version, payload_json FROM constitution_rule_versions
                WHERE rule_id = ? AND status IN ('active', 'deprecated') ORDER BY version DESC LIMIT 1
                """,
                (rule_id,),
            ).fetchone()
            if previous is not None:
                deprecated_payload = json.loads(previous["payload_json"])
                deprecated_payload["status"] = "deprecated"
                deprecated_payload["updated_at"] = now
                connection.execute(
                    "UPDATE constitution_rule_versions SET status = 'deprecated', payload_json = ?, signature = ? WHERE rule_id = ? AND version = ?",
                    (
                        canonical_json(deprecated_payload),
                        self.sign(deprecated_payload),
                        rule_id,
                        previous["version"],
                    ),
                )
            connection.execute(
                """
                INSERT INTO constitution_rule_versions (
                    rule_id, version, status, payload_json, signature, created_at, created_by, change_note
                ) VALUES (?, ?, 'active', ?, ?, ?, ?, ?)
                """,
                (
                    rule_id,
                    version,
                    canonical_json(restored),
                    signature,
                    now,
                    author,
                    clean_text(reason, limit=500) or f"Rollback vers la version {target_version}",
                ),
            )
            connection.execute(
                """
                UPDATE constitution_rules
                SET version = ?, status = 'active', payload_json = ?, signature = ?, updated_at = ?,
                    created_by = ?, approved_by = ?, approved_at = ?, reviewed_at = ?
                WHERE rule_id = ?
                """,
                (
                    version,
                    canonical_json(restored),
                    signature,
                    now,
                    author,
                    author,
                    now,
                    now,
                    rule_id,
                ),
            )
            self._audit(
                connection,
                actor=author,
                action="rule.rolled_back",
                subject_type="rule",
                subject_id=rule_id,
                details={"from_version": current.get("version"), "to_version": version, "restored": target_version},
            )
        return {**restored, "signature": signature, "has_test": False}

    def mark_rule_tested(self, rule_id: str, *, tested: bool = True) -> None:
        """Marque une règle comme couverte par un test généré."""
        with self._connection() as connection:
            connection.execute(
                "UPDATE constitution_rules SET has_test = ? WHERE rule_id = ?",
                (1 if tested else 0, rule_id),
            )

    # -- jeux de règles ---------------------------------------------------------

    def create_ruleset(
        self,
        payload: Mapping[str, Any],
        *,
        actor: str | None = None,
    ) -> dict[str, Any]:
        """Crée un RuleSet (version 1)."""
        ruleset_id = clean_text(payload.get("ruleset_id"), limit=160)
        if not ruleset_id:
            raise UserFacingError("L'identifiant du jeu de règles est obligatoire.")
        rules = [clean_text(item, limit=MAX_RULE_ID_LENGTH) for item in (payload.get("rules") or [])]
        known = {rule["rule_id"] for rule in self.list_rules()}
        unknown = [rule_id for rule_id in rules if rule_id not in known]
        if unknown:
            raise UserFacingError("Règles inconnues dans le jeu de règles : " + ", ".join(sorted(unknown)))
        author = clean_text(actor or self.default_actor, limit=120) or "local"
        now = utc_now()
        ruleset = RuleSet(
            ruleset_id=ruleset_id,
            name=clean_text(payload.get("name"), limit=200) or ruleset_id,
            version=1,
            rules=rules,
            description=clean_text(payload.get("description"), limit=4_000),
            effective_from=clean_text(payload.get("effective_from"), limit=40) or now,
            effective_until=None,
            supersedes=clean_text(payload.get("supersedes"), limit=160) or None,
        )
        signature = self.sign(ruleset.to_dict())
        with self._connection() as connection:
            existing = connection.execute(
                "SELECT ruleset_id FROM constitution_rulesets WHERE ruleset_id = ?", (ruleset_id,)
            ).fetchone()
            if existing is not None:
                raise UserFacingError(f"Le jeu de règles « {ruleset_id} » existe déjà.")
            connection.execute(
                """
                INSERT INTO constitution_rulesets (
                    ruleset_id, version, name, payload_json, signature, created_at,
                    effective_from, effective_until, supersedes, created_by
                ) VALUES (?, ?, ?, ?, ?, ?, ?, NULL, ?, ?)
                """,
                (
                    ruleset.ruleset_id,
                    ruleset.version,
                    ruleset.name,
                    canonical_json(ruleset.to_dict()),
                    signature,
                    now,
                    ruleset.effective_from,
                    ruleset.supersedes,
                    author,
                ),
            )
            connection.execute(
                """
                INSERT INTO constitution_ruleset_versions (
                    ruleset_id, version, payload_json, signature, created_at, created_by, change_note
                ) VALUES (?, ?, ?, ?, ?, ?, '')
                """,
                (ruleset.ruleset_id, ruleset.version, canonical_json(ruleset.to_dict()), signature, now, author),
            )
            self._audit(
                connection,
                actor=author,
                action="ruleset.created",
                subject_type="ruleset",
                subject_id=ruleset.ruleset_id,
                details={"version": ruleset.version, "rules": len(ruleset.rules)},
            )
        return {**ruleset.to_dict(), "signature": signature}

    def get_ruleset(self, ruleset_id: str) -> dict[str, Any] | None:
        """Retourne un jeu de règles (dernière version)."""
        with self._connection() as connection:
            row = connection.execute(
                "SELECT * FROM constitution_rulesets WHERE ruleset_id = ?", (ruleset_id,)
            ).fetchone()
        if row is None:
            return None
        payload = json.loads(row["payload_json"])
        payload["signature"] = row["signature"]
        return payload

    def list_rulesets(self) -> list[dict[str, Any]]:
        """Liste les jeux de règles."""
        with self._connection() as connection:
            rows = connection.execute("SELECT * FROM constitution_rulesets ORDER BY ruleset_id").fetchall()
        rulesets: list[dict[str, Any]] = []
        for row in rows:
            payload = json.loads(row["payload_json"])
            payload["signature"] = row["signature"]
            rulesets.append(payload)
        return rulesets

    def list_ruleset_versions(self, ruleset_id: str) -> list[dict[str, Any]]:
        """Historique des versions d'un jeu de règles."""
        with self._connection() as connection:
            rows = connection.execute(
                "SELECT * FROM constitution_ruleset_versions WHERE ruleset_id = ? ORDER BY version DESC",
                (ruleset_id,),
            ).fetchall()
        versions: list[dict[str, Any]] = []
        for row in rows:
            payload = json.loads(row["payload_json"])
            payload["signature"] = row["signature"]
            payload["change_note"] = row["change_note"]
            versions.append(payload)
        return versions

    def update_ruleset(
        self,
        ruleset_id: str,
        changes: Mapping[str, Any],
        *,
        actor: str | None = None,
        change_note: str = "",
    ) -> dict[str, Any]:
        """Crée une nouvelle version d'un jeu de règles (l'ancienne reste en vigueur)."""
        current = self.get_ruleset(ruleset_id)
        if current is None:
            raise UserFacingError(f"Le jeu de règles « {ruleset_id} » est introuvable.")
        merged = {**current, **dict(changes)}
        merged.pop("signature", None)
        rules = [clean_text(item, limit=MAX_RULE_ID_LENGTH) for item in (merged.get("rules") or [])]
        known = {rule["rule_id"] for rule in self.list_rules()}
        unknown = [rule_id for rule_id in rules if rule_id not in known]
        if unknown:
            raise UserFacingError("Règles inconnues dans le jeu de règles : " + ", ".join(sorted(unknown)))
        author = clean_text(actor or self.default_actor, limit=120) or "local"
        now = utc_now()
        version = int(current.get("version", 1)) + 1
        updated = {
            "ruleset_id": ruleset_id,
            "name": clean_text(merged.get("name"), limit=200) or ruleset_id,
            "version": version,
            "rules": rules,
            "description": clean_text(merged.get("description"), limit=4_000),
            "effective_from": now,
            "effective_until": None,
            "supersedes": clean_text(merged.get("supersedes"), limit=160) or None,
        }
        signature = self.sign(updated)
        with self._connection() as connection:
            connection.execute(
                """
                INSERT INTO constitution_ruleset_versions (
                    ruleset_id, version, payload_json, signature, created_at, created_by, change_note
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (ruleset_id, version, canonical_json(updated), signature, now, author, clean_text(change_note, limit=500)),
            )
            connection.execute(
                """
                UPDATE constitution_rulesets
                SET version = ?, name = ?, payload_json = ?, signature = ?, effective_from = ?, effective_until = NULL
                WHERE ruleset_id = ?
                """,
                (version, updated["name"], canonical_json(updated), signature, now, ruleset_id),
            )
            self._audit(
                connection,
                actor=author,
                action="ruleset.updated",
                subject_type="ruleset",
                subject_id=ruleset_id,
                details={"version": version, "rules": len(rules)},
            )
        return {**updated, "signature": signature}

    def rollback_ruleset(
        self,
        ruleset_id: str,
        *,
        target_version: int | None = None,
        actor: str | None = None,
        reason: str = "",
    ) -> dict[str, Any]:
        """Restaure une version antérieure d'un jeu de règles (nouvelle version)."""
        current = self.get_ruleset(ruleset_id)
        if current is None:
            raise UserFacingError(f"Le jeu de règles « {ruleset_id} » est introuvable.")
        if target_version is None:
            history = self.list_ruleset_versions(ruleset_id)
            previous = [item for item in history if item["version"] < current["version"]]
            if not previous:
                raise UserFacingError(f"Le jeu de règles « {ruleset_id} » n'a pas de version antérieure.")
            target_version = int(previous[0]["version"])
        target = None
        for item in self.list_ruleset_versions(ruleset_id):
            if int(item["version"]) == int(target_version):
                target = item
                break
        if target is None:
            raise UserFacingError(f"La version {target_version} du jeu de règles « {ruleset_id} » est introuvable.")
        author = clean_text(actor or self.default_actor, limit=120) or "local"
        now = utc_now()
        version = int(current.get("version", 1)) + 1
        restored = {
            **target,
            "version": version,
            "effective_from": now,
            "effective_until": None,
        }
        restored.pop("signature", None)
        signature = self.sign(restored)
        with self._connection() as connection:
            connection.execute(
                "UPDATE constitution_rulesets SET effective_until = ? WHERE ruleset_id = ? AND effective_until IS NULL",
                (now, ruleset_id),
            )
            connection.execute(
                """
                INSERT INTO constitution_ruleset_versions (
                    ruleset_id, version, payload_json, signature, created_at, created_by, change_note
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    ruleset_id,
                    version,
                    canonical_json(restored),
                    signature,
                    now,
                    author,
                    clean_text(reason, limit=500) or f"Rollback vers la version {target_version}",
                ),
            )
            connection.execute(
                """
                UPDATE constitution_rulesets
                SET version = ?, name = ?, payload_json = ?, signature = ?, effective_from = ?, effective_until = NULL
                WHERE ruleset_id = ?
                """,
                (version, restored["name"], canonical_json(restored), signature, now, ruleset_id),
            )
            self._audit(
                connection,
                actor=author,
                action="ruleset.rolled_back",
                subject_type="ruleset",
                subject_id=ruleset_id,
                details={"from_version": current.get("version"), "restored": target_version, "to_version": version},
            )
        return {**restored, "signature": signature}

    # -- audit et conformité ----------------------------------------------------

    def _audit(
        self,
        connection: sqlite3.Connection,
        *,
        actor: str,
        action: str,
        subject_type: str,
        subject_id: str,
        details: Mapping[str, Any],
    ) -> None:
        payload = {
            "occurred_at": utc_now(),
            "actor": clean_text(actor, limit=120) or "local",
            "action": action,
            "subject_type": subject_type,
            "subject_id": subject_id,
            "details": dict(details),
        }
        connection.execute(
            """
            INSERT INTO constitution_audit_log (
                occurred_at, actor, action, subject_type, subject_id, details_json, signature
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                payload["occurred_at"],
                payload["actor"],
                payload["action"],
                payload["subject_type"],
                payload["subject_id"],
                canonical_json(payload["details"]),
                self.sign(payload),
            ),
        )

    def list_audit(
        self,
        *,
        limit: int = 100,
        subject_type: str | None = None,
        subject_id: str | None = None,
    ) -> list[dict[str, Any]]:
        """Journal d'audit (le plus récent d'abord)."""
        clauses: list[str] = []
        values: list[Any] = []
        if subject_type:
            clauses.append("subject_type = ?")
            values.append(subject_type)
        if subject_id:
            clauses.append("subject_id = ?")
            values.append(subject_id)
        where = f" WHERE {' AND '.join(clauses)}" if clauses else ""
        values.append(max(1, min(int(limit), 1_000)))
        with self._connection() as connection:
            rows = connection.execute(
                f"SELECT * FROM constitution_audit_log{where} ORDER BY id DESC LIMIT ?", values
            ).fetchall()
        entries: list[dict[str, Any]] = []
        for row in rows:
            try:
                details = json.loads(row["details_json"])
            except (TypeError, ValueError):
                details = {}
            entries.append(
                {
                    "id": row["id"],
                    "occurred_at": row["occurred_at"],
                    "actor": row["actor"],
                    "action": row["action"],
                    "subject_type": row["subject_type"],
                    "subject_id": row["subject_id"],
                    "details": details,
                    "signature": row["signature"],
                }
            )
        return entries

    def record_conformance(self, report: Mapping[str, Any]) -> None:
        """Enregistre un rapport de conformité pour l'historique et les tendances."""
        violations = report.get("violations") or []
        failed = len(violations)
        with self._connection() as connection:
            connection.execute(
                """
                INSERT INTO constitution_conformance (
                    entity_id, entity_type, ruleset_id, ruleset_version, checked_at,
                    compliance_score, passed, failed, warnings, errors, critical, report_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    clean_text(report.get("entity_id"), limit=160),
                    clean_text(report.get("entity_type"), limit=40),
                    clean_text(report.get("ruleset_id"), limit=160),
                    int(report.get("ruleset_version", 1) or 1),
                    clean_text(report.get("checked_at"), limit=40) or utc_now(),
                    float(report.get("compliance_score", 0.0) or 0.0),
                    int(report.get("passed", 0) or 0),
                    failed,
                    int(report.get("warnings", 0) or 0),
                    int(report.get("errors", 0) or 0),
                    int(report.get("critical", 0) or 0),
                    canonical_json(dict(report)),
                ),
            )

    def conformance_history(self, entity_id: str | None = None, *, limit: int = 50) -> list[dict[str, Any]]:
        """Historique des rapports de conformité (le plus récent d'abord)."""
        clauses: list[str] = []
        values: list[Any] = []
        if entity_id:
            clauses.append("entity_id = ?")
            values.append(entity_id)
        where = f" WHERE {' AND '.join(clauses)}" if clauses else ""
        values.append(max(1, min(int(limit), 1_000)))
        with self._connection() as connection:
            rows = connection.execute(
                f"SELECT * FROM constitution_conformance{where} ORDER BY id DESC LIMIT ?", values
            ).fetchall()
        history: list[dict[str, Any]] = []
        for row in rows:
            try:
                report = json.loads(row["report_json"])
            except (TypeError, ValueError):
                report = {}
            history.append(
                {
                    "entity_id": row["entity_id"],
                    "entity_type": row["entity_type"],
                    "ruleset_id": row["ruleset_id"],
                    "ruleset_version": row["ruleset_version"],
                    "checked_at": row["checked_at"],
                    "compliance_score": row["compliance_score"],
                    "passed": row["passed"],
                    "failed": row["failed"],
                    "warnings": row["warnings"],
                    "errors": row["errors"],
                    "critical": row["critical"],
                    "violations": report.get("violations", []),
                }
            )
        return history

    # -- amorçage ---------------------------------------------------------------

    def seed_defaults(self, *, actor: str = "system") -> dict[str, Any]:
        """Installe la Constitution de référence (idempotent)."""
        created_rules: list[str] = []
        created_rulesets: list[str] = []
        existing = {rule["rule_id"] for rule in self.list_rules()}
        for payload in DEFAULT_RULES:
            if payload["rule_id"] in existing:
                continue
            status = str(payload.get("status", "draft"))
            now = utc_now()
            rule = normalize_rule_payload(
                payload,
                version=1,
                status=status,
                now=now,
                created_by=actor,
                approved_by=actor if status == "active" else None,
                approved_at=now if status == "active" else None,
            )
            signature = self.sign(rule)
            with self._connection() as connection:
                connection.execute(
                    """
                    INSERT INTO constitution_rules (
                        rule_id, version, status, domain, name, payload_json, signature,
                        created_at, updated_at, created_by, approved_by, approved_at, reviewed_at, has_test
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0)
                    """,
                    (
                        rule["rule_id"],
                        rule["version"],
                        rule["status"],
                        rule["domain"],
                        rule["name"],
                        canonical_json(rule),
                        signature,
                        rule["created_at"],
                        rule["updated_at"],
                        rule["created_by"],
                        rule["approved_by"],
                        rule["approved_at"],
                        rule["approved_at"],
                    ),
                )
                connection.execute(
                    """
                    INSERT INTO constitution_rule_versions (
                        rule_id, version, status, payload_json, signature, created_at, created_by, change_note
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        rule["rule_id"],
                        rule["version"],
                        rule["status"],
                        canonical_json(rule),
                        signature,
                        rule["created_at"],
                        rule["created_by"],
                        "Référentiel initial de la Constitution",
                    ),
                )
                self._audit(
                    connection,
                    actor=actor,
                    action="rule.seeded",
                    subject_type="rule",
                    subject_id=rule["rule_id"],
                    details={"version": rule["version"], "status": rule["status"]},
                )
            created_rules.append(rule["rule_id"])
        existing_rulesets = {ruleset["ruleset_id"] for ruleset in self.list_rulesets()}
        for payload in DEFAULT_RULESETS:
            if payload["ruleset_id"] in existing_rulesets:
                continue
            self.create_ruleset(payload, actor=actor)
            created_rulesets.append(payload["ruleset_id"])
        return {"rules": created_rules, "rulesets": created_rulesets}


def load_rules(store: ConstitutionStore, *, statuses: Sequence[str] | None = None) -> list[Rule]:
    """Charge les règles stockées sous forme d'objets ``Rule``."""
    wanted = list(statuses) if statuses else ["active", "deprecated", "draft"]
    rules: list[Rule] = []
    for status in wanted:
        for payload in store.list_rules(status=status):
            rules.append(Rule.from_dict(payload))
    return rules
