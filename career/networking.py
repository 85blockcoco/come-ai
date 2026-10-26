"""Local networking directory (SPEC-040 / CVBOOST-75).

Three capabilities, all strictly offline:

1. Import of the user's own LinkedIn export (unzipped ``Profile.csv`` and
   ``Connections.csv``).  Facts parsed from these files are tagged
   ``source=linkedin_export`` and stored in the local SQLite directory only —
   they are never sent anywhere.
2. Target recommendations: match between the user's target role and a
   contact's role/department, alumni matching, and finance-specific desks
   (IBC, M&A, TMT, coverage).  Every recommendation cites its provenance
   (who states the fact, and where).
3. Networking message drafts (first alumni contact, school recruiter,
   coverage desk), written only from approved profile facts and exported to
   a file the user sends themself.  There is no sending feature at all.
"""

from __future__ import annotations

import csv
import io
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .models import clean_text, normalized_text
from .networking_schema import (
    NETWORKING_SCHEMA_VERSION,
    SOURCE_LINKEDIN_EXPORT,
)

__all__ = [
    "DESK_FAMILIES",
    "DRAFT_KINDS",
    "ImportSummary",
    "LINKEDIN_CONNECTIONS_FILENAME",
    "LINKEDIN_PROFILE_FILENAME",
    "MessageDraft",
    "MissingFactError",
    "NETWORKING_SCHEMA_VERSION",
    "Recommendation",
    "SOURCE_LINKEDIN_EXPORT",
    "detect_desk_families",
    "draft_message",
    "draft_messages_for_recommendation",
    "export_drafts",
    "format_linkedin_date",
    "import_linkedin_export",
    "is_recruiter",
    "parse_linkedin_connections_csv",
    "parse_linkedin_profile_csv",
    "recommend_targets",
]

LINKEDIN_CONNECTIONS_FILENAME = "Connections.csv"
LINKEDIN_PROFILE_FILENAME = "Profile.csv"

# Finance desk families (IBC, M&A, TMT, coverage) with local, versioned keywords.
DESK_FAMILIES: dict[str, tuple[str, ...]] = {
    "ibc": (
        "ibc",
        "institutional banking",
        "banque de financement",
        "bfi",
        "banque de financement et d'investissement",
        "investment banking",
        "ibd",
    ),
    "m&a": (
        "m&a",
        "m & a",
        "merger",
        "acquisition",
        "fusions-acquisitions",
        "fusion-acquisition",
        "corporate finance",
        "banque d'affaires",
        "transactions",
    ),
    "tmt": (
        "tmt",
        "tech, media",
        "technology, media",
        "technologies, medias",
        "technologies, médias",
        "telecom",
        "télécom",
    ),
    "coverage": (
        "coverage",
        "couverture",
        "corporate coverage",
        "financial sponsors",
        "large corporates",
        "grandes entreprises",
        "institutional clients",
        "clients institutionnels",
    ),
}

_RECRUITER_KEYWORDS = (
    "recruteur",
    "recruteuse",
    "recruiter",
    "recruitment",
    "recrutement",
    "talent acquisition",
    "talent partner",
    "human resources",
    "campus manager",
)

# Weight used by recommend_targets().
_WEIGHT_ALUMNI = 3
_WEIGHT_RECRUITER = 2
_WEIGHT_DESK = 2
_WEIGHT_ROLE_TOKEN = 1
_MAX_ROLE_TOKENS = 2


class MissingFactError(ValueError):
    """Raised when a draft template requires a fact nobody approved or provided."""


# --------------------------------------------------------------------------- csv parsing
def parse_linkedin_connections_csv(content: str) -> list[dict[str, str]]:
    """Parse ``Connections.csv`` from a LinkedIn export into normalized rows.

    The reference format is ``First Name,Last Name,URL,Email Address,Company,
    Position,Connected On``; optional or reordered columns are tolerated and
    missing values simply stay empty.
    """
    rows = _csv_rows(content)
    if not rows:
        return []
    header = [normalized_text(cell) for cell in rows[0]]
    index = {name: position for position, name in enumerate(header)}
    contacts: list[dict[str, str]] = []
    for raw in rows[1:]:
        first = _cell(raw, index.get("first name"))
        last = _cell(raw, index.get("last name"))
        full_name = clean_text(f"{first} {last}".strip(), limit=200)
        if not full_name:
            continue
        connected_on = _cell(raw, index.get("connected on"))
        contacts.append(
            {
                "full_name": full_name,
                "profile_url": _cell(raw, index.get("url")),
                "email": _cell(raw, index.get("email address")),
                "company": _cell(raw, index.get("company")),
                "headline": _cell(raw, index.get("position")),
                "connected_on": connected_on,
                "last_contact_at": format_linkedin_date(connected_on),
            }
        )
    return contacts


def parse_linkedin_profile_csv(content: str) -> list[dict[str, str]]:
    """Extract (kind, value) facts about the user from their ``Profile.csv``.

    LinkedIn's full export stores the user's own profile as a header row plus a
    single data row.  Schools may appear in a ``Schools`` column and roles in
    ``Positions``; the headline is read from ``Headline``.  Anything unknown is
    ignored rather than invented.
    """
    rows = _csv_rows(content)
    if not rows:
        return []
    header = [normalized_text(cell) for cell in rows[0]]
    data = rows[1] if len(rows) > 1 else []
    facts: list[dict[str, str]] = []

    def _collect(kind: str, raw_values: str) -> None:
        for value in _split_multi(raw_values):
            facts.append({"kind": kind, "value": value})

    for column, kind in (("schools", "school"), ("school", "school"), ("education", "school")):
        if column in header:
            _collect(kind, _cell(data, header.index(column)))
    for column, kind in (("positions", "role"), ("position", "role"), ("job title", "role")):
        if column in header:
            _collect(kind, _cell(data, header.index(column)))
    if "headline" in header:
        headline = _cell(data, header.index("headline"))
        if headline:
            facts.append({"kind": "headline", "value": headline})
    return facts


def format_linkedin_date(value: str) -> str:
    """Normalize the locale-dependent LinkedIn dates to ISO, or '' when unknown."""
    text = clean_text(value, limit=60)
    if not text:
        return ""
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", text):
        return text
    months = {
        "jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6,
        "jul": 7, "aug": 8, "sep": 9, "oct": 10, "nov": 11, "dec": 12,
        "janv": 1, "fevr": 2, "mars": 3, "avr": 4, "juin": 6, "juil": 7,
        "aout": 8, "sept": 9, "okt": 10, "dez": 12,
    }
    match = re.fullmatch(r"(\d{1,2})\s+([A-Za-zéûôè.]+)\s+(\d{4})", text)
    if match:
        day, month_token, year = match.groups()
        month = months.get(month_token[:4].lower()) or months.get(month_token[:3].lower())
        if month:
            return f"{int(year):04d}-{month:02d}-{int(day):02d}"
    match = re.fullmatch(r"(\d{1,2})/(\d{1,2})/(\d{4})", text)
    if match:
        day, month, year = match.groups()
        return f"{int(year):04d}-{int(month):02d}-{int(day):02d}"
    return ""


def _csv_rows(content: str) -> list[list[str]]:
    text = clean_text(content.replace("﻿", ""), limit=2_000_000)
    if not text:
        return []
    reader = csv.reader(io.StringIO(text))
    return [row for row in reader if any(cell.strip() for cell in row)]


def _cell(row: list[str], position: int | None) -> str:
    if position is None or position >= len(row):
        return ""
    return clean_text(row[position], limit=500)


def _split_multi(value: str) -> list[str]:
    return [clean_text(part, limit=300) for part in re.split(r"[;,]", value) if clean_text(part)]


# ------------------------------------------------------------------------------- import
@dataclass(frozen=True)
class ImportSummary:
    connections_imported: int = 0
    contacts_updated: int = 0
    profile_facts: int = 0
    source: str = "linkedin_export"
    files: tuple[str, ...] = field(default_factory=tuple)


def import_linkedin_export(
    store: Any,
    *,
    profile_csv: str | None = None,
    connections_csv: str | None = None,
) -> ImportSummary:
    """Import an unzipped LinkedIn export into the local store.  Offline only."""
    connections_imported = 0
    contacts_updated = 0
    facts_added = 0
    files: list[str] = []

    if connections_csv is not None:
        rows = parse_linkedin_connections_csv(connections_csv)
        existing_keys = {
            (normalized_text(contact.full_name), normalized_text(contact.company))
            for contact in store.list_contacts(source=SOURCE_LINKEDIN_EXPORT)
        }
        provenance = _linkedin_provenance(LINKEDIN_CONNECTIONS_FILENAME, ("poste", "entreprise", "identite"))
        for row in rows:
            key = (normalized_text(row["full_name"]), normalized_text(row["company"]))
            is_update = key in existing_keys
            existing_keys.add(key)
            store.upsert_contact(
                full_name=row["full_name"],
                headline=row["headline"],
                company=row["company"],
                email=row["email"],
                profile_url=row["profile_url"],
                relation="first",
                source=SOURCE_LINKEDIN_EXPORT,
                provenance=provenance,
            )
            if is_update:
                contacts_updated += 1
            else:
                connections_imported += 1
        store.record_import(
            filename=LINKEDIN_CONNECTIONS_FILENAME,
            kind="connections",
            source="linkedin_export",
            rows_total=len(rows),
            rows_imported=len(rows),
        )
        files.append(LINKEDIN_CONNECTIONS_FILENAME)

    if profile_csv is not None:
        facts = parse_linkedin_profile_csv(profile_csv)
        for fact in facts:
            store.add_profile_fact(
                kind=fact["kind"],
                value=fact["value"],
                source="linkedin_export",
                origin=LINKEDIN_PROFILE_FILENAME,
            )
            facts_added += 1
        store.record_import(
            filename=LINKEDIN_PROFILE_FILENAME,
            kind="profile",
            source="linkedin_export",
            rows_total=1,
            rows_imported=len(facts),
        )
        files.append(LINKEDIN_PROFILE_FILENAME)

    return ImportSummary(
        connections_imported=connections_imported,
        contacts_updated=contacts_updated,
        profile_facts=facts_added,
        source="linkedin_export",
        files=tuple(files),
    )


def _linkedin_provenance(where: str, fields: tuple[str, ...]) -> list[dict[str, str]]:
    return [
        {"field": name, "source": "linkedin_export", "where": where}
        for name in fields
    ]


# ---------------------------------------------------------------------- recommendations
@dataclass(frozen=True)
class Recommendation:
    contact_id: int
    full_name: str
    score: int
    families: tuple[str, ...]
    reasons: tuple[str, ...]
    provenance: tuple[dict[str, str], ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "contact_id": self.contact_id,
            "full_name": self.full_name,
            "score": self.score,
            "families": list(self.families),
            "reasons": list(self.reasons),
            "provenance": [dict(item) for item in self.provenance],
        }


def detect_desk_families(*texts: str) -> tuple[str, ...]:
    """Finance desk families (IBC, M&A, TMT, coverage) found in the given texts."""
    haystack = normalized_text(" ".join(text for text in texts if text))
    matched: list[str] = []
    for family, keywords in DESK_FAMILIES.items():
        for keyword in keywords:
            if normalized_text(keyword) and normalized_text(keyword) in haystack:
                matched.append(family)
                break
    return tuple(matched)


def is_recruiter(*texts: str) -> bool:
    haystack = normalized_text(" ".join(text for text in texts if text))
    return any(keyword in haystack for keyword in _RECRUITER_KEYWORDS)


def recommend_targets(
    contacts: list[Any],
    *,
    target_role: str = "",
    schools: list[str] | tuple[str, ...] = (),
    limit: int = 10,
) -> list[Recommendation]:
    """Rank the contacts worth contacting first, each reason citing its provenance.

    ``contacts`` accepts ``Contact`` objects or plain dicts with the same keys.
    Duplicated contacts (same normalized name + company) are deduplicated so
    the same person is never recommended twice.
    """
    normalized_schools = {normalized_text(school) for school in schools if clean_text(school)}
    role_tokens = {token for token in normalized_text(target_role).split() if len(token) > 2}
    recommendations: list[Recommendation] = []
    seen: set[tuple[str, str]] = set()

    for contact in contacts:
        person = _as_contact_mapping(contact)
        full_name = person["full_name"]
        key = (normalized_text(full_name), normalized_text(person["company"]))
        if not full_name or key in seen:
            continue
        seen.add(key)

        provenance = [dict(item) for item in person.get("provenance", []) if isinstance(item, dict)]
        default_where = provenance[0].get("where", "saisie manuelle") if provenance else "saisie manuelle"
        default_source = provenance[0].get("source", person.get("source", "manual")) if provenance else person.get("source", "manual")

        families = detect_desk_families(person.get("headline", ""), person.get("company", ""))
        reasons: list[str] = []
        cited_provenance: list[dict[str, str]] = []
        score = 0

        shared_schools = sorted(
            {school for school in {normalized_text(person.get("school", ""))} | {normalized_text(s) for s in _split_multi(person.get("school", ""))}
             if school and school in normalized_schools}
        )
        if shared_schools:
            score += _WEIGHT_ALUMNI
            display_school = next(
                (school for school in person["school"].split(";") if normalized_text(school) in shared_schools),
                person.get("school", ""),
            ).strip()
            reasons.append(
                f"Alumni {display_school} — fait déclaré par {default_source} ({default_where})"
            )
            cited_provenance.append({"field": "école", "source": default_source, "where": default_where})

        if families:
            score += _WEIGHT_DESK * len(families)
            reasons.append(
                f"Poste « {person.get('headline', '')} » / {person.get('company', '')} correspond aux desks {', '.join(families)}"
                f" — fait déclaré par {default_source} ({default_where})"
            )
            cited_provenance.append({"field": "poste", "source": default_source, "where": default_where})

        if is_recruiter(person.get("headline", "")):
            score += _WEIGHT_RECRUITER
            reasons.append(
                f"Profil recruteur (« {person.get('headline', '')} ») — fait déclaré par {default_source} ({default_where})"
            )
            cited_provenance.append({"field": "poste", "source": default_source, "where": default_where})

        contact_tokens = set(normalized_text(person.get("headline", "")).split())
        overlap = sorted(role_tokens & contact_tokens)
        if overlap:
            score += _WEIGHT_ROLE_TOKEN * min(len(overlap), _MAX_ROLE_TOKENS)
            reasons.append(
                f"Chevauchement avec le poste cible « {target_role} » ({', '.join(overlap)})"
                f" — fait déclaré par {default_source} ({default_where})"
            )
            cited_provenance.append({"field": "poste", "source": default_source, "where": default_where})

        if score <= 0 or not reasons:
            continue
        recommendations.append(
            Recommendation(
                contact_id=int(person.get("id", 0)),
                full_name=full_name,
                score=score,
                families=families,
                reasons=tuple(reasons),
                provenance=tuple(cited_provenance),
            )
        )

    recommendations.sort(key=lambda item: (-item.score, item.full_name))
    return recommendations[: max(1, int(limit))]


def _as_contact_mapping(contact: Any) -> dict[str, Any]:
    if hasattr(contact, "to_dict"):
        return dict(contact.to_dict())
    if isinstance(contact, dict):
        return dict(contact)
    if hasattr(contact, "__dict__"):
        return dict(vars(contact))
    raise TypeError("contact doit être un Contact, un dict ou un objet simple")


# ------------------------------------------------------------------------------- drafts
DRAFT_KINDS = ("alumni_first_contact", "school_recruiter", "coverage_desk")

_DRAFT_TEMPLATES: dict[str, dict[str, str]] = {
    "alumni_first_contact": {
        "label": "Premier contact alumni",
        "subject": "Contact alumni {school} — {sender_name}",
        "body": (
            "Bonjour {contact_name},\n\n"
            "Je m'appelle {sender_name}, {sender_role} et ancien{sender_gender} élève de {school}.\n"
            "{approved_sentence}\n\n"
            "Votre parcours chez {company} en tant que {contact_headline} m'intéresse beaucoup, "
            "et j'aimerais échanger 15 minutes avec vous sur votre expérience et mes candidatures ciblées.\n\n"
            "Merci d'avance,\n{sender_name}"
        ),
    },
    "school_recruiter": {
        "label": "Recruteur école / campus",
        "subject": "Candidature {target_role} — {sender_name} ({school})",
        "body": (
            "Bonjour {contact_name},\n\n"
            "Je m'appelle {sender_name}, élève de {school}, {sender_role}.\n"
            "{approved_sentence}\n\n"
            "Je poste actuellement pour un poste de {target_role}. Serait-il possible d'échanger sur les "
            "candidatures de {company} et sur les profils recherchés ?\n\n"
            "Bien cordialement,\n{sender_name}"
        ),
    },
    "coverage_desk": {
        "label": "Desk coverage / banque d'affaires",
        "subject": "Échange {families} — {sender_name}",
        "body": (
            "Bonjour {contact_name},\n\n"
            "Je m'appelle {sender_name}, {sender_role}.\n"
            "{approved_sentence}\n\n"
            "Votre expérience sur les desks {families} chez {company} correspond exactement aux équipes "
            "que je cible ({target_role}). Auriez-vous 15 minutes pour en discuter ?\n\n"
            "Bien cordialement,\n{sender_name}"
        ),
    },
}


@dataclass(frozen=True)
class MessageDraft:
    kind: str
    label: str
    contact_id: int
    contact_name: str
    subject: str
    body: str
    facts_used: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return dict(self.__dict__)


def draft_message(
    contact: Any,
    kind: str,
    *,
    sender_name: str,
    sender_role: str = "",
    sender_school: str = "",
    sender_gender: str = "",
    target_role: str = "",
    approved_facts: list[str] | tuple[str, ...] = (),
) -> MessageDraft:
    """Build a segmented networking draft from approved profile facts only.

    The draft is contingent: each template raises :class:`MissingFactError`
    when a fact it needs was never approved or provided, and only the facts
    explicitly passed in may appear in the message.
    """
    if kind not in _DRAFT_TEMPLATES:
        raise ValueError(f"type de brouillon inconnu: {kind}")
    person = _as_contact_mapping(contact)
    template = _DRAFT_TEMPLATES[kind]
    sender_name = clean_text(sender_name, limit=120)
    if not sender_name:
        raise MissingFactError("le brouillon requiert le nom de l'expéditeur")

    contact_name = clean_text(person.get("full_name", ""), limit=200) or "Madame, Monsieur"
    facts_used: list[str] = []
    approved_sentence = ""
    if approved_facts:
        kept = [clean_text(fact, limit=300) for fact in approved_facts if clean_text(fact)]
        if kept:
            approved_sentence = f"Pour contexte : {' ; '.join(kept[:2])}."
            facts_used = kept[:2]

    school = ""
    shared_schools = _shared_schools(person, sender_school)
    families = detect_desk_families(person.get("headline", ""), person.get("company", ""))

    if kind == "alumni_first_contact":
        if not shared_schools:
            raise MissingFactError("brouillon alumni impossible sans école commune approuvée")
        school = shared_schools[0]
    elif kind == "school_recruiter":
        if not clean_text(sender_school):
            raise MissingFactError("brouillon recruteur école impossible sans école de l'expéditeur")
        if not clean_text(target_role):
            raise MissingFactError("brouillon recruteur école impossible sans poste cible")
        school = clean_text(sender_school, limit=200)
    elif kind == "coverage_desk":
        if not families:
            raise MissingFactError("brouillon desk coverage impossible sans desk détecté sur le contact")
        if not clean_text(target_role):
            raise MissingFactError("brouillon desk coverage impossible sans poste cible")

    mapping = {
        "contact_name": contact_name,
        "contact_headline": clean_text(person.get("headline", ""), limit=200) or clean_text(person.get("company", ""), limit=200) or "votre parcours",
        "company": clean_text(person.get("company", ""), limit=200) or "votre entreprise",
        "sender_name": sender_name,
        "sender_role": clean_text(sender_role, limit=200),
        "sender_gender": "e" if clean_text(sender_gender, limit=20).lower() in ("f", "femme", "feminine") else "",
        "school": school or clean_text(sender_school, limit=200),
        "target_role": clean_text(target_role, limit=200) or "poste visé",
        "families": ", ".join(families).upper() if families else "coverage",
        "approved_sentence": approved_sentence or "Je me permets de vous contacter de façon spontanée.",
    }
    subject = clean_text(template["subject"].format(**mapping), limit=200)
    body = template["body"].format(**mapping)
    return MessageDraft(
        kind=kind,
        label=template["label"],
        contact_id=int(person.get("id", 0)),
        contact_name=contact_name,
        subject=subject,
        body=body,
        facts_used=tuple(facts_used),
    )


def draft_messages_for_recommendation(
    recommendation: Recommendation,
    contacts_by_id: dict[int, Any],
    *,
    kinds: list[str] | tuple[str, ...] = (),
    **kwargs: Any,
) -> list[MessageDraft]:
    """Convenience helper: build every applicable draft kind for a recommended contact."""
    contact = contacts_by_id.get(recommendation.contact_id)
    if contact is None:
        return []
    drafts: list[MessageDraft] = []
    for kind in (kinds or DRAFT_KINDS):
        try:
            drafts.append(draft_message(contact, kind, **kwargs))
        except MissingFactError:
            continue  # contingent: a draft is only produced when its facts exist
    return drafts


def export_drafts(drafts: list[MessageDraft], path: str | Path) -> Path:
    """Write the drafts to a local file the user sends themself.  No sending here."""
    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    lines = ["# Brouillons networking", "", "Aucun envoi automatique : copiez-collez et envoyez vous-même.", ""]
    for draft in drafts:
        lines.append(f"## {draft.label} — {draft.contact_name}")
        lines.append("")
        lines.append(f"Objet : {draft.subject}")
        lines.append("")
        lines.append(draft.body)
        lines.append("")
        if draft.facts_used:
            lines.append("Faits approuvés utilisés : " + " ; ".join(draft.facts_used))
            lines.append("")
    output.write_text("\n".join(lines), encoding="utf-8")
    return output


def _shared_schools(contact: Any, sender_school: str) -> list[str]:
    sender = normalized_text(sender_school)
    if not sender:
        return []
    contact_schools = {normalized_text(part) for part in _split_multi(clean_text(contact.get("school", ""), limit=300))}
    contact_schools.discard("")
    matches = [school for school in contact_schools if school == sender]
    if matches:
        return [clean_text(sender_school, limit=200)]
    return []
