"""Shortlist export to CSV/JSON (N100-C09)."""

from __future__ import annotations

import csv
import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Iterable

DEFAULT_FIELDS = ("id", "title", "company", "location", "deadline", "score")


@dataclass
class ShortlistExport:
    path: str
    format: str
    rows: int
    fields: list[str] = field(default_factory=list)


def _coerce_fields(offers: Iterable[dict[str, Any]], fields: Iterable[str] | None) -> list[str]:
    if fields:
        return [str(f) for f in fields]
    keys: list[str] = []
    for o in offers:
        for k in o:
            if k not in keys:
                keys.append(k)
    return keys or list(DEFAULT_FIELDS)


def export_shortlist_json(offers: Iterable[dict[str, Any]], target: str | Path, *, indent: int = 2) -> ShortlistExport:
    path = Path(target)
    path.parent.mkdir(parents=True, exist_ok=True)
    rows = [o for o in offers]
    path.write_text(json.dumps(rows, ensure_ascii=False, indent=indent), encoding="utf-8")
    return ShortlistExport(path=str(path), format="json", rows=len(rows))


def export_shortlist_csv(offers: Iterable[dict[str, Any]], target: str | Path, *, fields: Iterable[str] | None = None) -> ShortlistExport:
    path = Path(target)
    path.parent.mkdir(parents=True, exist_ok=True)
    rows = [o for o in offers]
    use = _coerce_fields(rows, fields)
    with path.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=use, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow({k: row.get(k, "") for k in use})
    return ShortlistExport(path=str(path), format="csv", rows=len(rows), fields=use)


def shortlist_to_dicts(offers: Iterable[Any]) -> list[dict[str, Any]]:
    """Normalize objects with ``to_dict`` or Mapping into plain dicts."""
    out: list[dict[str, Any]] = []
    for o in offers:
        if isinstance(o, dict):
            out.append(dict(o))
        elif hasattr(o, "to_dict"):
            out.append(o.to_dict())  # type: ignore[attr-defined]
        else:
            out.append(asdict(o))  # type: ignore[arg-type]
    return out
