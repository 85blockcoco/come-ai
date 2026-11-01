"""Bundle export report (N100-G10)."""

from __future__ import annotations

import datetime
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Iterable


@dataclass
class ExportReport:
    bundle_path: str
    file_count: int
    total_bytes: int
    formats: dict[str, int] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)
    created_at: str = ""


def build_export_report(
    *,
    bundle_path: str,
    files: Iterable[tuple[str, int]] = (),
    warnings: Iterable[str] = (),
    at: str = "",
) -> ExportReport:
    files = list(files or [])
    formats: dict[str, int] = {}
    total = 0
    for name, size in files:
        ext = Path(name).suffix.lstrip(".").lower() or "none"
        formats[ext] = formats.get(ext, 0) + 1
        total += int(size or 0)
    warns = list(warnings or [])
    if not files:
        warns.append("bundle vide — rien à exporter")
    return ExportReport(
        bundle_path=bundle_path,
        file_count=len(files),
        total_bytes=total,
        formats=formats,
        warnings=warns,
        created_at=at or datetime.datetime.now(datetime.timezone.utc).isoformat(),
    )


def to_dict(r: ExportReport) -> dict[str, Any]:
    return asdict(r)
