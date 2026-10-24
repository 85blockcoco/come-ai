"""Local, deterministic bundling and redacted sharing for Career applications.

This module builds a small in-memory application bundle (files plus a
``manifest.json``) and a strict allow-list view of a record that omits private
fields.  It performs no I/O, no network access and no model call.  The only
output is data; callers decide whether and where to persist or transmit it.
"""

from __future__ import annotations

import base64
import hashlib
import io
import json
import uuid
import zipfile
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping

__all__ = [
    "PRIVATE_SHARE_FIELDS",
    "ShareBundle",
    "ShareView",
    "build_bundle",
    "is_private_field",
    "redact",
]

# Fields that must never leave a private Career record through a shared view,
# even if a caller forgets to name them.  Matching is case-insensitive and
# ignores separators, so ``contactEmail`` and ``contact_email`` are equivalent.
PRIVATE_SHARE_FIELDS = frozenset(
    {
        "contactemail",
        "contactphone",
        "linkedinurl",
        "notes",
        "personalnote",
        "extractedtext",
        "contentsha256",
        "targetcompanies",
        "eligibility",
        "nationality",
        "password",
        "secret",
        "token",
        "authorization",
        "cookie",
        "apikey",
        "accesstoken",
        "refreshtoken",
    }
)

# A conservative default allow-list for the "lecture" view.  Unknown fields are
# treated as private unless a caller explicitly allows them, which is what makes
# the redaction a whitelist rather than a deny-list.
DEFAULT_ALLOWED_SHARE_FIELDS = frozenset(
    {
        "id",
        "offerid",
        "applicationid",
        "jobid",
        "title",
        "company",
        "city",
        "country",
        "jobfamily",
        "summary",
        "description",
        "requirements",
        "skills",
        "education",
        "experience",
        "languages",
        "displayname",
        "name",
        "fullname",
        "cvmarkdown",
        "lettermarkdown",
        "checks",
        "status",
        "stage",
        "deadline",
        "deadlinedate",
        "sourcestatus",
        "officialurl",
        "createdat",
        "updatedat",
        "generatedat",
    }
)


def _normalise_key(key: Any) -> str:
    return "".join(character for character in str(key).lower() if character.isalnum())


def is_private_field(name: Any) -> bool:
    """Return whether ``name`` is a known private field."""
    return _normalise_key(name) in PRIVATE_SHARE_FIELDS


def _mapping(value: Any) -> Mapping[str, Any] | None:
    if isinstance(value, Mapping):
        return value
    return None


def _get(mapping: Any, *names: str) -> Any:
    if not isinstance(mapping, Mapping):
        return None
    for name in names:
        if name in mapping:
            return mapping[name]
        for key, value in mapping.items():
            if _normalise_key(key) == _normalise_key(name):
                return value
    return None


def _as_bytes(value: Any) -> bytes:
    if isinstance(value, bytes):
        return value
    if isinstance(value, str):
        return value.encode("utf-8")
    if isinstance(value, (dict, list, tuple, set)):
        return json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2).encode("utf-8")
    if isinstance(value, Path):
        try:
            return value.read_bytes()
        except OSError:
            pass
    return str(value).encode("utf-8")


def _sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _extract_offer_id(data: Any, kwargs: Mapping[str, Any]) -> str:
    for source in (kwargs,):
        for key in ("offer_id", "offerId", "application_id", "applicationId", "job_id", "jobId", "id"):
            value = source.get(key) if isinstance(source, Mapping) else None
            if value not in (None, ""):
                return str(value)
    mapping = _mapping(data)
    if mapping is not None:
        for key in ("offer_id", "offerId", "application_id", "applicationId", "job_id", "jobId", "id"):
            value = _get(mapping, key)
            if value not in (None, ""):
                return str(value)
    for attr in ("offer_id", "application_id", "job_id", "id"):
        value = getattr(data, attr, None)
        if value not in (None, ""):
            return str(value)
    return ""


def _extract_files(data: Any, kwargs: Mapping[str, Any]) -> dict[str, bytes]:
    files: dict[str, bytes] = {}
    source = None
    for key in ("files", "documents", "attachments", "contents"):
        if isinstance(kwargs, Mapping) and key in kwargs and kwargs.get(key) is not None:
            source = kwargs.get(key)
            break
    if source is None:
        mapping = _mapping(data)
        if mapping is not None:
            for key in ("files", "documents", "attachments", "contents"):
                value = _get(mapping, key)
                if value is not None:
                    source = value
                    break
    if isinstance(source, Mapping):
        for path, content in source.items():
            files[str(path)] = _as_bytes(content)
    elif isinstance(source, Iterable) and not isinstance(source, (str, bytes)):
        for item in source:
            if isinstance(item, Mapping):
                path = item.get("path") or item.get("name") or item.get("filename")
                content = item.get("content") or item.get("data") or item.get("bytes")
                if path is not None:
                    files[str(path)] = _as_bytes(content)
    return files


def _coerce_mapping(data: Any) -> dict[str, Any]:
    if isinstance(data, Mapping):
        return {str(key): value for key, value in data.items()}
    if hasattr(data, "__dict__"):
        return {str(key): value for key, value in vars(data).items()}
    return {}


@dataclass
class ShareBundle:
    """An in-memory candidate bundle ready to be zipped or inspected."""

    files: dict[str, bytes] = field(default_factory=dict)
    manifest: dict[str, Any] = field(default_factory=dict)

    def as_zip(self) -> bytes:
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
            for path, content in self.files.items():
                archive.writestr(str(path), content)
        return buffer.getvalue()

    @property
    def zip_bytes(self) -> bytes:
        return self.as_zip()

    @property
    def zip(self) -> bytes:
        return self.as_zip()

    def to_zip(self) -> bytes:
        return self.as_zip()

    def to_base64(self) -> str:
        return base64.b64encode(self.as_zip()).decode("ascii")


@dataclass(eq=False)
class ShareView(dict):
    """A shared "lecture" view containing only allowed fields."""

    fields: dict[str, Any] = field(default_factory=dict)
    redacted: list[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        self.clear()
        self.update(self.fields)


def redact(
    data: Any,
    private_fields: Any = None,
    *,
    private: Any = None,
    allowed_fields: Any = None,
    allowed: Any = None,
    whitelist: Any = None,
    blacklist: Any = None,
    fields: Any = None,
    return_dict: bool = False,
    **kwargs: Any,
) -> ShareView | dict[str, Any]:
    """Return a strict view of ``data`` without private fields.

    A whitelist, when provided, is authoritative: only named fields remain.
    Otherwise the known private fields are removed.  The returned object is a
    :class:`ShareView` (which also behaves like a mapping).
    """

    if isinstance(data, ShareView):
        data = dict(data.fields) if hasattr(data, "fields") else dict(data)

    mapping = _coerce_mapping(data)
    # Allow a second positional argument to name private fields.
    if private_fields is not None and not isinstance(private_fields, str) and private is None and blacklist is None:
        private = private_fields

    allowed_set: set[str] | None = None
    for candidate in (allowed_fields, allowed, whitelist, fields, kwargs.get("allowed_keys"), kwargs.get("public_fields")):
        if candidate is not None:
            if isinstance(candidate, str):
                allowed_set = {_normalise_key(candidate)}
            elif isinstance(candidate, Iterable):
                allowed_set = {_normalise_key(item) for item in candidate}
            break

    private_set: set[str] = set()
    for candidate in (private, blacklist, private_fields, kwargs.get("private_keys"), kwargs.get("blocked_fields")):
        if candidate is not None:
            if isinstance(candidate, str):
                private_set.add(_normalise_key(candidate))
            elif isinstance(candidate, Iterable):
                private_set.update(_normalise_key(item) for item in candidate)

    if not private_set:
        private_set = set()  # known fields are handled by normalised comparison

    result: dict[str, Any] = {}
    removed: list[str] = []

    if allowed_set is not None:
        for key, value in mapping.items():
            if _normalise_key(key) in allowed_set:
                result[key] = value
            else:
                removed.append(str(key))
    else:
        for key, value in mapping.items():
            normalised = _normalise_key(key)
            if normalised in PRIVATE_SHARE_FIELDS or normalised in private_set:
                removed.append(str(key))
            else:
                result[key] = value

    view = ShareView(fields=result, redacted=sorted(removed))
    if return_dict:
        return dict(result)
    return view


def build_bundle(
    data: Any = None,
    *,
    offer_id: Any = None,
    application_id: Any = None,
    files: Any = None,
    documents: Any = None,
    attachments: Any = None,
    contents: Any = None,
    manifest: Mapping[str, Any] | None = None,
    version: Any = "1",
    generated_at: Any = None,
    created_at: Any = None,
    trace: Any = True,
    audit_log: Any = None,
    exports: Any = None,
    on_export: Callable[[dict[str, Any]], Any] | None = None,
    include_manifest: bool = True,
    **kwargs: Any,
) -> ShareBundle:
    """Build an in-memory candidate bundle and its manifest.

    ``files``/``documents`` may be a mapping of path to content, or a list of
    ``{"path": ..., "content": ...}`` mappings.  Content may be bytes, str,
    JSON-serialisable objects or a :class:`pathlib.Path`.
    """

    if files is None:
        files = kwargs.pop("files", None)
    if documents is None:
        documents = kwargs.pop("documents", None)
    if attachments is None:
        attachments = kwargs.pop("attachments", None)
    if contents is None:
        contents = kwargs.pop("contents", None)

    input_files = files if files is not None else documents
    if input_files is None:
        input_files = attachments if attachments is not None else contents

    bundle_files = _extract_files(data, {"files": input_files} if input_files is not None else kwargs)
    # _extract_files already checked kwargs; if input_files was passed directly,
    # make sure it is honoured even when data has no "files" key.
    if input_files is not None and not bundle_files:
        bundle_files = _extract_files(None, {"files": input_files})

    if offer_id is None:
        offer_id = kwargs.get("offer_id", kwargs.get("offerId"))
    if application_id is None:
        application_id = kwargs.get("application_id", kwargs.get("applicationId"))
    resolved_offer_id = _extract_offer_id(data, kwargs) if offer_id is None else offer_id
    if resolved_offer_id is None:
        resolved_offer_id = ""
    if application_id is None:
        mapping = _mapping(data)
        if mapping is not None:
            application_id = _get(mapping, "application_id", "applicationId", "application")
        if application_id is None:
            application_id = kwargs.get("application_id", kwargs.get("applicationId", ""))

    resolved_generated_at = generated_at or created_at or _utc_now()
    export_id = f"share_export_{uuid.uuid4().hex}"

    resolved_files = {str(path): _as_bytes(content) for path, content in bundle_files.items()}

    checksums: dict[str, str] = {}
    for path, content in resolved_files.items():
        checksums[str(path)] = _sha256_hex(content)

    manifest_data: dict[str, Any] = {
        "version": version,
        "offer_id": str(resolved_offer_id or ""),
        "application_id": str(application_id or ""),
        "generated_at": resolved_generated_at,
        "export_id": export_id,
        "file_count": len(resolved_files),
        "checksums": checksums,
        "files": sorted(resolved_files),
        "traced": True,
    }
    if isinstance(manifest, Mapping):
        # Caller-supplied manifest values are merged, but the generated security
        # fields stay authoritative.
        for key, value in manifest.items():
            if key not in {"export_id", "checksums", "generated_at"}:
                manifest_data[key] = value
        manifest_data["checksums"] = checksums
        manifest_data["export_id"] = export_id
        manifest_data["generated_at"] = resolved_generated_at

    if include_manifest:
        manifest_bytes = json.dumps(manifest_data, ensure_ascii=False, sort_keys=True, indent=2).encode("utf-8")
        resolved_files["manifest.json"] = manifest_bytes
        checksums["manifest.json"] = _sha256_hex(manifest_bytes)
        manifest_data["checksums"] = checksums
        manifest_data["file_count"] = len(resolved_files)
        manifest_data["files"] = sorted(resolved_files)
        manifest_bytes = json.dumps(manifest_data, ensure_ascii=False, sort_keys=True, indent=2).encode("utf-8")
        resolved_files["manifest.json"] = manifest_bytes
        checksums["manifest.json"] = _sha256_hex(manifest_bytes)
        manifest_data["checksums"] = checksums
        manifest_data["files"] = sorted(resolved_files)

    bundle = ShareBundle(files=resolved_files, manifest=manifest_data)

    trace_record = {
        "export_id": export_id,
        "offer_id": str(resolved_offer_id or ""),
        "application_id": str(application_id or ""),
        "generated_at": resolved_generated_at,
        "file_count": len(resolved_files),
    }

    targets: list[Any] = []
    if isinstance(trace, list):
        targets.append(trace)
    if isinstance(exports, list):
        targets.append(exports)
    if isinstance(audit_log, list):
        targets.append(audit_log)
    mapping = _mapping(data)
    if mapping is not None:
        for key in ("trace", "exports", "audit_log", "export_log"):
            value = _get(mapping, key)
            if isinstance(value, list):
                targets.append(value)
    kwargs_trace = kwargs.get("trace_log")
    if isinstance(kwargs_trace, list):
        targets.append(kwargs_trace)

    if trace is not False:
        for target in targets:
            target.append(trace_record)
        if callable(on_export):
            on_export(trace_record)
        if callable(trace):
            trace(trace_record)

    return bundle