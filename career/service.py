"""SQLite-backed, deterministic local Career service for Côme AI V3.

This module intentionally has no network client and no model dependency. It
stores candidate information outside ``data/`` so the document-analysis agent
cannot discover it as an ordinary workspace file.
"""

from __future__ import annotations

import csv
import hashlib
import json
import os
import re
import sqlite3
import threading
import time
import urllib.parse
import uuid
from contextlib import contextmanager
from dataclasses import replace
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterator, Mapping

from .models import (
    AVAILABILITY_STATES,
    APPLICATION_STAGES,
    GENERIC_APPLICATION_STAGES,
    JOB_FAMILIES,
    PRIMARY_LOCATIONS,
    PipelineStage,
    availability_assessment,
    canonical_url,
    clean_text,
    date_text,
    deadline_state,
    dedup_key,
    parse_date,
    scoped_normalized_text_cache,
    utc_now,
    validate_choice,
)
from .application_studio import (
    KIT_TEXT_FIELDS,
    KIT_TEXT_LIMITS,
    MAX_DRAFT_CHARS,
    ApplicationDraft,
    build_ai_prompt,
    build_kit_texts,
    build_local_application_draft,
    generate_application_kit,
    normalize_language,
    parse_ai_draft,
    render_application_html,
    scan_kit_placeholders,
)
from .calendar_export import build_deadline_calendar_ics
from .application_dashboard import (
    CHECKLIST_EVENT_TYPE,
    CHECKLIST_KEYS,
    DEADLINE_FILTER_VALUES,
    MAX_DASHBOARD_APPLICATIONS,
    RECEIPT_FILTER_VALUES,
    build_dashboard_payload,
)
from .action_center import build_application_action_center
from .application_prep import (
    prepare_application,
    reconcile_cv_plan_with_requirements_fit,
    summarize_offer,
)
from .application_sprint import MAX_SPRINT_CANDIDATES, MAX_SPRINT_ITEMS, build_application_sprint
from .requirements_fit import analyze_fit
from .source_trust import check_trust, status_label as source_trust_label
from .quick_answers import SUPPORTED_LANGS, build_answer_pack
from .send_confirmation import (
    FOLLOWUP_RECORDED_EVENT_TYPE,
    SEND_CONFIRMATION_EVENT_TYPE,
    STAGES_AT_OR_AFTER_SENT,
    TRACKER_HONESTY_NOTE,
    MAX_TRACKER_APPLICATIONS,
    SendConfirmationError,
    SendEvidence,
    build_followup_draft,
    evidence_fingerprint,
    evidence_payload,
    latest_followup_on,
    latest_send_evidence,
    send_record_from_payload,
    send_record_to_dict,
    validate_evidence,
)
from .cv_fit import (
    PipelineItem,
    classify_variant,
    compute_coverage,
    derive_pipeline_stage,
    generate_diff,
    serialize_gap,
)
from .cv_variants import ALL_VARIANTS

try:
    from consent_guard import ConsentGuard
except Exception:  # pragma: no cover - optional dependency
    ConsentGuard = None  # type: ignore[misc, assignment]
from .stage_search import (
    STAGE_DOMAINS,
    brief_is_configured,
    default_brief,
    score_brief_match,
    search_terms_for,
    validate_brief,
    vocabulary as stage_search_vocabulary,
)
from .document_export import write_docx, write_pdf
from .intake import answer_for_step, normalize_answers, serialize_intake
from .interview import (
    DIFFICULTIES,
    INTERVIEW_MODES,
    evaluate_answer,
    normalize_config as normalize_interview_config,
    progress_summary,
    select_question,
)
from .ocr import LocalVisionOCR, OCRResult
from .discovery import DiscoveryPayload, GreenhouseBoard, GreenhouseJobBoardConnector, PublicSourceError, parse_greenhouse_board_token
from .connectors import default_exploration_connectors
from .exploration import (
    EXPLORATION_LAST_SETTING,
    EXPLORATION_MAX_RESULTS,
    EXPLORATION_MAX_SOURCES,
    EXPLORATION_NETWORK_BUDGET_SECONDS,
    classify_internship,
    criteria_admit,
    ranking_key,
)
from .offer_qualification import qualify_offer
from .offer_intelligence import (
    align_display_requirements,
    build_snapshot,
    snapshot_summary,
)
from . import offer_intelligence_store
from . import source_material_store
from .scoring import classify_job_family, score_job
from .source_coverage import CoverageRunNotFound, compute_metrics
from workspace_core import UserFacingError, extract_text, safe_error
from .cv_quality.parser import extract_text_from_file
from .profile_import import (
    ALLOWED_PROFILE_SUFFIXES,
    MAX_PROFILE_IMPORT_BYTES,
    PROFILE_IMPORT_KINDS,
    parse_profile_text,
)
from .profile_readiness import assess_profile_readiness
from .qualification_persistence import (
    decode_qualification_snapshot,
    normalize_qualification_snapshot,
    snapshot_matches_current_source,
)


SCHEMA_VERSION = 8
# The Stage Hunter brief lives in career_settings as one JSON value: no
# schema migration, and it is exported with the rest of the local settings.
STAGE_SEARCH_SETTING_KEY = "stage_search_brief"
DISCOVERY_CACHE_SECONDS = 10 * 60


def _attach_qualification_presentation(match: dict[str, Any], qualification: dict[str, Any]) -> dict[str, Any]:
    """Keep relevance and mandatory eligibility distinct in every API path."""
    status = clean_text(qualification.get("target_status"), limit=40) or "to_verify"
    fit_label = clean_text(match.get("label"), limit=160)
    match["fit_label"] = fit_label
    match["qualification_status"] = status
    if status == "non_conforming":
        match["label"] = "Hors critères obligatoires sélectionnés"
    elif status == "to_verify":
        score = match.get("score")
        if isinstance(score, (int, float)) and score >= 70:
            match["label"] = "Pertinence élevée — informations obligatoires à vérifier"
        elif isinstance(score, (int, float)) and score >= 45:
            match["label"] = "Pertinence possible — informations obligatoires à vérifier"
        else:
            match["label"] = "Informations obligatoires à vérifier"
    return match


def _requirement_ids_of(job: dict[str, Any]) -> list[str]:
    """Return the requirement identifiers of the current snapshot of an offer.

    The explorer, the detailed view, the matching panel and the preparation
    panel all read this list: a requirement keeps one identifier everywhere.
    """
    summary = job.get("offer_intelligence_summary")
    if not isinstance(summary, dict):
        return []
    return [str(item) for item in summary.get("requirement_ids") or []]


DELETE_CONFIRMATION = "SUPPRIMER MES DONNÉES CAREER"
PROFILE_EDITABLE_FIELDS = (
    "display_name",
    "contact_email",
    "contact_phone",
    "linkedin_url",
    "education",
    "experience",
    "skills",
    "languages",
)
PROFILE_FIELD_LIMITS = {
    "display_name": 160,
    "contact_email": 320,
    "contact_phone": 80,
    "linkedin_url": 2_000,
    "education": 1_000,
    "experience": 6_000,
    "skills": 4_000,
    "languages": 2_000,
}
MAX_PROFILE_PASTED_CHARS = 100_000

# The dashboard is deliberately a small, actionable summary rather than a
# second task database.  These items are computed afresh from local state so
# they can never trigger a network request or become stale persisted advice.
ACTION_PLAN_LIMIT = 12
PROFILE_ACTION_FIELDS: tuple[tuple[str, str], ...] = (
    ("display_name", "nom"),
    ("education", "formation"),
    ("experience", "expérience"),
    ("skills", "compétences"),
    ("languages", "langues"),
)
# A job that has been explicitly closed off by the candidate, or whose
# associated application has moved beyond a manual submission, must not keep
# generating urgent dashboard reminders.  This is deliberately a small local
# policy used only by the computed action plan; it does not change tracker
# history or application stages.
POST_SUBMISSION_APPLICATION_STAGES = frozenset(
    {
        "submitted",
        "submitted_confirmed",
        "response_received",
        "interview",
        "offer_received",
        "rejected",
        "refused",
        "withdrawn",
    }
)


def re_sub_filename(value: str) -> str:
    """Make a short, non-path component for a locally exported draft."""
    compact = re.sub(r"[^A-Za-z0-9À-ÿ._-]+", "-", clean_text(value, limit=80)).strip(".-_")
    return compact[:60] or "candidature"


class CareerService:
    """Small local service with short SQLite connections and explicit rules."""

    @staticmethod
    def render_letter(**kwargs: Any) -> dict[str, Any]:
        from .letter_language import render_multilingual_letter, to_dict
        return to_dict(render_multilingual_letter(**kwargs))

    @staticmethod
    def check_letter(letter_body: str, evidence: list[str]) -> dict[str, Any]:
        from .letter_check import score_letter, to_dict
        return to_dict(score_letter(letter_body, evidence))

    @staticmethod
    def personalize_letter(**kwargs: Any) -> dict[str, Any]:
        from .letter_personalization import personalize_letter, to_dict
        return to_dict(personalize_letter(**kwargs))

    @staticmethod
    def _letter_fingerprint(body: str, language: str) -> str:
        return hashlib.sha256(json.dumps([body, language], ensure_ascii=False).encode("utf-8")).hexdigest()

    def approve_letter(self, **kwargs: Any) -> dict[str, Any]:
        identifier = kwargs["letter_id"]
        body = kwargs.get("letter_body", "")
        language = kwargs.get("language", "fr")
        approved = bool(kwargs["approved"] and body.strip())
        blockers = [] if not kwargs["approved"] or approved else ["Relis le contenu de la lettre avant de l’approuver."]
        with self._lock, self._connection() as connection:
            connection.execute(
                "INSERT INTO letter_content_approvals(letter_id, fingerprint, approved, version, note, updated_at) "
                "VALUES (?, ?, ?, ?, ?, ?) ON CONFLICT(letter_id) DO UPDATE SET "
                "fingerprint=excluded.fingerprint, approved=excluded.approved, version=excluded.version, "
                "note=excluded.note, updated_at=excluded.updated_at",
                (identifier, self._letter_fingerprint(body, language), int(approved),
                 kwargs.get("version", 1), kwargs.get("note", ""), utc_now()),
            )
        return {"letter_id": identifier, "approved": approved, "version": kwargs.get("version", 1),
                "approver": "human", "warnings": [], "blockers": blockers}

    def export_letter(self, **kwargs: Any) -> dict[str, Any]:
        from .letter_export import ALLOWED_FORMATS, export_letter
        title = kwargs.get("title", "")
        body = kwargs.get("letter_body", "")
        language = kwargs.get("language", "fr")
        fmt = clean_text(kwargs.get("fmt"), limit=8).lower()
        if fmt not in ALLOWED_FORMATS:
            return {"ok": False, "error": "Format d’export non supporté."}
        with self._lock, self._connection() as connection:
            approval = connection.execute(
                "SELECT fingerprint, approved FROM letter_content_approvals WHERE letter_id = ?", (title,),
            ).fetchone()
            if not approval or not approval["approved"] or approval["fingerprint"] != self._letter_fingerprint(body, language):
                return {"ok": False, "error": "Approuve cette version exacte de la lettre avant l’export."}
            # Opaque, fresh filenames cannot collide with an existing original or symlink.
            target = self.export_dir / f"career_letter_{uuid.uuid4().hex}.{fmt}"
            result = export_letter(letter_body=body, title=title, language=language, target=target, fmt=fmt, approved=True)
            if result.get("ok"):
                os.chmod(target, 0o600)
                result["download_url"] = f"/api/career/letter/exports/{target.name}"
            return result

    def letter_export_path(self, filename: str) -> Path:
        if not re.fullmatch(r"career_letter_[0-9a-f]{32}\.(?:md|txt|pdf|docx)", filename):
            raise UserFacingError("Cet export de lettre est introuvable.")
        path = self.export_dir / filename
        if path.is_symlink() or not path.is_file():
            raise UserFacingError("Cet export de lettre est introuvable.")
        return path

    def shortlist(self) -> list[dict[str, Any]]:
        return self.list_jobs(shortlisted=True)

    @staticmethod
    def rank_offers(offers: list[dict[str, Any]], today: str | None = None) -> dict[str, Any]:
        from .urgency_ranking import rank_by_urgency
        rows, ordered = rank_by_urgency(offers, today=today)
        return {"rows": [row.to_dict() for row in rows], "ordered": ordered, "warnings": [], "blockers": []}

    @staticmethod
    def render_shortlist(offers: list[dict[str, Any]], today: str | None = None) -> dict[str, Any]:
        from .shortlist_dashboard import render_dashboard, to_dict
        result = to_dict(render_dashboard(offers, today=today))
        result.update({"warnings": [], "blockers": []})
        return result

    def export_shortlist(self, offers: list[dict[str, Any]], fmt: str, fields: list[str]) -> dict[str, Any]:
        if not offers:
            return {"ok": False, "warnings": [], "blockers": ["Aucune offre à exporter."]}
        from .shortlist_export import export_shortlist_csv, export_shortlist_json
        normalized = fmt.lower()
        if normalized not in {"csv", "json"}:
            return {"ok": False, "warnings": [], "blockers": ["Format shortlist non supporté."]}
        target = self.export_dir / f"shortlist.{normalized}"
        if normalized == "csv":
            result = export_shortlist_csv(offers, target, fields=fields or None)
        else:
            result = export_shortlist_json(offers, target)
        return {"ok": True, **result.__dict__, "warnings": [], "blockers": []}

    def ats_fields(self, platform: str) -> dict[str, Any]:
        from .ats_fields import missing_required, prefill_fields, to_dict
        fields = prefill_fields(platform, self.get_profile())
        missing = missing_required(fields)
        return {
            "platform": platform or "generic",
            "fields": [to_dict(field) for field in fields],
            "warnings": [],
            "blockers": [f"Champ obligatoire manquant : {name}" for name in missing],
        }

    @staticmethod
    def dossier_checklist(dossier: str, provided: list[str]) -> dict[str, Any]:
        from .dossier_checklist import checklist_for, completeness, to_dict
        items = checklist_for(dossier, provided)
        status = completeness(items)
        return {
            "dossier": dossier or "stage",
            "items": [to_dict(item) for item in items],
            "completeness": status,
            "warnings": [],
            "blockers": [f"Document obligatoire manquant : {name}" for name in status["missing_required"]],
        }

    @staticmethod
    def dossier_preview(**kwargs: Any) -> dict[str, Any]:
        from .dossier_preview import build_preview, to_dict
        result = to_dict(build_preview(**kwargs))
        result.setdefault("blockers", [])
        return result

    def __init__(
        self,
        base_dir: Path,
        *,
        ocr: LocalVisionOCR | None = None,
        discovery_connector: GreenhouseJobBoardConnector | None = None,
        curated_sources: tuple[dict[str, Any], ...] | None = None,
        exploration_connectors: dict[str, Any] | None = None,
    ):
        self.base_dir = base_dir.resolve()
        self.data_dir = self.base_dir / "career_data"
        # Profile sources are deliberately outside the V3 workspace ``data/``.
        # The general document chat never lists or receives these files.
        self.documents_dir = self.data_dir / "documents"
        self.export_dir = self.data_dir / "exports"
        self.ocr_dir = self.data_dir / "ocr"
        self.studio_dir = self.data_dir / "application_studio"
        # Backups are intentionally separate from exports and source documents:
        # they contain a complete private snapshot of the local Career data.
        self.backups_dir = self.data_dir / "backups"
        self.db_path = self.data_dir / "career.sqlite3"
        self.ocr = ocr or LocalVisionOCR(self.ocr_dir)
        # The discovery lock is intentionally process-local: the local web
        # server has one process, and it prevents double-clicks from issuing
        # parallel requests to the same public board.
        self.discovery_connector = discovery_connector or GreenhouseJobBoardConnector()
        self._curated_sources = curated_sources
        self._exploration_connectors = (exploration_connectors if exploration_connectors is not None
                                        else default_exploration_connectors(self.discovery_connector))
        # Bounded in-memory cache, separate from personal boards and private
        # profile settings. Restarting drops HTTP cache but keeps the last
        # result's job references and tracking in SQLite.
        self._exploration_cache: dict[str, tuple[str, Any]] = {}
        self._prep_cache: set[str] = set()
        self._discovery_lock = threading.Lock()
        self._lock = threading.RLock()
        self._ensure_storage()
        self._initialize()
        if ConsentGuard is not None:
            try:
                self.consent_guard = ConsentGuard(self.data_dir / "consent")
            except Exception:
                self.consent_guard = None
        else:
            self.consent_guard = None

    def _ensure_storage(self) -> None:
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.documents_dir.mkdir(parents=True, exist_ok=True)
        self.export_dir.mkdir(parents=True, exist_ok=True)
        self.ocr_dir.mkdir(parents=True, exist_ok=True)
        self.studio_dir.mkdir(parents=True, exist_ok=True)
        self.backups_dir.mkdir(parents=True, exist_ok=True)
        for path in (
            self.data_dir,
            self.documents_dir,
            self.export_dir,
            self.ocr_dir,
            self.studio_dir,
            self.backups_dir,
        ):
            try:
                os.chmod(path, 0o700)
            except OSError:
                pass

    @contextmanager
    def _connection(self) -> Iterator[sqlite3.Connection]:
        connection = sqlite3.connect(self.db_path, timeout=5.0)
        connection.row_factory = sqlite3.Row
        try:
            connection.execute("PRAGMA foreign_keys = ON")
            connection.execute("PRAGMA busy_timeout = 5000")
            # This reduces residual copies in the active SQLite database after
            # a person removes their Career data. It cannot erase OS backups.
            connection.execute("PRAGMA secure_delete = ON")
            yield connection
            connection.commit()
        except sqlite3.Error as error:
            connection.rollback()
            raise UserFacingError("La base Career locale a rencontré un problème. Réessaie.") from error
        finally:
            connection.close()

    def _initialize(self) -> None:
        with self._lock, self._connection() as connection:
            version = connection.execute("PRAGMA user_version").fetchone()[0]
            if version > SCHEMA_VERSION:
                raise UserFacingError("La base Career a été créée par une version plus récente de l’application.")
            if 0 < version < SCHEMA_VERSION:
                # Do this before changing the journal mode or schema. SQLite's
                # backup API includes committed WAL content, unlike a file copy.
                self._backup_before_migration(connection, version)
            connection.execute("PRAGMA journal_mode = WAL")
            if version == 0:
                connection.executescript(
                    """
                    CREATE TABLE candidate_profile (
                        id INTEGER PRIMARY KEY CHECK (id = 1),
                        display_name TEXT NOT NULL DEFAULT '',
                        contact_email TEXT NOT NULL DEFAULT '',
                        contact_phone TEXT NOT NULL DEFAULT '',
                        linkedin_url TEXT NOT NULL DEFAULT '',
                        education TEXT NOT NULL DEFAULT '',
                        experience TEXT NOT NULL DEFAULT '',
                        skills TEXT NOT NULL DEFAULT '',
                        languages TEXT NOT NULL DEFAULT '',
                        eligibility TEXT NOT NULL DEFAULT 'unknown',
                        target_companies TEXT NOT NULL DEFAULT '',
                        notes TEXT NOT NULL DEFAULT '',
                        updated_at TEXT NOT NULL
                    );

                    CREATE TABLE preference_items (
                        kind TEXT NOT NULL CHECK (kind IN ('family', 'location')),
                        item_key TEXT NOT NULL,
                        label TEXT NOT NULL,
                        enabled INTEGER NOT NULL DEFAULT 1 CHECK (enabled IN (0, 1)),
                        priority INTEGER NOT NULL DEFAULT 100,
                        scope TEXT NOT NULL DEFAULT 'primary',
                        PRIMARY KEY (kind, item_key)
                    );

                    CREATE TABLE career_settings (
                        setting_key TEXT PRIMARY KEY,
                        setting_value TEXT NOT NULL
                    );

                    CREATE TABLE jobs (
                        id TEXT PRIMARY KEY,
                        dedup_key TEXT NOT NULL UNIQUE,
                        source_name TEXT NOT NULL,
                        source_id TEXT NOT NULL DEFAULT '',
                        official_url TEXT NOT NULL DEFAULT '',
                        company TEXT NOT NULL,
                        title TEXT NOT NULL,
                        job_family TEXT NOT NULL DEFAULT 'À préciser',
                        city TEXT NOT NULL DEFAULT '',
                        country TEXT NOT NULL DEFAULT '',
                        posted_date TEXT,
                        deadline_date TEXT,
                        start_date TEXT,
                        end_date TEXT,
                        duration_months INTEGER,
                        source_status TEXT NOT NULL DEFAULT 'unknown',
                        calendar_status TEXT NOT NULL DEFAULT 'to_verify',
                        calendar_reasons_json TEXT NOT NULL DEFAULT '[]',
                        employment_type TEXT NOT NULL DEFAULT '',
                        role_level TEXT NOT NULL DEFAULT '',
                        requirements TEXT NOT NULL DEFAULT '',
                        languages_required TEXT NOT NULL DEFAULT '',
                        eligibility_requirement TEXT NOT NULL DEFAULT '',
                        description_original TEXT NOT NULL DEFAULT '',
                        personal_note TEXT NOT NULL DEFAULT '',
                        status TEXT NOT NULL DEFAULT 'discovered',
                        shortlisted INTEGER NOT NULL DEFAULT 0 CHECK (shortlisted IN (0, 1)),
                        discovery_source_id TEXT NOT NULL DEFAULT '',
                        last_seen_at TEXT NOT NULL DEFAULT '',
                        created_at TEXT NOT NULL,
                        updated_at TEXT NOT NULL,
                        last_verified_at TEXT NOT NULL
                    );
                    CREATE INDEX jobs_family_idx ON jobs(job_family);
                    CREATE INDEX jobs_city_idx ON jobs(city);
                    CREATE INDEX jobs_status_idx ON jobs(status, shortlisted);
                    CREATE INDEX jobs_deadline_idx ON jobs(deadline_date);
                    CREATE INDEX jobs_discovery_source_idx ON jobs(discovery_source_id, last_seen_at);

                    CREATE TABLE job_qualification_snapshots (
                        job_id TEXT PRIMARY KEY REFERENCES jobs(id) ON DELETE CASCADE,
                        schema_version INTEGER NOT NULL,
                        facts_json TEXT NOT NULL DEFAULT '{}',
                        provenance_json TEXT NOT NULL DEFAULT '{}',
                        missing_fields_json TEXT NOT NULL DEFAULT '[]',
                        reasons_json TEXT NOT NULL DEFAULT '[]',
                        source_fingerprint TEXT NOT NULL DEFAULT '',
                        updated_at TEXT NOT NULL
                    );

                    CREATE TABLE applications (
                        id TEXT PRIMARY KEY,
                        job_id TEXT NOT NULL UNIQUE REFERENCES jobs(id) ON DELETE CASCADE,
                        stage TEXT NOT NULL DEFAULT 'to_prepare',
                        receipt_status TEXT NOT NULL DEFAULT 'not_submitted',
                        approval_granted INTEGER NOT NULL DEFAULT 0 CHECK (approval_granted IN (0, 1)),
                        confirmation_reference TEXT NOT NULL DEFAULT '',
                        created_at TEXT NOT NULL,
                        updated_at TEXT NOT NULL
                    );
                    CREATE INDEX applications_stage_idx ON applications(stage);

                    CREATE TABLE application_events (
                        id TEXT PRIMARY KEY,
                        application_id TEXT REFERENCES applications(id) ON DELETE CASCADE,
                        job_id TEXT NOT NULL,
                        event_type TEXT NOT NULL,
                        detail TEXT NOT NULL DEFAULT '',
                        created_at TEXT NOT NULL
                    );
                    CREATE INDEX application_events_job_idx ON application_events(job_id, created_at DESC);

                    CREATE TABLE career_audit_log (
                        id TEXT PRIMARY KEY,
                        action TEXT NOT NULL,
                        subject_type TEXT NOT NULL,
                        subject_id TEXT NOT NULL,
                        created_at TEXT NOT NULL
                    );

                    CREATE TABLE profile_imports (
                        id TEXT PRIMARY KEY,
                        source_kind TEXT NOT NULL CHECK (source_kind IN ('cv', 'linkedin_export', 'linkedin_text', 'profile_document')),
                        original_name TEXT NOT NULL,
                        stored_filename TEXT NOT NULL DEFAULT '',
                        content_sha256 TEXT NOT NULL UNIQUE,
                        size_bytes INTEGER NOT NULL DEFAULT 0,
                        extracted_text TEXT NOT NULL,
                        extraction_method TEXT NOT NULL DEFAULT 'embedded_text',
                        ocr_pages INTEGER NOT NULL DEFAULT 0,
                        ocr_warnings_json TEXT NOT NULL DEFAULT '[]',
                        suggestions_json TEXT NOT NULL DEFAULT '{}',
                        status TEXT NOT NULL DEFAULT 'pending' CHECK (status IN ('pending', 'applied')),
                        base_profile_updated_at TEXT NOT NULL,
                        created_at TEXT NOT NULL,
                        applied_at TEXT
                    );
                    CREATE INDEX profile_imports_created_idx ON profile_imports(created_at DESC);

                    CREATE TABLE career_intake (
                        id INTEGER PRIMARY KEY CHECK (id = 1),
                        step_index INTEGER NOT NULL DEFAULT 0 CHECK (step_index >= 0 AND step_index <= 6),
                        answers_json TEXT NOT NULL DEFAULT '{}',
                        completed INTEGER NOT NULL DEFAULT 0 CHECK (completed IN (0, 1)),
                        updated_at TEXT NOT NULL
                    );

                    CREATE TABLE application_drafts (
                        id TEXT PRIMARY KEY,
                        job_id TEXT NOT NULL REFERENCES jobs(id) ON DELETE CASCADE,
                        language TEXT NOT NULL,
                        variant TEXT NOT NULL DEFAULT '',
                        generation_mode TEXT NOT NULL CHECK (generation_mode IN ('local', 'ai')),
                        provider TEXT NOT NULL DEFAULT 'Local',
                        cv_markdown TEXT NOT NULL,
                        letter_markdown TEXT NOT NULL,
                        checks_json TEXT NOT NULL DEFAULT '[]',
                        quality_json TEXT NOT NULL DEFAULT '{}',
                        profile_updated_at TEXT NOT NULL,
                        job_updated_at TEXT NOT NULL,
                        created_at TEXT NOT NULL
                    );
                    CREATE INDEX application_drafts_job_idx ON application_drafts(job_id, created_at DESC);

                    CREATE TABLE discovery_sources (
                        id TEXT PRIMARY KEY,
                        provider TEXT NOT NULL CHECK (provider IN ('greenhouse')),
                        company TEXT NOT NULL,
                        board_token TEXT NOT NULL UNIQUE,
                        enabled INTEGER NOT NULL DEFAULT 1 CHECK (enabled IN (0, 1)),
                        created_at TEXT NOT NULL,
                        updated_at TEXT NOT NULL,
                        last_checked_at TEXT NOT NULL DEFAULT '',
                        last_success_at TEXT NOT NULL DEFAULT '',
                        last_error_code TEXT NOT NULL DEFAULT '',
                        last_error_at TEXT NOT NULL DEFAULT ''
                    );
                    CREATE INDEX discovery_sources_enabled_idx ON discovery_sources(enabled, updated_at DESC);

                    CREATE TABLE discovery_runs (
                        id TEXT PRIMARY KEY,
                        source_id TEXT NOT NULL,
                        started_at TEXT NOT NULL,
                        finished_at TEXT NOT NULL DEFAULT '',
                        status TEXT NOT NULL CHECK (status IN ('running', 'success', 'partial', 'error', 'cached')),
                        found_count INTEGER NOT NULL DEFAULT 0,
                        imported_count INTEGER NOT NULL DEFAULT 0,
                        updated_count INTEGER NOT NULL DEFAULT 0,
                        skipped_count INTEGER NOT NULL DEFAULT 0,
                        message TEXT NOT NULL DEFAULT ''
                    );
                    CREATE INDEX discovery_runs_source_idx ON discovery_runs(source_id, started_at DESC);

                    CREATE TABLE interview_sessions (
                        id TEXT PRIMARY KEY,
                        application_id TEXT NOT NULL DEFAULT '',
                        job_id TEXT NOT NULL DEFAULT '',
                        mode TEXT NOT NULL,
                        difficulty TEXT NOT NULL,
                        language TEXT NOT NULL,
                        status TEXT NOT NULL CHECK (status IN ('active', 'completed', 'archived')),
                        current_question_json TEXT NOT NULL DEFAULT '{}',
                        turns_json TEXT NOT NULL DEFAULT '[]',
                        started_at TEXT NOT NULL,
                        updated_at TEXT NOT NULL,
                        completed_at TEXT NOT NULL DEFAULT ''
                    );
                    CREATE INDEX interview_sessions_updated_idx ON interview_sessions(status, updated_at DESC);
                    CREATE INDEX interview_sessions_job_idx ON interview_sessions(job_id, updated_at DESC);
                    """
                )
                connection.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")
            elif version < SCHEMA_VERSION:
                self._migrate(connection, version)
                connection.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")
            self._add_column_if_missing(
                connection,
                "application_drafts",
                "variant",
                "TEXT NOT NULL DEFAULT ''",
            )
            self._seed_defaults(connection)
            # The versioned offer-intelligence snapshot lives beside the offers,
            # never as a new column on the offers themselves.
            offer_intelligence_store.ensure_schema(connection)
            source_material_store.ensure_schema(connection)
            connection.execute(
                "CREATE TABLE IF NOT EXISTS letter_content_approvals ("
                "letter_id TEXT PRIMARY KEY, fingerprint TEXT NOT NULL, approved INTEGER NOT NULL, "
                "version INTEGER NOT NULL, note TEXT NOT NULL, updated_at TEXT NOT NULL)"
            )
        try:
            os.chmod(self.db_path, 0o600)
        except OSError:
            pass

    def _backup_before_migration(self, connection: sqlite3.Connection, version: int) -> Path:
        """Create one private, consistent snapshot before an in-place migration.

        A migration never reuses or removes a snapshot.  The temporary file is
        owned by this operation and only exists until SQLite reports a complete
        backup; an existing user backup is consequently never overwritten.
        """
        timestamp = datetime.now().strftime("%Y%m%dT%H%M%S%f")
        stem = f"career-before-v{version}-to-v{SCHEMA_VERSION}-{timestamp}-{uuid.uuid4().hex[:8]}"
        backup_path = self.backups_dir / f"{stem}.sqlite3"
        temporary_path = self.backups_dir / f".{stem}.tmp"
        destination: sqlite3.Connection | None = None
        try:
            # Claim a unique, owner-only path before SQLite opens it.  The
            # exclusive create also means this method can never replace a
            # backup that was already present in the directory.
            descriptor = os.open(temporary_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            os.close(descriptor)
            destination = sqlite3.connect(temporary_path)
            connection.backup(destination)
            destination.commit()
            integrity = destination.execute("PRAGMA integrity_check").fetchone()
            if not integrity or str(integrity[0]).lower() != "ok":
                raise sqlite3.DatabaseError("La vérification de la sauvegarde SQLite a échoué.")
            destination.close()
            destination = None
            # ``replace`` within this private directory is atomic. The mode is
            # set before it, so the final snapshot is never briefly public.
            os.chmod(temporary_path, 0o600)
            os.replace(temporary_path, backup_path)
            return backup_path
        except (OSError, sqlite3.Error) as error:
            if destination is not None:
                destination.close()
            # This is only the unique temporary filename allocated above; it
            # cannot refer to a user-created backup.
            try:
                temporary_path.unlink(missing_ok=True)
            except OSError:
                pass
            raise UserFacingError(
                "La sauvegarde locale de sécurité avant mise à jour n’a pas pu être créée. "
                "Aucune migration n’a été appliquée."
            ) from error

    @staticmethod
    def _add_column_if_missing(
        connection: sqlite3.Connection, table: str, column: str, definition: str
    ) -> None:
        columns = {str(row["name"]) for row in connection.execute(f"PRAGMA table_info({table})").fetchall()}
        if column not in columns:
            connection.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")

    def _migrate(self, connection: sqlite3.Connection, version: int) -> None:
        """Migrate in-place without touching a person's existing Career data."""
        if version < 1 or version > 7:
            raise UserFacingError("La base Career locale ne peut pas être mise à jour automatiquement.")
        if version == 1:
            self._migrate_to_v2(connection)
            version = 2
        if version == 2:
            self._migrate_to_v3(connection)
            version = 3
        if version == 3:
            self._migrate_to_v4(connection)
            version = 4
        if version == 4:
            self._migrate_to_v5(connection)
            version = 5
        if version == 5:
            self._migrate_to_v6(connection)
            version = 6
        if version == 6:
            self._add_column_if_missing(
                connection, "application_drafts", "quality_json", "TEXT NOT NULL DEFAULT '{}'"
            )
            version = 7
        if version == 7:
            self._migrate_to_v8(connection)

    def _migrate_to_v2(self, connection: sqlite3.Connection) -> None:
        self._add_column_if_missing(connection, "candidate_profile", "contact_email", "TEXT NOT NULL DEFAULT ''")
        self._add_column_if_missing(connection, "candidate_profile", "contact_phone", "TEXT NOT NULL DEFAULT ''")
        self._add_column_if_missing(connection, "candidate_profile", "linkedin_url", "TEXT NOT NULL DEFAULT ''")
        self._add_column_if_missing(connection, "candidate_profile", "experience", "TEXT NOT NULL DEFAULT ''")
        connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS profile_imports (
                id TEXT PRIMARY KEY,
                source_kind TEXT NOT NULL CHECK (source_kind IN ('cv', 'linkedin_export', 'linkedin_text', 'profile_document')),
                original_name TEXT NOT NULL,
                stored_filename TEXT NOT NULL DEFAULT '',
                content_sha256 TEXT NOT NULL UNIQUE,
                size_bytes INTEGER NOT NULL DEFAULT 0,
                extracted_text TEXT NOT NULL,
                suggestions_json TEXT NOT NULL DEFAULT '{}',
                status TEXT NOT NULL DEFAULT 'pending' CHECK (status IN ('pending', 'applied')),
                base_profile_updated_at TEXT NOT NULL,
                created_at TEXT NOT NULL,
                applied_at TEXT
            );
            CREATE INDEX IF NOT EXISTS profile_imports_created_idx ON profile_imports(created_at DESC);
            """
        )

    def _migrate_to_v3(self, connection: sqlite3.Connection) -> None:
        self._add_column_if_missing(
            connection, "profile_imports", "extraction_method", "TEXT NOT NULL DEFAULT 'embedded_text'"
        )
        self._add_column_if_missing(connection, "profile_imports", "ocr_pages", "INTEGER NOT NULL DEFAULT 0")
        self._add_column_if_missing(
            connection, "profile_imports", "ocr_warnings_json", "TEXT NOT NULL DEFAULT '[]'"
        )

    def _migrate_to_v4(self, connection: sqlite3.Connection) -> None:
        connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS career_intake (
                id INTEGER PRIMARY KEY CHECK (id = 1),
                step_index INTEGER NOT NULL DEFAULT 0 CHECK (step_index >= 0 AND step_index <= 6),
                answers_json TEXT NOT NULL DEFAULT '{}',
                completed INTEGER NOT NULL DEFAULT 0 CHECK (completed IN (0, 1)),
                updated_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS application_drafts (
                id TEXT PRIMARY KEY,
                job_id TEXT NOT NULL REFERENCES jobs(id) ON DELETE CASCADE,
                language TEXT NOT NULL,
                variant TEXT NOT NULL DEFAULT '',
                generation_mode TEXT NOT NULL CHECK (generation_mode IN ('local', 'ai')),
                provider TEXT NOT NULL DEFAULT 'Local',
                cv_markdown TEXT NOT NULL,
                letter_markdown TEXT NOT NULL,
                checks_json TEXT NOT NULL DEFAULT '[]',
                profile_updated_at TEXT NOT NULL,
                job_updated_at TEXT NOT NULL,
                created_at TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS application_drafts_job_idx ON application_drafts(job_id, created_at DESC);
            """
        )

    def _migrate_to_v5(self, connection: sqlite3.Connection) -> None:
        """Add public-board configuration without modifying existing jobs."""
        self._add_column_if_missing(
            connection, "jobs", "discovery_source_id", "TEXT NOT NULL DEFAULT ''"
        )
        self._add_column_if_missing(connection, "jobs", "last_seen_at", "TEXT NOT NULL DEFAULT ''")
        connection.executescript(
            """
            CREATE INDEX IF NOT EXISTS jobs_discovery_source_idx ON jobs(discovery_source_id, last_seen_at);

            CREATE TABLE IF NOT EXISTS discovery_sources (
                id TEXT PRIMARY KEY,
                provider TEXT NOT NULL CHECK (provider IN ('greenhouse')),
                company TEXT NOT NULL,
                board_token TEXT NOT NULL UNIQUE,
                enabled INTEGER NOT NULL DEFAULT 1 CHECK (enabled IN (0, 1)),
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                last_checked_at TEXT NOT NULL DEFAULT '',
                last_success_at TEXT NOT NULL DEFAULT '',
                last_error_code TEXT NOT NULL DEFAULT '',
                last_error_at TEXT NOT NULL DEFAULT ''
            );
            CREATE INDEX IF NOT EXISTS discovery_sources_enabled_idx ON discovery_sources(enabled, updated_at DESC);

            CREATE TABLE IF NOT EXISTS discovery_runs (
                id TEXT PRIMARY KEY,
                source_id TEXT NOT NULL,
                started_at TEXT NOT NULL,
                finished_at TEXT NOT NULL DEFAULT '',
                status TEXT NOT NULL CHECK (status IN ('running', 'success', 'partial', 'error', 'cached')),
                found_count INTEGER NOT NULL DEFAULT 0,
                imported_count INTEGER NOT NULL DEFAULT 0,
                updated_count INTEGER NOT NULL DEFAULT 0,
                skipped_count INTEGER NOT NULL DEFAULT 0,
                message TEXT NOT NULL DEFAULT ''
            );
            CREATE INDEX IF NOT EXISTS discovery_runs_source_idx ON discovery_runs(source_id, started_at DESC);
            """
        )

    def _migrate_to_v6(self, connection: sqlite3.Connection) -> None:
        """Add local interview history without modifying existing Career data."""
        connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS interview_sessions (
                id TEXT PRIMARY KEY,
                application_id TEXT NOT NULL DEFAULT '',
                job_id TEXT NOT NULL DEFAULT '',
                mode TEXT NOT NULL,
                difficulty TEXT NOT NULL,
                language TEXT NOT NULL,
                status TEXT NOT NULL CHECK (status IN ('active', 'completed', 'archived')),
                current_question_json TEXT NOT NULL DEFAULT '{}',
                turns_json TEXT NOT NULL DEFAULT '[]',
                started_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                completed_at TEXT NOT NULL DEFAULT ''
            );
            CREATE INDEX IF NOT EXISTS interview_sessions_updated_idx ON interview_sessions(status, updated_at DESC);
            CREATE INDEX IF NOT EXISTS interview_sessions_job_idx ON interview_sessions(job_id, updated_at DESC);
            """
        )

    @staticmethod
    def _migrate_to_v8(connection: sqlite3.Connection) -> None:
        """Add derived qualification snapshots without rewriting source facts."""
        connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS job_qualification_snapshots (
                job_id TEXT PRIMARY KEY REFERENCES jobs(id) ON DELETE CASCADE,
                schema_version INTEGER NOT NULL,
                facts_json TEXT NOT NULL DEFAULT '{}',
                provenance_json TEXT NOT NULL DEFAULT '{}',
                missing_fields_json TEXT NOT NULL DEFAULT '[]',
                reasons_json TEXT NOT NULL DEFAULT '[]',
                source_fingerprint TEXT NOT NULL DEFAULT '',
                updated_at TEXT NOT NULL
            );
            """
        )

    def _seed_defaults(self, connection: sqlite3.Connection) -> None:
        now = utc_now()
        connection.execute(
            """
            INSERT OR IGNORE INTO candidate_profile
                (id, display_name, education, skills, languages, eligibility, target_companies, notes, updated_at)
            VALUES (1, '', '', '', '', 'unknown', '', '', ?)
            """,
            (now,),
        )
        # The six requested career families deliberately start at equal weight.
        # A priority is only a user-controlled display/tie-break preference in
        # Initial tracker behaviour; it is not yet a hidden scoring weight.
        for label in JOB_FAMILIES:
            connection.execute(
                """
                INSERT OR IGNORE INTO preference_items (kind, item_key, label, enabled, priority, scope)
                VALUES ('family', ?, ?, 1, ?, 'primary')
                """,
                (self._preference_key(label), label, 100),
            )
        # The six named cities are equally primary. "Other Europe" is visible
        # but starts as the separate, secondary option requested in the brief.
        for item_key, label, scope in PRIMARY_LOCATIONS:
            connection.execute(
                """
                INSERT OR IGNORE INTO preference_items (kind, item_key, label, enabled, priority, scope)
                VALUES ('location', ?, ?, 1, ?, ?)
                """,
                (item_key, label, 50 if scope == "secondary" else 100, scope),
            )
        defaults = {
            "availability_start": "2027-01-01",
            "availability_end": "2027-06-30",
            "minimum_duration_months": "3",
            "maximum_duration_months": "6",
        }
        for key, value in defaults.items():
            connection.execute(
                "INSERT OR IGNORE INTO career_settings (setting_key, setting_value) VALUES (?, ?)",
                (key, value),
            )
        connection.execute(
            """
            INSERT OR IGNORE INTO career_intake (id, step_index, answers_json, completed, updated_at)
            VALUES (1, 0, '{}', 0, ?)
            """,
            (now,),
        )

    @staticmethod
    def _preference_key(label: str) -> str:
        return "-".join(clean_text(label).lower().replace("&", "and").replace("/", " ").split())

    def _audit(self, connection: sqlite3.Connection, action: str, subject_type: str, subject_id: str) -> None:
        connection.execute(
            "INSERT INTO career_audit_log (id, action, subject_type, subject_id, created_at) VALUES (?, ?, ?, ?, ?)",
            (f"audit_{uuid.uuid4().hex}", action, subject_type, subject_id, utc_now()),
        )

    @staticmethod
    def _row_dict(row: sqlite3.Row | None) -> dict[str, Any]:
        return dict(row) if row else {}

    def get_profile(self) -> dict[str, Any]:
        with self._lock, self._connection() as connection:
            profile = self._row_dict(connection.execute("SELECT * FROM candidate_profile WHERE id = 1").fetchone())
        # Work authorization is deliberately a user-declared field. No location,
        # school, language or other profile fact changes its value automatically.
        profile["readiness"] = assess_profile_readiness(profile)
        return profile

    def update_profile(self, payload: dict[str, Any]) -> dict[str, Any]:
        allowed_eligibility = {"unknown", "compatible", "incompatible"}
        values = self._clean_profile_editable_fields(payload)
        values.update(
            {
            "eligibility": validate_choice(
                payload.get("eligibility"), allowed_eligibility, "L’éligibilité", "unknown"
            ),
            "target_companies": clean_text(payload.get("target_companies"), limit=2_000),
            "notes": clean_text(payload.get("notes"), limit=4_000),
            }
        )
        with self._lock, self._connection() as connection:
            connection.execute(
                """
                UPDATE candidate_profile SET
                    display_name = :display_name, contact_email = :contact_email,
                    contact_phone = :contact_phone, linkedin_url = :linkedin_url,
                    education = :education, experience = :experience, skills = :skills,
                    languages = :languages, eligibility = :eligibility,
                    target_companies = :target_companies, notes = :notes, updated_at = :updated_at
                WHERE id = 1
                """,
                values | {"updated_at": utc_now()},
            )
            self._audit(connection, "profile_updated", "profile", "1")
        return self.get_profile()

    @staticmethod
    def _clean_linkedin_url(value: Any) -> str:
        raw = clean_text(value, limit=PROFILE_FIELD_LIMITS["linkedin_url"])
        if not raw:
            return ""
        try:
            canonical = canonical_url(raw)
        except UserFacingError as error:
            raise UserFacingError("L’URL LinkedIn doit être une URL publique http(s) valide.") from error
        hostname = (urllib.parse.urlsplit(canonical).hostname or "").lower()
        if hostname != "linkedin.com" and not hostname.endswith(".linkedin.com"):
            raise UserFacingError("L’URL de profil doit pointer vers linkedin.com.")
        return canonical

    def _clean_profile_editable_fields(self, payload: dict[str, Any]) -> dict[str, str]:
        values: dict[str, str] = {}
        for field in PROFILE_EDITABLE_FIELDS:
            values[field] = self._clean_profile_editable_value(field, payload.get(field))
        return values

    def _clean_profile_editable_value(self, field: str, value: Any) -> str:
        if field not in PROFILE_EDITABLE_FIELDS:
            raise UserFacingError("Ce champ ne peut pas être modifié depuis un document de profil.")
        if field == "linkedin_url":
            return self._clean_linkedin_url(value)
        return clean_text(value, limit=PROFILE_FIELD_LIMITS[field])

    def profile_upload_temp_path(self) -> Path:
        """Return a private, opaque temporary location for one browser upload."""
        return self.documents_dir / f".profile-upload-{uuid.uuid4().hex}.part"

    @staticmethod
    def _safe_profile_source_name(raw_name: str | None, *, fallback: str) -> str:
        name = Path(raw_name or fallback).name
        name = "".join(character for character in name if ord(character) >= 32).strip().lstrip(".")
        if not name or name in {".", ".."}:
            return fallback
        return name[:180]

    @staticmethod
    def _validate_profile_import_kind(source_kind: Any) -> str:
        kind = clean_text(source_kind, limit=40)
        if kind not in PROFILE_IMPORT_KINDS:
            raise UserFacingError("Le type de source de profil est inconnu.")
        return kind

    def _find_profile_import_by_hash(self, content_sha256: str, *, reopen_pending: bool = False) -> dict[str, Any] | None:
        with self._lock, self._connection() as connection:
            row = connection.execute(
                "SELECT id, status FROM profile_imports WHERE content_sha256 = ?", (content_sha256,)
            ).fetchone()
            if row and reopen_pending and str(row["status"]) == "pending":
                profile = connection.execute("SELECT updated_at FROM candidate_profile WHERE id = 1").fetchone()
                connection.execute(
                    "UPDATE profile_imports SET base_profile_updated_at = ? WHERE id = ?",
                    (str(profile["updated_at"]), str(row["id"])),
                )
                self._audit(connection, "profile_import_reopened", "profile_import", str(row["id"]))
        return self.get_profile_import(str(row["id"])) if row else None

    def import_profile_document(
        self,
        *,
        source_kind: str,
        original_name: str | None,
        temporary_path: Path,
        content_sha256: str,
        size_bytes: int,
    ) -> dict[str, Any]:
        """Turn one uploaded local CV/profile into a reviewable draft.

        ``temporary_path`` must already be an opaque file under
        ``career_data/documents``. It is never copied to the normal V3
        workspace, and it is deleted if extraction or validation fails.
        """
        kind = self._validate_profile_import_kind(source_kind)
        safe_name = self._safe_profile_source_name(original_name, fallback="document-profil")
        suffix = Path(safe_name).suffix.lower()
        if suffix not in ALLOWED_PROFILE_SUFFIXES:
            raise UserFacingError("Le profil doit être un PDF, DOCX, TXT ou Markdown.")
        if not content_sha256 or len(content_sha256) != 64:
            raise UserFacingError("Le document de profil est invalide.")
        if not isinstance(size_bytes, int) or not 0 < size_bytes <= MAX_PROFILE_IMPORT_BYTES:
            raise UserFacingError("Document de profil trop volumineux (maximum 10 Mo).")
        temporary = temporary_path.resolve()
        if temporary.parent != self.documents_dir.resolve() or temporary.suffix != ".part" or not temporary.is_file():
            raise UserFacingError("Import de document de profil invalide.")
        if temporary.stat().st_size != size_bytes:
            raise UserFacingError("Le document de profil est incomplet ou invalide.")

        duplicate = self._find_profile_import_by_hash(content_sha256, reopen_pending=True)
        if duplicate:
            temporary.unlink(missing_ok=True)
            duplicate["duplicate"] = True
            return duplicate

        destination = self.documents_dir / f"profile_{uuid.uuid4().hex}{suffix}"
        try:
            # A text file containing NUL bytes is not a useful CV source and
            # can otherwise render inconsistently across platforms.
            with temporary.open("rb") as source:
                signature = source.read(8_192)
            if suffix == ".pdf" and not signature.startswith(b"%PDF-"):
                raise UserFacingError("Le fichier PDF de profil est invalide.")
            if suffix in {".txt", ".md"} and b"\x00" in signature:
                raise UserFacingError("Le document texte de profil semble binaire.")
            temporary.replace(destination)
            try:
                os.chmod(destination, 0o600)
            except OSError:
                pass
            extraction_method = "embedded_text"
            ocr_pages = 0
            ocr_warnings: list[str] = []
            try:
                if suffix == ".md":
                    # The quality parser intentionally accepts only PDF,
                    # DOCX, and TXT. Preserve Markdown support from the
                    # profile-import contract through the local text reader.
                    text = extract_text(destination).strip()
                else:
                    # PDFs use coordinate-aware Canva reading order; DOCX/TXT
                    # retain the same local quality parser for extraction.
                    doc_input = extract_text_from_file(destination)
                    text = doc_input.text.strip()
                    extraction_method = f"cv_quality_{doc_input.filetype}"
            except (UserFacingError, ValueError, FileNotFoundError):
                # A scanned PDF often raises the same user-facing extraction
                # error as a text-less PDF. It is safe to try on-device OCR
                # only for the private file just uploaded by this endpoint.
                text = ""
            if suffix == ".pdf" and len(text) < 120:
                ocr_result: OCRResult = self.ocr.extract_pdf(destination)
                text = ocr_result.text
                extraction_method = ocr_result.engine
                ocr_pages = ocr_result.pages
                ocr_warnings = list(ocr_result.warnings)
            if not text:
                raise UserFacingError(
                    "Le document ne contient pas de texte exploitable. Essaie un PDF plus net, un DOCX ou colle le texte."
                )
            result = self._create_profile_import(
                source_kind=kind,
                original_name=safe_name,
                stored_filename=destination.name,
                content_sha256=content_sha256,
                size_bytes=size_bytes,
                extracted_text=text,
                extraction_method=extraction_method,
                ocr_pages=ocr_pages,
                ocr_warnings=ocr_warnings,
            )
            result.setdefault("duplicate", False)
            return result
        except Exception:
            destination.unlink(missing_ok=True)
            raise
        finally:
            temporary.unlink(missing_ok=True)

    def import_profile_text(
        self,
        *,
        source_kind: str,
        text: Any,
        original_name: str | None = None,
    ) -> dict[str, Any]:
        """Create a private draft from text the person pasted themselves."""
        kind = self._validate_profile_import_kind(source_kind)
        raw_text = str(text or "").replace("\x00", "").strip()
        if not raw_text:
            raise UserFacingError("Colle le texte du profil ou de l’export avant de l’importer.")
        if len(raw_text) > MAX_PROFILE_PASTED_CHARS:
            raise UserFacingError("Le texte de profil est trop long (maximum 100 000 caractères).")
        encoded = raw_text.encode("utf-8")
        content_sha256 = hashlib.sha256(encoded).hexdigest()
        duplicate = self._find_profile_import_by_hash(content_sha256, reopen_pending=True)
        if duplicate:
            duplicate["duplicate"] = True
            return duplicate
        result = self._create_profile_import(
            source_kind=kind,
            original_name=self._safe_profile_source_name(original_name, fallback="texte-profil"),
            stored_filename="",
            content_sha256=content_sha256,
            size_bytes=len(encoded),
            extracted_text=raw_text,
        )
        result["duplicate"] = False
        return result

    def _create_profile_import(
        self,
        *,
        source_kind: str,
        original_name: str,
        stored_filename: str,
        content_sha256: str,
        size_bytes: int,
        extracted_text: str,
        extraction_method: str = "embedded_text",
        ocr_pages: int = 0,
        ocr_warnings: list[str] | None = None,
    ) -> dict[str, Any]:
        suggestions = parse_profile_text(extracted_text)
        if ocr_warnings:
            existing_warnings = suggestions.get("warnings", [])
            if not isinstance(existing_warnings, list):
                existing_warnings = []
            suggestions["warnings"] = [
                *[clean_text(item, limit=300) for item in existing_warnings if clean_text(item, limit=300)],
                *[clean_text(item, limit=300) for item in ocr_warnings if clean_text(item, limit=300)],
            ][:8]
        import_id = f"profile_import_{uuid.uuid4().hex}"
        now = utc_now()
        with self._lock, self._connection() as connection:
            existing = connection.execute(
                "SELECT id FROM profile_imports WHERE content_sha256 = ?", (content_sha256,)
            ).fetchone()
            if existing:
                if stored_filename:
                    self._profile_document_path(stored_filename).unlink(missing_ok=True)
                result = self.get_profile_import(str(existing["id"]))
                result["duplicate"] = True
                return result
            profile_row = connection.execute(
                "SELECT updated_at FROM candidate_profile WHERE id = 1"
            ).fetchone()
            connection.execute(
                """
                INSERT INTO profile_imports (
                    id, source_kind, original_name, stored_filename, content_sha256,
                    size_bytes, extracted_text, extraction_method, ocr_pages,
                    ocr_warnings_json, suggestions_json, status,
                    base_profile_updated_at, created_at, applied_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'pending', ?, ?, NULL)
                """,
                (
                    import_id,
                    source_kind,
                    original_name,
                    stored_filename,
                    content_sha256,
                    size_bytes,
                    extracted_text,
                    clean_text(extraction_method, limit=40) or "embedded_text",
                    max(0, min(int(ocr_pages), 12)),
                    json.dumps([clean_text(item, limit=300) for item in (ocr_warnings or []) if clean_text(item, limit=300)][:4], ensure_ascii=False),
                    json.dumps(suggestions, ensure_ascii=False),
                    str(profile_row["updated_at"]),
                    now,
                ),
            )
            self._audit(connection, "profile_import_created", "profile_import", import_id)
        return self.get_profile_import(import_id)

    def _profile_document_path(self, stored_filename: str) -> Path:
        if not stored_filename:
            return self.documents_dir / ".missing"
        candidate = (self.documents_dir / Path(stored_filename).name).resolve()
        if candidate.parent != self.documents_dir.resolve() or candidate.name != stored_filename:
            raise UserFacingError("Document de profil introuvable.")
        return candidate

    @staticmethod
    def _import_suggestions(value: str) -> dict[str, Any]:
        try:
            parsed = json.loads(value or "{}")
        except json.JSONDecodeError:
            return {"values": {}, "warnings": ["Les suggestions de ce document ne sont plus lisibles."]}
        return parsed if isinstance(parsed, dict) else {"values": {}, "warnings": []}

    @staticmethod
    def _profile_preview(text: str) -> str:
        cleaned = clean_text(text, limit=5_000)
        return cleaned + ("\n\n[Extrait limité pour la relecture.]" if len(text) > len(cleaned) else "")

    def _serialize_profile_import(self, row: sqlite3.Row, *, include_preview: bool) -> dict[str, Any]:
        suggestions = self._import_suggestions(str(row["suggestions_json"]))
        values = suggestions.get("values", {})
        suggested_fields = [
            field for field in PROFILE_EDITABLE_FIELDS if isinstance(values, dict) and clean_text(values.get(field))
        ]
        result = {
            "id": row["id"],
            "source_kind": row["source_kind"],
            "original_name": row["original_name"],
            "has_local_file": bool(row["stored_filename"]),
            "size_bytes": int(row["size_bytes"]),
            "extraction_method": row["extraction_method"] if "extraction_method" in row.keys() else "embedded_text",
            "ocr_pages": int(row["ocr_pages"] or 0) if "ocr_pages" in row.keys() else 0,
            "ocr_warnings": self._ocr_warnings(row["ocr_warnings_json"]) if "ocr_warnings_json" in row.keys() else [],
            "status": row["status"],
            "base_profile_updated_at": row["base_profile_updated_at"],
            "created_at": row["created_at"],
            "applied_at": row["applied_at"],
            "suggestions": suggestions,
            "suggested_fields": suggested_fields,
        }
        if include_preview:
            extracted_text = str(row["extracted_text"])
            result["preview"] = self._profile_preview(extracted_text)
            if str(row["source_kind"]) == "cv":
                # Reuse the existing deterministic CV-quality engine on the
                # text that was already extracted locally. Only actionable
                # messages and aggregate counts leave this private boundary;
                # source excerpts are deliberately not repeated in the API.
                from .cv_quality import DocumentInput, STATUS_INFO, STATUS_RISK, analyze_cv

                suffix = Path(str(row["original_name"] or "cv.txt")).suffix.lower().lstrip(".")
                filetype = suffix if suffix in {"pdf", "docx", "txt"} else "txt"
                analysis = analyze_cv(
                    DocumentInput(
                        text=extracted_text,
                        filename=str(row["original_name"] or "cv"),
                        filetype=filetype,
                        page_count=int(row["ocr_pages"] or 0) or None,
                    )
                )
                risks = [item for item in analysis.findings if item.status == STATUS_RISK]
                information = [item for item in analysis.findings if item.status == STATUS_INFO]
                result["cv_quality"] = {
                    "status": "action_required" if risks else "review_recommended" if information else "no_structural_risk_detected",
                    "risk_count": len(risks),
                    "information_count": len(information),
                    "detected_sections": [item.title for item in analysis.sections],
                    "detected_experiences": len(analysis.experiences),
                    "actions": [
                        {"code": item.code, "priority": "high", "message": item.message}
                        for item in risks[:8]
                    ] + [
                        {"code": item.code, "priority": "review", "message": item.message}
                        for item in information[:4]
                    ],
                    "disclaimer": (
                        "Diagnostic structurel local : il signale des risques ATS, pas une note de recrutement. "
                        "Vérifie visuellement le PDF avant toute candidature."
                    ),
                }
        return result

    @staticmethod
    def _ocr_warnings(value: str) -> list[str]:
        try:
            parsed = json.loads(value or "[]")
        except json.JSONDecodeError:
            return []
        if not isinstance(parsed, list):
            return []
        return [clean_text(item, limit=300) for item in parsed if clean_text(item, limit=300)][:4]

    def list_profile_imports(self) -> list[dict[str, Any]]:
        with self._lock, self._connection() as connection:
            rows = connection.execute(
                "SELECT * FROM profile_imports ORDER BY created_at DESC"
            ).fetchall()
        return [self._serialize_profile_import(row, include_preview=False) for row in rows]

    def get_profile_import(self, import_id: str) -> dict[str, Any]:
        identifier = clean_text(import_id, limit=80)
        with self._lock, self._connection() as connection:
            row = connection.execute("SELECT * FROM profile_imports WHERE id = ?", (identifier,)).fetchone()
        if not row:
            raise UserFacingError("Cette importation de profil n’existe pas.")
        return self._serialize_profile_import(row, include_preview=True)

    def apply_profile_import(
        self,
        import_id: str,
        updates: list[dict[str, Any]],
        base_profile_updated_at: str = "",
    ) -> dict[str, Any]:
        if not isinstance(updates, list) or not updates:
            raise UserFacingError("Sélectionne au moins un champ de profil à appliquer.")
        if len(updates) > len(PROFILE_EDITABLE_FIELDS):
            raise UserFacingError("Trop de champs de profil ont été envoyés.")
        identifier = clean_text(import_id, limit=80)
        supplied_revision = clean_text(base_profile_updated_at, limit=64)
        with self._lock, self._connection() as connection:
            imported = connection.execute("SELECT * FROM profile_imports WHERE id = ?", (identifier,)).fetchone()
            if not imported:
                raise UserFacingError("Cette importation de profil n’existe pas.")
            if imported["status"] != "pending":
                raise UserFacingError("Cette importation a déjà été appliquée ou ne peut plus être modifiée.")
            profile = connection.execute("SELECT * FROM candidate_profile WHERE id = 1").fetchone()
            if supplied_revision and supplied_revision != imported["base_profile_updated_at"]:
                raise UserFacingError("La page de relecture est obsolète. Recharge l’import avant de l’appliquer.")
            if profile["updated_at"] != imported["base_profile_updated_at"]:
                raise UserFacingError(
                    "Le profil a été modifié depuis cette extraction. Recharge le document puis vérifie les propositions à nouveau."
                )
            seen: set[str] = set()
            changed: dict[str, str] = {}
            appendable = {"education", "experience", "skills", "languages"}
            for raw in updates:
                if not isinstance(raw, dict):
                    raise UserFacingError("Un champ de profil à appliquer est invalide.")
                field = clean_text(raw.get("field"), limit=80)
                mode = clean_text(raw.get("mode"), limit=20) or "replace"
                if field not in PROFILE_EDITABLE_FIELDS or field in seen:
                    raise UserFacingError("Un champ de profil à appliquer est invalide.")
                if mode not in {"replace", "append"} or (mode == "append" and field not in appendable):
                    raise UserFacingError("Le mode de mise à jour du profil est invalide.")
                value = self._clean_profile_editable_value(field, raw.get("value"))
                if not value:
                    raise UserFacingError("Un champ sélectionné ne peut pas être vide.")
                if mode == "append" and clean_text(profile[field], limit=PROFILE_FIELD_LIMITS[field]):
                    value = clean_text(
                        f"{profile[field]}\n{value}", limit=PROFILE_FIELD_LIMITS[field]
                    )
                changed[field] = value
                seen.add(field)
            now = utc_now()
            assignments = ", ".join(f"{field} = :{field}" for field in changed)
            connection.execute(
                f"UPDATE candidate_profile SET {assignments}, updated_at = :updated_at WHERE id = 1",
                changed | {"updated_at": now},
            )
            connection.execute(
                "UPDATE profile_imports SET status = 'applied', applied_at = ? WHERE id = ?",
                (now, identifier),
            )
            self._audit(connection, "profile_import_applied", "profile_import", identifier)
        return {"profile": self.get_profile(), "profile_import": self.get_profile_import(identifier)}

    def delete_profile_import(self, import_id: str) -> None:
        identifier = clean_text(import_id, limit=80)
        with self._lock, self._connection() as connection:
            row = connection.execute(
                "SELECT stored_filename FROM profile_imports WHERE id = ?", (identifier,)
            ).fetchone()
            if not row:
                raise UserFacingError("Cette importation de profil n’existe pas.")
            stored_filename = str(row["stored_filename"] or "")
            if stored_filename:
                try:
                    self._profile_document_path(stored_filename).unlink(missing_ok=True)
                except OSError as error:
                    raise UserFacingError("Le document de profil n’a pas pu être supprimé.") from error
            connection.execute("DELETE FROM profile_imports WHERE id = ?", (identifier,))
            self._audit(connection, "profile_import_deleted", "profile_import", identifier)

    @staticmethod
    def _intake_answers(value: str) -> dict[str, str]:
        try:
            decoded = json.loads(value or "{}")
        except json.JSONDecodeError:
            decoded = {}
        return normalize_answers(decoded)

    def _serialize_intake_row(self, row: sqlite3.Row) -> dict[str, Any]:
        return serialize_intake(
            step_index=int(row["step_index"]),
            answers=self._intake_answers(str(row["answers_json"])),
            updated_at=str(row["updated_at"]),
        )

    def get_intake(self) -> dict[str, Any]:
        with self._lock, self._connection() as connection:
            row = connection.execute("SELECT * FROM career_intake WHERE id = 1").fetchone()
        if not row:
            raise UserFacingError("Le mini-entretien Career local est indisponible.")
        return self._serialize_intake_row(row)

    def answer_intake(self, answer: Any) -> dict[str, Any]:
        with self._lock, self._connection() as connection:
            row = connection.execute("SELECT * FROM career_intake WHERE id = 1").fetchone()
            if not row:
                raise UserFacingError("Le mini-entretien Career local est indisponible.")
            answers, next_step = answer_for_step(
                self._intake_answers(str(row["answers_json"])), int(row["step_index"]), answer
            )
            now = utc_now()
            connection.execute(
                """
                UPDATE career_intake
                SET step_index = ?, answers_json = ?, completed = ?, updated_at = ?
                WHERE id = 1
                """,
                (next_step, json.dumps(answers, ensure_ascii=False), int(next_step >= 6), now),
            )
            self._audit(connection, "career_intake_answered", "career_intake", "1")
            result = serialize_intake(step_index=next_step, answers=answers, updated_at=now)
        return result

    def reset_intake(self) -> dict[str, Any]:
        now = utc_now()
        with self._lock, self._connection() as connection:
            connection.execute(
                "UPDATE career_intake SET step_index = 0, answers_json = '{}', completed = 0, updated_at = ? WHERE id = 1",
                (now,),
            )
            self._audit(connection, "career_intake_reset", "career_intake", "1")
        return self.get_intake()

    @staticmethod
    def _json_object(value: Any) -> dict[str, Any]:
        try:
            parsed = json.loads(str(value or "{}"))
        except json.JSONDecodeError:
            return {}
        return parsed if isinstance(parsed, dict) else {}

    @staticmethod
    def _interview_turns(value: Any) -> list[dict[str, Any]]:
        try:
            parsed = json.loads(str(value or "[]"))
        except json.JSONDecodeError:
            return []
        return [item for item in parsed if isinstance(item, dict)][:24] if isinstance(parsed, list) else []

    @staticmethod
    def _session_job_context(row: sqlite3.Row | dict[str, Any] | None) -> dict[str, Any]:
        if not row:
            return {}
        values = dict(row)
        return {
            "id": clean_text(values.get("job_id") or values.get("id"), limit=80),
            "company": clean_text(values.get("company"), limit=240),
            "title": clean_text(values.get("title"), limit=300),
        }

    def _serialize_interview_session(self, row: sqlite3.Row, *, include_turns: bool) -> dict[str, Any]:
        current = self._json_object(row["current_question_json"])
        turns = self._interview_turns(row["turns_json"])
        result: dict[str, Any] = {
            "id": row["id"],
            "application_id": row["application_id"],
            "job_id": row["job_id"],
            "company": row["company"] if "company" in row.keys() else "",
            "title": row["title"] if "title" in row.keys() else "",
            "mode": row["mode"],
            "difficulty": row["difficulty"],
            "language": row["language"],
            "status": row["status"],
            "current_question": current,
            "started_at": row["started_at"],
            "updated_at": row["updated_at"],
            "completed_at": row["completed_at"],
            "progress": progress_summary(turns),
        }
        if include_turns:
            result["turns"] = turns
        return result

    def _get_interview_session_row(self, connection: sqlite3.Connection, session_id: str) -> sqlite3.Row | None:
        return connection.execute(
            """
            SELECT interview_sessions.*, jobs.company, jobs.title
            FROM interview_sessions LEFT JOIN jobs ON jobs.id = interview_sessions.job_id
            WHERE interview_sessions.id = ?
            """,
            (session_id,),
        ).fetchone()

    def create_interview_session(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Start a local text-coach session; no provider call is made."""
        mode, difficulty, language = normalize_interview_config(
            payload.get("mode", "technical"),
            payload.get("difficulty", "intermediate"),
            payload.get("language", "fr"),
        )
        requested_job_id = clean_text(payload.get("job_id"), limit=80)
        requested_application_id = clean_text(payload.get("application_id"), limit=80)
        with self._lock, self._connection() as connection:
            job_context: dict[str, Any] = {}
            job_id = requested_job_id
            if requested_application_id:
                application = connection.execute(
                    "SELECT id, job_id FROM applications WHERE id = ?", (requested_application_id,)
                ).fetchone()
                if not application:
                    raise UserFacingError("Cette candidature Career n’existe pas.")
                if job_id and job_id != str(application["job_id"]):
                    raise UserFacingError("L’offre et la candidature sélectionnées ne correspondent pas.")
                job_id = str(application["job_id"])
            if job_id:
                job = connection.execute("SELECT id, company, title FROM jobs WHERE id = ?", (job_id,)).fetchone()
                if not job:
                    raise UserFacingError("Cette offre Career n’existe pas.")
                job_context = self._session_job_context(job)
            question = select_question(
                mode=mode, difficulty=difficulty, language=language, job=job_context
            )
            session_id = f"interview_{uuid.uuid4().hex}"
            now = utc_now()
            connection.execute(
                """
                INSERT INTO interview_sessions (
                    id, application_id, job_id, mode, difficulty, language, status,
                    current_question_json, turns_json, started_at, updated_at, completed_at
                ) VALUES (?, ?, ?, ?, ?, ?, 'active', ?, '[]', ?, ?, '')
                """,
                (
                    session_id,
                    requested_application_id,
                    job_id,
                    mode,
                    difficulty,
                    language,
                    json.dumps(question, ensure_ascii=False),
                    now,
                    now,
                ),
            )
            self._audit(connection, "interview_session_started", "interview_session", session_id)
        return self.get_interview_session(session_id)

    def list_interview_sessions(self, *, limit: int = 30) -> list[dict[str, Any]]:
        bounded_limit = self._bounded_int(limit, 1, 100, "La limite d’historique")
        with self._lock, self._connection() as connection:
            rows = connection.execute(
                """
                SELECT interview_sessions.*, jobs.company, jobs.title
                FROM interview_sessions LEFT JOIN jobs ON jobs.id = interview_sessions.job_id
                ORDER BY CASE interview_sessions.status WHEN 'active' THEN 0 ELSE 1 END,
                         interview_sessions.updated_at DESC
                LIMIT ?
                """,
                (bounded_limit,),
            ).fetchall()
        return [self._serialize_interview_session(row, include_turns=False) for row in rows]

    def get_interview_session(self, session_id: str) -> dict[str, Any]:
        identifier = clean_text(session_id, limit=80)
        with self._lock, self._connection() as connection:
            row = self._get_interview_session_row(connection, identifier)
        if not row:
            raise UserFacingError("Cette séance d’entretien n’existe pas.")
        return self._serialize_interview_session(row, include_turns=True)

    def answer_interview_session(self, session_id: str, answer: Any) -> dict[str, Any]:
        identifier = clean_text(session_id, limit=80)
        response = clean_text(answer, limit=6_000)
        if len(response) < 3:
            raise UserFacingError("Écris une réponse avant de demander le retour du coach.")
        with self._lock, self._connection() as connection:
            row = self._get_interview_session_row(connection, identifier)
            if not row:
                raise UserFacingError("Cette séance d’entretien n’existe pas.")
            if row["status"] != "active":
                raise UserFacingError("Cette séance est terminée. Démarre une nouvelle séance pour continuer.")
            turns = self._interview_turns(row["turns_json"])
            if len(turns) >= 20:
                raise UserFacingError("Cette séance a atteint 20 réponses. Termine-la puis démarre une nouvelle séance.")
            current = self._json_object(row["current_question_json"])
            question_id = clean_text(current.get("id"), limit=120)
            if not question_id:
                raise UserFacingError("La question active de cette séance est indisponible. Démarre une nouvelle séance.")
            feedback = evaluate_answer(question_id, response, row["language"])
            answered_at = utc_now()
            turns.append(
                {
                    "question": current,
                    "topic": current.get("topic", ""),
                    "answer": response,
                    "feedback": feedback,
                    "answered_at": answered_at,
                }
            )
            job_context = self._session_job_context(row)
            next_question = select_question(
                mode=str(row["mode"]),
                difficulty=str(row["difficulty"]),
                language=str(row["language"]),
                asked_ids=[turn.get("question", {}).get("id", "") for turn in turns],
                last_score=int(feedback["scores"]["overall"]),
                job=job_context,
            )
            connection.execute(
                """
                UPDATE interview_sessions
                SET current_question_json = ?, turns_json = ?, updated_at = ?
                WHERE id = ?
                """,
                (json.dumps(next_question, ensure_ascii=False), json.dumps(turns, ensure_ascii=False), answered_at, identifier),
            )
            self._audit(connection, "interview_answer_reviewed", "interview_session", identifier)
        return self.get_interview_session(identifier)

    def complete_interview_session(self, session_id: str) -> dict[str, Any]:
        identifier = clean_text(session_id, limit=80)
        now = utc_now()
        with self._lock, self._connection() as connection:
            result = connection.execute(
                """
                UPDATE interview_sessions SET status = 'completed', updated_at = ?, completed_at = ?
                WHERE id = ? AND status = 'active'
                """,
                (now, now, identifier),
            )
            if result.rowcount != 1:
                existing = connection.execute("SELECT id FROM interview_sessions WHERE id = ?", (identifier,)).fetchone()
                if not existing:
                    raise UserFacingError("Cette séance d’entretien n’existe pas.")
                raise UserFacingError("Cette séance est déjà terminée.")
            self._audit(connection, "interview_session_completed", "interview_session", identifier)
        return self.get_interview_session(identifier)

    def delete_interview_session(self, session_id: str) -> None:
        identifier = clean_text(session_id, limit=80)
        with self._lock, self._connection() as connection:
            result = connection.execute("DELETE FROM interview_sessions WHERE id = ?", (identifier,))
            if result.rowcount != 1:
                raise UserFacingError("Cette séance d’entretien n’existe pas.")
            self._audit(connection, "interview_session_deleted", "interview_session", identifier)

    def _application_context(self, job_id: str, language: Any) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any], str]:
        identifier = clean_text(job_id, limit=80)
        normalized_language = normalize_language(language)
        with self._lock, self._connection() as connection:
            profile = self._row_dict(connection.execute("SELECT * FROM candidate_profile WHERE id = 1").fetchone())
            intake_row = connection.execute("SELECT * FROM career_intake WHERE id = 1").fetchone()
            job_row = connection.execute("SELECT * FROM jobs WHERE id = ?", (identifier,)).fetchone()
            snapshot = offer_intelligence_store.load_snapshot(connection, identifier)
        if not job_row:
            raise UserFacingError("Cette offre Career n’existe pas.")
        if not intake_row:
            raise UserFacingError("Le mini-entretien Career local est indisponible.")
        job = dict(job_row)
        if snapshot:
            # The CV and the cover letter quote the same canonical
            # requirements as every other screen of the workspace.
            job["offer_intelligence"] = snapshot
        return profile, self._serialize_intake_row(intake_row), job, normalized_language

    def create_application_draft(
        self,
        job_id: str,
        language: Any,
        *,
        use_ai: bool = False,
        ai_generator: Any | None = None,
        variant: str = "",
    ) -> dict[str, Any]:
        """Create a saved CV/letter draft from a selected local offer.

        In the default mode this never leaves the Mac.  The optional callback
        is deliberately injected by the web route only after that route has
        checked an explicit user consent checkbox.
        """
        profile, intake, job, normalized_language = self._application_context(job_id, language)
        local_draft = build_local_application_draft(profile, intake, job, normalized_language)
        draft: ApplicationDraft = local_draft
        generation_mode = "local"
        provider = "Local · gabarit factuel"
        if use_ai:
            if not callable(ai_generator):
                raise UserFacingError("Le mode IA n’est pas configuré. Utilise le brouillon local ou configure un fournisseur.")
            result = ai_generator(build_ai_prompt(profile, intake, job, normalized_language))
            if not isinstance(result, dict):
                raise UserFacingError("Le fournisseur IA a renvoyé un résultat invalide.")
            draft = parse_ai_draft(result.get("text", ""), normalized_language)
            generation_mode = "ai"
            provider = clean_text(result.get("provider"), limit=160) or "Fournisseur IA configuré"

        draft_id = f"draft_{uuid.uuid4().hex}"
        now = utc_now()
        with self._lock, self._connection() as connection:
            # Re-check the selected offer right before saving so a deleted job
            # cannot leave a detached document behind.
            current_job = connection.execute(
                "SELECT updated_at FROM jobs WHERE id = ?", (str(job["id"]),)
            ).fetchone()
            current_profile = connection.execute("SELECT updated_at FROM candidate_profile WHERE id = 1").fetchone()
            if not current_job or not current_profile:
                raise UserFacingError("L’offre ou le profil a changé pendant la préparation du brouillon. Réessaie.")
            if (
                str(current_job["updated_at"]) != str(job["updated_at"])
                or str(current_profile["updated_at"]) != str(profile["updated_at"])
            ):
                raise UserFacingError("L’offre ou le profil a changé pendant la préparation du brouillon. Réessaie.")
            connection.execute(
                """
                INSERT INTO application_drafts (
                    id, job_id, language, variant, generation_mode, provider, cv_markdown,
                    letter_markdown, checks_json, profile_updated_at, job_updated_at, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    draft_id,
                    str(job["id"]),
                    draft.language,
                    variant,
                    generation_mode,
                    provider,
                    draft.cv_markdown,
                    draft.letter_markdown,
                    json.dumps(draft.checks, ensure_ascii=False),
                    str(current_profile["updated_at"]),
                    str(current_job["updated_at"]),
                    now,
                ),
            )
            self._audit(connection, f"application_draft_created_{generation_mode}", "application_draft", draft_id)
        return self.get_application_draft(draft_id)

    @staticmethod
    def _draft_checks(value: str) -> list[str]:
        try:
            parsed = json.loads(value or "[]")
        except json.JSONDecodeError:
            return []
        return [clean_text(item, limit=500) for item in parsed if clean_text(item, limit=500)][:6] if isinstance(parsed, list) else []

    def _serialize_application_draft(self, row: sqlite3.Row, *, include_content: bool) -> dict[str, Any]:
        result = {
            "id": row["id"],
            "job_id": row["job_id"],
            "company": row["company"],
            "title": row["title"],
            "language": row["language"],
            "variant": row["variant"] if "variant" in row.keys() else "",
            "generation_mode": row["generation_mode"],
            "provider": row["provider"],
            "checks": self._draft_checks(str(row["checks_json"])),
            "profile_updated_at": row["profile_updated_at"],
            "job_updated_at": row["job_updated_at"],
            "created_at": row["created_at"],
        }
        if include_content:
            result["cv_markdown"] = row["cv_markdown"]
            result["letter_markdown"] = row["letter_markdown"]
        return result

    def list_application_drafts(self) -> list[dict[str, Any]]:
        with self._lock, self._connection() as connection:
            rows = connection.execute(
                """
                SELECT application_drafts.*, jobs.company, jobs.title
                FROM application_drafts JOIN jobs ON jobs.id = application_drafts.job_id
                ORDER BY application_drafts.created_at DESC
                """
            ).fetchall()
        return [self._serialize_application_draft(row, include_content=False) for row in rows]

    def get_application_draft(self, draft_id: str) -> dict[str, Any]:
        identifier = clean_text(draft_id, limit=80)
        with self._lock, self._connection() as connection:
            row = connection.execute(
                """
                SELECT application_drafts.*, jobs.company, jobs.title
                FROM application_drafts JOIN jobs ON jobs.id = application_drafts.job_id
                WHERE application_drafts.id = ?
                """,
                (identifier,),
            ).fetchone()
        if not row:
            raise UserFacingError("Ce brouillon de candidature n’existe pas.")
        return self._serialize_application_draft(row, include_content=True)

    def delete_application_draft(self, draft_id: str) -> None:
        identifier = clean_text(draft_id, limit=80)
        with self._lock, self._connection() as connection:
            result = connection.execute("DELETE FROM application_drafts WHERE id = ?", (identifier,))
            if result.rowcount != 1:
                raise UserFacingError("Ce brouillon de candidature n’existe pas.")
            self._audit(connection, "application_draft_deleted", "application_draft", identifier)

    def export_application_draft(self, draft_id: str, kind: str, export_format: str) -> Path:
        if kind not in {"cv", "letter"}:
            raise UserFacingError("Type de document de candidature inconnu.")
        if export_format not in {"md", "html", "docx", "pdf"}:
            raise UserFacingError("Format de brouillon non pris en charge. Choisis Markdown, HTML, Word ou PDF.")
        draft = self.get_application_draft(draft_id)
        content = str(draft[f"{kind}_markdown"])
        safe_company = re_sub_filename(str(draft["company"]))
        safe_title = re_sub_filename(str(draft["title"]))
        prefix = "cv" if kind == "cv" else "lettre"
        target = self.studio_dir / f"{prefix}_{safe_company}_{safe_title}_{uuid.uuid4().hex[:8]}.{export_format}"
        if export_format == "md":
            target.write_text(content, encoding="utf-8")
        elif export_format == "html":
            document_title = f"{prefix.upper()} — {draft['title']} — {draft['company']}"
            target.write_text(
                render_application_html(title=document_title, markdown=content, language=str(draft["language"])),
                encoding="utf-8",
            )
        else:
            document_title = f"{prefix.upper()} — {draft['title']} — {draft['company']}"
            try:
                if export_format == "docx":
                    write_docx(
                        markdown=content,
                        title=document_title,
                        language=str(draft["language"]),
                        target=target,
                    )
                else:
                    write_pdf(
                        markdown=content,
                        title=document_title,
                        language=str(draft["language"]),
                        target=target,
                    )
            except Exception as error:
                target.unlink(missing_ok=True)
                raise UserFacingError("Le document de candidature n’a pas pu être généré localement.") from error
        try:
            os.chmod(target, 0o600)
        except OSError:
            pass
        with self._lock, self._connection() as connection:
            self._audit(connection, f"application_draft_exported_{kind}_{export_format}", "application_draft", str(draft["id"]))
        return target

    def update_application_draft(self, draft_id: str, cv_markdown: Any, letter_markdown: Any) -> dict[str, Any]:
        """Apply one explicit user edit to a saved draft before any export.

        The correction stays fully local: the same bounded, text-only parsing
        powers the later DOCX/PDF exports, so the saved version is always what
        the person last reviewed.
        """
        identifier = clean_text(draft_id, limit=80)
        cv = clean_text(cv_markdown, limit=MAX_DRAFT_CHARS)
        letter = clean_text(letter_markdown, limit=MAX_DRAFT_CHARS)
        if not cv:
            raise UserFacingError("Le CV corrigé ne peut pas être vide.")
        if not letter:
            raise UserFacingError("La lettre corrigée ne peut pas être vide.")
        with self._lock, self._connection() as connection:
            result = connection.execute(
                "UPDATE application_drafts SET cv_markdown = ?, letter_markdown = ? WHERE id = ?",
                (cv, letter, identifier),
            )
            if result.rowcount != 1:
                raise UserFacingError("Ce brouillon de candidature n’existe pas.")
            self._audit(connection, "application_draft_edited", "application_draft", identifier)
        return self.get_application_draft(identifier)

    def get_preferences(self) -> dict[str, Any]:
        with self._lock, self._connection() as connection:
            rows = connection.execute(
                "SELECT kind, item_key, label, enabled, priority, scope FROM preference_items ORDER BY kind, priority DESC, label"
            ).fetchall()
            settings = {
                row["setting_key"]: row["setting_value"]
                for row in connection.execute("SELECT setting_key, setting_value FROM career_settings").fetchall()
            }
        return self._serialize_preferences(rows, settings)

    @staticmethod
    def _serialize_preferences(
        rows: list[sqlite3.Row], settings: dict[str, str],
    ) -> dict[str, Any]:
        items = {
            "family": [],
            "location": [],
        }
        for row in rows:
            items[str(row["kind"])].append(
                {
                    "key": row["item_key"],
                    "label": row["label"],
                    "enabled": bool(row["enabled"]),
                    "priority": int(row["priority"]),
                    "scope": row["scope"],
                }
            )
        return {
            "availability": dict(settings),
            "families": items["family"],
            "locations": items["location"],
        }

    @staticmethod
    def _availability_values(settings: dict[str, Any]) -> dict[str, Any]:
        """Validate the editable, local availability settings once."""
        start = parse_date(settings.get("availability_start", "2027-01-01"), "La disponibilité de début")
        end = parse_date(settings.get("availability_end", "2027-06-30"), "La disponibilité de fin")
        if not start or not end or end < start:
            raise UserFacingError("La disponibilité de fin doit être postérieure à la disponibilité de début.")
        minimum = CareerService._bounded_int(
            settings.get("minimum_duration_months", 3), 1, 24, "La durée minimale"
        )
        maximum = CareerService._bounded_int(
            settings.get("maximum_duration_months", 6), 1, 24, "La durée maximale"
        )
        if minimum > maximum:
            raise UserFacingError("La durée minimale ne peut pas dépasser la durée maximale.")
        return {
            "availability_start": start,
            "availability_end": end,
            "minimum_duration_months": minimum,
            "maximum_duration_months": maximum,
        }

    def _current_availability_values(self) -> dict[str, Any]:
        with self._lock, self._connection() as connection:
            settings = {
                row["setting_key"]: row["setting_value"]
                for row in connection.execute("SELECT setting_key, setting_value FROM career_settings").fetchall()
            }
        return self._availability_values(settings)

    @staticmethod
    def _calendar_assessment(payload: dict[str, Any], availability: dict[str, Any]) -> dict[str, Any]:
        return availability_assessment(
            start_date=clean_text(payload.get("start_date")) or None,
            end_date=clean_text(payload.get("end_date")) or None,
            duration_months=payload.get("duration_months"),
            **availability,
        )

    def _refresh_job_availability(self, connection: sqlite3.Connection, availability: dict[str, Any]) -> None:
        """Re-score factual calendars when the user's availability changes."""
        rows = connection.execute(
            "SELECT id, start_date, end_date, duration_months FROM jobs"
        ).fetchall()
        now = utc_now()
        for row in rows:
            assessment = self._calendar_assessment(dict(row), availability)
            connection.execute(
                """
                UPDATE jobs SET calendar_status = ?, calendar_reasons_json = ?, updated_at = ? WHERE id = ?
                """,
                (
                    assessment["status"],
                    json.dumps(assessment["reasons"], ensure_ascii=False),
                    now,
                    row["id"],
                ),
            )

    def update_preferences(self, payload: dict[str, Any]) -> dict[str, Any]:
        families = payload.get("families", [])
        locations = payload.get("locations", [])
        if not isinstance(families, list) or not isinstance(locations, list):
            raise UserFacingError("Les préférences Career sont invalides.")
        settings = payload.get("availability", {})
        if not isinstance(settings, dict):
            raise UserFacingError("La disponibilité Career est invalide.")
        availability = self._availability_values(settings)
        with self._lock, self._connection() as connection:
            self._replace_preferences(
                connection,
                "family",
                families,
                allowed_items={self._preference_key(label): (label, "primary") for label in JOB_FAMILIES},
            )
            self._replace_preferences(
                connection,
                "location",
                locations,
                allowed_items={key: (label, scope) for key, label, scope in PRIMARY_LOCATIONS},
            )
            values = {
                "availability_start": date_text(availability["availability_start"]),
                "availability_end": date_text(availability["availability_end"]),
                "minimum_duration_months": str(availability["minimum_duration_months"]),
                "maximum_duration_months": str(availability["maximum_duration_months"]),
            }
            for key, value in values.items():
                connection.execute(
                    """
                    INSERT INTO career_settings (setting_key, setting_value) VALUES (?, ?)
                    ON CONFLICT(setting_key) DO UPDATE SET setting_value = excluded.setting_value
                    """,
                    (key, value),
                )
            self._refresh_job_availability(connection, availability)
            self._audit(connection, "preferences_updated", "preferences", "search")
        return self.get_preferences()

    # ------------------------------------------------------------------
    # Stage Hunter: the person's own search brief, explainable matching and
    # factual application preparation.  Everything below is deterministic,
    # local and reuses the facts already stored by Career.
    # ------------------------------------------------------------------

    def _read_stage_search_raw(self, connection: sqlite3.Connection) -> str:
        row = connection.execute(
            "SELECT setting_value FROM career_settings WHERE setting_key = ?",
            (STAGE_SEARCH_SETTING_KEY,),
        ).fetchone()
        return str(row["setting_value"]) if row else ""

    def get_stage_search(self) -> dict[str, Any]:
        with self._lock, self._connection() as connection:
            raw = self._read_stage_search_raw(connection)
        brief = default_brief()
        # Keep the reusable matching contract neutral, but make the first
        # Career screen immediately useful for this finance-focused product.
        # Every domain remains an editable checkbox and a saved choice wins.
        brief["domains"] = list(STAGE_DOMAINS)
        brief["excluded_countries"] = ["France"]
        brief["excluded_cities"] = ["Paris"]
        brief["require_known_location"] = True
        if not raw:
            # This product is configured for the current user's stated goal:
            # internships from January 2027 onward. Every month after that
            # date remains eligible unless the person narrows the month list.
            brief["start_date"] = "2027-01-01"
            brief["start_months"] = list(range(1, 13))
        # A stored brief can become invalid without any action from the person
        # (a vocabulary entry removed by an update, a manual database edit…).
        # A read must never fail hard and lock the whole tab: fall back to an
        # empty brief, say so explicitly, and let the next save re-validate.
        stored_brief_invalid = False
        if raw:
            try:
                stored_payload = json.loads(raw)
                if not isinstance(stored_payload, dict):
                    raise TypeError("stored stage-search brief must be an object")
                stored_payload.setdefault("excluded_countries", ["France"])
                stored_payload.setdefault("excluded_cities", ["Paris"])
                stored_payload.setdefault("require_known_location", True)
                brief = validate_brief(stored_payload)
            except (json.JSONDecodeError, TypeError, ValueError, UserFacingError):
                brief = default_brief()
                brief["domains"] = list(STAGE_DOMAINS)
                brief["excluded_countries"] = ["France"]
                brief["excluded_cities"] = ["Paris"]
                brief["require_known_location"] = True
                brief["start_date"] = "2027-01-01"
                brief["start_months"] = list(range(1, 13))
                stored_brief_invalid = True
        return {
            "brief": brief,
            "configured": bool(raw) and not stored_brief_invalid and brief_is_configured(brief),
            "stored_brief_invalid": stored_brief_invalid,
            "vocabulary": stage_search_vocabulary(),
            "search_terms": search_terms_for(brief.get("domains", [])),
            "disclaimer": (
                "Critères enregistrés localement. Par défaut : stages uniquement, "
                "tous les domaines financiers, débuts à partir du 1er janvier 2027 et stages d’au moins six mois. "
                "France et Paris sont exclus ; un pays inconnu reste à vérifier. Modifie les cases selon ta recherche."
            ),
        }

    def update_stage_search(self, payload: dict[str, Any]) -> dict[str, Any]:
        brief = validate_brief(payload)
        with self._lock, self._connection() as connection:
            connection.execute(
                """
                INSERT INTO career_settings (setting_key, setting_value) VALUES (?, ?)
                ON CONFLICT(setting_key) DO UPDATE SET setting_value = excluded.setting_value
                """,
                (STAGE_SEARCH_SETTING_KEY, json.dumps(brief, ensure_ascii=False)),
            )
            self._audit(connection, "stage_search_updated", "preferences", "stage_search")
        return self.get_stage_search()

    def list_stage_matches(
        self,
        *,
        _scoring_context: dict[str, Any] | None = None,
        _include_recommendation_scores: bool = True,
    ) -> dict[str, Any]:
        """Rank every stored offer against the brief, with the reason for each score."""
        payload = self.get_stage_search()
        brief = payload["brief"]
        jobs = self.list_jobs(
            _scoring_context=_scoring_context,
            _include_scoring=_include_recommendation_scores,
        )
        matches: list[dict[str, Any]] = []
        if payload["configured"]:
            for job in jobs:
                stage_match = score_brief_match(brief, job)
                qualification = qualify_offer(
                    job,
                    allowed_contract_types=brief.get("contract_types"),
                    allowed_start_months=brief.get("start_months"),
                    required_start_date=brief.get("start_date"),
                    minimum_stage_duration_months=brief.get("minimum_stage_duration_months", 6),
                    excluded_countries=brief.get("excluded_countries"),
                    excluded_cities=brief.get("excluded_cities"),
                    require_known_location=brief.get("require_known_location", True),
                ).to_dict()
                _attach_qualification_presentation(stage_match, qualification)
                matches.append({
                    "job": job,
                    "stage_match": stage_match,
                    "qualification": qualification,
                    # The matching panel points at the very same requirement
                    # identifiers as the explorer and the detailed view.
                    "requirement_ids": _requirement_ids_of(job),
                })
            # Break ties by source identity, never a random database ID or
            # import/update time: the same postings have the same ordering
            # after a board reorders its feed or the application restarts.
            matches.sort(key=lambda item: (
                {"conforming": 0, "to_verify": 1, "non_conforming": 2}.get(
                    item["stage_match"].get("qualification_status"), 0
                ),
                -(int(item["stage_match"]["score"] or 0)),
                (item["stage_match"].get("education_access") or {}).get("priority_rank", 2),
                str(item["job"].get("source_name") or ""),
                str(item["job"].get("source_id") or ""),
                str(item["job"].get("canonical_url") or item["job"].get("official_url") or ""),
                str(item["job"].get("company") or ""),
                str(item["job"].get("title") or ""),
            ))
        else:
            matches = []
            for job in jobs:
                qualification = qualify_offer(
                    job,
                    allowed_contract_types=brief.get("contract_types"),
                    allowed_start_months=brief.get("start_months"),
                    required_start_date=brief.get("start_date"),
                    minimum_stage_duration_months=brief.get("minimum_stage_duration_months", 6),
                    excluded_countries=brief.get("excluded_countries"),
                    excluded_cities=brief.get("excluded_cities"),
                    require_known_location=brief.get("require_known_location", True),
                ).to_dict()
                matches.append({"job": job, "stage_match": None, "qualification": qualification,
                                "requirement_ids": _requirement_ids_of(job),
                                "education_access": score_brief_match(brief, job)["education_access"]})
        payload["matches"] = matches
        return payload

    def _current_cv_analysis(self):
        """Analyze the latest approved CV locally, or an explicit empty CV."""
        from .cv_quality import DocumentInput, analyze_cv

        with self._lock, self._connection() as connection:
            current_cv = connection.execute(
                """
                SELECT original_name, extracted_text, ocr_pages
                FROM profile_imports
                WHERE source_kind = 'cv'
                ORDER BY CASE status WHEN 'applied' THEN 0 ELSE 1 END,
                         created_at DESC
                LIMIT 1
                """
            ).fetchone()
        if current_cv:
            original_name = str(current_cv["original_name"] or "current-cv.txt")
            suffix = Path(original_name).suffix.lower().lstrip(".")
            filetype = suffix if suffix in {"pdf", "docx", "txt"} else "txt"
            document = DocumentInput(
                text=str(current_cv["extracted_text"] or ""),
                filename=original_name,
                filetype=filetype,
                page_count=int(current_cv["ocr_pages"] or 0) or None,
            )
        else:
            document = DocumentInput(
                text="",
                filename=None,
                filetype="txt",
                page_count=None,
            )
        return analyze_cv(document)

    def get_job_prep(
        self,
        job_id: str,
        *,
        _scoring_context: dict[str, Any] | None = None,
        _cv_analysis: Any | None = None,
        _job: dict[str, Any] | None = None,
        _qualification: dict[str, Any] | None = None,
        _include_requirements_fit: bool = True,
    ) -> dict[str, Any]:
        """Factual preparation panel for one offer; no model, no invention."""
        context = _scoring_context if _scoring_context is not None else self._scoring_context()
        job = (
            dict(_job)
            if isinstance(_job, dict)
            else self.get_job(job_id, scoring_context=context)
        )
        profile = context.get("profile") or {}
        analysis = prepare_application(
            profile,
            context.get("intake") or {},
            job,
            intelligence=job.get("offer_intelligence"),
        )
        # Keep the preparation card aligned with the canonical offer serializer.
        # prepare_application intentionally returns a compact offer object, so
        # attach the locally reconstructed source trust and qualification facts
        # needed by the UI instead of letting it display a generic fallback.
        prep_job = dict(analysis.get("job") or {})
        for field in (
            "qualification_facts",
            "official_source_trust",
            "official_source_trust_label",
            "source_verified",
        ):
            if field in job:
                prep_job[field] = job[field]
        analysis["job"] = prep_job
        if _include_requirements_fit:
            approved_profile_facts = []
            for field, category in (
                ("education", "etudes"),
                ("experience", "experience"),
                ("skills", "tech"),
                ("languages", "langues"),
            ):
                value = clean_text(profile.get(field), limit=20_000)
                if value:
                    approved_profile_facts.append({
                        "category": category,
                        "value": value,
                        "quote": value,
                        "status": "approved",
                        "source": "career_profile",
                    })
            # These fields are only present after a person has saved them in
            # the local editable Career profile. Do not inspect pending OCR.
            analysis["requirements_fit"] = analyze_fit(
                job, {"facts": approved_profile_facts}
            ).to_dict()
            reconcile_cv_plan_with_requirements_fit(
                analysis, analysis["requirements_fit"]
            )
        cv_analysis = _cv_analysis if _cv_analysis is not None else self._current_cv_analysis()
        qualification = (
            dict(_qualification)
            if isinstance(_qualification, dict)
            else qualify_offer(job).to_dict()
        )
        fit_job = {
            **job,
            **analysis,
            "qualification": qualification,
        }
        classification = classify_variant(fit_job, profile, ALL_VARIANTS)
        coverage = compute_coverage(
            fit_job,
            cv_analysis,
            profile,
            classification.primary_variant,
        )
        variant_coverage = {
            variant.id: compute_coverage(
                fit_job,
                cv_analysis,
                profile,
                variant,
            ).mandatory_pct
            for variant in ALL_VARIANTS
        }
        gaps = generate_diff(
            coverage,
            cv_analysis,
            profile,
            classification.primary_variant,
        )
        coverage = replace(
            coverage,
            gaps=gaps,
            variant_rationale=classification.rationale,
        )
        analysis.update(
            {
                "recommended_variant": classification.primary_variant.id,
                "recommended_variant_label": classification.primary_variant.label,
                "variant_scores": classification.scores,
                "variant_coverage": variant_coverage,
                "variant_rationale": classification.rationale,
                "coverage": {
                    "mandatory_total": coverage.mandatory_total,
                    "mandatory_covered": coverage.mandatory_covered,
                    "preferred_total": coverage.preferred_total,
                    "preferred_covered": coverage.preferred_covered,
                    "mandatory_pct": coverage.mandatory_pct,
                    "preferred_pct": coverage.preferred_pct,
                },
                "gaps": self._gaps_with_requirement_ids(gaps, job),
                "automatic_submission": False,
            }
        )
        self._prep_cache.add(job_id)
        return analysis

    @staticmethod
    def _gaps_with_requirement_ids(
        gaps: list[Any], job: dict[str, Any]
    ) -> list[dict[str, Any]]:
        """Attach the canonical requirement identifier to every CV gap."""
        payload = [serialize_gap(gap) for gap in gaps]
        snapshot = job.get("offer_intelligence")
        if not isinstance(snapshot, Mapping):
            return payload
        aligned = align_display_requirements(
            [{"text": str(item.get("requirement") or "")} for item in payload],
            snapshot,
        )
        for gap, entry in zip(payload, aligned):
            identifier = entry.get("requirement_id")
            if identifier:
                gap["requirement_id"] = identifier
        return payload

    def build_apply_kit(
        self,
        job_id: str,
        language: str = "fr",
        variant: str | None = None,
        profile: Any = None,
    ) -> dict[str, Any]:
        if isinstance(language, Mapping) and profile is None:
            profile = language
            language = "fr"
        if profile is None:
            profile = self.get_profile()
        from dataclasses import asdict

        from career.apply_kit import build_apply_kit as _build

        job = self.get_job(job_id)
        try:
            intake = self.get_intake()
        except Exception:
            intake = {}
        kit = _build(
            job_id,
            profile,
            job=job,
            intake=intake,
            service=self,
            variant=variant,
            language=language,
        )
        return asdict(kit)

    def get_application_sprint(self, *, limit: int = 12) -> dict[str, Any]:
        # Ranking and preparation normalize many of the same short job and
        # criteria strings. Keep these results only for this local operation;
        # profile and CV text is never retained in a process-wide cache.
        with scoped_normalized_text_cache():
            return self._build_application_sprint(limit=limit)

    def _build_application_sprint(self, *, limit: int) -> dict[str, Any]:
        """Prioritise a bounded batch for local preparation, without sending.

        This deliberately composes the canonical matching and preparation
        paths so the batch cannot silently use different eligibility or CV
        rules from the individual Career screens.
        """
        bounded_limit = max(1, min(MAX_SPRINT_ITEMS, int(limit or 12)))
        # Share the same profile/preferences snapshot across ranking and
        # preparation. This keeps a sprint internally consistent if profile
        # settings change while it is being assembled and avoids rereading it.
        scoring_context = self._scoring_context()
        stage_search = self.list_stage_matches(_scoring_context=scoring_context)
        matches = stage_search.get("matches") or []
        eligible_matches = [
            match
            for match in matches
            if (match.get("stage_match") or {}).get("qualification_status") != "non_conforming"
        ][:MAX_SPRINT_CANDIDATES]
        # All candidates in one sprint share the same approved profile and CV.
        # Load those facts once instead of reopening SQLite and reparsing the
        # current CV for every candidate.
        cv_analysis = self._current_cv_analysis()
        candidate_ids = [
            str(match["job"]["id"])
            for match in eligible_matches
            if isinstance(match.get("job"), dict) and match["job"].get("id")
        ]
        snapshots: dict[str, dict[str, Any]] = {}
        if candidate_ids:
            placeholders = ",".join("?" for _ in candidate_ids)
            with self._lock, self._connection() as connection:
                rows = connection.execute(
                    "SELECT job_id, snapshot_json FROM job_offer_intelligence_snapshots "
                    f"WHERE is_current = 1 AND job_id IN ({placeholders})",
                    candidate_ids,
                ).fetchall()
            for row in rows:
                try:
                    snapshot = json.loads(row["snapshot_json"] or "{}")
                except (TypeError, ValueError):
                    snapshot = {}
                if isinstance(snapshot, dict):
                    snapshots[str(row["job_id"])] = snapshot
        preparations = {
            str(match["job"]["id"]): self.get_job_prep(
                str(match["job"]["id"]),
                _scoring_context=scoring_context,
                _cv_analysis=cv_analysis,
                _job={
                    **match["job"],
                    "offer_intelligence": snapshots.get(str(match["job"]["id"])),
                },
                _qualification=match.get("qualification"),
                _include_requirements_fit=False,
            )
            for match in eligible_matches
            if isinstance(match.get("job"), dict) and match["job"].get("id")
        }
        return build_application_sprint(
            matches,
            preparations,
            self.list_applications(),
            limit=bounded_limit,
            profile=scoring_context.get("profile") or {},
            criteria=stage_search.get("brief") or {},
        )

    def get_application_pipeline(self) -> dict[str, Any]:
        """Return a read-only, derived view of the complete local workflow."""

        # Matching normalizes the same brief terms, locations, and contract
        # labels for every offer. Keep those short strings only for this one
        # synchronous read; the cache is reset in a finally block and never
        # retains profile or offer text across requests.
        with scoped_normalized_text_cache():
            return self._build_application_pipeline()

    def _build_application_pipeline(self) -> dict[str, Any]:
        """Build the pipeline while its request-scoped text cache is active."""

        drafts = self.list_application_drafts()
        applications = self.list_applications()
        # Stage matches already carry the serialized local jobs. Reuse them
        # here instead of listing and serializing every offer twice.
        matches = self.list_stage_matches(_include_recommendation_scores=False).get("matches") or []
        jobs = [
            match["job"]
            for match in matches
            if isinstance(match.get("job"), dict) and match["job"].get("id")
        ]
        sprint_queue = [
            {
                "job_id": str((match.get("job") or {}).get("id") or ""),
                "readiness": (
                    "prepare_now"
                    if (match.get("stage_match") or {}).get("qualification_status")
                    == "conforming"
                    else "offer_to_verify"
                ),
                "match_score": int((match.get("stage_match") or {}).get("score") or 0),
            }
            for match in matches
            if isinstance(match.get("job"), dict)
            and (match.get("job") or {}).get("id")
            and (match.get("stage_match") or {}).get("qualification_status")
            != "non_conforming"
        ]
        sprint_by_job = {item["job_id"]: item for item in sprint_queue}
        draft_by_job = {str(item.get("job_id")): item for item in drafts}
        app_by_job = {str(item.get("job_id")): item for item in applications}
        jobs_by_id = {str(item.get("id")): item for item in jobs}
        job_context = {
            str(job["id"]): {
                "qualification_facts_json": "1"
                if job.get("qualification_facts")
                else ""
            }
            for job in jobs
        }
        context = {
            "jobs": job_context,
            "sprint_queue": sprint_queue,
            "prep_cache": set(self._prep_cache),
            "selected_variant": {},
            "application_drafts": drafts,
            "applications": applications,
        }
        items: list[PipelineItem] = []
        for job in jobs:
            job_id = str(job["id"])
            draft = draft_by_job.get(job_id, {})
            variant_id = clean_text(draft.get("variant"), limit=40)
            variant = next(
                (item for item in ALL_VARIANTS if item.id == variant_id), None
            )
            application = app_by_job.get(job_id, {})
            sprint = sprint_by_job.get(job_id, {})
            items.append(
                PipelineItem(
                    job_id=job_id,
                    company=clean_text(job.get("company"), limit=240)
                    or "Entreprise inconnue",
                    title=clean_text(job.get("title"), limit=300) or "Sans titre",
                    stage=derive_pipeline_stage(job_id, context),
                    variant=variant,
                    variant_label=variant.label if variant else None,
                    kit_generated_at=clean_text(draft.get("created_at"), limit=64)
                    or None,
                    tracking_stage=clean_text(application.get("stage"), limit=80)
                    or None,
                    readiness=clean_text(sprint.get("readiness"), limit=80),
                    match_score=int(sprint.get("match_score") or 0),
                )
            )
        stage_priority = {
            PipelineStage.TRACKING_CREATED: 0,
            PipelineStage.KIT_GENERATED: 1,
            PipelineStage.VARIANT_SELECTED: 2,
            PipelineStage.PREP_ANALYZED: 3,
            PipelineStage.SPRINT_QUEUED: 4,
            PipelineStage.QUALIFIED: 5,
            PipelineStage.DISCOVERED: 6,
        }
        items.sort(
            key=lambda item: (
                stage_priority[item.stage],
                -item.match_score,
                item.company.casefold(),
            )
        )
        serialized = [
                {
                    "job_id": item.job_id,
                    "company": item.company,
                    "title": item.title,
                    "stage": item.stage.value,
                    "variant": item.variant.id if item.variant else None,
                    "variant_label": item.variant_label,
                    "kit_generated_at": item.kit_generated_at,
                    "tracking_stage": item.tracking_stage,
                    "readiness": item.readiness,
                    "match_score": item.match_score,
                    "application_id": clean_text(
                        app_by_job.get(item.job_id, {}).get("id"), limit=80
                    ) or None,
                    "official_url": clean_text(
                        jobs_by_id.get(item.job_id, {}).get("official_url"), limit=2_000
                    ),
                    "source_verified": bool(
                        jobs_by_id.get(item.job_id, {}).get("source_verified")
                    ),
                    "deadline_date": clean_text(
                        jobs_by_id.get(item.job_id, {}).get("deadline_date"), limit=32
                    ),
                }
                for item in items
            ]
        return build_application_action_center(serialized)

    def get_job_summary(
        self,
        job_id: str,
        *,
        mode: str = "local",
        consent_external: bool = False,
        consent_id: str | None = None,
        ai_generator: Any | None = None,
        provider: str = "career",
        model: str = "career-summary",
        purpose: str = "job_application",
    ) -> dict[str, Any]:
        """Structured, factual summary of one offer.

        The local summary is always available.  An optional cloud enhancement
        requires an explicit consent (boolean checkbox or consent_guard id);
        when consent is refused or unavailable, the local summary is returned
        instead of raising.
        """

        job = self.get_job(job_id)
        base = summarize_offer(job)
        # Keep the deterministic pertinence score alongside the offer facts.
        scoring = job.get("scoring") if isinstance(job.get("scoring"), dict) else {}
        if "score" not in base:
            base["score"] = scoring.get("score")
        if "pertinence" not in base:
            base["pertinence"] = scoring.get("score")
        base["job_id"] = job.get("id")

        result: dict[str, Any] = {
            **base,
            "mode": "local",
            "ai_used": False,
            "ai_summary": None,
            "ai_provider": None,
            "ai_error": None,
            "consent_status": None,
            "consent_required": True,
        }

        normalized_mode = str(mode or "local").strip().lower()
        if normalized_mode != "ai":
            result["mode"] = "local"
            return result

        result["mode"] = "ai"
        # Le prompt final est construit AVANT la décision de consentement :
        # son empreinte est exactement ce qui est signé et consommé (aucune
        # donnée au-delà de ce qui a été validé par l'utilisateur).
        prompt = (
            "Résume de façon structurée et factuelle l'offre suivante, sans inventer. "
            "Retourne un JSON avec les clés: summary, missions, prerequisites, dates, relevance, official_url. "
            f"Offre: {job}"
        )
        payload_for_consent: dict[str, Any] = {"prompt": prompt}

        allowed = False
        refusal_message: str | None = None
        consent_status: str | None = None

        guard = getattr(self, "consent_guard", None)
        if guard is None:
            # Échec en absence d'option : sans garde-fou disponible, aucun
            # contenu local ne quitte le disque. Le résumé local reste servi.
            refusal_message = "Garde-fou de consentement indisponible ; aucun envoi cloud n'est possible."
        elif consent_id:
            try:
                decision = guard.check(
                    consent_id,
                    provider=provider,
                    model=model,
                    purpose=purpose,
                    payload=payload_for_consent,
                )
            except Exception as error:  # pragma: no cover - defensive
                decision = None
                refusal_message = str(error)
            if decision is not None:
                consent_status = getattr(decision, "code", None)
                if getattr(decision, "allowed", False):
                    try:
                        guard.consume(
                            consent_id,
                            provider=provider,
                            model=model,
                            purpose=purpose,
                            payload=payload_for_consent,
                        )
                        allowed = True
                    except Exception as error:
                        allowed = False
                        refusal_message = str(error)
                        consent_status = getattr(error, "code", consent_status) or consent_status
                else:
                    refusal_message = getattr(decision, "message", None)
        elif consent_external:
            # L'accord explicite de l'utilisateur ne court-circuite plus le garde :
            # il devient un reçu unique signé sur l'empreinte du prompt exact,
            # consommé immédiatement pour cette transmission.
            try:
                envelope = guard.grant(
                    payload_for_consent,
                    provider=provider,
                    model=model,
                    purpose=purpose,
                    actor="come_ai_career_summary_ui",
                )
                consent_status = "allowed"
            except Exception as error:
                refusal_message = str(error)
            else:
                try:
                    guard.consume(
                        envelope.consent_id,
                        provider=provider,
                        model=model,
                        purpose=purpose,
                        payload=payload_for_consent,
                    )
                    allowed = True
                except Exception as error:
                    refusal_message = str(error)
                    consent_status = getattr(error, "code", consent_status) or consent_status
        else:
            refusal_message = "Consentement cloud requis ; résumé local conservé."

        if not allowed:
            result["ai_error"] = (refusal_message or "Consentement refusé ; résumé local conservé.") + " (repli local)"
            result["consent_status"] = consent_status
            result["mode"] = "local"
            return result

        if not callable(ai_generator):
            result["ai_error"] = "Aucun fournisseur IA configuré ; résumé local conservé. (repli local)"
            result["consent_status"] = consent_status
            result["mode"] = "local"
            return result

        try:
            generated = ai_generator(prompt)
        except Exception as error:
            result["ai_error"] = (
                "Le fournisseur IA a échoué ; résumé local conservé. (repli local) "
                + safe_error(error)
            )
            result["consent_status"] = consent_status
            result["mode"] = "local"
            return result

        if not isinstance(generated, dict):
            result["ai_error"] = "Le fournisseur IA a renvoyé un résultat invalide ; résumé local conservé. (repli local)"
            result["consent_status"] = consent_status
            result["mode"] = "local"
            return result

        text = clean_text(generated.get("text"), limit=20_000)
        provider_name = clean_text(generated.get("provider"), limit=160) or "Fournisseur IA configuré"
        parsed: Any = None
        try:
            import json as _json

            parsed = _json.loads(text)
        except Exception:
            parsed = None
        result["ai_used"] = True
        result["ai_provider"] = provider_name
        result["ai_summary"] = parsed if isinstance(parsed, dict) else text
        result["consent_status"] = consent_status or "consumed"
        return result

    def summarize_job(self, job_id: str, **kwargs: Any) -> dict[str, Any]:
        return self.get_job_summary(job_id, **kwargs)

    def _exploration_registry(self) -> tuple[dict[str, Any], ...]:
        if self._curated_sources is not None:
            return tuple(dict(source) for source in self._curated_sources)
        from .source_registry import CURATED_SOURCES

        return tuple(dict(source) for source in CURATED_SOURCES)

    @staticmethod
    def _exploration_limits() -> dict[str, Any]:
        return {"max_sources": EXPLORATION_MAX_SOURCES, "max_results": EXPLORATION_MAX_RESULTS,
                "network_budget_seconds": EXPLORATION_NETWORK_BUDGET_SECONDS,
                "request_timeout_seconds": 8, "max_response_bytes_per_source": 8 * 1024 * 1024,
                "note": "Aucune nouvelle requête après 60 secondes ; une requête déjà en cours peut dépasser ce budget."}

    @staticmethod
    def _exploration_brief_fingerprint(brief: dict[str, Any]) -> str:
        return hashlib.sha256(json.dumps(brief, sort_keys=True, ensure_ascii=False).encode("utf-8")).hexdigest()

    def get_exploration(self) -> dict[str, Any]:
        """Read and rescore the last explorer snapshot; never perform network I/O."""
        brief_payload = self.get_stage_search()
        brief = brief_payload["brief"]
        with self._lock, self._connection() as connection:
            row = connection.execute("SELECT setting_value FROM career_settings WHERE setting_key = ?",
                                     (EXPLORATION_LAST_SETTING,)).fetchone()
        snapshot: dict[str, Any] = {}
        if row:
            try:
                decoded = json.loads(str(row["setting_value"]))
                if isinstance(decoded, dict):
                    snapshot = decoded
            except (ValueError, TypeError):
                pass
        matches: list[dict[str, Any]] = []
        references = snapshot.get("match_refs", [])
        if not isinstance(references, list):
            references = []
        for reference in references[:EXPLORATION_MAX_RESULTS]:
            if not isinstance(reference, dict):
                continue
            try:
                job = self.get_job(str(reference.get("job_id") or ""))
            except UserFacingError:
                # A person may have deliberately deleted an offer since the
                # snapshot was saved. Never recreate it on a read.
                continue
            internship = classify_internship(job)
            match = score_brief_match(brief, job)
            qualification = qualify_offer(
                {**job, "source_verified": bool(reference.get("verified_at"))},
                allowed_contract_types=brief.get("contract_types"),
                allowed_start_months=brief.get("start_months"),
                required_start_date=brief.get("start_date"),
                minimum_stage_duration_months=brief.get("minimum_stage_duration_months", 6),
                excluded_countries=brief.get("excluded_countries"),
                excluded_cities=brief.get("excluded_cities"),
                require_known_location=brief.get("require_known_location", True),
            ).to_dict()
            if job.get("source_status") == "closed" or qualification["target_status"] == "non_conforming":
                continue
            job["qualification"] = qualification
            _attach_qualification_presentation(match, qualification)
            if qualification["contract_type"] == "unknown" and not internship.get("evidence"):
                continue
            matches.append({"job": job, "stage_match": match, "internship": internship,
                            "qualification": qualification,
                            "source_id": reference.get("source_id", ""),
                            "verified_at": reference.get("verified_at", "")})
        matches.sort(key=lambda item: ranking_key(item["job"], item["stage_match"]))
        changed = bool(snapshot) and snapshot.get("brief_fingerprint") != self._exploration_brief_fingerprint(brief)
        if changed:
            # A previous result set is not a match for newly saved criteria.
            # Require an explicit refresh instead of presenting stale offers.
            matches = []
        summary = dict(snapshot["summary"]) if isinstance(snapshot.get("summary"), dict) else {}
        summary["displayed_count"] = len(matches)
        return {"mode": "explore", "has_run": bool(snapshot), "run_id": snapshot.get("run_id", ""),
                "started_at": snapshot.get("started_at", ""), "finished_at": snapshot.get("finished_at", ""),
                "criteria_changed": changed, "requires_refresh": changed,
                "configured": brief_payload["configured"], "brief": brief,
                "outcomes": snapshot.get("outcomes", []) if isinstance(snapshot.get("outcomes", []), list) else [],
                "summary": summary, "matches": matches,
                "registry": list(self._exploration_registry()), "limits": self._exploration_limits(),
                "disclaimer": "Sources publiques uniquement. Résultats du dernier parcours, reclassés localement ; aucune candidature envoyée."
                + (" Tes critères ont changé : relance l’exploration pour couvrir les sources avec ces critères." if changed else "")}

    def get_stage_source_coverage(self, run_id: str | None = None) -> dict[str, Any]:
        """Return exact synthetic/live metrics for the latest local exploration."""
        current = self.get_exploration().get("run_id", "")
        requested = clean_text(run_id, limit=160) or clean_text(current, limit=160)
        if not requested:
            raise UserFacingError("Aucune exploration locale n’est disponible à mesurer.")
        try:
            return compute_metrics(requested, base_dir=self.base_dir).to_dict()
        except CoverageRunNotFound as error:
            raise UserFacingError(str(error)) from error

    def explore_internships(self, *, force: bool = False) -> dict[str, Any]:
        """Explicit read-only exploration; works with zero personal boards.

        Only confirmed internships meeting explicit domain/location admission
        are ranked. Source errors never erase jobs, notes or applications.
        The source interface is extensible; unsupported connectors are visible,
        never silently treated as a success or fetched through arbitrary URLs.
        """
        if not self._discovery_lock.acquire(blocking=False):
            raise UserFacingError("Une recherche d’opportunités est déjà en cours. Attends sa fin avant de relancer.")
        try:
            brief = self.get_stage_search()["brief"]
            fingerprint = self._exploration_brief_fingerprint(brief)
            started_at = utc_now()
            started_clock = time.monotonic()
            deadline = started_clock + EXPLORATION_NETWORK_BUDGET_SECONDS
            registry = self._exploration_registry()
            outcomes: list[dict[str, Any]] = []
            candidates: list[dict[str, Any]] = []
            allowed_ids = {str(source.get("id") or "") for source in registry[:EXPLORATION_MAX_SOURCES]}
            self._exploration_cache = {key: value for key, value in self._exploration_cache.items() if key in allowed_ids}
            for index, source in enumerate(registry):
                source_id = clean_text(source.get("id"), limit=160)
                provider = clean_text(source.get("provider"), limit=40)
                company = clean_text(source.get("company"), limit=240)
                outcome: dict[str, Any] = {"source_id": source_id, "provider": provider, "company": company,
                                          "public_url": source.get("public_url", ""),
                                          "provenance_url": source.get("provenance_url", ""),
                                          "registry_verified_at": source.get("verified_at", ""), "attempted": False}
                if index >= EXPLORATION_MAX_SOURCES:
                    outcome.update(status="not_queried", message="Limite de sources de ce parcours atteinte.")
                    outcomes.append(outcome)
                    continue
                connector = self._exploration_connectors.get(provider)
                if connector is None or not callable(getattr(connector, "discover_internships", None)):
                    outcome.update(status="unsupported", message="Connecteur non disponible ; source non consultée.")
                    outcomes.append(outcome)
                    continue
                if not source_id or not company or not source.get("verified_at") or not source.get("provenance_url"):
                    outcome.update(status="unsupported", message="Source sans identité ou provenance vérifiée ; non consultée.")
                    outcomes.append(outcome)
                    continue
                cache_fingerprint = hashlib.sha256(
                    json.dumps(source, sort_keys=True, ensure_ascii=False).encode("utf-8") + fingerprint.encode("ascii")
                ).hexdigest()
                cached = self._exploration_cache.get(source_id)
                result = None
                if not force and cached and cached[0] == cache_fingerprint and self._discovery_cache_valid(cached[1].verified_at):
                    result = cached[1]
                    outcome.update(status="cached", message="Dernière lecture réussie conservée (cache de 10 minutes).")
                elif time.monotonic() >= deadline:
                    outcome.update(status="not_queried", message="Budget réseau atteint ; cette source n’a pas été consultée.")
                    outcomes.append(outcome)
                    continue
                else:
                    try:
                        # Greenhouse currently is the only registry provider.
                        # Future connectors receive their own source descriptor.
                        descriptor = GreenhouseBoard(source_id, company, parse_greenhouse_board_token(source.get("board_token"))) if provider == "greenhouse" else source
                        outcome["attempted"] = True
                        result = connector.discover_internships(descriptor, selection_brief=brief, deadline=deadline)
                        if not isinstance(result, DiscoveryPayload) or not isinstance(result.jobs, tuple) or any(not isinstance(job, dict) for job in result.jobs):
                            raise PublicSourceError("Le connecteur n’a pas renvoyé un résultat d’exploration valide.", code="invalid_payload")
                        counts = (result.raw_count, result.evaluated_count, result.invalid_count,
                                  result.confirmed_count, result.uncertain_count, result.excluded_count,
                                  result.relevant_count, result.filtered_criteria_count)
                        if (any(type(count) is not int or count < 0 for count in counts)
                            or result.raw_count != result.evaluated_count + result.invalid_count
                            or result.evaluated_count != result.confirmed_count + result.uncertain_count + result.excluded_count
                            or result.relevant_count + result.filtered_criteria_count != result.confirmed_count + result.uncertain_count
                            or len(result.jobs) > min(EXPLORATION_MAX_RESULTS, result.relevant_count)):
                            raise PublicSourceError("Le connecteur n’a pas fourni des compteurs d’exploration cohérents.", code="invalid_counts")
                        self._exploration_cache[source_id] = (cache_fingerprint, result)
                        outcome.update(status="success", message="Flux officiel lu ; admission et classement effectués localement.")
                    except Exception as caught:
                        self._exploration_cache.pop(source_id, None)
                        code = clean_text(getattr(caught, "code", "unexpected"), limit=40)
                        outcome.update(status="error", error_code=code,
                                       message="Cette source n’a pas pu être vérifiée. Les offres et candidatures existantes sont conservées.")
                        outcomes.append(outcome)
                        continue
                if result is None:
                    continue
                count_fields = ("raw_count", "evaluated_count", "invalid_count", "confirmed_count", "uncertain_count",
                                "excluded_count", "relevant_count", "filtered_criteria_count")
                outcome.update({key: int(getattr(result, key, 0)) for key in count_fields})
                outcome.update(verified_at=result.verified_at, retained_count=len(result.jobs), truncated=bool(result.truncated))
                if result.invalid_count and outcome["status"] == "success":
                    outcome.update(status="partial", message="Flux officiel lu, avec des entrées incomplètes ou invalides ignorées.")
                outcomes.append(outcome)
                for job in result.jobs:
                    # Re-qualify at the service boundary using the current
                    # saved criteria; connector output is never trusted alone.
                    classification = classify_internship(job)
                    match = score_brief_match(brief, job)
                    qualification = qualify_offer(
                        {**job, "source_verified": bool(result.verified_at)},
                        allowed_contract_types=brief.get("contract_types"),
                        allowed_start_months=brief.get("start_months"),
                        required_start_date=brief.get("start_date"),
                        minimum_stage_duration_months=brief.get("minimum_stage_duration_months", 6),
                        excluded_countries=brief.get("excluded_countries"),
                        excluded_cities=brief.get("excluded_cities"),
                        require_known_location=brief.get("require_known_location", True),
                    ).to_dict()
                    qualified_job = {**job, "qualification": qualification}
                    if (qualification["target_status"] != "non_conforming"
                            and (qualification["contract_type"] != "unknown" or classification.get("evidence"))
                            and criteria_admit(match, qualified_job, brief)):
                        _attach_qualification_presentation(match, qualification)
                        candidates.append({"job": qualified_job, "stage_match": match, "internship": classification,
                                           "qualification": qualification,
                                           "source_id": source_id, "verified_at": result.verified_at,
                                           "board_token": source.get("board_token", "")})
            # At most eight per-source heaps of 150 are materialised. Sort then
            # collapse exact official URL aliases before the global cap, so a
            # repeated board cannot fill the list with duplicates.
            candidates.sort(key=lambda item: ranking_key(item["job"], item["stage_match"]))
            unique: dict[str, dict[str, Any]] = {}
            for candidate in candidates:
                url = canonical_url(candidate["job"].get("official_url"))
                unique.setdefault(url, candidate)
            selected = list(unique.values())[:EXPLORATION_MAX_RESULTS]
            imported = updated = invalid_imports = 0
            match_refs: list[dict[str, Any]] = []
            availability = self._current_availability_values()
            for item in selected:
                payload = dict(item["job"])
                payload["source_id"] = f"curated:{item['board_token']}:{payload.get('source_id', '')}"
                try:
                    job = self.import_job(payload, availability=availability, preserve_unknown_source_fields=True)
                except UserFacingError:
                    invalid_imports += 1
                    continue
                imported += int(job["created"])
                updated += int(not job["created"])
                with self._lock, self._connection() as connection:
                    connection.execute("UPDATE jobs SET last_seen_at = ?, last_verified_at = ? WHERE id = ?",
                                       (item["verified_at"], item["verified_at"], job["id"]))
                match_refs.append({"job_id": job["id"], "source_id": item["source_id"], "verified_at": item["verified_at"]})
            summary = {"sources_total": len(registry),
                       "sources_attempted": sum(int(item["attempted"]) for item in outcomes),
                       "sources_succeeded": sum(item["status"] in {"success", "partial"} for item in outcomes),
                       "sources_cached": sum(item["status"] == "cached" for item in outcomes),
                       "sources_failed": sum(item["status"] == "error" for item in outcomes),
                       "sources_not_queried": sum(item["status"] in {"not_queried", "unsupported"} for item in outcomes),
                       "retained_count": len(match_refs), "imported_count": imported, "updated_count": updated,
                       "invalid_imports": invalid_imports, "duplicate_count": len(candidates) - len(unique),
                       "elapsed_seconds": round(time.monotonic() - started_clock, 3),
                       "partial": any(item["status"] not in {"success", "cached"} for item in outcomes)
                       or any(item.get("invalid_count", 0) for item in outcomes) or bool(invalid_imports),
                       "counts_include_cached_sources": any(item["status"] == "cached" for item in outcomes)}
            for key in ("raw_count", "evaluated_count", "invalid_count", "confirmed_count", "uncertain_count",
                        "excluded_count", "relevant_count", "filtered_criteria_count"):
                summary[key] = sum(int(item.get(key, 0)) for item in outcomes)
            snapshot = {"run_id": f"explore_{uuid.uuid4().hex}", "started_at": started_at, "finished_at": utc_now(),
                        "brief_fingerprint": fingerprint, "outcomes": outcomes, "summary": summary, "match_refs": match_refs}
            with self._lock, self._connection() as connection:
                connection.execute("INSERT INTO career_settings (setting_key, setting_value) VALUES (?, ?) "
                                   "ON CONFLICT(setting_key) DO UPDATE SET setting_value = excluded.setting_value",
                                   (EXPLORATION_LAST_SETTING, json.dumps(snapshot, ensure_ascii=False)))
                self._audit(connection, "internships_explored", "stage_explorer", snapshot["run_id"])
            return self.get_exploration()
        finally:
            self._discovery_lock.release()

    @staticmethod
    def _serialize_discovery_source(row: sqlite3.Row) -> dict[str, Any]:
        result = dict(row)
        result["enabled"] = bool(result["enabled"])
        result["public_url"] = GreenhouseBoard(
            id=str(result["id"]), company=str(result["company"]), board_token=str(result["board_token"])
        ).public_url
        result["jobs_stored"] = int(result.pop("jobs_stored", 0) or 0)
        return result

    def list_discovery_sources(self) -> list[dict[str, Any]]:
        with self._lock, self._connection() as connection:
            rows = connection.execute(
                """
                SELECT discovery_sources.*,
                       COUNT(jobs.id) AS jobs_stored
                FROM discovery_sources
                LEFT JOIN jobs ON jobs.discovery_source_id = discovery_sources.id
                GROUP BY discovery_sources.id
                ORDER BY discovery_sources.enabled DESC, discovery_sources.company COLLATE NOCASE ASC
                """
            ).fetchall()
        return [self._serialize_discovery_source(row) for row in rows]

    def create_discovery_source(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Save one official Greenhouse board; no request is made here."""
        company = clean_text(payload.get("company"), limit=240)
        if not company:
            raise UserFacingError("Indique le nom de l’entreprise associée au board public.")
        token = parse_greenhouse_board_token(payload.get("board_reference", payload.get("board_token", "")))
        enabled = bool(payload.get("enabled", True))
        now = utc_now()
        with self._lock, self._connection() as connection:
            count = int(connection.execute("SELECT COUNT(*) FROM discovery_sources").fetchone()[0])
            existing = connection.execute(
                "SELECT id FROM discovery_sources WHERE board_token = ?", (token,)
            ).fetchone()
            if not existing and count >= 8:
                raise UserFacingError("Limite de 8 boards publics configurés. Désactive une source avant d’en ajouter une autre.")
            if existing:
                source_id = str(existing["id"])
                connection.execute(
                    "UPDATE discovery_sources SET company = ?, enabled = ?, updated_at = ? WHERE id = ?",
                    (company, int(enabled), now, source_id),
                )
                action = "discovery_source_updated"
            else:
                source_id = f"source_{uuid.uuid4().hex}"
                connection.execute(
                    """
                    INSERT INTO discovery_sources (
                        id, provider, company, board_token, enabled, created_at, updated_at
                    ) VALUES (?, 'greenhouse', ?, ?, ?, ?, ?)
                    """,
                    (source_id, company, token, int(enabled), now, now),
                )
                action = "discovery_source_created"
            self._audit(connection, action, "discovery_source", source_id)
        for source in self.list_discovery_sources():
            if source["id"] == source_id:
                return source
        raise UserFacingError("La source publique n’a pas pu être enregistrée.")

    def set_discovery_source_enabled(self, source_id: str, enabled: bool) -> dict[str, Any]:
        identifier = clean_text(source_id, limit=80)
        with self._lock, self._connection() as connection:
            result = connection.execute(
                "UPDATE discovery_sources SET enabled = ?, updated_at = ? WHERE id = ?",
                (int(bool(enabled)), utc_now(), identifier),
            )
            if result.rowcount != 1:
                raise UserFacingError("Cette source publique Career n’existe pas.")
            self._audit(
                connection,
                "discovery_source_enabled" if enabled else "discovery_source_disabled",
                "discovery_source",
                identifier,
            )
        for source in self.list_discovery_sources():
            if source["id"] == identifier:
                return source
        raise UserFacingError("Cette source publique Career n’existe pas.")

    def list_discovery_runs(self, *, limit: int = 30) -> list[dict[str, Any]]:
        bounded = max(1, min(int(limit), 100))
        with self._lock, self._connection() as connection:
            rows = connection.execute(
                """
                SELECT discovery_runs.*, discovery_sources.company, discovery_sources.board_token
                FROM discovery_runs LEFT JOIN discovery_sources ON discovery_sources.id = discovery_runs.source_id
                ORDER BY discovery_runs.started_at DESC LIMIT ?
                """,
                (bounded,),
            ).fetchall()
        return [dict(row) for row in rows]

    @staticmethod
    def _discovery_cache_valid(last_success_at: str) -> bool:
        if not last_success_at:
            return False
        try:
            previous = datetime.fromisoformat(last_success_at)
            if previous.tzinfo is None:
                return False
            return (datetime.now(previous.tzinfo) - previous).total_seconds() < DISCOVERY_CACHE_SECONDS
        except (TypeError, ValueError):
            return False

    def _record_discovery_run(
        self,
        source_id: str,
        *,
        status: str,
        started_at: str,
        finished_at: str = "",
        found_count: int = 0,
        imported_count: int = 0,
        updated_count: int = 0,
        skipped_count: int = 0,
        message: str = "",
    ) -> str:
        run_id = f"discovery_{uuid.uuid4().hex}"
        with self._lock, self._connection() as connection:
            connection.execute(
                """
                INSERT INTO discovery_runs (
                    id, source_id, started_at, finished_at, status, found_count,
                    imported_count, updated_count, skipped_count, message
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    run_id,
                    source_id,
                    started_at,
                    finished_at,
                    status,
                    found_count,
                    imported_count,
                    updated_count,
                    skipped_count,
                    clean_text(message, limit=1_000),
                ),
            )
        return run_id

    def _finish_discovery_run(
        self,
        run_id: str,
        *,
        status: str,
        found_count: int,
        imported_count: int,
        updated_count: int,
        skipped_count: int,
        message: str,
    ) -> None:
        with self._lock, self._connection() as connection:
            connection.execute(
                """
                UPDATE discovery_runs SET finished_at = ?, status = ?, found_count = ?,
                    imported_count = ?, updated_count = ?, skipped_count = ?, message = ?
                WHERE id = ?
                """,
                (
                    utc_now(),
                    status,
                    found_count,
                    imported_count,
                    updated_count,
                    skipped_count,
                    clean_text(message, limit=1_000),
                    run_id,
                ),
            )

    def discover_opportunities(self, *, force: bool = False) -> dict[str, Any]:
        """Refresh explicitly configured official boards after a user action.

        A source failure is isolated: existing data survives unchanged, while
        other enabled boards continue.  There is no automatic scheduler and
        no provider/model call anywhere in this workflow.
        """
        if not self._discovery_lock.acquire(blocking=False):
            raise UserFacingError("Une recherche d’opportunités est déjà en cours. Attends sa fin avant de relancer.")
        try:
            brief = self.get_stage_search()["brief"]
            selection_fingerprint = hashlib.sha256(
                json.dumps(brief, sort_keys=True, ensure_ascii=False).encode("utf-8")
            ).hexdigest()
            with self._lock, self._connection() as connection:
                sources = connection.execute(
                    "SELECT * FROM discovery_sources WHERE enabled = 1 ORDER BY company COLLATE NOCASE ASC"
                ).fetchall()
                cached_selections = {
                    str(row["setting_key"]): str(row["setting_value"])
                    for row in connection.execute(
                        "SELECT setting_key, setting_value FROM career_settings "
                        "WHERE setting_key LIKE 'stage_search_selection:%'"
                    ).fetchall()
                }
            if not sources:
                raise UserFacingError("Ajoute d’abord au moins un board Greenhouse public à suivre.")

            outcomes: list[dict[str, Any]] = []
            for row in sources:
                source = dict(row)
                source_id = str(source["id"])
                selection_key = f"stage_search_selection:{source_id}"
                started_at = utc_now()
                if (
                    not force
                    and self._discovery_cache_valid(str(source["last_success_at"]))
                    and cached_selections.get(selection_key) == selection_fingerprint
                ):
                    run_id = self._record_discovery_run(
                        source_id,
                        status="cached",
                        started_at=started_at,
                        finished_at=utc_now(),
                        message="Résultats conservés : vérification réussie il y a moins de 10 minutes.",
                    )
                    outcomes.append(
                        {
                            "source_id": source_id,
                            "company": source["company"],
                            "status": "cached",
                            "run_id": run_id,
                            "message": "Résultats récents conservés (cache de 10 minutes).",
                            "verified_at": source["last_success_at"],
                        }
                    )
                    continue

                run_id = self._record_discovery_run(source_id, status="running", started_at=started_at)
                with self._lock, self._connection() as connection:
                    connection.execute(
                        "UPDATE discovery_sources SET last_checked_at = ?, updated_at = ? WHERE id = ?",
                        (started_at, started_at, source_id),
                    )
                try:
                    board = GreenhouseBoard(
                        id=source_id,
                        company=str(source["company"]),
                        board_token=str(source["board_token"]),
                    )
                    ranked_discovery = getattr(self.discovery_connector, "discover_ranked", None)
                    if callable(ranked_discovery):
                        result = ranked_discovery(board, selection_brief=brief)
                    else:
                        # Retain the original injectable connector contract.
                        # Production Greenhouse always uses ranked discovery;
                        # legacy fixtures/connectors return their own payload.
                        result = self.discovery_connector.discover(board)
                except Exception as caught:
                    # A connector is isolated from the rest of the local
                    # tracker.  The public implementation raises
                    # ``PublicSourceError`` for expected source failures, but
                    # an unexpected parser/transport defect must still close
                    # this run cleanly rather than leaving it marked running
                    # or surfacing a server error to the browser.
                    error = (
                        caught
                        if isinstance(caught, PublicSourceError)
                        else PublicSourceError(
                            "Cette source officielle a rencontré une erreur locale inattendue. Les offres déjà enregistrées sont conservées.",
                            code="unexpected",
                        )
                    )
                    message = clean_text(str(error), limit=1_000)
                    self._finish_discovery_run(
                        run_id,
                        status="error",
                        found_count=0,
                        imported_count=0,
                        updated_count=0,
                        skipped_count=0,
                        message=message,
                    )
                    with self._lock, self._connection() as connection:
                        connection.execute(
                            """
                            UPDATE discovery_sources
                            SET last_error_code = ?, last_error_at = ?, updated_at = ? WHERE id = ?
                            """,
                            (clean_text(getattr(error, "code", "error"), limit=80), utc_now(), utc_now(), source_id),
                        )
                        self._audit(connection, "discovery_source_error", "discovery_source", source_id)
                    outcomes.append(
                        {
                            "source_id": source_id,
                            "company": source["company"],
                            "status": "error",
                            "run_id": run_id,
                            "message": message,
                            "verified_at": source["last_success_at"],
                        }
                    )
                    continue

                imported = updated = 0
                skipped = result.invalid_count
                seen_at = result.verified_at
                availability = self._current_availability_values()
                for raw_job in result.jobs:
                    try:
                        payload = dict(raw_job)
                        raw_source_id = clean_text(payload.get("source_id"), limit=240)
                        if not raw_source_id:
                            skipped += 1
                            continue
                        payload["source_id"] = f"{source_id}:{raw_source_id}"
                        imported_job = self.import_job(payload, availability=availability)
                        if imported_job["created"]:
                            imported += 1
                        else:
                            updated += 1
                        with self._lock, self._connection() as connection:
                            connection.execute(
                                """
                                UPDATE jobs
                                SET discovery_source_id = ?, last_seen_at = ?, last_verified_at = ?
                                WHERE id = ?
                                """,
                                (source_id, seen_at, seen_at, imported_job["id"]),
                            )
                    except UserFacingError:
                        # One malformed remote posting must not prevent other
                        # official postings on the same board from being saved.
                        skipped += 1

                with self._lock, self._connection() as connection:
                    # A successful full feed no longer showing an earlier role
                    # is evidence only that it was not observed now.  It is not
                    # safe to call the role closed automatically.
                    # Exclusion from a ranked top-150 or a malformed source
                    # row is not evidence that an earlier posting vanished.
                    # Preserve its last verified state and tracking instead.
                    if not result.truncated and not result.invalid_count:
                        connection.execute(
                            """
                            UPDATE jobs SET source_status = 'unknown', updated_at = ?
                            WHERE discovery_source_id = ? AND last_seen_at != ? AND source_status = 'open'
                            """,
                            (utc_now(), source_id, seen_at),
                        )
                    connection.execute(
                        """
                        UPDATE discovery_sources
                        SET last_success_at = ?, last_error_code = '', last_error_at = '', updated_at = ?
                        WHERE id = ?
                        """,
                        (seen_at, utc_now(), source_id),
                    )
                    # An additive setting, not a schema replacement. This
                    # fingerprint also makes an in-flight search using an old
                    # brief non-cacheable after the person saves new criteria.
                    connection.execute(
                        """
                        INSERT INTO career_settings (setting_key, setting_value) VALUES (?, ?)
                        ON CONFLICT(setting_key) DO UPDATE SET setting_value = excluded.setting_value
                        """,
                        (selection_key, selection_fingerprint),
                    )
                    self._audit(connection, "discovery_source_refreshed", "discovery_source", source_id)
                status = "partial" if skipped else "success"
                message = f"{len(result.jobs)} offre(s) publiée(s) vérifiée(s), {imported} nouvelle(s), {updated} actualisée(s)."
                if skipped:
                    message += f" {skipped} entrée(s) source ignorée(s) car incomplète(s) ou invalide(s)."
                if result.truncated:
                    message += (
                        f" Les 150 offres les plus pertinentes parmi {result.evaluated_count} entrées admissibles "
                        "ont été conservées après classement local selon tes critères "
                        "(ordre neutre et déterministe sans critères). "
                        "Les autres offres déjà suivies restent conservées."
                    )
                self._finish_discovery_run(
                    run_id,
                    status=status,
                    found_count=len(result.jobs),
                    imported_count=imported,
                    updated_count=updated,
                    skipped_count=skipped,
                    message=message,
                )
                outcomes.append(
                    {
                        "source_id": source_id,
                        "company": source["company"],
                        "status": status,
                        "run_id": run_id,
                        "found_count": len(result.jobs),
                        "imported_count": imported,
                        "updated_count": updated,
                        "skipped_count": skipped,
                        "verified_at": seen_at,
                        "message": message,
                    }
                )
            return {"outcomes": outcomes, "sources": self.list_discovery_sources()}
        finally:
            self._discovery_lock.release()

    def _replace_preferences(
        self,
        connection: sqlite3.Connection,
        kind: str,
        items: list[Any],
        *,
        allowed_items: dict[str, tuple[str, str]],
    ) -> None:
        if len(items) > 30:
            raise UserFacingError("Trop de préférences Career ont été envoyées.")
        seen: set[str] = set()
        for raw in items:
            if not isinstance(raw, dict):
                raise UserFacingError("Une préférence Career est invalide.")
            key = clean_text(raw.get("key"), limit=80)
            label = clean_text(raw.get("label"), limit=160)
            scope = clean_text(raw.get("scope"), limit=20) or "primary"
            if not key or not label or key in seen:
                raise UserFacingError("Les préférences Career doivent avoir des identifiants uniques.")
            expected = allowed_items.get(key)
            if expected is None or (label, scope) != expected:
                raise UserFacingError("Une préférence Career ne correspond pas à la configuration initiale.")
            seen.add(key)
            priority = self._bounded_int(raw.get("priority", 0), 0, 1_000, "La priorité")
            connection.execute(
                """
                INSERT INTO preference_items (kind, item_key, label, enabled, priority, scope)
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(kind, item_key) DO UPDATE SET
                    label = excluded.label, enabled = excluded.enabled,
                    priority = excluded.priority, scope = excluded.scope
                """,
                (kind, key, label, int(bool(raw.get("enabled", True))), priority, scope),
            )
        if seen != set(allowed_items):
            raise UserFacingError("Toutes les préférences Career initiales doivent être conservées ou désactivées.")

    @staticmethod
    def _bounded_int(value: Any, minimum: int, maximum: int, label: str) -> int:
        try:
            number = int(value)
        except (TypeError, ValueError) as error:
            raise UserFacingError(f"{label} doit être un nombre entier.") from error
        if not minimum <= number <= maximum:
            raise UserFacingError(f"{label} doit être compris entre {minimum} et {maximum}.")
        return number

    @staticmethod
    def _store_qualification_snapshot(
        connection: sqlite3.Connection,
        job_id: str,
        qualification: dict[str, Any],
        source_payload: dict[str, Any],
    ) -> None:
        """Replace derived metadata only when the current import supplied it."""
        snapshot = normalize_qualification_snapshot(qualification, source_payload)
        connection.execute(
            """
            INSERT INTO job_qualification_snapshots (
                job_id, schema_version, facts_json, provenance_json,
                missing_fields_json, reasons_json, source_fingerprint, updated_at
            ) VALUES (
                :job_id, :schema_version, :facts_json, :provenance_json,
                :missing_fields_json, :reasons_json, :source_fingerprint, :updated_at
            )
            ON CONFLICT(job_id) DO UPDATE SET
                schema_version = excluded.schema_version,
                facts_json = excluded.facts_json,
                provenance_json = excluded.provenance_json,
                missing_fields_json = excluded.missing_fields_json,
                reasons_json = excluded.reasons_json,
                source_fingerprint = excluded.source_fingerprint,
                updated_at = excluded.updated_at
            """,
            snapshot | {"job_id": job_id, "updated_at": utc_now()},
        )

    @staticmethod
    def _offer_intelligence_qualification(job: dict[str, Any]) -> dict[str, Any]:
        """Return the source-attributed qualification of one offer.

        The criteria of the person (contract types, excluded countries, minimum
        duration) are deliberately neutral here: the snapshot describes the
        offer, not the match between the offer and a brief.
        """
        try:
            return qualify_offer(job).to_dict()
        except (TypeError, ValueError):
            return {}

    @classmethod
    def _store_offer_intelligence(
        cls,
        connection: sqlite3.Connection,
        job: dict[str, Any],
        *,
        now: str,
    ) -> dict[str, Any]:
        """Derive and version the intelligence snapshot of one offer.

        An unchanged source keeps its version and its identifiers; a changed
        source creates a new version and retires the previous one, which stays
        in the history but is never presented as the current analysis.
        """
        snapshot = build_snapshot(
            job,
            cls._offer_intelligence_qualification(job),
            clock=lambda: now,
        )
        return offer_intelligence_store.store_snapshot(connection, snapshot, now=now)

    def _store_source_material(
        self, connection: sqlite3.Connection, job_id: str, payload: Mapping[str, Any], *, now: str
    ) -> None:
        """Reject only oversized/unusable source metadata, never the offer."""
        try:
            source_material_store.store_current(connection, job_id, payload, now=now)
        except (TypeError, ValueError):
            self._audit(connection, "source_material_rejected", "job", job_id)

    def import_job(self, payload: dict[str, Any], *, availability: dict[str, Any] | None = None,
                   preserve_unknown_source_fields: bool = False) -> dict[str, Any]:
        current_availability = availability or self._current_availability_values()
        qualification = payload.get("qualification")
        if not isinstance(qualification, dict):
            qualification = None
        job = self._normalize_job(payload, availability=current_availability)
        with self._lock, self._connection() as connection:
            existing = connection.execute("SELECT * FROM jobs WHERE dedup_key = ?", (job["dedup_key"],)).fetchone()
            # A person may have pasted an official offer before configuring the
            # company's board.  If a public source later returns exactly that
            # canonical official URL, refresh the same record rather than
            # creating a second opportunity with a different ATS source ID.
            if not existing and job["source_name"] != "manual" and job["official_url"]:
                existing = connection.execute(
                    "SELECT * FROM jobs WHERE official_url = ?", (job["official_url"],)
                ).fetchone()
            now = utc_now()
            if existing:
                job_id = str(existing["id"])
                if preserve_unknown_source_fields:
                    # Explorer receives a public ATS feed that often omits
                    # dates, duration and structured requirements. Absence is
                    # not evidence that previously recorded facts vanished.
                    # This opt-in is NOT applied to explicit manual edits or
                    # the existing personal-board discovery behaviour.
                    for key in ("city", "country", "posted_date", "deadline_date", "start_date", "end_date",
                                "duration_months", "employment_type", "role_level", "requirements",
                                "languages_required", "eligibility_requirement"):
                        if job.get(key) in {"", None} and existing[key] not in {"", None}:
                            job[key] = existing[key]
                    if job["job_family"] == "À préciser" and existing["job_family"] != "À préciser":
                        job["job_family"] = existing["job_family"]
                    assessment = self._calendar_assessment(job, current_availability)
                    job["calendar_status"] = assessment["status"]
                    job["calendar_reasons_json"] = json.dumps(assessment["reasons"], ensure_ascii=False)
                # A repeated import refreshes factual source fields but does not
                # erase a user's shortlist, status, personal note or application.
                connection.execute(
                    """
                    UPDATE jobs SET source_name = :source_name, source_id = :source_id,
                        official_url = :official_url, company = :company, title = :title,
                        job_family = :job_family, city = :city, country = :country,
                        posted_date = :posted_date, deadline_date = :deadline_date,
                        start_date = :start_date, end_date = :end_date,
                        duration_months = :duration_months, source_status = :source_status,
                        calendar_status = :calendar_status, calendar_reasons_json = :calendar_reasons_json,
                        employment_type = :employment_type, role_level = :role_level,
                        requirements = :requirements, languages_required = :languages_required,
                        eligibility_requirement = :eligibility_requirement,
                        description_original = :description_original, updated_at = :updated_at,
                        last_verified_at = :last_verified_at
                    WHERE id = :id
                    """,
                    job | {"id": job_id, "updated_at": now, "last_verified_at": now},
                )
                self._audit(connection, "job_refreshed_without_duplicate", "job", job_id)
                store_qualification = qualification is not None
                if store_qualification:
                    saved_snapshot = connection.execute(
                        "SELECT facts_json, source_fingerprint FROM job_qualification_snapshots WHERE job_id = ?",
                        (job_id,),
                    ).fetchone()
                    if saved_snapshot is not None:
                        try:
                            saved_facts = json.loads(saved_snapshot["facts_json"] or "{}")
                        except (TypeError, ValueError, json.JSONDecodeError):
                            saved_facts = {}
                        incoming_fingerprint = normalize_qualification_snapshot({}, payload)["source_fingerprint"]
                        if (
                            isinstance(saved_facts, dict)
                            and saved_facts.get("verification_status") == "verified"
                            and qualification.get("verification_status") != "verified"
                            and saved_snapshot["source_fingerprint"] == incoming_fingerprint
                        ):
                            # A same-text manual/API refresh cannot downgrade
                            # an official qualification. Changed source text
                            # gets a new, unverified snapshot and fails the
                            # current-source fingerprint check as expected.
                            store_qualification = False
                if store_qualification:
                    self._store_qualification_snapshot(connection, job_id, qualification, payload)
                self._store_offer_intelligence(connection, {**job, "id": job_id}, now=now)
                self._store_source_material(connection, job_id, payload, now=now)
                created = False
            else:
                job_id = f"job_{uuid.uuid4().hex}"
                connection.execute(
                    """
                    INSERT INTO jobs (
                        id, dedup_key, source_name, source_id, official_url, company, title, job_family,
                        city, country, posted_date, deadline_date, start_date, end_date, duration_months,
                        source_status, calendar_status, calendar_reasons_json, employment_type, role_level,
                        requirements, languages_required, eligibility_requirement, description_original,
                        personal_note, status, shortlisted, created_at, updated_at, last_verified_at
                    ) VALUES (
                        :id, :dedup_key, :source_name, :source_id, :official_url, :company, :title, :job_family,
                        :city, :country, :posted_date, :deadline_date, :start_date, :end_date, :duration_months,
                        :source_status, :calendar_status, :calendar_reasons_json, :employment_type, :role_level,
                        :requirements, :languages_required, :eligibility_requirement, :description_original,
                        '', 'discovered', 0, :created_at, :updated_at, :last_verified_at
                    )
                    """,
                    job | {"id": job_id, "created_at": now, "updated_at": now, "last_verified_at": now},
                )
                audit_source = re.sub(r"[^a-z0-9_-]+", "_", job["source_name"].lower()).strip("_") or "manual"
                self._audit(connection, f"job_imported_{audit_source}", "job", job_id)
                if qualification is not None:
                    self._store_qualification_snapshot(connection, job_id, qualification, payload)
                self._store_offer_intelligence(connection, {**job, "id": job_id}, now=now)
                self._store_source_material(connection, job_id, payload, now=now)
                created = True
        result = self.get_job(job_id)
        result["created"] = created
        result["duplicate"] = not created
        return result

    def _normalize_job(self, payload: dict[str, Any], *, availability: dict[str, Any]) -> dict[str, Any]:
        company = clean_text(payload.get("company"), limit=240)
        title = clean_text(payload.get("title"), limit=300)
        if not company or not title:
            raise UserFacingError("L’entreprise et l’intitulé du poste sont obligatoires.")
        source_name = clean_text(payload.get("source_name"), limit=120) or "manual"
        source_id = clean_text(payload.get("source_id"), limit=240)
        official_url = canonical_url(payload.get("official_url")) if clean_text(payload.get("official_url")) else ""
        job_family = clean_text(payload.get("job_family"), limit=160) or "À préciser"
        if job_family == "À préciser":
            job_family = classify_job_family(
                clean_text(payload.get("title"), limit=300),
                clean_text(payload.get("description_original"), limit=30_000),
            )
        if job_family != "À préciser" and job_family not in {
            *JOB_FAMILIES,
            "Markets / Quant",
            "Corporate Finance / FP&A",
        }:
            raise UserFacingError("La famille professionnelle sélectionnée est inconnue.")
        duration_raw = payload.get("duration_months")
        duration = None
        if clean_text(duration_raw):
            duration = self._bounded_int(duration_raw, 1, 24, "La durée du stage")
        assessment = self._calendar_assessment(
            {
                "start_date": clean_text(payload.get("start_date")) or None,
                "end_date": clean_text(payload.get("end_date")) or None,
                "duration_months": duration,
            },
            availability,
        )
        posted = date_text(parse_date(payload.get("posted_date"), "La date de publication"))
        deadline = date_text(parse_date(payload.get("deadline_date"), "La date limite"))
        source_status = validate_choice(
            payload.get("source_status"), AVAILABILITY_STATES, "Le statut de disponibilité", "unknown"
        )
        return {
            "dedup_key": dedup_key(
                source_name=source_name,
                source_id=source_id,
                official_url=official_url,
                company=company,
                title=title,
                city=clean_text(payload.get("city"), limit=160),
            ),
            "source_name": source_name,
            "source_id": source_id,
            "official_url": official_url,
            "company": company,
            "title": title,
            "job_family": job_family,
            "city": clean_text(payload.get("city"), limit=160),
            "country": clean_text(payload.get("country"), limit=120),
            "posted_date": posted,
            "deadline_date": deadline,
            "start_date": date_text(parse_date(payload.get("start_date"), "La date de début")),
            "end_date": date_text(parse_date(payload.get("end_date"), "La date de fin")),
            "duration_months": duration,
            "source_status": source_status,
            "calendar_status": assessment["status"],
            "calendar_reasons_json": json.dumps(assessment["reasons"], ensure_ascii=False),
            "employment_type": clean_text(payload.get("employment_type"), limit=120),
            "role_level": clean_text(payload.get("role_level"), limit=120),
            "requirements": clean_text(payload.get("requirements"), limit=12_000),
            "languages_required": clean_text(payload.get("languages_required"), limit=2_000),
            "eligibility_requirement": clean_text(payload.get("eligibility_requirement"), limit=2_000),
            "description_original": clean_text(payload.get("description_original"), limit=30_000),
        }

    def get_job(
        self, job_id: str, *, scoring_context: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        with self._lock, self._connection() as connection:
            row = connection.execute(
                """
                SELECT jobs.*, applications.id AS application_id, applications.stage AS application_stage,
                       applications.receipt_status AS application_receipt_status,
                       applications.approval_granted AS application_approval_granted,
                       job_qualification_snapshots.schema_version AS qualification_schema_version,
                       job_qualification_snapshots.facts_json AS qualification_facts_json,
                       job_qualification_snapshots.provenance_json AS qualification_provenance_json,
                       job_qualification_snapshots.missing_fields_json AS qualification_missing_json,
                       job_qualification_snapshots.reasons_json AS qualification_reasons_json,
                       job_qualification_snapshots.source_fingerprint AS qualification_source_fingerprint,
                       job_qualification_snapshots.updated_at AS qualification_updated_at
                FROM jobs
                LEFT JOIN applications ON applications.job_id = jobs.id
                LEFT JOIN job_qualification_snapshots ON job_qualification_snapshots.job_id = jobs.id
                WHERE jobs.id = ?
                """,
                (job_id,),
            ).fetchone()
            if not row:
                raise UserFacingError("Cette offre Career n’existe pas.")
            context = scoring_context if scoring_context is not None else self._scoring_context()
            result = self._serialize_job(row, context)
            self._attach_offer_intelligence(connection, result, full=True)
            self._attach_source_material(connection, result)
        return result

    @staticmethod
    def _attach_source_material(connection: sqlite3.Connection, result: dict[str, Any]) -> None:
        """Expose the exact, attributed source fields as unverified material."""
        snapshot = source_material_store.load_current(connection, str(result.get("id") or ""))
        result["source_material"] = snapshot

    @staticmethod
    def _attach_offer_intelligence(
        connection: sqlite3.Connection,
        result: dict[str, Any],
        *,
        full: bool = False,
    ) -> None:
        """Attach the current intelligence snapshot of one offer.

        The explorer only receives the compact summary: it points at the very
        same identifiers as the detailed view, it never recomputes them.
        """
        job_id = str(result.get("id") or "")
        current = offer_intelligence_store.load_current(connection, job_id)
        if current is None:
            result["offer_intelligence"] = None
            result["offer_intelligence_summary"] = None
            result["offer_intelligence_version"] = None
            result["offer_intelligence_current"] = False
            return
        result["offer_intelligence_summary"] = snapshot_summary(current["snapshot"])
        result["offer_intelligence_version"] = current["version"]
        result["offer_intelligence_current"] = True
        if full:
            result["offer_intelligence"] = current["snapshot"]
        else:
            result["offer_intelligence"] = None

    def get_offer_intelligence(self, job_id: str) -> dict[str, Any]:
        """Return the current intelligence snapshot of one offer, with its history."""
        job = self.get_job(job_id)
        with self._lock, self._connection() as connection:
            history = offer_intelligence_store.load_history(connection, job_id)
        return {
            "job_id": job_id,
            "snapshot": job.get("offer_intelligence"),
            "summary": job.get("offer_intelligence_summary"),
            "version": job.get("offer_intelligence_version"),
            "history": history,
        }

    def get_quick_answers(self, job_id: str, lang: str = "fr") -> dict[str, Any]:
        """SPEC-045 — réponses types copiables calculées depuis les données locales.

        Zéro invention : une information absente donne une réponse ``missing``
        à valeur vide, à compléter par la personne.  Aucune donnée ne quitte
        l'espace local et rien n'est soumis automatiquement.
        """
        normalized_lang = clean_text(lang, limit=8).lower() or "fr"
        if normalized_lang not in SUPPORTED_LANGS:
            raise UserFacingError("La langue demandée doit être fr ou en.")
        with self._lock, self._connection() as connection:
            row = connection.execute(
                "SELECT * FROM jobs WHERE id = ?",
                (clean_text(job_id, limit=80),),
            ).fetchone()
            if not row:
                raise UserFacingError("Cette offre Career n’existe pas.")
            job = self._row_dict(row)
            profile = self._row_dict(
                connection.execute("SELECT * FROM candidate_profile WHERE id = 1").fetchone()
            )
            preference_rows = connection.execute(
                "SELECT kind, item_key, label, enabled, priority, scope "
                "FROM preference_items ORDER BY kind, priority DESC, label"
            ).fetchall()
            settings = {
                setting["setting_key"]: setting["setting_value"]
                for setting in connection.execute(
                    "SELECT setting_key, setting_value FROM career_settings"
                ).fetchall()
            }
        preferences = self._serialize_preferences(preference_rows, settings)
        answers = build_answer_pack(profile=profile, job=job, preferences=preferences, lang=normalized_lang)
        return {
            "job_id": str(job.get("id") or ""),
            "lang": normalized_lang,
            "answers": [answer.to_dict() for answer in answers],
        }

    def list_jobs(
        self,
        *,
        query: str = "",
        family: str = "",
        city: str = "",
        source_status: str = "",
        shortlisted: bool | None = None,
        calendar_status: str = "",
        _scoring_context: dict[str, Any] | None = None,
        _include_scoring: bool = True,
    ) -> list[dict[str, Any]]:
        clauses = ["1 = 1"]
        params: list[Any] = []
        if query := clean_text(query, limit=240):
            clauses.append("(lower(company) LIKE ? OR lower(title) LIKE ? OR lower(city) LIKE ?)")
            like = f"%{query.lower()}%"
            params.extend([like, like, like])
        if family:
            clauses.append("job_family = ?")
            params.append(clean_text(family, limit=160))
        if city:
            clauses.append("lower(city) LIKE ?")
            params.append(f"%{clean_text(city, limit=160).lower()}%")
        if source_status:
            clauses.append("source_status = ?")
            params.append(validate_choice(source_status, AVAILABILITY_STATES, "Le statut de disponibilité", "unknown"))
        if shortlisted is not None:
            clauses.append("shortlisted = ?")
            params.append(int(shortlisted))
        if calendar_status:
            clauses.append("calendar_status = ?")
            params.append(clean_text(calendar_status, limit=80))
        statement = f"""
            SELECT jobs.*, applications.id AS application_id, applications.stage AS application_stage,
                   applications.receipt_status AS application_receipt_status,
                   applications.approval_granted AS application_approval_granted,
                   job_qualification_snapshots.schema_version AS qualification_schema_version,
                   job_qualification_snapshots.facts_json AS qualification_facts_json,
                   job_qualification_snapshots.provenance_json AS qualification_provenance_json,
                   job_qualification_snapshots.missing_fields_json AS qualification_missing_json,
                   job_qualification_snapshots.reasons_json AS qualification_reasons_json,
                   job_qualification_snapshots.source_fingerprint AS qualification_source_fingerprint,
                   job_qualification_snapshots.updated_at AS qualification_updated_at
            FROM jobs
            LEFT JOIN applications ON applications.job_id = jobs.id
            LEFT JOIN job_qualification_snapshots ON job_qualification_snapshots.job_id = jobs.id
            WHERE {' AND '.join(clauses)}
            ORDER BY shortlisted DESC,
                CASE source_status WHEN 'open' THEN 0 WHEN 'unknown' THEN 1 ELSE 2 END,
                CASE WHEN deadline_date IS NULL OR deadline_date = '' THEN 1 ELSE 0 END,
                deadline_date ASC, updated_at DESC
        """
        with self._lock, self._connection() as connection:
            rows = connection.execute(statement, params).fetchall()
            summaries: dict[str, dict[str, Any]] = {}
            versions: dict[str, int] = {}
            for item in connection.execute(
                "SELECT job_id, version, summary_json FROM job_offer_intelligence_snapshots "
                "WHERE is_current = 1"
            ).fetchall():
                identifier = str(item["job_id"])
                versions[identifier] = int(item["version"] or 0)
                try:
                    payload = json.loads(item["summary_json"] or "{}")
                except (TypeError, ValueError):
                    payload = {}
                summaries[identifier] = payload if isinstance(payload, dict) else {}
            source_material = source_material_store.load_current_all(connection)
        context = _scoring_context
        if _include_scoring and context is None:
            context = self._scoring_context()
        jobs = [
            self._serialize_job(row, context, include_scoring=_include_scoring)
            for row in rows
        ]
        for job in jobs:
            # The explorer shows the identifiers of the current snapshot: it
            # never recomputes a requirement on its own. The summary is the
            # very same document as the detailed view, while source material
            # stays a separately labelled set of publisher-provided fields.
            identifier = str(job.get("id") or "")
            summary = summaries.get(identifier)
            job["offer_intelligence_summary"] = summary
            job["offer_intelligence"] = None
            job["offer_intelligence_current"] = identifier in versions
            job["offer_intelligence_version"] = versions.get(identifier)
            job["source_material"] = source_material.get(identifier)
        source_rank = {"open": 0, "unknown": 1, "closed": 2}
        if _include_scoring:
            jobs.sort(
                key=lambda job: (
                    bool(job["scoring"].get("blocking_constraints")),
                    not bool(job["scoring"].get("is_recommendable")),
                    -int(job["scoring"].get("score", 0)),
                    source_rank.get(str(job.get("source_status")), 3),
                    not bool(job.get("deadline_date")),
                    str(job.get("deadline_date") or "9999-12-31"),
                    str(job.get("updated_at") or ""),
                )
            )
        return jobs

    def _scoring_context(self) -> dict[str, Any]:
        """Load current local facts once; scores are never persisted stale."""
        with self._lock, self._connection() as connection:
            profile = self._row_dict(
                connection.execute("SELECT * FROM candidate_profile WHERE id = 1").fetchone()
            )
            preference_rows = connection.execute(
                "SELECT kind, item_key, label, enabled, priority, scope FROM preference_items ORDER BY kind, priority DESC, label"
            ).fetchall()
            settings = {
                row["setting_key"]: row["setting_value"]
                for row in connection.execute("SELECT setting_key, setting_value FROM career_settings").fetchall()
            }
            intake_row = connection.execute("SELECT * FROM career_intake WHERE id = 1").fetchone()
        return {
            "profile": profile,
            "preferences": self._serialize_preferences(preference_rows, settings),
            "intake": self._serialize_intake_row(intake_row) if intake_row else {},
        }

    def _serialize_job(
        self,
        row: sqlite3.Row,
        context: dict[str, Any] | None = None,
        *,
        include_scoring: bool = True,
    ) -> dict[str, Any]:
        result = dict(row)
        qualification_row = {
            "qualification_schema_version": result.pop("qualification_schema_version", None),
            "qualification_facts_json": result.pop("qualification_facts_json", None),
            "qualification_provenance_json": result.pop("qualification_provenance_json", None),
            "qualification_missing_json": result.pop("qualification_missing_json", None),
            "qualification_reasons_json": result.pop("qualification_reasons_json", None),
            "qualification_source_fingerprint": result.pop("qualification_source_fingerprint", None),
            "qualification_updated_at": result.pop("qualification_updated_at", None),
        }
        result["qualification_facts"] = decode_qualification_snapshot(qualification_row)
        snapshot_current = snapshot_matches_current_source(result)
        result["qualification_snapshot_current"] = snapshot_current
        source_trust = check_trust(
            result.get("official_url") or "",
            employer_hint=result.get("company") or "",
            declared_provider=result.get("source_name") or "",
            clock=lambda: clean_text(result.get("last_verified_at") or result.get("updated_at"), limit=40)
            or "unknown",
        ).to_dict()
        result["official_source_trust"] = source_trust
        result["official_source_trust_label"] = source_trust_label(source_trust["status"])
        # Trust is reconstructed only from a current, source-attributed
        # snapshot or from a job tied to a discovery source after a successful
        # feed read. A manual import cannot become verified by claiming a flag.
        result["source_verified"] = bool(
            result.get("official_url")
            and result.get("last_verified_at")
            and source_trust["status"] == "verified"
            and (
                (
                    snapshot_current
                    and result["qualification_facts"].get("verification_status") == "verified"
                )
                or result.get("discovery_source_id")
            )
        )
        result["shortlisted"] = bool(result["shortlisted"])
        result["calendar_reasons"] = json.loads(result.pop("calendar_reasons_json") or "[]")
        result["deadline_status"] = deadline_state(result.get("deadline_date"), result.get("source_status", "unknown"))
        if include_scoring:
            context = context or self._scoring_context()
            result["scoring"] = score_job(
                context.get("profile"), context.get("preferences"), context.get("intake"), result
            )
        application_id = result.pop("application_id", None)
        stage = result.pop("application_stage", None)
        receipt = result.pop("application_receipt_status", None)
        approval = result.pop("application_approval_granted", None)
        result["application"] = (
            {
                "id": application_id,
                "stage": stage,
                "receipt_status": receipt,
                "approval_granted": bool(approval),
            }
            if application_id
            else None
        )
        return result

    def set_shortlist(self, job_id: str, shortlisted: bool, note: str = "") -> dict[str, Any]:
        with self._lock, self._connection() as connection:
            current = connection.execute("SELECT id, status FROM jobs WHERE id = ?", (job_id,)).fetchone()
            if not current:
                raise UserFacingError("Cette offre Career n’existe pas.")
            status = "shortlisted" if shortlisted else ("discovered" if current["status"] == "shortlisted" else current["status"])
            connection.execute(
                "UPDATE jobs SET shortlisted = ?, status = ?, personal_note = ?, updated_at = ? WHERE id = ?",
                (int(shortlisted), status, clean_text(note, limit=4_000), utc_now(), job_id),
            )
            self._audit(connection, "job_shortlisted" if shortlisted else "job_removed_from_shortlist", "job", job_id)
        return self.get_job(job_id)

    def update_job_note(self, job_id: str, note: str) -> dict[str, Any]:
        with self._lock, self._connection() as connection:
            result = connection.execute(
                "UPDATE jobs SET personal_note = ?, updated_at = ? WHERE id = ?",
                (clean_text(note, limit=4_000), utc_now(), job_id),
            )
            if result.rowcount != 1:
                raise UserFacingError("Cette offre Career n’existe pas.")
            self._audit(connection, "job_note_updated", "job", job_id)
        return self.get_job(job_id)

    def delete_job(self, job_id: str) -> None:
        with self._lock, self._connection() as connection:
            result = connection.execute("DELETE FROM jobs WHERE id = ?", (job_id,))
            if result.rowcount != 1:
                raise UserFacingError("Cette offre Career n’existe pas.")
            self._audit(connection, "job_deleted", "job", job_id)

    def create_application(self, job_id: str) -> dict[str, Any]:
        with self._lock, self._connection() as connection:
            job = connection.execute("SELECT id FROM jobs WHERE id = ?", (job_id,)).fetchone()
            if not job:
                raise UserFacingError("Cette offre Career n’existe pas.")
            existing = connection.execute("SELECT id FROM applications WHERE job_id = ?", (job_id,)).fetchone()
            if existing:
                application_id = str(existing["id"])
                created = False
            else:
                application_id = f"app_{uuid.uuid4().hex}"
                now = utc_now()
                connection.execute(
                    """
                    INSERT INTO applications (id, job_id, stage, receipt_status, approval_granted, confirmation_reference, created_at, updated_at)
                    VALUES (?, ?, 'to_review', 'not_submitted', 0, '', ?, ?)
                    """,
                    (application_id, job_id, now, now),
                )
                self._application_event(connection, application_id, job_id, "application_created", "")
                self._audit(connection, "application_created", "application", application_id)
                created = True
        record = self.get_application(application_id)
        record["created"] = created
        return record

    def _application_event(
        self,
        connection: sqlite3.Connection,
        application_id: str,
        job_id: str,
        event_type: str,
        detail: str,
    ) -> None:
        connection.execute(
            """
            INSERT INTO application_events (id, application_id, job_id, event_type, detail, created_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (f"event_{uuid.uuid4().hex}", application_id, job_id, event_type, clean_text(detail, limit=1_000), utc_now()),
        )

    def get_application(self, application_id: str) -> dict[str, Any]:
        with self._lock, self._connection() as connection:
            row = connection.execute(
                """
                SELECT applications.*, jobs.company, jobs.title, jobs.city, jobs.country, jobs.official_url,
                       jobs.deadline_date, jobs.calendar_status, jobs.source_status
                FROM applications JOIN jobs ON jobs.id = applications.job_id WHERE applications.id = ?
                """,
                (application_id,),
            ).fetchone()
            events = connection.execute(
                "SELECT event_type, detail, created_at FROM application_events WHERE application_id = ? ORDER BY created_at DESC",
                (application_id,),
            ).fetchall()
        if not row:
            raise UserFacingError("Cette candidature Career n’existe pas.")
        result = dict(row)
        result["approval_granted"] = bool(result["approval_granted"])
        result["events"] = [dict(event) for event in events]
        return result

    def list_applications(self) -> list[dict[str, Any]]:
        with self._lock, self._connection() as connection:
            rows = connection.execute(
                """
                SELECT applications.*, jobs.company, jobs.title, jobs.city, jobs.country, jobs.official_url,
                       jobs.deadline_date, jobs.calendar_status, jobs.source_status
                FROM applications JOIN jobs ON jobs.id = applications.job_id
                ORDER BY applications.updated_at DESC
                """
            ).fetchall()
        records: list[dict[str, Any]] = []
        for row in rows:
            record = dict(row)
            record["approval_granted"] = bool(record["approval_granted"])
            records.append(record)
        return records

    def application_dashboard(
        self,
        *,
        stage: str = "",
        receipt: str = "",
        action_required: bool | None = None,
        deadline: str = "",
        query: str = "",
    ) -> dict[str, Any]:
        """CVBOOST-09 : projection déterministe des candidatures suivies.

        Réutilise les événements et les états existants, sans migration et
        sans réseau. Toute donnée imprévisible reste un inconnu affiché, jamais
        un chiffre inventé ; une ligne SQLite n'est jamais un envoi.
        """
        normalized_stage = clean_text(stage, limit=80)
        if normalized_stage and normalized_stage not in APPLICATION_STAGES:
            raise UserFacingError("Ce statut de filtre est invalide.")
        normalized_receipt = clean_text(receipt, limit=80)
        if normalized_receipt and normalized_receipt not in RECEIPT_FILTER_VALUES[1:]:
            raise UserFacingError("Ce filtre de réception est invalide.")
        normalized_deadline = clean_text(deadline, limit=40)
        if normalized_deadline and normalized_deadline not in DEADLINE_FILTER_VALUES[1:]:
            raise UserFacingError("Ce filtre d’échéance est invalide.")
        action_filter: bool | None = None
        if action_required is not None:
            action_filter = bool(action_required)
        with self._lock, self._connection() as connection:
            application_rows = connection.execute(
                """
                SELECT a.id AS application_id, a.job_id, a.stage, a.receipt_status,
                       a.approval_granted, a.confirmation_reference,
                       a.created_at AS application_created_at, a.updated_at AS application_updated_at,
                       j.id AS joined_job_id, j.company, j.title, j.city, j.country, j.official_url,
                       j.deadline_date, j.source_status, j.employment_type, j.role_level,
                       j.requirements, j.languages_required, j.eligibility_requirement,
                       j.description_original, j.job_family
                FROM applications a JOIN jobs j ON a.job_id = j.id
                ORDER BY a.updated_at DESC, a.id ASC
                LIMIT ?
                """,
                (MAX_DASHBOARD_APPLICATIONS,),
            ).fetchall()
            total_applications = int(
                connection.execute("SELECT COUNT(*) AS total FROM applications").fetchone()["total"]
            )
            events_by_application: dict[str, list[dict[str, Any]]] = {}
            application_ids = [str(row["application_id"]) for row in application_rows]
            if application_ids:
                placeholders = ", ".join("?" for _ in application_ids)
                event_rows = connection.execute(
                    f"""
                    SELECT application_id, event_type, detail, created_at
                    FROM application_events
                    WHERE application_id IN ({placeholders})
                    ORDER BY created_at ASC
                    """,
                    application_ids,
                ).fetchall()
                for event_row in event_rows:
                    events_by_application.setdefault(str(event_row["application_id"]), []).append(dict(event_row))
            jobs_by_id: dict[str, dict[str, Any]] = {}
            for row in application_rows:
                job_id = str(row["job_id"])
                if job_id in jobs_by_id:
                    continue
                job_row = connection.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()
                jobs_by_id[job_id] = dict(job_row) if job_row else {}
            # The checklist reads the very same snapshot as the other screens.
            for job_id in list(jobs_by_id):
                snapshot = offer_intelligence_store.load_snapshot(connection, job_id)
                if snapshot:
                    jobs_by_id[job_id]["offer_intelligence"] = snapshot
        context = self._scoring_context()
        return build_dashboard_payload(
            [dict(row) for row in application_rows],
            events_by_application,
            jobs_by_id,
            context.get("profile") or {},
            context.get("intake") or {},
            today=date.today(),
            now_iso=utc_now(),
            total_applications=total_applications,
            stage=normalized_stage,
            receipt=normalized_receipt,
            action_required=action_filter,
            deadline=normalized_deadline,
            query=query,
        )

    def set_application_checklist(self, application_id: str, checked: list[str]) -> dict[str, Any]:
        """Enregistre l'état local de la checklist dans le journal existant.

        Aucun changement de schéma : un événement ``checklist`` porte l'état
        complet en JSON, le dernier événement faisant foi. Rien n'est envoyé,
        nulle part.
        """
        cleaned = [clean_text(item, limit=80) for item in (checked or []) if clean_text(item, limit=80)]
        unknown_keys = sorted(set(cleaned) - CHECKLIST_KEYS)
        if unknown_keys:
            raise UserFacingError("Cette case de checklist est inconnue : " + ", ".join(unknown_keys))
        with self._lock, self._connection() as connection:
            application = connection.execute(
                "SELECT job_id FROM applications WHERE id = ?", (application_id,)
            ).fetchone()
            if not application:
                raise UserFacingError("Cette candidature Career n’existe pas.")
            detail = json.dumps(
                {"items": {key: True for key in sorted(set(cleaned))}},
                ensure_ascii=False,
            )
            self._application_event(
                connection, application_id, str(application["job_id"]), CHECKLIST_EVENT_TYPE, detail
            )
            self._audit(connection, "application_checklist_updated", "application", application_id)
        result = self.get_application(application_id)
        result["checklist"] = {
            "checked_keys": sorted(set(cleaned)),
            "unknown": False,
        }
        return result


    def update_application_stage(self, application_id: str, stage: str, note: str = "") -> dict[str, Any]:
        normalized_stage = clean_text(stage, limit=80)
        if normalized_stage not in GENERIC_APPLICATION_STAGES:
            raise UserFacingError(
                "Ce statut ne peut pas être défini directement. Une réception confirmée nécessite une action séparée."
            )
        with self._lock, self._connection() as connection:
            application = connection.execute(
                "SELECT job_id, stage, receipt_status, approval_granted FROM applications WHERE id = ?",
                (application_id,),
            ).fetchone()
            if not application:
                raise UserFacingError("Cette candidature Career n’existe pas.")
            # Recording "Envoyée" only states the person's own manual action,
            # but it must still follow the explicit approval for this offer:
            # nothing may be presented as deposited without that validation.
            if normalized_stage == "submitted" and not application["approval_granted"]:
                raise UserFacingError(
                    "Approuve d’abord le dépôt manuel pour cette offre avant d’enregistrer son envoi."
                )
            if (
                application["receipt_status"] == "confirmed"
                and normalized_stage
                not in {"response_received", "interview", "offer_received", "rejected", "refused", "withdrawn"}
            ):
                raise UserFacingError(
                    "Une candidature dont la réception est confirmée ne peut pas revenir à un statut antérieur."
                )
            # "Envoyée" is a person-declared deposit: the receipt is unknown
            # until a confirmation reference is recorded separately.
            receipt_status = (
                "unknown" if normalized_stage in {"receipt_unknown", "submitted"} else None
            )
            if receipt_status:
                connection.execute(
                    "UPDATE applications SET stage = ?, receipt_status = ?, updated_at = ? WHERE id = ?",
                    (normalized_stage, receipt_status, utc_now(), application_id),
                )
            else:
                connection.execute(
                    "UPDATE applications SET stage = ?, updated_at = ? WHERE id = ?",
                    (normalized_stage, utc_now(), application_id),
                )
            self._application_event(connection, application_id, str(application["job_id"]), "stage_updated", note)
            self._audit(connection, "application_stage_updated", "application", application_id)
        return self.get_application(application_id)

    def approve_for_manual_submission(self, application_id: str, approved: bool, note: str = "") -> dict[str, Any]:
        if not approved:
            raise UserFacingError("L’approbation explicite est requise pour cette offre précise.")
        with self._lock, self._connection() as connection:
            application = connection.execute(
                "SELECT job_id, approval_granted, receipt_status FROM applications WHERE id = ?", (application_id,)
            ).fetchone()
            if not application:
                raise UserFacingError("Cette candidature Career n’existe pas.")
            if application["receipt_status"] == "confirmed":
                raise UserFacingError("La réception de cette candidature est déjà confirmée.")
            if application["approval_granted"]:
                return self.get_application(application_id)
            connection.execute(
                """
                UPDATE applications SET approval_granted = 1, stage = 'approved_for_manual_submission', updated_at = ?
                WHERE id = ?
                """,
                (utc_now(), application_id),
            )
            self._application_event(
                connection,
                application_id,
                str(application["job_id"]),
                "manual_submission_approved",
                note,
            )
            self._audit(connection, "application_manual_submission_approved", "application", application_id)
        return self.get_application(application_id)

    def confirm_receipt(self, application_id: str, confirmation_reference: str) -> dict[str, Any]:
        reference = clean_text(confirmation_reference, limit=1_000)
        if len(reference) < 2:
            raise UserFacingError("Indique une référence ou une note de confirmation de réception.")
        with self._lock, self._connection() as connection:
            application = connection.execute(
                "SELECT job_id, receipt_status, approval_granted FROM applications WHERE id = ?", (application_id,)
            ).fetchone()
            if not application:
                raise UserFacingError("Cette candidature Career n’existe pas.")
            if not application["approval_granted"]:
                raise UserFacingError(
                    "Approuve d’abord le dépôt manuel pour cette offre précise avant de confirmer sa réception."
                )
            if application["receipt_status"] == "confirmed":
                raise UserFacingError("Cette candidature possède déjà une confirmation de réception.")
            connection.execute(
                """
                UPDATE applications SET stage = 'submitted_confirmed', receipt_status = 'confirmed',
                    confirmation_reference = ?, updated_at = ? WHERE id = ?
                """,
                (reference, utc_now(), application_id),
            )
            self._application_event(
                connection,
                application_id,
                str(application["job_id"]),
                "receipt_confirmed",
                reference,
            )
            self._audit(connection, "application_receipt_confirmed", "application", application_id)
        return self.get_application(application_id)

    def mark_receipt_unknown(self, application_id: str, note: str) -> dict[str, Any]:
        with self._lock, self._connection() as connection:
            application = connection.execute(
                "SELECT job_id, receipt_status FROM applications WHERE id = ?", (application_id,)
            ).fetchone()
            if not application:
                raise UserFacingError("Cette candidature Career n’existe pas.")
            if application["receipt_status"] == "confirmed":
                raise UserFacingError("La réception de cette candidature est déjà confirmée.")
            connection.execute(
                """
                UPDATE applications SET stage = 'receipt_unknown', receipt_status = 'unknown', updated_at = ?
                WHERE id = ?
                """,
                (utc_now(), application_id),
            )
            self._application_event(
                connection, application_id, str(application["job_id"]), "receipt_unknown", note
            )
            self._audit(connection, "application_receipt_unknown", "application", application_id)
        return self.get_application(application_id)

    # ------------------------------------------------------------------
    # SPEC-047 — Confirmation d'envoi humaine + relance optimale
    #
    # L'envoi n'est jamais simulé ni déclenché ici : la personne effectue le
    # dépôt manuel (déjà encadré par l'approbation explicite de l'offre) puis
    # déclare ce dépôt via ``record_send``. Le tracking passe alors à
    # « envoyée » (stage ``submitted``), et uniquement alors. La preuve
    # déclarée vit dans le journal ``application_events`` (event_type
    # ``send_confirmation``) : aucun changement de schéma, l'état reste
    # rejouable. Une relance déjà faite (``followup_recorded``) décale la
    # prochaine échéance de sept jours ouvrés. Rien n'est jamais transmis :
    # la relance reste un brouillon local à copier.
    # ------------------------------------------------------------------

    @staticmethod
    def _send_events(connection: sqlite3.Connection, application_id: str) -> list[dict[str, Any]]:
        rows = connection.execute(
            """
            SELECT id, event_type, detail, created_at FROM application_events
            WHERE application_id = ? ORDER BY created_at ASC, rowid ASC
            """,
            (application_id,),
        ).fetchall()
        return [dict(row) for row in rows]

    def _send_record_response(
        self,
        *,
        job_id: str,
        application_id: str,
        created: bool,
        note: str | None = None,
    ) -> dict[str, Any]:
        """Reconstruit la réponse complète (record + brouillon) depuis le journal."""
        with self._lock, self._connection() as connection:
            events = self._send_events(connection, application_id)
            application = connection.execute(
                "SELECT stage, receipt_status, confirmation_reference FROM applications WHERE id = ?",
                (application_id,),
            ).fetchone()
            job = connection.execute(
                "SELECT company, title FROM jobs WHERE id = ?", (job_id,)
            ).fetchone()
        if application is None or job is None:
            raise UserFacingError("Cette candidature Career n’existe pas.")
        send = latest_send_evidence(events)
        if send is None:
            raise UserFacingError("Aucun envoi déclaré pour cette offre.")
        evidence_note = send[1].get("note")
        last_followup = latest_followup_on(events)
        record = send_record_from_payload(job_id, send[1], last_followup_on=last_followup)
        if record is None:
            raise UserFacingError("L'envoi déclaré est illisible : enregistre-le à nouveau.")
        draft = build_followup_draft(
            title=str(job["title"]),
            company=str(job["company"]),
            channel=record.channel,
            sent_at=record.sent_at,
            reference=str(application["confirmation_reference"] or ""),
        )
        return {
            "record": send_record_to_dict(record, note=evidence_note if note is None else note),
            "job_id": job_id,
            "application_id": application_id,
            "created": created,
            "stage": str(application["stage"]),
            "receipt_status": str(application["receipt_status"]),
            "followup_done_on": last_followup.isoformat() if last_followup else None,
            "followup_draft": draft,
            "honesty": TRACKER_HONESTY_NOTE,
        }

    def record_send(
        self,
        job_id: str,
        evidence: SendEvidence,
        *,
        now: datetime | None = None,
    ) -> dict[str, Any]:
        """Enregistre l'envoi déclaré par la personne (dépôt manuel effectué).

        Idempotent : la même preuve ne duplique ni l'historique ni l'état ;
        une preuve différente met l'envoi déclaré à jour en place. Le stage ne
        passe à ``submitted`` que si aucune étape postérieure n'est atteinte.
        """
        current = now or datetime.now(timezone.utc)
        if current.tzinfo is None:
            current = current.replace(tzinfo=timezone.utc)
        try:
            validate_evidence(evidence, now=current)
        except SendConfirmationError as error:
            raise UserFacingError(str(error)) from error
        identifier = clean_text(job_id, limit=80)
        if not identifier:
            raise UserFacingError("Indique l'offre concernée par la confirmation d'envoi.")
        detail = json.dumps(evidence_payload(evidence), ensure_ascii=False)
        fingerprint = evidence_fingerprint(evidence)
        now_iso = utc_now()
        with self._lock, self._connection() as connection:
            job = connection.execute("SELECT id FROM jobs WHERE id = ?", (identifier,)).fetchone()
            if not job:
                raise UserFacingError("Cette offre Career n’existe pas.")
            application = connection.execute(
                "SELECT id, stage, approval_granted FROM applications WHERE job_id = ?",
                (identifier,),
            ).fetchone()
            if not application:
                raise UserFacingError(
                    "Aucune candidature suivie pour cette offre : crée d'abord le suivi local "
                    "avant de confirmer un envoi."
                )
            application_id = str(application["id"])
            if not application["approval_granted"]:
                raise UserFacingError(
                    "Approuve d’abord le dépôt manuel pour cette offre avant d’enregistrer son envoi."
                )
            existing = latest_send_evidence(self._send_events(connection, application_id))
            created = False
            if existing is None:
                created = True
                connection.execute(
                    """
                    INSERT INTO application_events (id, application_id, job_id, event_type, detail, created_at)
                    VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (
                        f"event_{uuid.uuid4().hex}",
                        application_id,
                        identifier,
                        SEND_CONFIRMATION_EVENT_TYPE,
                        detail,
                        now_iso,
                    ),
                )
            elif json.dumps(existing[1], sort_keys=True, ensure_ascii=False) != fingerprint:
                # Double envoi : mise à jour de l'envoi déclaré, sans dupliquer
                # l'historique — le journal garde exactement un envoi.
                connection.execute(
                    "UPDATE application_events SET detail = ? WHERE id = ?",
                    (detail, existing[0]),
                )
            if application["stage"] not in STAGES_AT_OR_AFTER_SENT:
                connection.execute(
                    """
                    UPDATE applications SET stage = 'submitted', receipt_status = 'unknown', updated_at = ?
                    WHERE id = ?
                    """,
                    (now_iso, application_id),
                )
                self._application_event(
                    connection,
                    application_id,
                    identifier,
                    "stage_updated",
                    "Envoi déclaré manuellement par la personne (confirmation d'envoi).",
                )
            self._audit(connection, "send_confirmation_recorded", "application", application_id)
        return self._send_record_response(
            job_id=identifier, application_id=application_id, created=created
        )

    def record_followup_done(
        self,
        job_id: str,
        *,
        done_on: date | None = None,
        note: str = "",
    ) -> dict[str, Any]:
        """Déclare une relance déjà faite ; la prochaine échéance repart à +7 jours ouvrés."""
        identifier = clean_text(job_id, limit=80)
        if not identifier:
            raise UserFacingError("Indique l'offre concernée par la relance.")
        followed_up_on = done_on or date.today()
        now_iso = utc_now()
        with self._lock, self._connection() as connection:
            application = connection.execute(
                "SELECT id FROM applications WHERE job_id = ?", (identifier,)
            ).fetchone()
            if not application:
                raise UserFacingError("Cette candidature Career n’existe pas.")
            application_id = str(application["id"])
            if latest_send_evidence(self._send_events(connection, application_id)) is None:
                raise UserFacingError(
                    "Enregistre d'abord l'envoi déclaré avant de noter une relance."
                )
            events = self._send_events(connection, application_id)
            if latest_followup_on(events) == followed_up_on:
                return self._send_record_response(
                    job_id=identifier, application_id=application_id, created=False
                )
            connection.execute(
                """
                INSERT INTO application_events (id, application_id, job_id, event_type, detail, created_at)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    f"event_{uuid.uuid4().hex}",
                    application_id,
                    identifier,
                    FOLLOWUP_RECORDED_EVENT_TYPE,
                    json.dumps({"done_on": followed_up_on.isoformat()}, ensure_ascii=False),
                    now_iso,
                ),
            )
            self._audit(connection, "followup_recorded", "application", application_id)
        return self._send_record_response(
            job_id=identifier, application_id=application_id, created=False
        )

    def get_send_record(self, job_id: str) -> dict[str, Any]:
        """Lit l'envoi déclaré d'une offre : record, échéance, brouillon de relance."""
        identifier = clean_text(job_id, limit=80)
        if not identifier:
            raise UserFacingError("Indique l'offre dont lire la confirmation d'envoi.")
        with self._lock, self._connection() as connection:
            application = connection.execute(
                "SELECT id FROM applications WHERE job_id = ?", (identifier,)
            ).fetchone()
        if not application:
            raise UserFacingError("Cette candidature Career n’existe pas.")
        return self._send_record_response(
            job_id=identifier, application_id=str(application["id"]), created=False
        )

    def build_followup_draft(self, job_id: str) -> str:
        """Brouillon de relance court et prêt à copier, en français."""
        return str(self.get_send_record(job_id)["followup_draft"])

    def apply_tracker(self) -> dict[str, Any]:
        """Suivi des candidatures envoyées sans réponse, priorisées par échéance.

        Lecture pure : seules les candidatures dont le tracking porte un envoi
        déclaré et aucun stade de réponse entrent dans la liste ; l'ordre est
        l'échéance de relance croissante, puis le titre. Aucune relance n'est
        envoyée — chaque entrée porte un brouillon local à copier.
        """
        today = date.today()
        with self._lock, self._connection() as connection:
            rows = connection.execute(
                """
                SELECT a.id AS application_id, a.job_id, a.stage, a.receipt_status,
                       a.confirmation_reference, j.company, j.title, j.city, j.official_url
                FROM applications a JOIN jobs j ON a.job_id = j.id
                WHERE a.stage IN ('submitted', 'submitted_confirmed')
                ORDER BY a.updated_at DESC, a.id ASC
                LIMIT ?
                """,
                (MAX_TRACKER_APPLICATIONS,),
            ).fetchall()
            items: list[dict[str, Any]] = []
            for row in rows:
                events = self._send_events(connection, str(row["application_id"]))
                send = latest_send_evidence(events)
                if send is None:
                    continue
                record = send_record_from_payload(
                    str(row["job_id"]), send[1], last_followup_on=latest_followup_on(events)
                )
                if record is None:
                    continue
                due_day = record.follow_up_due.date()
                draft = build_followup_draft(
                    title=str(row["title"] or ""),
                    company=str(row["company"] or ""),
                    channel=record.channel,
                    sent_at=record.sent_at,
                    reference=str(row["confirmation_reference"] or ""),
                )
                items.append(
                    {
                        "job_id": str(row["job_id"]),
                        "application_id": str(row["application_id"]),
                        "title": str(row["title"] or "Offre sans intitulé"),
                        "company": str(row["company"] or ""),
                        "city": str(row["city"] or ""),
                        "official_url": str(row["official_url"] or ""),
                        "stage": str(row["stage"]),
                        "receipt_status": str(row["receipt_status"]),
                        "channel": record.channel,
                        "sent_at": record.sent_at.isoformat(),
                        "follow_up_due": record.follow_up_due.isoformat(),
                        "follow_up_due_date": due_day.isoformat(),
                        "days_waiting": max((today - record.sent_at.date()).days, 0),
                        "status": "due" if due_day <= today else "upcoming",
                        "overdue": due_day < today,
                        "followup_draft": draft,
                        "is_email": False,
                    }
                )
        items.sort(key=lambda item: (item["follow_up_due_date"], item["title"].casefold()))
        due_items = [item for item in items if item["status"] == "due"]
        return {
            "generated_at": utc_now(),
            "today": today.isoformat(),
            "items": items,
            "totals": {
                "sent_without_response": len(items),
                "due": len(due_items),
                "overdue": sum(1 for item in items if item["overdue"]),
            },
            "honesty": TRACKER_HONESTY_NOTE,
        }

    # ------------------------------------------------------------------
    # Local application kit (CVBOOST-05)
    #
    # One explicit user action opens a pre-filled kit for ONE tracked offer:
    # the idempotent tracker record, the latest local CV/letter draft in the
    # requested language, and short reviewable texts (motivation, availability)
    # plus the copy-paste fields (company, title, reference, official URL).
    # Persistence uses the existing application_events rows with JSON payloads
    # (event_type "kit_content"), so no schema change is needed.  Nothing here
    # ever transmits an application: submitting remains a purely manual act by
    # the person, outside this program.
    # ------------------------------------------------------------------

    @staticmethod
    def _kit_content_edits(detail: str) -> dict[str, str]:
        """Read previously saved kit text edits from a JSON event payload."""
        try:
            parsed = json.loads(detail or "{}")
        except json.JSONDecodeError:
            return {}
        if not isinstance(parsed, dict):
            return {}
        edits: dict[str, str] = {}
        for field in KIT_TEXT_FIELDS:
            value = parsed.get(field)
            if isinstance(value, str) and value.strip():
                edits[field] = value
        return edits

    @staticmethod
    def _kit_unverified_requirements(profile: dict[str, Any], intake: dict[str, Any], job: dict[str, Any]) -> list[dict[str, str]]:
        """Surface offer requirements with no supporting profile excerpt.

        This reuses the deterministic preparation fact-checker: a requirement
        is "non trouvé dans ton profil" until the profile itself proves it.
        The kit never claims it is satisfied.  Each line keeps the canonical
        identifier of the requirement, the one every other screen uses.
        """
        prep = prepare_application(profile or {}, intake or {}, job)
        intelligence = prep.get("offer_intelligence")
        intelligence = intelligence if isinstance(intelligence, dict) else {}
        by_id = intelligence.get("requirements_by_id")
        by_id = by_id if isinstance(by_id, dict) else {}
        by_text = {
            str(record.get("text") or ""): str(identifier)
            for identifier, record in by_id.items()
            if isinstance(record, dict)
        }
        return [
            {
                "requirement_id": clean_text(item.get("requirement_id"), limit=80)
                or by_text.get(clean_text(item.get("requirement"), limit=300), ""),
                "requirement": clean_text(item.get("requirement"), limit=300),
                "note": clean_text(item.get("note"), limit=300),
            }
            for item in prep.get("unverified_elements", [])
        ][:6]

    @staticmethod
    def _variant_config(variant_id: Any):
        identifier = clean_text(variant_id, limit=40) or "m_a"
        variant = next((item for item in ALL_VARIANTS if item.id == identifier), None)
        if variant is None:
            raise UserFacingError("Variante CV inconnue.")
        return variant

    def _generate_targeted_kit_files(
        self, job_id: str, variant_id: str
    ) -> dict[str, Any]:
        variant = self._variant_config(variant_id)
        profile = self.get_profile()
        job = self.get_job(job_id)
        prep = self.get_job_prep(job_id)
        cv_analysis = self._current_cv_analysis()
        job.update(prep)
        job["qualification"] = qualify_offer(job).to_dict()
        coverage = compute_coverage(job, cv_analysis, profile, variant)
        gaps = generate_diff(coverage, cv_analysis, profile, variant)
        coverage = replace(
            coverage,
            gaps=gaps,
            recommended_variant=variant,
            variant_rationale=(
                f"Variante {variant.label} sélectionnée explicitement ; "
                "couverture recalculée sur les preuves locales."
            ),
        )
        output_dir = self.base_dir / "output" / "career" / "kits" / f"{job_id}_{variant.id}"
        generated = generate_application_kit(
            job,
            profile,
            variant,
            coverage,
            cv_analysis,
            output_dir,
        )
        return {
            "variant": variant.id,
            "variant_label": variant.label,
            "generated_at": generated.generated_at,
            "artifacts": {
                "cv": str(generated.cv_path),
                "cover_letter": str(generated.cover_letter_path),
                "prep_sheet": str(generated.prep_sheet_path),
            },
            "provenance_map": generated.provenance_map,
            "automatic_submission": False,
        }

    def create_application_kit(
        self, job_id: str, language: Any, variant: Any = "m_a"
    ) -> dict[str, Any]:
        """Open (or reopen) the preparation kit for one explicitly chosen offer.

        Idempotent by design: the tracker record is created only if absent
        (``create_application``), and the local draft is created once per
        (offer, language). Repeating the action reopens the same kit instead
        of generating documents in a loop.
        """
        identifier = clean_text(job_id, limit=80)
        normalized_language = normalize_language(language)
        selected_variant = self._variant_config(variant)
        tracking = self.create_application(identifier)
        created_tracking = bool(tracking.get("created"))
        application_id = str(tracking["id"])
        existing = None
        with self._lock, self._connection() as connection:
            existing = connection.execute(
                """
                SELECT id FROM application_drafts
                WHERE job_id = ? AND language = ? AND variant = ?
                ORDER BY created_at DESC, application_drafts.rowid DESC LIMIT 1
                """,
                (identifier, normalized_language, selected_variant.id),
            ).fetchone()
        if existing:
            result = self.get_application_kit(
                application_id, normalized_language, selected_variant.id
            )
            result.update(self._generate_targeted_kit_files(identifier, selected_variant.id))
            result["created_tracking"] = created_tracking
            result["created_draft"] = False
            return result
        draft = self.create_application_draft(
            identifier, normalized_language, variant=selected_variant.id
        )
        draft_id = str(draft["id"])
        with self._lock, self._connection() as connection:
            application = connection.execute(
                "SELECT job_id FROM applications WHERE id = ?", (application_id,)
            ).fetchone()
            if not application:
                raise UserFacingError("Cette candidature Career n’existe pas.")
            self._application_event(
                connection,
                application_id,
                str(application["job_id"]),
                "kit_prepared",
                json.dumps(
                    {
                        "draft_id": draft_id,
                        "language": normalized_language,
                        "variant": selected_variant.id,
                        "mode": "local",
                    },
                    ensure_ascii=False,
                ),
            )
            self._audit(connection, "application_kit_prepared", "application", application_id)
        result = self.get_application_kit(
            application_id, normalized_language, selected_variant.id
        )
        result.update(self._generate_targeted_kit_files(identifier, selected_variant.id))
        result["created_tracking"] = created_tracking
        result["created_draft"] = True
        return result

    def get_application_kit(
        self, application_id: str, language: Any, variant: Any = ""
    ) -> dict[str, Any]:
        """Assemble the local kit for one tracked application (read-only)."""
        identifier = clean_text(application_id, limit=80)
        normalized_language = normalize_language(language)
        selected_variant = clean_text(variant, limit=40)
        with self._lock, self._connection() as connection:
            application = connection.execute(
                """
                SELECT applications.*, jobs.company, jobs.title, jobs.city, jobs.country,
                       jobs.official_url, jobs.source_id, jobs.deadline_date
                FROM applications JOIN jobs ON jobs.id = applications.job_id
                WHERE applications.id = ?
                """,
                (identifier,),
            ).fetchone()
            if not application:
                raise UserFacingError("Cette candidature Career n’existe pas.")
            job_id = str(application["job_id"])
            # The fact-checker needs the full, immutable offer row: a join
            # projection deliberately limited to display fields would strip
            # the requirement text it must compare against the profile.
            job_row = connection.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()
            # Honor the explicitly requested language when a draft exists in
            # it; otherwise fall back to the latest local draft for this offer.
            variant_clause = " AND application_drafts.variant = ?" if selected_variant else ""
            parameters: tuple[Any, ...] = (
                (job_id, normalized_language, selected_variant)
                if selected_variant
                else (job_id, normalized_language)
            )
            draft_row = connection.execute(
                f"""
                SELECT application_drafts.*, jobs.company, jobs.title
                FROM application_drafts JOIN jobs ON jobs.id = application_drafts.job_id
                WHERE application_drafts.job_id = ? AND application_drafts.language = ?
                {variant_clause}
                ORDER BY application_drafts.created_at DESC, application_drafts.rowid DESC LIMIT 1
                """,
                parameters,
            ).fetchone()
            if draft_row is None:
                draft_row = connection.execute(
                    """
                    SELECT application_drafts.*, jobs.company, jobs.title
                    FROM application_drafts JOIN jobs ON jobs.id = application_drafts.job_id
                    WHERE application_drafts.job_id = ?
                    ORDER BY application_drafts.created_at DESC, application_drafts.rowid DESC LIMIT 1
                    """,
                    (job_id,),
                ).fetchone()
            profile = self._row_dict(connection.execute("SELECT * FROM candidate_profile WHERE id = 1").fetchone())
            intake_row = connection.execute("SELECT * FROM career_intake WHERE id = 1").fetchone()
            content_rows = connection.execute(
                """
                SELECT detail FROM application_events
                WHERE application_id = ? AND event_type = 'kit_content'
                ORDER BY created_at ASC, rowid ASC
                """,
                (identifier,),
            ).fetchall()
            # The letter and the fact-checker of the kit read the same snapshot
            # as the explorer, the detailed view and the preparation panel.
            snapshot = offer_intelligence_store.load_snapshot(connection, job_id)
        kit_language = normalize_language(str(draft_row["language"])) if draft_row else normalized_language
        job = {
            "id": job_id,
            "company": clean_text(application["company"], limit=240),
            "title": clean_text(application["title"], limit=300),
            "city": clean_text(application["city"], limit=120),
            "country": clean_text(application["country"], limit=120),
            "official_url": clean_text(application["official_url"], limit=2_000),
            "reference": clean_text(application["source_id"], limit=200),
            "deadline_date": clean_text(application["deadline_date"], limit=32),
        }
        kit_job = dict(job_row) if job_row else dict(job)
        if snapshot:
            kit_job["offer_intelligence"] = snapshot
            job["offer_intelligence_summary"] = snapshot_summary(snapshot)
        intake = self._serialize_intake_row(intake_row) if intake_row else {"answers": {}}
        kit_texts = build_kit_texts(profile, intake, kit_job, kit_language)
        # Each saved edit is an event row storing a partial JSON delta; they
        # replay in order so the possible last save wins per field only.
        edits: dict[str, str] = {}
        for row in content_rows:
            edits.update(self._kit_content_edits(str(row["detail"])))
        kit_texts.update(edits)
        draft = self._serialize_application_draft(draft_row, include_content=True) if draft_row else None
        unverified = self._kit_unverified_requirements(profile, intake, kit_job)
        return {
            "application": {
                "id": identifier,
                "job_id": job_id,
                "stage": clean_text(application["stage"], limit=80),
                "receipt_status": clean_text(application["receipt_status"], limit=80),
                "approval_granted": bool(application["approval_granted"]),
                "created_at": clean_text(application["created_at"], limit=40),
            },
            "job": job,
            "draft": draft,
            "language": kit_language,
            "kit_texts": {field: kit_texts.get(field, "") for field in KIT_TEXT_FIELDS},
            "kit_edited": bool(edits),
            "fact_checks": {
                "placeholders": scan_kit_placeholders(kit_texts),
                "unverified_requirements": unverified,
            },
            "checks": [
                "Chaque texte du kit est généré localement, passe par le vérificateur de faits et reste modifiable avant tout export.",
                "L’envoi est strictement manuel : ce kit ne transmet rien, ne poste rien et n’ouvre aucun client de messagerie.",
                "Relis la référence et les coordonnées du destinataire dans l’offre officielle avant d’utiliser ce kit.",
            ],
            "disclaimer": (
                "Kit de candidature local : honorifique, prérempli depuis l’offre enregistrée et ton profil. "
                "Aucun envoi automatique ; la candidature est déposée par toi uniquement."
            ),
        }

    def update_kit_texts(self, application_id: str, texts: dict[str, Any]) -> dict[str, Any]:
        """Save one explicit edit of the kit texts as a JSON event row.

        Partial updates are intentional: each edited field is validated and
        stored, and previously saved fields stay untouched (event overlay).
        """
        identifier = clean_text(application_id, limit=80)
        if not isinstance(texts, dict):
            raise UserFacingError("Le contenu du kit à enregistrer est invalide.")
        cleaned: dict[str, str] = {}
        limits_labels = {"motivation_short": "motivation courte", "availability": "disponibilité"}
        for field in KIT_TEXT_FIELDS:
            if field not in texts or texts.get(field) is None:
                continue
            limit = KIT_TEXT_LIMITS[field]
            raw_value = texts.get(field)
            if not isinstance(raw_value, str) or not clean_text(raw_value, limit=limit):
                raise UserFacingError(
                    f"Le texte « {limits_labels[field]} » doit contenir du texte lisible."
                )
            if len(raw_value) > limit:
                raise UserFacingError(
                    f"Le texte « {limits_labels[field]} » dépasse la taille maximale ({limit} caractères)."
                )
            cleaned[field] = clean_text(raw_value, limit=limit)
        if not cleaned:
            raise UserFacingError("Aucun texte du kit à enregistrer.")
        with self._lock, self._connection() as connection:
            application = connection.execute(
                "SELECT job_id FROM applications WHERE id = ?", (identifier,)
            ).fetchone()
            if not application:
                raise UserFacingError("Cette candidature Career n’existe pas.")
            # The kit language follows the same rule as the read path: the
            # latest local draft for this offer, so saved texts and documents
            # stay in one consistent language.
            draft_row = connection.execute(
                """
                SELECT language FROM application_drafts WHERE job_id = ?
                ORDER BY created_at DESC, rowid DESC LIMIT 1
                """,
                (str(application["job_id"]),),
            ).fetchone()
            self._application_event(
                connection,
                identifier,
                str(application["job_id"]),
                "kit_content",
                json.dumps(cleaned, ensure_ascii=False),
            )
            self._audit(connection, "application_kit_texts_updated", "application", identifier)
        return self.get_application_kit(identifier, str(draft_row["language"]) if draft_row else "fr")

    @staticmethod
    def _dashboard_action(
        identifier: str,
        priority: int,
        title: str,
        detail: str,
        target_view: str,
    ) -> dict[str, Any]:
        """Return one display-safe, client-addressable action-plan item.

        The identifiers are intentionally semantic rather than tied to a
        mutable database row.  That makes an action stable as its count or
        explanatory text changes, and gives the local web client a small,
        fixed set of destinations to support.
        """
        return {
            "id": identifier,
            "priority": priority,
            "title": clean_text(title, limit=160),
            "detail": clean_text(detail, limit=600),
            "target_view": target_view,
        }

    @staticmethod
    def _dashboard_job_label(job: dict[str, Any]) -> str:
        """Make a compact local label without exposing a URL or description."""
        title = clean_text(job.get("title"), limit=180) or "Offre sans intitulé"
        company = clean_text(job.get("company"), limit=160)
        return f"{title} — {company}" if company else title

    @staticmethod
    def _dashboard_job_is_actionable(job: dict[str, Any]) -> bool:
        """Whether a tracked offer still merits a next-step reminder.

        ``list_jobs`` intentionally retains archived/rejected offers and jobs
        with completed applications for traceability.  The dashboard should
        retain that history without repeatedly telling the person to act on
        it.  This classifier only reads already-serialized local data and is
        tolerant of legacy rows without the optional application object.
        """
        if clean_text(job.get("status"), limit=80) in {"rejected", "archived"}:
            return False
        application = job.get("application")
        if not isinstance(application, dict):
            return True
        receipt_status = clean_text(application.get("receipt_status"), limit=80)
        stage = clean_text(application.get("stage"), limit=80)
        return receipt_status != "confirmed" and stage not in POST_SUBMISSION_APPLICATION_STAGES

    def _dashboard_action_plan(
        self,
        *,
        profile: dict[str, Any],
        intake: dict[str, Any],
        sources: list[dict[str, Any]],
        jobs: list[dict[str, Any]],
        applications: list[dict[str, Any]],
        drafts: list[dict[str, Any]],
        interviews: list[dict[str, Any]],
        today: date,
    ) -> list[dict[str, Any]]:
        """Build bounded next steps from already-loaded local Career state.

        This method must remain deterministic and side-effect free: in
        particular, it does not refresh a public source, call a model, write
        the database, or infer facts about the candidate.  The plan is a
        convenience layer over facts that are already visible in the local
        tracker, not an automated job-search or application engine.
        """
        actions: list[dict[str, Any]] = []

        def quantity(count: int, singular: str, plural: str | None = None) -> str:
            return f"{count} {singular if count == 1 else (plural or singular + 's')}"

        missing_profile_fields = [
            label for field, label in PROFILE_ACTION_FIELDS if not clean_text(profile.get(field))
        ]
        if missing_profile_fields:
            labels = ", ".join(missing_profile_fields)
            actions.append(
                self._dashboard_action(
                    "profile-completeness",
                    80,
                    "Complète ton profil Career",
                    f"Renseigne encore : {labels}. Ces informations restent locales et servent à adapter les brouillons.",
                    "profile",
                )
            )

        if not bool(intake.get("completed")):
            total_steps = max(1, int(intake.get("total_steps") or 0))
            step_index = min(max(int(intake.get("step_index") or 0), 0), total_steps)
            remaining = max(total_steps - step_index, 0)
            actions.append(
                self._dashboard_action(
                    "intake-completion",
                    90,
                    "Termine les questions de recherche",
                    f"Il reste {quantity(remaining, 'question')} pour préciser les postes, lieux et contraintes recherchés.",
                    "profile",
                )
            )

        enabled_sources = [source for source in sources if bool(source.get("enabled"))]
        if not enabled_sources:
            has_configured_source = bool(sources)
            actions.append(
                self._dashboard_action(
                    "discover-source",
                    100,
                    "Active une source publique" if has_configured_source else "Ajoute une source publique",
                    (
                        "Aucun board Greenhouse public n’est actif. Active une source configurée avant de lancer une recherche manuelle."
                        if has_configured_source
                        else "Ajoute un board Greenhouse public choisi par toi, ou importe une offre manuellement."
                    ),
                    "discover",
                )
            )

        actionable_jobs = [job for job in jobs if self._dashboard_job_is_actionable(job)]
        if not actionable_jobs:
            actions.append(
                self._dashboard_action(
                    "discover-jobs",
                    110,
                    "Ajoute une offre à suivre",
                    (
                        "Aucune offre active n’est à traiter. Lance une recherche manuelle sur une source active ou importe une offre officielle."
                        if enabled_sources
                        else "Aucune offre active n’est à traiter. Importe une offre officielle ou configure une source publique."
                    ),
                    "discover",
                )
            )

        reviewable_jobs = [
            job
            for job in actionable_jobs
            if job.get("deadline_status") != "closed"
            and (
                job.get("source_status") == "unknown"
                or job.get("calendar_status") in {"to_verify", "potentially_incompatible", "partial"}
            )
        ]
        if reviewable_jobs:
            first = self._dashboard_job_label(reviewable_jobs[0])
            count = len(reviewable_jobs)
            actions.append(
                self._dashboard_action(
                    "offers-verification",
                    40,
                    "Vérifie les informations d’offres",
                    f"{quantity(count, 'offre')} {'nécessite' if count == 1 else 'nécessitent'} une vérification de disponibilité ou de calendrier. Exemple : {first}.",
                    "discover",
                )
            )

        deadline_limit = today + timedelta(days=7)
        imminent_deadlines: list[tuple[date, dict[str, Any]]] = []
        for job in actionable_jobs:
            if job.get("deadline_status") == "closed":
                continue
            try:
                deadline = parse_date(job.get("deadline_date"), "La date limite")
            except UserFacingError:
                # Imported data are validated before insertion, but an older
                # manually-edited SQLite file should not make the entire
                # dashboard unavailable.
                deadline = None
            if deadline and today <= deadline <= deadline_limit:
                imminent_deadlines.append((deadline, job))
        imminent_deadlines.sort(key=lambda item: (item[0], self._dashboard_job_label(item[1]).casefold()))
        if imminent_deadlines:
            nearest_date, nearest_job = imminent_deadlines[0]
            count = len(imminent_deadlines)
            actions.append(
                self._dashboard_action(
                    "offers-deadline",
                    20,
                    "Traite les échéances proches",
                    f"{quantity(count, 'offre')} {'a' if count == 1 else 'ont'} une date limite dans les 7 jours. La plus proche : {self._dashboard_job_label(nearest_job)} ({nearest_date.isoformat()}).",
                    "discover",
                )
            )

        if drafts:
            latest_draft = drafts[0]
            count = len(drafts)
            actions.append(
                self._dashboard_action(
                    "draft-review",
                    50,
                    "Relis les brouillons de candidature",
                    f"{quantity(count, 'brouillon')} {'est' if count == 1 else 'sont'} {'disponible' if count == 1 else 'disponibles'}. Vérifie les faits et adapte-les avant toute approbation manuelle. Dernier : {self._dashboard_job_label(latest_draft)}.",
                    "applications",
                )
            )

        receipt_unknown = [application for application in applications if application.get("receipt_status") == "unknown"]
        if receipt_unknown:
            count = len(receipt_unknown)
            actions.append(
                self._dashboard_action(
                    "applications-receipt",
                    10,
                    "Vérifie les réceptions inconnues",
                    f"{quantity(count, 'candidature')} {'a' if count == 1 else 'ont'} une réception à confirmer ou à mettre à jour manuellement.",
                    "applications",
                )
            )

        awaiting_manual_submission = [
            application
            for application in applications
            if application.get("receipt_status") == "not_submitted"
            and (
                bool(application.get("approval_granted"))
                or application.get("stage") == "approved_for_manual_submission"
            )
        ]
        if awaiting_manual_submission:
            count = len(awaiting_manual_submission)
            actions.append(
                self._dashboard_action(
                    "applications-manual-submission",
                    30,
                    "Effectue les dépôts manuels approuvés",
                    f"{quantity(count, 'candidature')} {'est' if count == 1 else 'sont'} {'approuvée' if count == 1 else 'approuvées'} pour un dépôt manuel. Aucun envoi automatique n’est effectué.",
                    "applications",
                )
            )

        applications_to_prepare = [
            application
            for application in applications
            if application.get("stage") in {"to_review", "to_prepare", "ready_to_apply"}
            and application.get("receipt_status") != "confirmed"
        ]
        if applications_to_prepare:
            count = len(applications_to_prepare)
            actions.append(
                self._dashboard_action(
                    "applications-preparation",
                    60,
                    "Prépare les candidatures en cours",
                    f"{quantity(count, 'candidature')} {'nécessite' if count == 1 else 'nécessitent'} encore une relecture, des documents ou une approbation explicite.",
                    "applications",
                )
            )

        active_interviews = [session for session in interviews if session.get("status") == "active"]
        if active_interviews:
            count = len(active_interviews)
            actions.append(
                self._dashboard_action(
                    "interview-continue",
                    70,
                    "Poursuis l’entraînement d’entretien",
                    f"{quantity(count, 'séance')} d’entraînement {'est' if count == 1 else 'sont'} {'active' if count == 1 else 'actives'}. Le coach est local et ne prédit pas les décisions de recrutement.",
                    "interviews",
                )
            )

        return sorted(actions, key=lambda action: (int(action["priority"]), str(action["id"])))[:ACTION_PLAN_LIMIT]

    def dashboard(self) -> dict[str, Any]:
        jobs = self.list_jobs()
        applications = self.list_applications()
        drafts = self.list_application_drafts()
        interviews = self.list_interview_sessions(limit=100)
        profile = self.get_profile()
        intake = self.get_intake()
        sources = self.list_discovery_sources()
        availability = self.get_preferences()["availability"]
        today = date.today()
        upcoming_with_dates: list[tuple[date, dict[str, Any]]] = []
        for job in jobs:
            if not self._dashboard_job_is_actionable(job) or job.get("deadline_status") == "closed":
                continue
            try:
                deadline = parse_date(job.get("deadline_date"), "La date limite")
            except UserFacingError:
                # A legacy manually-edited local database must not prevent the
                # rest of the dashboard from loading.
                deadline = None
            if deadline and deadline >= today:
                upcoming_with_dates.append((deadline, job))
        upcoming_with_dates.sort(key=lambda item: (item[0], self._dashboard_job_label(item[1]).casefold()))
        upcoming = [job for _, job in upcoming_with_dates[:6]]
        return {
            "availability_window": {
                "start": availability.get("availability_start", ""),
                "end": availability.get("availability_end", ""),
            },
            "jobs_total": len(jobs),
            "jobs_open": sum(1 for job in jobs if job["deadline_status"] == "open"),
            "shortlisted": sum(1 for job in jobs if job["shortlisted"]),
            "to_review": sum(1 for job in jobs if job["calendar_status"] in {"to_verify", "potentially_incompatible"}),
            "applications_total": len(applications),
            "drafts_total": len(drafts),
            "interviews_total": len(interviews),
            "interviews_active": sum(1 for interview in interviews if interview["status"] == "active"),
            "receipt_unknown": sum(1 for application in applications if application["receipt_status"] == "unknown"),
            "upcoming_deadlines": upcoming,
            "action_plan": self._dashboard_action_plan(
                profile=profile,
                intake=intake,
                sources=sources,
                jobs=jobs,
                applications=applications,
                drafts=drafts,
                interviews=interviews,
                today=today,
            ),
        }

    def local_capabilities(self) -> dict[str, Any]:
        """Configuration-only capability report; it never starts OCR or a model."""
        return {
            "ocr": self.ocr.status(),
            "guided_intake": True,
            "application_studio": {"local_drafts": True, "formats": ["md", "html", "docx", "pdf"]},
            "interview_coach": {
                "enabled": True,
                "local_text_only": True,
                "modes": sorted(INTERVIEW_MODES),
                "difficulties": list(DIFFICULTIES),
                "provider_required": False,
                "recruitment_probability": False,
            },
            "discovery": {
                "enabled": True,
                "providers": ["greenhouse"],
                "manual_trigger_only": True,
                "cache_seconds": DISCOVERY_CACHE_SECONDS,
                "automated_submission": False,
            },
            "scoring": {
                "enabled": True,
                "version": "deterministic-v1",
                "ai_required": False,
                "not_a_recruitment_probability": True,
            },
            "calendar_export": {
                "enabled": True,
                "format": "ics",
                "local_only": True,
                "automatic_sync": False,
            },
            "stage_search": {
                "enabled": True,
                "ai_required": False,
                "local_only": True,
                "invented_facts": False,
            },
            "ats_guide": {
                "enabled": True,
                "local_only": True,
                "network_requests": False,
                "automated_submission": False,
                "platforms": ["greenhouse", "lever", "workday", "smartrecruiters", "recruitcrm", "breezy", "jobvite", "ashby", "ripplematch", "custom"],
            },
        }

    def export_deadline_calendar(self) -> Path:
        """Write a private, inert ``.ics`` file for actionable deadlines.

        This is an explicit local export, not a calendar integration or a
        background sync.  The pure calendar helper filters history that should
        no longer create reminders and makes copied job-board text inert before
        it becomes an iCalendar property.
        """
        created = datetime.now().strftime("%Y%m%d-%H%M%S")
        target = self.export_dir / f"career_echeances_{created}_{uuid.uuid4().hex[:8]}.ics"
        calendar = build_deadline_calendar_ics(self.list_jobs(), self.list_applications())
        try:
            target.write_text(calendar, encoding="utf-8")
            os.chmod(target, 0o600)
        except OSError as error:
            try:
                target.unlink(missing_ok=True)
            except OSError:
                pass
            raise UserFacingError("Le calendrier local n’a pas pu être créé.") from error
        with self._lock, self._connection() as connection:
            self._audit(connection, "deadlines_calendar_exported", "export", target.name)
        return target

    def export_applications(self, export_format: str) -> Path:
        if export_format not in {"csv", "xlsx"}:
            raise UserFacingError("Format d’export Career non pris en charge.")
        rows = self.list_applications()
        created = datetime.now().strftime("%Y%m%d-%H%M%S")
        target = self.export_dir / f"career_candidatures_{created}_{uuid.uuid4().hex[:8]}.{export_format}"
        fields = [
            ("Entreprise", "company"),
            ("Poste", "title"),
            ("Ville", "city"),
            ("Pays", "country"),
            ("URL officielle", "official_url"),
            ("Date limite", "deadline_date"),
            ("Compatibilité calendrier", "calendar_status"),
            ("Statut suivi", "stage"),
            ("Réception", "receipt_status"),
            ("Approbation manuelle", "approval_granted"),
            ("Référence de confirmation", "confirmation_reference"),
            ("Créée le", "created_at"),
            ("Mise à jour le", "updated_at"),
        ]
        if export_format == "csv":
            with target.open("w", encoding="utf-8-sig", newline="") as stream:
                writer = csv.DictWriter(stream, fieldnames=[label for label, _ in fields], delimiter=";")
                writer.writeheader()
                for row in rows:
                    writer.writerow({label: self._safe_export_value(row.get(key, "")) for label, key in fields})
        else:
            self._write_xlsx_export(target, rows, fields)
        try:
            os.chmod(target, 0o600)
        except OSError:
            pass
        with self._lock, self._connection() as connection:
            self._audit(connection, f"applications_exported_{export_format}", "export", target.name)
        return target

    @staticmethod
    def _safe_export_value(value: Any) -> Any:
        if isinstance(value, bool):
            return "Oui" if value else "Non"
        text = clean_text(value, limit=30_000)
        return "'" + text if text.startswith(("=", "+", "-", "@")) else text

    def _write_xlsx_export(self, target: Path, rows: list[dict[str, Any]], fields: list[tuple[str, str]]) -> None:
        from openpyxl import Workbook
        from openpyxl.styles import Font, PatternFill
        from openpyxl.utils import get_column_letter

        workbook = Workbook()
        sheet = workbook.active
        sheet.title = "Candidatures"
        header_fill = PatternFill("solid", fgColor="2946C8")
        for index, (label, _) in enumerate(fields, start=1):
            cell = sheet.cell(row=1, column=index, value=label)
            cell.font = Font(color="FFFFFF", bold=True)
            cell.fill = header_fill
        for row_index, row in enumerate(rows, start=2):
            for column_index, (_, key) in enumerate(fields, start=1):
                sheet.cell(row=row_index, column=column_index, value=self._safe_export_value(row.get(key, "")))
        for column_index, (label, _) in enumerate(fields, start=1):
            width = min(42, max(13, len(label) + 2))
            sheet.column_dimensions[get_column_letter(column_index)].width = width
        sheet.freeze_panes = "A2"
        sheet.auto_filter.ref = sheet.dimensions
        workbook.save(target)

    def export_personal_data(self) -> Path:
        created = datetime.now().strftime("%Y%m%d-%H%M%S")
        target = self.export_dir / f"career_donnees_personnelles_{created}_{uuid.uuid4().hex[:8]}.json"
        with self._lock, self._connection() as connection:
            preference_rows = connection.execute(
                "SELECT kind, item_key, label, enabled, priority, scope FROM preference_items ORDER BY kind, priority DESC, label"
            ).fetchall()
            settings = {
                row["setting_key"]: row["setting_value"]
                for row in connection.execute("SELECT setting_key, setting_value FROM career_settings").fetchall()
            }
            job_rows = connection.execute(
                """
                SELECT jobs.*, applications.id AS application_id, applications.stage AS application_stage,
                       applications.receipt_status AS application_receipt_status,
                       applications.approval_granted AS application_approval_granted
                FROM jobs LEFT JOIN applications ON applications.job_id = jobs.id
                ORDER BY jobs.created_at ASC
                """
            ).fetchall()
            application_rows = connection.execute(
                """
                SELECT applications.*, jobs.company, jobs.title, jobs.city, jobs.country, jobs.official_url,
                       jobs.deadline_date, jobs.calendar_status, jobs.source_status
                FROM applications JOIN jobs ON jobs.id = applications.job_id
                ORDER BY applications.created_at ASC
                """
            ).fetchall()
            profile_import_rows = connection.execute(
                "SELECT * FROM profile_imports ORDER BY created_at ASC"
            ).fetchall()
            intake_row = connection.execute("SELECT * FROM career_intake WHERE id = 1").fetchone()
            draft_rows = connection.execute(
                """
                SELECT application_drafts.*, jobs.company, jobs.title
                FROM application_drafts JOIN jobs ON jobs.id = application_drafts.job_id
                ORDER BY application_drafts.created_at ASC
                """
            ).fetchall()
            discovery_source_rows = connection.execute(
                """
                SELECT discovery_sources.*, COUNT(jobs.id) AS jobs_stored
                FROM discovery_sources LEFT JOIN jobs ON jobs.discovery_source_id = discovery_sources.id
                GROUP BY discovery_sources.id
                ORDER BY discovery_sources.company COLLATE NOCASE ASC
                """
            ).fetchall()
            discovery_run_rows = connection.execute(
                "SELECT * FROM discovery_runs ORDER BY started_at ASC"
            ).fetchall()
            interview_rows = connection.execute(
                """
                SELECT interview_sessions.*, jobs.company, jobs.title
                FROM interview_sessions LEFT JOIN jobs ON jobs.id = interview_sessions.job_id
                ORDER BY interview_sessions.started_at ASC
                """
            ).fetchall()
            data = {
                "profile": self._row_dict(connection.execute("SELECT * FROM candidate_profile WHERE id = 1").fetchone()),
                "preferences": self._serialize_preferences(preference_rows, settings),
                "jobs": [self._serialize_job(row) for row in job_rows],
                "applications": [
                    {**dict(row), "approval_granted": bool(row["approval_granted"])}
                    for row in application_rows
                ],
                "application_events": [
                    dict(row)
                    for row in connection.execute(
                        "SELECT * FROM application_events ORDER BY created_at ASC"
                    ).fetchall()
                ],
                # The privacy export includes the local text used to make a
                # draft, but never an absolute path nor a binary file copy.
                # This lets the person recover their own profile source while
                # keeping it outside the general V3 workspace.
                "profile_imports": [
                    {
                        "id": row["id"],
                        "source_kind": row["source_kind"],
                        "original_name": row["original_name"],
                        "has_local_file": bool(row["stored_filename"]),
                        "size_bytes": int(row["size_bytes"]),
                        "extraction_method": row["extraction_method"],
                        "ocr_pages": int(row["ocr_pages"] or 0),
                        "ocr_warnings": self._ocr_warnings(str(row["ocr_warnings_json"])),
                        "content_sha256": row["content_sha256"],
                        "status": row["status"],
                        "base_profile_updated_at": row["base_profile_updated_at"],
                        "created_at": row["created_at"],
                        "applied_at": row["applied_at"],
                        "extracted_text": row["extracted_text"],
                        "suggestions": self._import_suggestions(str(row["suggestions_json"])),
                    }
                    for row in profile_import_rows
                ],
                "career_intake": self._serialize_intake_row(intake_row) if intake_row else {},
                "application_drafts": [
                    self._serialize_application_draft(row, include_content=True) for row in draft_rows
                ],
                "discovery_sources": [
                    self._serialize_discovery_source(row) for row in discovery_source_rows
                ],
                "discovery_runs": [dict(row) for row in discovery_run_rows],
                "interview_sessions": [
                    self._serialize_interview_session(row, include_turns=True) for row in interview_rows
                ],
                "audit_log": [
                    dict(row)
                    for row in connection.execute(
                        "SELECT * FROM career_audit_log ORDER BY created_at ASC"
                    ).fetchall()
                ],
                "exported_at": utc_now(),
                "letter_approvals": [dict(row) for row in connection.execute(
                    "SELECT * FROM letter_content_approvals ORDER BY updated_at"
                ).fetchall()],
            }
        target.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        try:
            os.chmod(target, 0o600)
        except OSError:
            pass
        return target

    def reset_personal_data(self, confirmation: str) -> None:
        if confirmation != DELETE_CONFIRMATION:
            raise UserFacingError("La phrase de confirmation de suppression est incorrecte.")
        with self._lock, self._connection() as connection:
            document_rows = connection.execute(
                "SELECT stored_filename FROM profile_imports WHERE stored_filename != ''"
            ).fetchall()
            document_paths = [self._profile_document_path(str(row["stored_filename"])) for row in document_rows]
            try:
                for path in document_paths:
                    path.unlink(missing_ok=True)
            except OSError as error:
                raise UserFacingError("Un document de profil n’a pas pu être supprimé.") from error
            connection.execute("DELETE FROM profile_imports")
            connection.execute("DELETE FROM application_drafts")
            connection.execute("DELETE FROM interview_sessions")
            connection.execute("DELETE FROM career_intake")
            connection.execute("DELETE FROM application_events")
            connection.execute("DELETE FROM applications")
            connection.execute("DELETE FROM discovery_runs")
            connection.execute("DELETE FROM discovery_sources")
            connection.execute("DELETE FROM jobs")
            connection.execute("DELETE FROM candidate_profile")
            connection.execute("DELETE FROM preference_items")
            connection.execute("DELETE FROM career_settings")
            connection.execute("DELETE FROM career_audit_log")
            connection.execute("DELETE FROM letter_content_approvals")
            self._seed_defaults(connection)
            self._audit(connection, "career_data_reset", "career", "all")
        for path in self.export_dir.glob("career_*"):
            try:
                path.unlink()
            except OSError:
                pass
        # Delete interrupted upload parts and any prior opaque source left by
        # an interrupted process. This directory is exclusively Career-owned.
        for pattern in (".profile-upload-*.part", "profile_*"):
            for path in self.documents_dir.glob(pattern):
                try:
                    if path.is_file():
                        path.unlink()
                except OSError:
                    pass
        for path in self.studio_dir.glob("*"):
            try:
                if path.is_file():
                    path.unlink()
            except OSError:
                pass
        # A reset is an explicit request to erase the Career space, so remove
        # the snapshots created by this application too.  Restrict the match
        # to our own naming convention: a person may keep another SQLite file
        # in this private directory without this operation deleting it.
        for pattern in ("career-before-v*-to-v*-*.sqlite3", ".career-before-v*-to-v*-*.tmp"):
            for path in self.backups_dir.glob(pattern):
                try:
                    if path.is_file():
                        path.unlink()
                except OSError:
                    pass

    def safe_export_path(self, filename: str) -> Path:
        candidate = (self.export_dir / Path(filename).name).resolve()
        if (
            filename != Path(filename).name
            or candidate.parent != self.export_dir.resolve()
            or not candidate.is_file()
            or candidate.suffix.lower() not in {".csv", ".xlsx", ".json", ".ics"}
        ):
            raise UserFacingError("Export Career introuvable.")
        return candidate
