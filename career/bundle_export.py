"""Grouped bundle export (zip) for an application dossier (N100-G05).

Creates a zip archive containing CV, letter, and supporting files.  Read-only
on inputs, writes only to the specified output path.  No network.
"""

from __future__ import annotations

import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable


@dataclass
class BundleResult:
    output_path: str
    files_included: list[str]
    size_bytes: int
    ok: bool
    error: str | None = None


def create_bundle(output_path: str | Path, files: Iterable[str | Path], base_dir: str | Path | None = None) -> BundleResult:
    """Create a zip bundle.  ``files`` are paths (absolute or relative to base_dir)."""
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    base = Path(base_dir) if base_dir else None
    included: list[str] = []
    try:
        with zipfile.ZipFile(output_path, "w", zipfile.ZIP_DEFLATED) as zf:
            for f in files:
                p = Path(f)
                if not p.is_absolute() and base is not None:
                    p = base / p
                if not p.exists() or not p.is_file():
                    continue
                arcname = p.name
                zf.write(p, arcname=arcname)
                included.append(str(p))
        size = output_path.stat().st_size if output_path.exists() else 0
        return BundleResult(output_path=str(output_path), files_included=included, size_bytes=size, ok=True)
    except Exception as exc:
        return BundleResult(output_path=str(output_path), files_included=included, size_bytes=0, ok=False, error=str(exc))


def list_bundle(output_path: str | Path) -> list[str]:
    """List file names in a zip bundle."""
    p = Path(output_path)
    if not p.exists():
        return []
    try:
        with zipfile.ZipFile(p, "r") as zf:
            return zf.namelist()
    except (zipfile.BadZipFile, OSError):
        return []