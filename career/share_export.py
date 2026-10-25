"""Read-only sharing views and sanitised application bundles for Career.

A bundle is meant to be sent by the person themselves to a contact, a school
or a recruiter.  It is therefore built in memory from already-local Career
records, never from a URL, a model or a secret.  Two rules drive this module:

* **strict allow-list** — a field is shared only when its name appears in a
  curated list *and* does not look private.  The private-name guard is a second
  line of defence: a mistaken allow-list entry cannot leak an e-mail, a phone
  number, a personal note or an approval flag.
* **inert output** — the result is a deterministic ZIP of JSON/text files plus
  a ``manifest.json`` that lists checksums and redacted *field names* only.
  No value that was redacted is ever repeated in the manifest.

The module performs no I/O and raises ``ValueError`` for malformed input; the
service layer turns those cases into a user-facing message.
"""

from __future__ import annotations

import io
import json
import math
import re
import zipfile
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import date, datetime, timezone
from hashlib import sha256
from typing import Any


SHARE_BUNDLE_VERSION = "1.0"
"""Version of the manifest/bundle contract emitted by ``build_bundle``."""

MANIFEST_NAME = "manifest.json"
README_NAME = "lisez-moi.txt"

MAX_FILES = 24
MAX_FILE_BYTES = 2_000_000
MAX_TOTAL_BYTES = 8_000_000
MAX_TEXT_LENGTH = 40_000
MAX_LIST_ITEMS = 200

#: Fields a shared read view may contain, per entity.  Curated by hand: adding
#: a field here is the only way to publish it.
PROFILE_SHARE_FIELDS: tuple[str, ...] = (
    "display_name",
    "education",
    "experience",
    "skills",
    "languages",
)
JOB_SHARE_FIELDS: tuple[str, ...] = (
    "company",
    "title",
    "job_family",
    "city",
    "country",
    "employment_type",
    "role_level",
    "duration_months",
    "start_date",
    "end_date",
    "deadline_date",
    "posted_date",
    "requirements",
    "languages_required",
    "eligibility_requirement",
    "official_url",
    "source_status",
)
APPLICATION_SHARE_FIELDS: tuple[str, ...] = (
    "stage",
    "receipt_status",
    "created_at",
    "updated_at",
)

#: Substrings that make a field private regardless of the allow-list.  Keys are
#: normalised to ``snake_case`` first so ``contactEmail`` is caught too.
_PRIVATE_KEY_MARKERS: tuple[str, ...] = (
    "address",
    "api_key",
    "apikey",
    "approval",
    "auth",
    "bank",
    "birth",
    "checklist",
    "consent",
    "contact",
    "cookie",
    "disability",
    "email",
    "ethnicity",
    "event",
    "gender",
    "iban",
    "internal",
    "linkedin",
    "medical",
    "note",
    "password",
    "phone",
    "private",
    "readiness",
    "reference",
    "religion",
    "salary",
    "secret",
    "session",
    "social_security",
    "ssn",
    "telephone",
    "token",
)

_RESERVED_NAMES = frozenset({MANIFEST_NAME, README_NAME})
_SAFE_FILE_NAME = re.compile(r"^[a-z0-9][a-z0-9._-]{0,80}$")
_UNSAFE_CHARACTERS = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
_UNSHAREABLE = object()
REDACTION_PLACEHOLDER = "[coordonnées non partagées]"


@dataclass
class ShareView:
    """A whitelisted projection of one record."""

    fields: dict[str, Any]
    redacted: list[str]


@dataclass
class ShareBundle:
    """Files to send plus the signed-off manifest describing them."""

    files: dict[str, bytes]
    manifest: dict[str, Any]

    def zip_bytes(self) -> bytes:
        """Return a deterministic ZIP archive (manifest first)."""
        return _zip_payloads(self.files, self.manifest)


def is_private_field(name: str) -> bool:
    """Return whether a field name must never leave the local workspace."""
    normalised = re.sub(r"[^a-z0-9]+", "_", str(name).lower()).strip("_")
    return any(marker in normalised for marker in _PRIVATE_KEY_MARKERS)


def _clean_text(value: Any, *, limit: int = MAX_TEXT_LENGTH) -> str:
    text = str(value).replace("\r\n", "\n").replace("\r", "\n")
    text = _UNSAFE_CHARACTERS.sub("", text)
    return text[:limit]


def _share_value(value: Any) -> Any:
    """Return a JSON-safe scalar/list, or ``_UNSHAREABLE`` for nested data."""
    if value is None or isinstance(value, bool):
        return value
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return value if math.isfinite(value) else _UNSHAREABLE
    if isinstance(value, str):
        return _clean_text(value)
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        if len(value) > MAX_LIST_ITEMS:
            return _UNSHAREABLE
        items: list[Any] = []
        for item in value:
            if isinstance(item, (str, int, float, bool)) or item is None:
                cleaned = _share_value(item)
                if cleaned is _UNSHAREABLE:
                    return _UNSHAREABLE
                items.append(cleaned)
            else:
                return _UNSHAREABLE
        return items
    # Mappings, sets, file handles… are never shared implicitly: a nested dict
    # could hide a private key that the top-level allow-list never checked.
    return _UNSHAREABLE


def redact(
    record: Mapping[str, Any],
    allowed_fields: Iterable[str] = (),
    *,
    text_limit: int = MAX_TEXT_LENGTH,
) -> ShareView:
    """Project ``record`` on ``allowed_fields`` with a private-name guard."""
    allowed = {str(field) for field in allowed_fields}
    fields: dict[str, Any] = {}
    redacted: set[str] = set()
    for raw_key, raw_value in record.items():
        key = str(raw_key)
        if key not in allowed or is_private_field(key):
            redacted.add(key)
            continue
        safe = _share_value(raw_value)
        if safe is _UNSHAREABLE:
            redacted.add(key)
            continue
        if isinstance(safe, str):
            safe = safe[:text_limit]
        fields[key] = safe
    return ShareView(fields=fields, redacted=sorted(redacted))


def bundle_checksums(files: Mapping[str, bytes]) -> dict[str, str]:
    """Return ``path -> sha256`` for every payload, sorted by path."""
    return {path: sha256(files[path]).hexdigest() for path in sorted(files)}


def scrub_text(text: str, sensitive_values: Iterable[Any] = ()) -> str:
    """Remove known private values (e-mail, phone, notes…) from shared text.

    Draft CV/letter text is produced by a local template that may repeat the
    profile contact block.  Sharing the document must not silently republish
    values the structured view just redacted, so those exact values are masked
    case-insensitively before the file enters the archive.
    """
    cleaned = _clean_text(text, limit=MAX_FILE_BYTES + 1)
    needles = {
        _clean_text(value).strip()
        for value in sensitive_values
        if value is not None and len(_clean_text(value).strip()) >= 4
    }
    for needle in sorted(needles, key=len, reverse=True):
        cleaned = re.sub(re.escape(needle), REDACTION_PLACEHOLDER, cleaned, flags=re.IGNORECASE)
    return cleaned


def _json_payload(payload: Mapping[str, Any]) -> bytes:
    text = json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False)
    return (text + "\n").encode("utf-8")


def _validate_offer_id(offer_id: Any) -> str:
    cleaned = _clean_text(offer_id, limit=160).strip()
    if not cleaned:
        raise ValueError("L’identifiant de l’offre est obligatoire pour un partage.")
    return cleaned


def _validate_generated_at(generated_at: datetime | None) -> str:
    moment = generated_at or datetime.now(timezone.utc)
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    return moment.astimezone(timezone.utc).replace(microsecond=0).strftime("%Y-%m-%dT%H:%M:%SZ")


def _coerce_document(value: str | bytes | bytearray) -> bytes:
    if isinstance(value, bytes):
        return bytes(value)
    if isinstance(value, bytearray):
        return bytes(value)
    if isinstance(value, str):
        return value.replace("\r\n", "\n").encode("utf-8")
    raise ValueError("Un document de partage doit être du texte ou des octets.")


def _add_payload(files: dict[str, bytes], name: str, payload: bytes, *, internal: bool = False) -> None:
    if name in _RESERVED_NAMES and not internal:
        raise ValueError(f"Le nom de fichier « {name} » est réservé au manifeste de partage.")
    if not _SAFE_FILE_NAME.match(name):
        raise ValueError(f"Le nom de fichier « {name} » n’est pas autorisé dans un partage.")
    if name in files:
        raise ValueError(f"Le fichier « {name} » est présent deux fois dans le partage.")
    if len(payload) > MAX_FILE_BYTES:
        raise ValueError(f"Le fichier « {name} » dépasse la taille maximale d’un partage local.")
    if len(files) >= MAX_FILES:
        raise ValueError("Le partage contient trop de fichiers.")
    if sum(len(item) for item in files.values()) + len(payload) > MAX_TOTAL_BYTES:
        raise ValueError("Le partage dépasse la taille cumulée autorisée.")
    files[name] = payload


def _readme(offer_id: str, generated_at: str) -> bytes:
    text = (
        "Dossier de candidature — lecture seule\n"
        "======================================\n\n"
        f"Offre : {offer_id}\n"
        f"Généré le : {generated_at}\n\n"
        "Ce dossier a été préparé localement. Il ne contient que les champs\n"
        "explicitement autorisés au partage ; les champs privés (coordonnées,\n"
        "notes personnelles, approbations, historique) ont été retirés avant\n"
        "la création de l’archive. Ces mêmes valeurs sont masquées si un\n"
        "brouillon de CV ou de lettre les répétait.\n\n"
        "Aucun envoi, aucune relance et aucune candidature ne sont déclenchés\n"
        "par ce fichier. Vérifiez son contenu avant de le transmettre.\n"
        "Le fichier manifest.json décrit les contrôles d’intégrité (SHA-256)\n"
        "de chaque document présent.\n"
    )
    return text.encode("utf-8")


def build_bundle(
    *,
    offer_id: str,
    job: Mapping[str, Any],
    profile: Mapping[str, Any] | None = None,
    application: Mapping[str, Any] | None = None,
    documents: Mapping[str, str | bytes] | None = None,
    sensitive_values: Iterable[Any] = (),
    generated_at: datetime | None = None,
) -> ShareBundle:
    """Build an in-memory share bundle for one offer.

    ``generated_at`` is injectable so callers and tests get reproducible
    archives.  ``documents`` maps safe relative names (``cv.md``, ``lettre.md``)
    to UTF-8 text or bytes; every other file is produced by this module.
    ``sensitive_values`` are exact private values (contact details, notes) that
    must also be masked if a draft document repeats them.
    """
    offer = _validate_offer_id(offer_id)
    stamp = _validate_generated_at(generated_at)
    if not isinstance(job, Mapping) or not job:
        raise ValueError("Une offre locale est nécessaire pour préparer un partage.")

    files: dict[str, bytes] = {}
    _add_payload(files, README_NAME, _readme(offer, stamp), internal=True)

    job_view = redact(job, JOB_SHARE_FIELDS)
    _add_payload(files, "offre.json", _json_payload(job_view.fields))

    redacted: dict[str, list[str]] = {"job": job_view.redacted}
    if profile is not None:
        profile_view = redact(profile, PROFILE_SHARE_FIELDS)
        _add_payload(files, "profil.json", _json_payload(profile_view.fields))
        redacted["profile"] = profile_view.redacted
    if application is not None:
        application_view = redact(application, APPLICATION_SHARE_FIELDS)
        _add_payload(files, "candidature.json", _json_payload(application_view.fields))
        redacted["application"] = application_view.redacted

    for name, value in (documents or {}).items():
        if isinstance(value, str):
            cleaned_document = scrub_text(value, sensitive_values)
        else:
            raw = _coerce_document(value)
            try:
                cleaned_document = scrub_text(raw.decode("utf-8"), sensitive_values)
            except UnicodeDecodeError as error:
                raise ValueError(
                    "Seuls les documents texte UTF-8 peuvent entrer dans un partage contrôlé."
                ) from error
        _add_payload(files, str(name), cleaned_document.encode("utf-8"))

    manifest: dict[str, Any] = {
        "version": SHARE_BUNDLE_VERSION,
        "offer_id": offer,
        "generated_at": stamp,
        "read_only": True,
        "checksums": bundle_checksums(files),
        "files": sorted(files),
        "redacted": redacted,
        "documents_scrubbed": bool(documents),
    }
    return ShareBundle(files=files, manifest=manifest)


def verify_bundle(bundle: ShareBundle) -> bool:
    """Return whether files match the manifest and stay inert/safe."""
    checksums = bundle.manifest.get("checksums")
    if not isinstance(checksums, Mapping) or dict(checksums) != bundle_checksums(bundle.files):
        return False
    for path, payload in bundle.files.items():
        if not _SAFE_FILE_NAME.match(path) or path == MANIFEST_NAME:
            return False
        if payload.startswith(b"PK\x03\x04"):
            return False
    return True


def bundle_filename(offer_id: str, generated_at: datetime | None = None, *, nonce: str = "") -> str:
    """Return an opaque, filesystem-safe archive name (never user text).

    ``nonce`` keeps two exports in the same second distinct; it must come from
    the caller (a local UUID), never from user text.
    """
    stamp = _validate_generated_at(generated_at).replace("-", "").replace(":", "")
    digest = sha256(_validate_offer_id(offer_id).encode("utf-8")).hexdigest()[:16]
    suffix = re.sub(r"[^a-z0-9]", "", str(nonce).lower())[:12]
    return f"career_partage_{stamp}_{digest}{'_' + suffix if suffix else ''}.zip"


def _zip_payloads(files: Mapping[str, bytes], manifest: Mapping[str, Any]) -> bytes:
    stream = io.BytesIO()
    ordered = [MANIFEST_NAME, *sorted(path for path in files if path != MANIFEST_NAME)]
    with zipfile.ZipFile(stream, "w", compression=zipfile.ZIP_DEFLATED, allowZip64=False) as archive:
        for path in ordered:
            payload = _json_payload(manifest) if path == MANIFEST_NAME else files[path]
            info = zipfile.ZipInfo(path, date_time=(1980, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            info.create_system = 3
            info.external_attr = 0o600 << 16
            archive.writestr(info, payload)
    return stream.getvalue()
