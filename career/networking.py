"""Local networking address book (SPEC-040): import, targets, drafts.

The module only works on data the user already owns:

* a **decompressed LinkedIn export** (``Profile.csv`` and ``Connections.csv``)
  that the user imported themselves -- the files never leave the machine;
* **public facts** collected by the local Web Researcher, each one carrying
  the page it comes from and an excerpt as proof (one page per company).

Nothing here sends a message, scrapes a profile, calls a social-network API or
exports the address book.  A draft is written to a local file and the user
sends it themselves.

All scoring is deterministic: same contacts and same target role always
produce the same recommendations, and every recommendation cites the
provenance of the facts it relies on.
"""

from __future__ import annotations

import csv
import io
import json
import os
import sqlite3
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Iterator, Mapping, Sequence

from .models import clean_text, normalized_text, utc_now
from .networking_schema import (
    Contact,
    NetworkingValidationError,
    Provenance,
    RELATION_LABELS,
    contact_from_row,
    init_networking_schema,
    merge_contacts,
    normalize_relation,
    provenance_from_row,
    same_person,
)


#: The LinkedIn export files this module reads.  Nothing else is opened.
LINKEDIN_FILES: tuple[str, ...] = ("Profile.csv", "Connections.csv")
OPTIONAL_EDUCATION_FILE = "Education.csv"

#: Deliberate local limits: an export is a personal file, not a data lake.
MAX_EXPORT_BYTES = 5 * 1024 * 1024
MAX_CONNECTIONS = 5_000
MIN_EXCERPT_LENGTH = 12

#: Finance desks named by the mission (IBC, M&A, TMT, coverage desks).
FINANCE_DESKS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("ma", ("m&a", "m & a", "mergers and acquisitions", "mergers acquisitions", "merger", "acquisition", "fusion acquisition", "fusion acquisitions")),
    ("tmt", ("tmt", "technology media telecom", "technology media telecommunications", "media telecom", "telecom", "technologie medias telecom")),
    ("ecm", ("ecm", "equity capital markets", "equity capital market", "marché actions")),
    ("dcm", ("dcm", "debt capital markets", "debt capital market", "marché obligataire")),
    ("leveraged_finance", ("leveraged finance", "leverage finance", "lbo", "acquisition finance")),
    ("private_equity", ("private equity", "private-equity")),
    ("ibc", ("ibc", "investment banking coverage", "international banking coverage")),
    ("coverage", ("coverage", "coverage desk", "corporate coverage", "sector coverage", "industry coverage", "client coverage")),
)

DESK_LABELS: dict[str, str] = {
    "ma": "M&A",
    "tmt": "TMT",
    "ecm": "ECM",
    "dcm": "DCM",
    "leveraged_finance": "Leveraged Finance",
    "private_equity": "Private Equity",
    "ibc": "IBC",
    "coverage": "Coverage",
}

DRAFT_KINDS: tuple[str, ...] = ("alumni_first_contact", "school_recruiter", "coverage_desk")

DRAFT_LABELS: dict[str, str] = {
    "alumni_first_contact": "Premier contact alumni",
    "school_recruiter": "Recruteur rencontré via l’école",
    "coverage_desk": "Contact coverage desk",
}

_RECRUITER_TOKENS: tuple[str, ...] = (
    "recruiter", "recruteur", "recruteuse", "talent", "campus", "hr ", "human resources", "ressources humaines",
)

#: Words that never prove a role match: they appear in almost every finance title.
_ROLE_STOPWORDS: frozenset[str] = frozenset({
    "the", "and", "for", "with", "des", "les", "une", "dans", "pour", "chez", "sur",
    "stage", "intern", "internship", "analyst", "analyste", "associate", "associe",
    "junior", "senior", "assistant", "manager", "finance", "financial", "banque", "bank",
    "banking", "equipe", "team", "poste", "role", "job", "offre",
})

_COLUMN_ALIASES: dict[str, str] = {
    "first name": "first_name",
    "firstname": "first_name",
    "prénom": "first_name",
    "prenom": "first_name",
    "last name": "last_name",
    "lastname": "last_name",
    "nom": "last_name",
    "nom de famille": "last_name",
    "full name": "full_name",
    "nom complet": "full_name",
    "company": "company",
    "société": "company",
    "societe": "company",
    "entreprise": "company",
    "organization": "company",
    "organisation": "company",
    "position": "role",
    "poste": "role",
    "titre": "role",
    "title": "role",
    "job title": "role",
    "url": "linkedin_url",
    "profile url": "linkedin_url",
    "linkedin url": "linkedin_url",
    "email address": "email",
    "adresse e-mail": "email",
    "adresse email": "email",
    "e-mail": "email",
    "connected on": "connected_on",
    "connecté le": "connected_on",
    "connecte le": "connected_on",
    "school": "school",
    "school name": "school",
    "école": "school",
    "ecole": "school",
    "établissement": "school",
    "etablissement": "school",
    "headline": "headline",
    "summary": "summary",
    "industry": "industry",
    "geo location": "location",
    "location": "location",
    "education": "education",
}

#: Header lookup is accent- and punctuation-insensitive: LinkedIn localises its
#: export ("Prénom", "Société", "Établissement"), so the aliases are normalised
#: with the same function as the received header.
_COLUMN_ALIAS_KEYS: dict[str, str] = {
    normalized_text(alias): canonical for alias, canonical in _COLUMN_ALIASES.items()
}


def _text(value: Any, limit: int = 10_000) -> str:
    text = clean_text(value, limit=limit)
    return "".join(character for character in text if character >= " " or character in "\n\t")


def classify_desk(*values: Any) -> str | None:
    """Name the finance desk a role/company describes, if any.

    The lookup is a closed list and follows the order of :data:`FINANCE_DESKS`:
    "M&A coverage" is M&A, never the generic coverage desk.
    """
    haystack = " | ".join(normalized_text(value) for value in values if clean_text(value))
    if not haystack:
        return None
    for desk, needles in FINANCE_DESKS:
        if any(normalized_text(needle) in haystack for needle in needles):
            return desk
    return None


# ---------------------------------------------------------------------------
# LinkedIn export import
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class LinkedInExport:
    """Parsed, still-unsaved content of a local LinkedIn export."""

    viewer: Mapping[str, str]
    viewer_schools: tuple[str, ...]
    contacts: tuple[Contact, ...]
    warnings: tuple[str, ...] = ()
    skipped_rows: int = 0
    files_read: tuple[str, ...] = ()


@dataclass(frozen=True)
class ImportReport:
    """Outcome of importing an export into the local SQLite store."""

    imported: int
    updated: int
    skipped_rows: int
    viewer: Mapping[str, str]
    viewer_schools: tuple[str, ...]
    warnings: tuple[str, ...] = ()
    contacts: tuple[Contact, ...] = ()

    def as_dict(self) -> dict[str, Any]:
        return {
            "imported": self.imported,
            "updated": self.updated,
            "skipped_rows": self.skipped_rows,
            "viewer": dict(self.viewer),
            "viewer_schools": list(self.viewer_schools),
            "warnings": list(self.warnings),
            "contacts": [contact.as_dict() for contact in self.contacts],
        }


def _read_export_text(source: Path | str | Mapping[str, str | bytes], filename: str, *, required: bool) -> str | None:
    if isinstance(source, Mapping):
        raw = source.get(filename)
        if raw is None:
            if required:
                raise FileNotFoundError(f"Export LinkedIn incomplet : {filename} est absent.")
            return None
        text = raw.decode("utf-8-sig") if isinstance(raw, bytes) else str(raw)
    else:
        path = Path(source)
        if path.is_dir():
            path = path / filename
        elif path.name != filename:
            if required:
                raise FileNotFoundError(f"Export LinkedIn incomplet : {filename} est absent.")
            return None
        if not path.exists():
            if required:
                raise FileNotFoundError(f"Export LinkedIn incomplet : {filename} est absent.")
            return None
        if path.stat().st_size > MAX_EXPORT_BYTES:
            raise NetworkingValidationError(f"{filename} dépasse la limite locale de {MAX_EXPORT_BYTES} octets.")
        raw_bytes = path.read_bytes()
        try:
            text = raw_bytes.decode("utf-8-sig")
        except UnicodeDecodeError:
            text = raw_bytes.decode("cp1252", errors="replace")
    if len(text.encode("utf-8", errors="ignore")) > MAX_EXPORT_BYTES:
        raise NetworkingValidationError(f"{filename} dépasse la limite locale de {MAX_EXPORT_BYTES} octets.")
    return text.lstrip("\ufeff")


def _canonical_row(row: Sequence[str]) -> dict[str, str]:
    values: dict[str, str] = {}
    for index, raw in enumerate(row):
        key = _COLUMN_ALIAS_KEYS.get(normalized_text(raw))
        if key and key not in values:
            values[key] = str(index)
    return values


def _dict_rows(text: str, *, min_columns: int = 2) -> tuple[list[dict[str, str]], list[str]]:
    """Return rows keyed by canonical column name, plus warnings.

    LinkedIn prepends a few ``Notes:`` lines before some headers, so the header
    is the first row that names enough known columns.
    """
    reader = list(csv.reader(io.StringIO(text)))
    for header_index, row in enumerate(reader):
        columns = _canonical_row(row)
        if len(columns) < min_columns:
            continue
        rows: list[dict[str, str]] = []
        warnings: list[str] = []
        for offset, data in enumerate(reader[header_index + 1 :], start=header_index + 2):
            if not any(clean_text(cell) for cell in data):
                continue
            item = {
                name: _text(data[int(index)], 2_000) if int(index) < len(data) else ""
                for name, index in columns.items()
            }
            line_number = str(offset)
            if len(data) != len(reader[header_index]):
                warnings.append(f"Ligne {line_number} : nombre de colonnes inattendu.")
            rows.append({**item, "_line": line_number})
        return rows, warnings
    return [], ["Aucune ligne d’en-tête reconnue."]


def _row_name(row: Mapping[str, str]) -> str:
    full = _text(row.get("full_name"), 160)
    if full:
        return full
    first = _text(row.get("first_name"), 80)
    last = _text(row.get("last_name"), 80)
    if first and last:
        return f"{first} {last}"
    # A half-name is not enough to identify a person: an export row without
    # both parts is skipped instead of being stored as "Martin".
    return ""


def _viewer_schools(profile_rows: Sequence[Mapping[str, str]], education_text: str | None) -> tuple[str, ...]:
    schools: list[str] = []
    for row in profile_rows:
        for key in ("education", "school"):
            for part in _text(row.get(key), 500).replace(";", ",").split(","):
                school = _text(part, 200)
                if school and school not in schools:
                    schools.append(school)
    if education_text:
        rows, _ = _dict_rows(education_text, min_columns=1)
        for row in rows:
            school = _text(row.get("school") or row.get("education") or row.get("full_name"), 200)
            if school and school not in schools:
                schools.append(school)
    return tuple(schools)


def parse_linkedin_export(source: Path | str | Mapping[str, str | bytes]) -> LinkedInExport:
    """Parse a decompressed export without writing or sending anything."""
    profile_text = _read_export_text(source, "Profile.csv", required=True)
    connections_text = _read_export_text(source, "Connections.csv", required=True)
    education_text = _read_export_text(source, OPTIONAL_EDUCATION_FILE, required=False)
    assert profile_text is not None and connections_text is not None  # required=True

    profile_rows, profile_warnings = _dict_rows(profile_text)
    viewer_schools = _viewer_schools(profile_rows, education_text)
    viewer: dict[str, str] = {}
    if profile_rows:
        first = profile_rows[0]
        viewer = {
            "name": _row_name(first),
            "headline": _text(first.get("headline"), 300),
            "location": _text(first.get("location"), 200),
            "industry": _text(first.get("industry"), 200),
        }

    connection_rows, connection_warnings = _dict_rows(connections_text)
    warnings = [*profile_warnings, *connection_warnings]
    contacts: list[Contact] = []
    by_id: dict[str, Contact] = {}
    skipped = 0
    viewer_keys = {normalized_text(school) for school in viewer_schools}

    for row in connection_rows:
        if len(contacts) >= MAX_CONNECTIONS:
            warnings.append(f"Limite de {MAX_CONNECTIONS} connexions atteinte : le reste est ignoré.")
            break
        name = _row_name(row)
        if not name:
            skipped += 1
            warnings.append(f"Ligne {row.get('_line', '?')} ignorée : nom absent.")
            continue
        company = _text(row.get("company"), 200)
        school = _text(row.get("school"), 200)
        relation = "alumni" if school and normalized_text(school) in viewer_keys else "first"
        provenance = Provenance(
            source="linkedin_export",
            detail=f"Export LinkedIn — Connections.csv, ligne {row.get('_line', '?')}",
            collected_at=utc_now(),
        )
        try:
            contact = Contact(
                name=name,
                role=_text(row.get("role"), 200),
                company=company,
                school=school,
                relation=relation,
                email=_text(row.get("email"), 320),
                linkedin_url=_text(row.get("linkedin_url"), 500),
                provenance=[provenance],
            ).validated()
        except NetworkingValidationError as error:
            skipped += 1
            warnings.append(f"Ligne {row.get('_line', '?')} ignorée : {error}")
            continue
        previous = by_id.get(contact.contact_id)
        if previous is not None:
            merged = merge_contacts(previous, contact)
            by_id[merged.contact_id] = merged
            contacts = [merged if item.contact_id == merged.contact_id else item for item in contacts]
            warnings.append(f"Ligne {row.get('_line', '?')} fusionnée avec un doublon.")
            continue
        by_id[contact.contact_id] = contact
        contacts.append(contact)

    return LinkedInExport(
        viewer=viewer,
        viewer_schools=viewer_schools,
        contacts=tuple(contacts),
        warnings=tuple(warnings),
        skipped_rows=skipped,
        files_read=tuple(["Profile.csv", "Connections.csv"] + ([OPTIONAL_EDUCATION_FILE] if education_text else [])),
    )


def import_linkedin_export(store: "NetworkingStore", source: Path | str | Mapping[str, str | bytes]) -> ImportReport:
    """Import the parsed contacts into the local store (idempotent)."""
    export = parse_linkedin_export(source)
    imported = 0
    updated = 0
    saved: list[Contact] = []
    for contact in export.contacts:
        existed = store.get_contact(contact.contact_id) is not None
        stored = store.save_contact(contact)
        saved.append(stored)
        if existed:
            updated += 1
        else:
            imported += 1
    return ImportReport(
        imported=imported,
        updated=updated,
        skipped_rows=export.skipped_rows,
        viewer=export.viewer,
        viewer_schools=export.viewer_schools,
        warnings=export.warnings,
        contacts=tuple(saved),
    )


# ---------------------------------------------------------------------------
# Local SQLite store
# ---------------------------------------------------------------------------


class NetworkingStore:
    """A private SQLite address book.  One short connection per operation."""

    def __init__(self, db_path: Path | str):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        with self._connection() as connection:
            init_networking_schema(connection)
        try:
            os.chmod(self.db_path, 0o600)
        except OSError:
            pass

    @contextmanager
    def _connection(self) -> Iterator[sqlite3.Connection]:
        connection = sqlite3.connect(self.db_path, timeout=5.0)
        connection.row_factory = sqlite3.Row
        try:
            connection.execute("PRAGMA foreign_keys = ON")
            connection.execute("PRAGMA busy_timeout = 5000")
            connection.execute("PRAGMA secure_delete = ON")
            yield connection
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def _provenance(self, connection: sqlite3.Connection, contact_id: str) -> list[Provenance]:
        rows = connection.execute(
            "SELECT source, source_url, detail, collected_at FROM networking_provenance "
            "WHERE contact_id = ? ORDER BY provenance_id",
            (contact_id,),
        ).fetchall()
        return [provenance_from_row(row) for row in rows]

    def count_contacts(self) -> int:
        with self._connection() as connection:
            return int(connection.execute("SELECT COUNT(*) FROM networking_contacts").fetchone()[0])

    def get_contact(self, contact_id: str) -> Contact | None:
        with self._connection() as connection:
            row = connection.execute(
                "SELECT * FROM networking_contacts WHERE contact_id = ?", (_text(contact_id, 80),)
            ).fetchone()
            if row is None:
                return None
            return contact_from_row(row, self._provenance(connection, row["contact_id"]))

    def list_contacts(
        self,
        *,
        relation: str | None = None,
        company: str | None = None,
        limit: int | None = None,
    ) -> list[Contact]:
        query = "SELECT * FROM networking_contacts"
        clauses: list[str] = []
        parameters: list[Any] = []
        if relation is not None:
            clauses.append("relation = ?")
            parameters.append(normalize_relation(relation))
        if company is not None:
            clauses.append("lower(company) = lower(?)")
            parameters.append(_text(company, 200))
        if clauses:
            query += " WHERE " + " AND ".join(clauses)
        query += " ORDER BY lower(name), contact_id"
        if limit is not None:
            if not isinstance(limit, int) or limit < 1:
                raise NetworkingValidationError("limit doit être un entier positif.")
            query += " LIMIT ?"
            parameters.append(limit)
        with self._connection() as connection:
            rows = connection.execute(query, parameters).fetchall()
            return [contact_from_row(row, self._provenance(connection, row["contact_id"])) for row in rows]

    def _find_existing(self, connection: sqlite3.Connection, contact: Contact) -> sqlite3.Row | None:
        direct = connection.execute(
            "SELECT * FROM networking_contacts WHERE contact_id = ?", (contact.contact_id,)
        ).fetchone()
        if direct is not None:
            return direct
        candidates = connection.execute(
            "SELECT * FROM networking_contacts WHERE lower(name) = lower(?) OR (linkedin_url <> '' AND ? <> '' AND lower(linkedin_url) = lower(?))",
            (contact.name, contact.linkedin_url, contact.linkedin_url),
        ).fetchall()
        for row in candidates:
            existing = contact_from_row(row, self._provenance(connection, row["contact_id"]))
            if same_person(existing, contact):
                return row
        return None

    def save_contact(self, contact: Contact) -> Contact:
        contact = contact.validated()
        with self._connection() as connection:
            existing_row = self._find_existing(connection, contact)
            if existing_row is None:
                connection.execute(
                    "INSERT INTO networking_contacts (contact_id, name, role, company, school, relation, notes, "
                    "last_contact, next_action, email, linkedin_url, created_at, updated_at) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        contact.contact_id, contact.name, contact.role, contact.company, contact.school,
                        contact.relation, contact.notes, contact.last_contact, contact.next_action,
                        contact.email, contact.linkedin_url, contact.created_at, contact.updated_at,
                    ),
                )
                stored_id = contact.contact_id
            else:
                stored_id = existing_row["contact_id"]
                existing = contact_from_row(
                    existing_row, self._provenance(connection, existing_row["contact_id"])
                )
                merged = merge_contacts(existing, contact)
                connection.execute(
                    "UPDATE networking_contacts SET name = ?, role = ?, company = ?, school = ?, relation = ?, "
                    "notes = ?, last_contact = ?, next_action = ?, email = ?, linkedin_url = ?, updated_at = ? "
                    "WHERE contact_id = ?",
                    (
                        merged.name, merged.role, merged.company, merged.school, merged.relation,
                        merged.notes, merged.last_contact, merged.next_action, merged.email,
                        merged.linkedin_url, utc_now(), stored_id,
                    ),
                )
                contact = merged
            for item in contact.provenance:
                connection.execute(
                    "INSERT OR IGNORE INTO networking_provenance "
                    "(contact_id, source, source_url, detail, collected_at) VALUES (?, ?, ?, ?, ?)",
                    (stored_id, item.source, item.source_url, item.detail, item.collected_at),
                )
            row = connection.execute(
                "SELECT * FROM networking_contacts WHERE contact_id = ?", (stored_id,)
            ).fetchone()
            return contact_from_row(row, self._provenance(connection, stored_id))

    def save_contacts(self, contacts: Iterable[Contact]) -> list[Contact]:
        return [self.save_contact(contact) for contact in contacts]

    def update_contact(self, contact_id: str, **fields: Any) -> Contact:
        allowed = {
            "name", "role", "company", "school", "relation", "notes", "last_contact",
            "next_action", "email", "linkedin_url",
        }
        unknown = set(fields) - allowed
        if unknown:
            raise NetworkingValidationError(f"Champs non modifiables : {', '.join(sorted(unknown))}.")
        current = self.get_contact(contact_id)
        if current is None:
            raise KeyError(contact_id)
        payload = {**current.as_dict(), **fields}
        normalized = Contact(
            contact_id=current.contact_id,
            name=payload["name"],
            role=payload["role"],
            company=payload["company"],
            school=payload["school"],
            relation=normalize_relation(payload["relation"]),
            notes=payload["notes"],
            last_contact=payload["last_contact"],
            next_action=payload["next_action"],
            email=payload["email"],
            linkedin_url=payload["linkedin_url"],
            provenance=current.provenance,
            created_at=current.created_at,
            updated_at=current.updated_at,
        ).validated()
        with self._connection() as connection:
            connection.execute(
                "UPDATE networking_contacts SET name = ?, role = ?, company = ?, school = ?, relation = ?, "
                "notes = ?, last_contact = ?, next_action = ?, email = ?, linkedin_url = ?, updated_at = ? "
                "WHERE contact_id = ?",
                (
                    normalized.name, normalized.role, normalized.company, normalized.school, normalized.relation,
                    normalized.notes, normalized.last_contact, normalized.next_action, normalized.email,
                    normalized.linkedin_url, utc_now(), contact_id,
                ),
            )
        updated = self.get_contact(contact_id)
        assert updated is not None
        return updated

    def delete_contact(self, contact_id: str) -> bool:
        with self._connection() as connection:
            cursor = connection.execute(
                "DELETE FROM networking_contacts WHERE contact_id = ?", (_text(contact_id, 80),)
            )
            return cursor.rowcount > 0

    def purge_all(self) -> int:
        """Delete every contact and every proof from this local address book."""
        with self._connection() as connection:
            deleted = int(connection.execute("SELECT COUNT(*) FROM networking_contacts").fetchone()[0])
            connection.execute("DELETE FROM networking_provenance")
            connection.execute("DELETE FROM networking_contacts")
            return deleted


# ---------------------------------------------------------------------------
# Target recommendations (greedy, deterministic, provenance-citing)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class TargetRecommendation:
    contact: Contact
    score: float
    reasons: tuple[str, ...]
    desk: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "contact_id": self.contact.contact_id,
            "name": self.contact.name,
            "role": self.contact.role,
            "company": self.contact.company,
            "school": self.contact.school,
            "relation": self.contact.relation,
            "relation_label": RELATION_LABELS.get(self.contact.relation, self.contact.relation),
            "desk": self.desk,
            "desk_label": DESK_LABELS.get(self.desk or "", ""),
            "score": self.score,
            "reasons": list(self.reasons),
            "provenance": [item.as_dict() for item in self.contact.provenance],
        }


def _significant_tokens(value: Any) -> set[str]:
    return {
        token
        for token in normalized_text(value).split()
        if len(token) >= 3 and token not in _ROLE_STOPWORDS
        and not token.isdigit()
    }


def _normalize_desks(values: Iterable[Any]) -> set[str]:
    desks: set[str] = set()
    for value in values:
        token = normalized_text(value).replace(" ", "_")
        canonical = {
            "m&a": "ma", "m_a": "ma", "mergers_and_acquisitions": "ma", "fusions_acquisitions": "ma",
            "technology_media_telecom": "tmt", "equity_capital_markets": "ecm",
            "debt_capital_markets": "dcm", "leveraged_finance": "leveraged_finance",
            "private_equity": "private_equity", "investment_banking_coverage": "ibc",
            "coverage_desk": "coverage",
        }.get(token, token)
        if canonical not in DESK_LABELS:
            raise NetworkingValidationError(f"Desk inconnu : {value!r}. Desks : {', '.join(DESK_LABELS)}.")
        desks.add(canonical)
    return desks


def recommend_targets(
    contacts: Iterable[Contact],
    *,
    target_role: str,
    target_departments: Iterable[str] = (),
    viewer_schools: Iterable[str] = (),
    limit: int = 20,
    per_company_limit: int = 2,
    min_score: float = 12.0,
) -> list[TargetRecommendation]:
    """Rank the contacts worth contacting, greedily and deterministically.

    Signals: shared role words with the target role, target finance desk,
    proven alumni link, and the declared relation.  Contacts below
    ``min_score`` are not recommended.  A company contributes at most
    ``per_company_limit`` targets so the list is not one employer repeated.
    """
    target_role = _text(target_role, 200)
    if not target_role:
        raise NetworkingValidationError("Le poste cible est obligatoire pour recommander des contacts.")
    if not isinstance(limit, int) or not 1 <= limit <= 200:
        raise NetworkingValidationError("limit doit être un entier entre 1 et 200.")
    if not isinstance(per_company_limit, int) or not 1 <= per_company_limit <= 20:
        raise NetworkingValidationError("per_company_limit doit être un entier entre 1 et 20.")

    wanted_desks = _normalize_desks(target_departments) or {classify_desk(target_role)} - {None}
    target_tokens = _significant_tokens(target_role)
    school_keys = {normalized_text(school) for school in viewer_schools if clean_text(school)}

    scored: list[TargetRecommendation] = []
    for contact in contacts:
        if not contact.provenance:
            continue
        score = 0.0
        reasons: list[str] = []
        desk = classify_desk(contact.role, contact.company)

        overlap = target_tokens & _significant_tokens(contact.role)
        if overlap:
            bonus = min(18.0, 6.0 * len(overlap))
            score += bonus
            reasons.append("Même métier : " + ", ".join(sorted(overlap)) + f" (+{bonus:g})")

        if desk is not None:
            score += 8.0
            reasons.append(f"Desk identifié : {DESK_LABELS[desk]} (+8)")
            if desk in wanted_desks:
                score += 20.0
                reasons.append(f"Desk ciblé : {DESK_LABELS[desk]} (+20)")

        if contact.relation == "alumni":
            score += 25.0
            reasons.append("Alumni avec école explicite (+25)")
        elif contact.school_key and contact.school_key in school_keys:
            score += 18.0
            reasons.append("École partagée, alumni à confirmer (+18)")

        if contact.relation == "first":
            score += 8.0
            reasons.append("Contact de 1er degré (+8)")
        elif contact.relation == "second":
            score += 2.0
            reasons.append("Contact de 2nd degré (+2)")

        if score < min_score:
            continue
        scored.append(TargetRecommendation(contact=contact, score=round(score, 2), reasons=tuple(reasons), desk=desk))

    relation_rank = {"first": 0, "alumni": 1, "second": 2}
    scored.sort(
        key=lambda item: (
            -item.score,
            relation_rank.get(item.contact.relation, 3),
            normalized_text(item.contact.name),
            item.contact.contact_id,
        )
    )

    selected: list[TargetRecommendation] = []
    seen_ids: set[str] = set()
    seen_people: set[tuple[str, str]] = set()
    per_company: dict[str, int] = {}
    for item in scored:
        contact = item.contact
        person_key = (normalized_text(contact.name), contact.company_key)
        if contact.contact_id in seen_ids:
            continue
        if contact.company_key and person_key in seen_people:
            continue
        if contact.company_key:
            if per_company.get(contact.company_key, 0) >= per_company_limit:
                continue
        selected.append(item)
        seen_ids.add(contact.contact_id)
        if contact.company_key:
            seen_people.add(person_key)
            per_company[contact.company_key] = per_company.get(contact.company_key, 0) + 1
        if len(selected) >= limit:
            break
    return selected


def recommend_from_store(
    store: NetworkingStore,
    *,
    target_role: str,
    target_departments: Iterable[str] = (),
    viewer_schools: Iterable[str] = (),
    limit: int = 20,
    per_company_limit: int = 2,
) -> list[TargetRecommendation]:
    return recommend_targets(
        store.list_contacts(),
        target_role=target_role,
        target_departments=target_departments,
        viewer_schools=viewer_schools,
        limit=limit,
        per_company_limit=per_company_limit,
    )


# ---------------------------------------------------------------------------
# Networking drafts (approved facts only, exported locally, never sent)
# ---------------------------------------------------------------------------


class DraftNotApplicable(ValueError):
    """The requested draft does not fit the contact or the approved facts."""


@dataclass(frozen=True)
class ProfileFact:
    """One approved profile fact.  Unapproved facts are never used."""

    fact_id: str
    text: str
    approved: bool = True
    source: str = ""


@dataclass(frozen=True)
class DraftSegment:
    fact_id: str
    text: str

    def as_dict(self) -> dict[str, str]:
        return {"fact_id": self.fact_id, "text": self.text}


@dataclass(frozen=True)
class NetworkingDraft:
    kind: str
    contact_id: str
    contact_name: str
    subject: str
    greeting: str
    segments: tuple[DraftSegment, ...]
    body: str
    provenance: tuple[Provenance, ...]
    can_send: bool = False

    def as_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "kind_label": DRAFT_LABELS[self.kind],
            "contact_id": self.contact_id,
            "contact_name": self.contact_name,
            "subject": self.subject,
            "greeting": self.greeting,
            "segments": [segment.as_dict() for segment in self.segments],
            "body": self.body,
            "provenance": [item.as_dict() for item in self.provenance],
            "can_send": self.can_send,
        }


def _coerce_fact(raw: Any, index: int) -> ProfileFact | None:
    if isinstance(raw, ProfileFact):
        fact = raw
    elif isinstance(raw, Mapping):
        fact = ProfileFact(
            fact_id=_text(raw.get("fact_id") or raw.get("id") or f"fact-{index}", 80),
            text=_text(raw.get("text"), 600),
            approved=raw.get("approved") is True,
            source=_text(raw.get("source"), 200),
        )
    else:
        # A bare string carries no approval: it is ignored on purpose.
        return None
    if not fact.approved or len(fact.text) < MIN_EXCERPT_LENGTH:
        return None
    return fact


def _approved_facts(profile_facts: Iterable[Any]) -> list[ProfileFact]:
    facts: list[ProfileFact] = []
    for index, raw in enumerate(profile_facts):
        fact = _coerce_fact(raw, index)
        if fact is not None and all(existing.text != fact.text for existing in facts):
            facts.append(fact)
    return facts


def _is_recruiter(contact: Contact) -> bool:
    haystack = " " + normalized_text(contact.role) + " "
    return any(token in haystack for token in _RECRUITER_TOKENS)


def select_draft_kind(contact: Contact, *, viewer_schools: Iterable[str] = ()) -> str | None:
    """Pick the pattern that fits a contact, in a documented priority order."""
    school_keys = {normalized_text(school) for school in viewer_schools if clean_text(school)}
    if contact.relation == "alumni" or (contact.school_key and contact.school_key in school_keys):
        return "alumni_first_contact"
    if classify_desk(contact.role, contact.company) is not None:
        return "coverage_desk"
    if _is_recruiter(contact):
        return "school_recruiter"
    return None


def _first_name(name: str) -> str:
    parts = clean_text(name, limit=160).split()
    return parts[0] if parts else ""


def build_networking_draft(
    contact: Contact,
    *,
    kind: str,
    profile_facts: Iterable[Any],
    viewer_schools: Iterable[str] = (),
    viewer_name: str = "",
    target_role: str = "",
) -> NetworkingDraft:
    """Write one segmented draft from approved facts.  Never sends anything."""
    if kind not in DRAFT_KINDS:
        raise NetworkingValidationError(f"Modèle inconnu : {kind!r}. Modèles : {', '.join(DRAFT_KINDS)}.")
    contact = contact.validated()
    viewer_schools = tuple(viewer_schools)
    facts = _approved_facts(profile_facts)
    if not facts:
        raise DraftNotApplicable("Aucun fait approuvé : aucun brouillon ne peut être rédigé.")

    school_keys = {normalized_text(school) for school in viewer_schools if clean_text(school)}
    if kind == "alumni_first_contact":
        if not (contact.relation == "alumni" or (contact.school_key and contact.school_key in school_keys)):
            raise DraftNotApplicable("Ce contact n’est pas alumni avec une école explicite.")
        school = contact.school or next(iter(viewer_schools), "")
        opener = (
            f"Je vous écris parce que nous sommes tous les deux passés par {school}. "
            f"Je m’intéresse aujourd’hui à {target_role or 'la finance'} et votre parcours chez "
            f"{contact.company or 'votre entreprise'} m’aiderait à mieux comprendre les attentes du secteur."
        )
        subject = f"Alumni {school} — un échange rapide ?" if school else "Un échange entre alumni ?"
    elif kind == "school_recruiter":
        if not _is_recruiter(contact):
            raise DraftNotApplicable("Ce contact n’est pas identifié comme recruteur (rôle sans preuve).")
        opener = (
            "Nous nous sommes croisés via l’école et je prépare ma candidature"
            + (f" pour un poste de {target_role}" if target_role else "")
            + f". Je serais ravi d’échanger quelques minutes sur les profils que {contact.company or 'votre équipe'} recherche."
        )
        subject = "Échange recruteur — profil candidat"
    else:
        desk = classify_desk(contact.role, contact.company)
        if desk is None:
            raise DraftNotApplicable("Ce contact n’est rattaché à aucun desk identifié.")
        opener = (
            f"Je m’intéresse aux desks {DESK_LABELS[desk]} et votre expérience chez "
            f"{contact.company or 'votre banque'} me serait très utile pour comprendre le métier au quotidien."
        )
        subject = f"Échange sur le desk {DESK_LABELS[desk]}"

    selected = facts[:2]
    segments = tuple(DraftSegment(fact_id=fact.fact_id, text=fact.text) for fact in selected)
    bullet_lines = "\n".join(f"- {segment.text}" for segment in segments)
    signature = _text(viewer_name, 120)
    body = "\n\n".join(
        part
        for part in (
            f"Bonjour {_first_name(contact.name)},",
            opener,
            "Pour être transparent, voici les faits de mon parcours que je peux confirmer :\n" + bullet_lines,
            "Auriez-vous 15 minutes pour un échange ? Je m’adapte à votre agenda.",
            f"Bonne journée,\n{signature}" if signature else "Bonne journée,",
        )
        if part
    )
    return NetworkingDraft(
        kind=kind,
        contact_id=contact.contact_id,
        contact_name=contact.name,
        subject=subject,
        greeting=f"Bonjour {_first_name(contact.name)},",
        segments=segments,
        body=body,
        provenance=tuple(contact.provenance),
        can_send=False,
    )


def draft_for_contact(
    contact: Contact,
    *,
    profile_facts: Iterable[Any],
    viewer_schools: Iterable[str] = (),
    viewer_name: str = "",
    target_role: str = "",
) -> NetworkingDraft | None:
    """Build the draft that fits the contact, or ``None`` when none fits."""
    kind = select_draft_kind(contact, viewer_schools=viewer_schools)
    if kind is None:
        return None
    try:
        return build_networking_draft(
            contact,
            kind=kind,
            profile_facts=profile_facts,
            viewer_schools=viewer_schools,
            viewer_name=viewer_name,
            target_role=target_role,
        )
    except DraftNotApplicable:
        return None


def export_drafts(drafts: Iterable[NetworkingDraft], path: Path | str) -> Path:
    """Write drafts to a local file.  There is no send/upload path here."""
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    items = [draft.as_dict() for draft in drafts]
    if target.suffix.lower() == ".json":
        content = json.dumps({"drafts": items, "can_send": False}, ensure_ascii=False, indent=2)
    else:
        blocks: list[str] = []
        for draft in items:
            blocks.append(
                f"=== {draft['kind_label']} — {draft['contact_name']} ===\n"
                f"Objet : {draft['subject']}\n\n{draft['body']}\n"
            )
        content = "\n".join(blocks)
    descriptor = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
        handle.write(content)
    return target


# ---------------------------------------------------------------------------
# Public facts from the local Web Researcher (proof mandatory)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class PublicFact:
    """A public fact about a person, with the page and excerpt proving it."""

    person_name: str
    company: str
    source_name: str
    source_url: str
    excerpt: str
    role: str = ""
    school: str = ""
    collected_at: str = ""


def record_public_fact(store: NetworkingStore, fact: PublicFact) -> Contact:
    """Record one evidenced public fact.  No page is fetched here."""
    return record_public_facts(store, [fact])[0]


def record_public_facts(
    store: NetworkingStore,
    facts: Iterable[PublicFact],
    *,
    max_pages_per_company: int = 1,
    viewer_schools: Iterable[str] = (),
) -> list[Contact]:
    """Record public facts, enforcing **one page per company per research**.

    The Web Researcher already fetched the pages; this function only validates
    the evidence and stores it.  Two different URLs for the same company in a
    single research run are refused instead of silently widening the scope.
    """
    if max_pages_per_company != 1:
        raise NetworkingValidationError("Une recherche accepte au maximum 1 page par entreprise.")
    school_keys = {normalized_text(school) for school in viewer_schools if clean_text(school)}
    urls_per_company: dict[str, str] = {}
    pending: list[Contact] = []
    for fact in facts:
        name = _text(fact.person_name, 160)
        company = _text(fact.company, 200)
        source_name = _text(fact.source_name, 200)
        source_url = _text(fact.source_url, 1_000)
        excerpt = _text(fact.excerpt, 1_000)
        school = _text(fact.school, 200)
        if not name or not company:
            raise NetworkingValidationError("Un fait public exige un nom de personne et une entreprise.")
        if not source_name or not source_url.startswith(("http://", "https://")):
            raise NetworkingValidationError("Un fait public exige une source nommée et une URL http(s).")
        if len(excerpt) < MIN_EXCERPT_LENGTH:
            raise NetworkingValidationError("Un fait public exige un extrait de preuve suffisant.")
        company_key = normalized_text(company)
        known_url = urls_per_company.get(company_key)
        if known_url is not None and known_url != source_url:
            raise NetworkingValidationError(
                f"Une seule page par entreprise : {company} a déjà été documentée par {known_url}."
            )
        urls_per_company[company_key] = source_url
        provenance = Provenance(
            source="web_research",
            detail=f"{source_name} — extrait : {excerpt[:300]}",
            source_url=source_url,
            collected_at=fact.collected_at or utc_now(),
        )
        relation = "alumni" if school and normalized_text(school) in school_keys else "second"
        pending.append(Contact(
            name=name,
            role=_text(fact.role, 200),
            company=company,
            school=school,
            relation=relation,
            provenance=[provenance],
        ).validated())
    # Every fact was validated before the first write: a refused research run
    # never leaves half of its contacts behind.
    return [store.save_contact(contact) for contact in pending]


#: Explicit reminder for readers and for the security tests: there is no
#: function in this module that sends, uploads or exports the address book.
NO_NETWORK_BY_DESIGN = True
