"""Local-only schema for the networking address book (SPEC-040).

A networking contact is a private, locally stored record: name, role, company,
school, relation, notes, last contact and next action.  Every fact attached to
a contact keeps its **provenance** (who says it, where) so a recommendation can
always be explained instead of asserted.

Security stance of this module:

* it never performs a network call, never scrapes a profile and never imports a
  social-network SDK;
* it only describes and validates records -- the SQLite storage lives in
  :mod:`career.networking`;
* a contact without provenance is rejected: an unsourced fact is not a fact.
"""

from __future__ import annotations

import hashlib
import re
import sqlite3
from dataclasses import dataclass, field, replace
from typing import Any

from .models import clean_text, normalized_text, utc_now


NETWORKING_SCHEMA_VERSION = 1

#: Relations accepted by the local address book.  ``alumni`` is a *proven*
#: relationship: it requires an explicit shared school, never a guess.
RELATIONS: tuple[str, ...] = ("first", "second", "alumni")
RELATION_LABELS: dict[str, str] = {
    "first": "1er degré",
    "second": "2nd degré",
    "alumni": "Alumni",
}
_RELATION_ALIASES: dict[str, str] = {
    "1": "first",
    "1er": "first",
    "1ere": "first",
    "1st": "first",
    "first": "first",
    "premier": "first",
    "contact direct": "first",
    "2": "second",
    "2e": "second",
    "2eme": "second",
    "2nd": "second",
    "2nd degree": "second",
    "second": "second",
    "deuxieme": "second",
    "alumni": "alumni",
    "alumnus": "alumni",
    "alumna": "alumni",
    "ecole": "alumni",
    "school": "alumni",
    "ancien eleve": "alumni",
    "ancienne eleve": "alumni",
}

#: Provenance sources.  ``linkedin_export`` is the user's own decompressed
#: export; ``web_research`` is a public fact collected with evidence by the
#: local Web Researcher; ``manual`` is a record the user typed themselves.
SOURCES: tuple[str, ...] = ("linkedin_export", "web_research", "manual")
SOURCE_LABELS: dict[str, str] = {
    "linkedin_export": "Export LinkedIn local",
    "web_research": "Recherche web publique (preuve jointe)",
    "manual": "Saisie manuelle",
}

FIELD_LIMITS: dict[str, int] = {
    "name": 160,
    "role": 200,
    "company": 200,
    "school": 200,
    "notes": 4_000,
    "last_contact": 40,
    "next_action": 500,
    "email": 320,
    "linkedin_url": 500,
    "source_url": 1_000,
    "detail": 1_000,
}

_CONTROL_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
_HTTP_RE = re.compile(r"^https?://", re.IGNORECASE)


class NetworkingValidationError(ValueError):
    """A contact, provenance or import row violates the local contract."""


@dataclass(frozen=True)
class Provenance:
    """Who says a fact, and where it was observed.

    ``detail`` names the speaker or the document (for example
    ``"Export LinkedIn (Connections.csv, ligne 4)"``); ``source_url`` is the
    page the fact comes from when one exists.  ``linkedin_export`` provenance
    deliberately has no URL: the export is a local file, not a public page.
    """

    source: str
    detail: str
    source_url: str = ""
    collected_at: str = ""

    def validated(self) -> "Provenance":
        source = normalized_text(self.source).replace(" ", "_")
        if source not in SOURCES:
            raise NetworkingValidationError(
                f"Provenance inconnue : {self.source!r}. Sources acceptées : {', '.join(SOURCES)}."
            )
        detail = _text(self.detail, "detail")
        if not detail:
            raise NetworkingValidationError("Une provenance doit dire QUI porte le fait (detail vide).")
        source_url = _url(self.source_url)
        if source == "web_research" and not source_url:
            raise NetworkingValidationError("Une provenance web_research exige l’URL de la preuve.")
        return Provenance(
            source=source,
            detail=detail,
            source_url=source_url,
            collected_at=_text(self.collected_at, "last_contact") or utc_now(),
        )
    def as_dict(self) -> dict[str, str]:
        return {
            "source": self.source,
            "source_label": SOURCE_LABELS.get(self.source, self.source),
            "detail": self.detail,
            "source_url": self.source_url,
            "collected_at": self.collected_at,
        }


@dataclass
class Contact:
    """One private networking contact, stored locally in SQLite."""

    name: str
    role: str = ""
    company: str = ""
    school: str = ""
    relation: str = "first"
    notes: str = ""
    last_contact: str = ""
    next_action: str = ""
    email: str = ""
    linkedin_url: str = ""
    contact_id: str = ""
    provenance: list[Provenance] = field(default_factory=list)
    created_at: str = ""
    updated_at: str = ""

    def validated(self) -> "Contact":
        name = _text(self.name, "name")
        if not name:
            raise NetworkingValidationError("Un contact doit avoir un nom.")
        provenance = [item.validated() for item in self.provenance]
        if not provenance:
            raise NetworkingValidationError("Un contact sans provenance n’est pas importable.")
        company = _text(self.company, "company")
        school = _text(self.school, "school")
        relation = normalize_relation(self.relation, school=school)
        now = utc_now()
        return Contact(
            name=name,
            role=_text(self.role, "role"),
            company=company,
            school=school,
            relation=relation,
            notes=_text(self.notes, "notes"),
            last_contact=_text(self.last_contact, "last_contact"),
            next_action=_text(self.next_action, "next_action"),
            email=_text(self.email, "email"),
            linkedin_url=_url(self.linkedin_url),
            contact_id=self.contact_id or contact_identifier(name=name, company=company, linkedin_url=self.linkedin_url),
            provenance=provenance,
            created_at=_text(self.created_at, "last_contact") or now,
            updated_at=now,
        )

    @property
    def company_key(self) -> str:
        return normalized_text(self.company)

    @property
    def school_key(self) -> str:
        return normalized_text(self.school)

    def as_dict(self) -> dict[str, Any]:
        return {
            "contact_id": self.contact_id,
            "name": self.name,
            "role": self.role,
            "company": self.company,
            "school": self.school,
            "relation": self.relation,
            "relation_label": RELATION_LABELS.get(self.relation, self.relation),
            "notes": self.notes,
            "last_contact": self.last_contact,
            "next_action": self.next_action,
            "email": self.email,
            "linkedin_url": self.linkedin_url,
            "provenance": [item.as_dict() for item in self.provenance],
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }


def _text(value: Any, key: str) -> str:
    limit = FIELD_LIMITS.get(key, 1_000)
    return _CONTROL_RE.sub("", clean_text(value, limit=limit))


def _url(value: Any) -> str:
    url = _text(value, "source_url")
    if not url:
        return ""
    if not _HTTP_RE.match(url):
        return ""
    return url[: FIELD_LIMITS.get("source_url", 1_000)]


def normalize_relation(value: Any, *, school: str = "") -> str:
    """Map a written relation to the closed vocabulary.

    An explicit ``alumni`` is accepted.  The ``school`` argument is only used
    to reject a contradiction, never to *promote* a contact to alumni: alumni
    status comes from an explicit school fact, not from proximity.
    """
    token = normalized_text(value)
    if not token:
        return "first"
    relation = _RELATION_ALIASES.get(token)
    if relation is None:
        raise NetworkingValidationError(
            f"Relation inconnue : {value!r}. Relations acceptées : {', '.join(RELATIONS)}."
        )
    return relation


def mark_alumni(contact: Contact, *, school: str) -> Contact:
    """Tag a contact as alumni from an *explicit* shared school.

    The school argument is mandatory: a caller cannot promote a contact on a
    hunch, a shared employer or a name similarity.
    """
    school = _text(school, "school")
    if not school:
        raise NetworkingValidationError("Le statut alumni exige une école explicite.")
    return replace(contact, relation="alumni", school=school)


def contact_identifier(*, name: str, company: str = "", linkedin_url: str = "") -> str:
    """Deterministic id so re-importing the same export is idempotent."""
    url = _url(linkedin_url).lower().rstrip("/")
    if url:
        seed = f"url|{url.split('?')[0]}"
    else:
        seed = f"identity|{normalized_text(name)}|{normalized_text(company)}"
    return "net_" + hashlib.sha256(seed.encode("utf-8")).hexdigest()[:16]


def same_person(left: Contact, right: Contact) -> bool:
    """Two records describe the same person when their stable keys agree.

    A shared name alone is not enough: two different people can share a name.
    The pair must also share a company or a LinkedIn URL.
    """
    if left.linkedin_url and right.linkedin_url:
        return left.linkedin_url.lower().rstrip("/") == right.linkedin_url.lower().rstrip("/")
    if normalized_text(left.name) != normalized_text(right.name):
        return False
    return bool(left.company_key) and left.company_key == right.company_key


def merge_contacts(existing: Contact, incoming: Contact) -> Contact:
    """Merge two records of the same person without losing any proof."""
    seen = {(p.source, p.source_url, p.detail) for p in existing.provenance}
    provenance = list(existing.provenance)
    for item in incoming.provenance:
        key = (item.source, item.source_url, item.detail)
        if key not in seen:
            provenance.append(item)
            seen.add(key)
    merged = replace(
        existing,
        role=incoming.role or existing.role,
        company=incoming.company or existing.company,
        school=incoming.school or existing.school,
        relation="alumni" if "alumni" in {existing.relation, incoming.relation} else existing.relation,
        notes=incoming.notes or existing.notes,
        last_contact=incoming.last_contact or existing.last_contact,
        next_action=incoming.next_action or existing.next_action,
        email=incoming.email or existing.email,
        linkedin_url=incoming.linkedin_url or existing.linkedin_url,
        provenance=provenance,
        updated_at=utc_now(),
    )
    return merged


SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS networking_contacts (
    contact_id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    role TEXT NOT NULL DEFAULT '',
    company TEXT NOT NULL DEFAULT '',
    school TEXT NOT NULL DEFAULT '',
    relation TEXT NOT NULL DEFAULT 'first'
        CHECK (relation IN ('first', 'second', 'alumni')),
    notes TEXT NOT NULL DEFAULT '',
    last_contact TEXT NOT NULL DEFAULT '',
    next_action TEXT NOT NULL DEFAULT '',
    email TEXT NOT NULL DEFAULT '',
    linkedin_url TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS networking_provenance (
    provenance_id INTEGER PRIMARY KEY AUTOINCREMENT,
    contact_id TEXT NOT NULL
        REFERENCES networking_contacts(contact_id) ON DELETE CASCADE,
    source TEXT NOT NULL
        CHECK (source IN ('linkedin_export', 'web_research', 'manual')),
    source_url TEXT NOT NULL DEFAULT '',
    detail TEXT NOT NULL,
    collected_at TEXT NOT NULL DEFAULT '',
    UNIQUE (contact_id, source, source_url, detail)
);

CREATE INDEX IF NOT EXISTS idx_networking_contacts_company
    ON networking_contacts (company);
CREATE INDEX IF NOT EXISTS idx_networking_contacts_relation
    ON networking_contacts (relation);
CREATE INDEX IF NOT EXISTS idx_networking_provenance_contact
    ON networking_provenance (contact_id);
"""


def init_networking_schema(connection: sqlite3.Connection) -> None:
    """Create the local tables (idempotent) and record the schema version."""
    connection.executescript(SCHEMA_SQL)
    connection.execute(f"PRAGMA user_version = {NETWORKING_SCHEMA_VERSION}")


def provenance_from_row(row: sqlite3.Row | dict[str, Any]) -> Provenance:
    return Provenance(
        source=row["source"],
        detail=row["detail"],
        source_url=row["source_url"],
        collected_at=row["collected_at"],
    )


def contact_from_row(row: sqlite3.Row | dict[str, Any], provenance: list[Provenance]) -> Contact:
    return Contact(
        contact_id=row["contact_id"],
        name=row["name"],
        role=row["role"],
        company=row["company"],
        school=row["school"],
        relation=row["relation"],
        notes=row["notes"],
        last_contact=row["last_contact"],
        next_action=row["next_action"],
        email=row["email"],
        linkedin_url=row["linkedin_url"],
        provenance=provenance,
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )
