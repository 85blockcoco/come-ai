"""Reporting helpers for ATS keyword profiles (SPEC-019)."""

from __future__ import annotations

import json
from typing import Any

from .keyword_extract import Keyword, KeywordProfile


def _as_profile(value: Any) -> KeywordProfile:
    if isinstance(value, KeywordProfile):
        return value
    if isinstance(value, list):
        return KeywordProfile(keywords=[v if isinstance(v, Keyword) else Keyword(**{k: val for k, val in v.items() if k in Keyword.__dataclass_fields__}) for v in value])
    if isinstance(value, dict):
        return KeywordProfile(
            offer_id=str(value.get("offer_id", "")),
            keywords=[v if isinstance(v, Keyword) else Keyword(**{k: val for k, val in v.items() if k in Keyword.__dataclass_fields__}) for v in value.get("keywords", [])],
            score_coverage=value.get("score_coverage", {}),
            gaps=[v if isinstance(v, Keyword) else Keyword(**{k: val for k, val in v.items() if k in Keyword.__dataclass_fields__}) for v in value.get("gaps", [])],
            generated_at=str(value.get("generated_at", "")),
        )
    return KeywordProfile()


def _keyword_to_dict(kw: Keyword) -> dict[str, Any]:
    return {
        "term": kw.term,
        "normalized": kw.normalized,
        "category": kw.category,
        "weight": kw.weight,
        "kind": kw.kind,
        "evidence_refs": list(kw.evidence_refs),
        "synonyms": list(kw.synonyms),
    }


def build_report(profile: Any, *, title: str = "ATS Keywords Report") -> dict[str, Any]:
    p = _as_profile(profile)
    by_kind: dict[str, int] = {}
    by_category: dict[str, int] = {}
    for kw in p.keywords:
        by_kind[kw.kind] = by_kind.get(kw.kind, 0) + 1
        by_category[kw.category] = by_category.get(kw.category, 0) + 1
    return {
        "title": title,
        "offer_id": p.offer_id,
        "generated_at": p.generated_at,
        "summary": {
            "total_keywords": len(p.keywords),
            "must_have": by_kind.get("must", 0),
            "nice_to_have": by_kind.get("nice", 0),
            "implicit": by_kind.get("implicit", 0),
            "gaps": len(p.gaps),
        },
        "by_kind": by_kind,
        "by_category": by_category,
        "keywords": [_keyword_to_dict(kw) for kw in p.keywords],
        "gaps": [_keyword_to_dict(kw) for kw in p.gaps],
        "score_coverage": p.score_coverage,
    }


def render_json(profile: Any, *, indent: int = 2) -> str:
    return json.dumps(build_report(profile), ensure_ascii=False, indent=indent)


def to_json(profile: Any, **kwargs: Any) -> str:
    return render_json(profile, **kwargs)


def render_html(profile: Any, *, title: str = "ATS Keywords Report") -> str:
    report = build_report(profile, title=title)
    rows = []
    for kw in report["keywords"]:
        rows.append(
            f"<tr><td>{kw['term']}</td><td>{kw['category']}</td>"
            f"<td>{kw['weight']:.2f}</td><td>{kw['kind']}</td></tr>"
        )
    html = [
        "<!DOCTYPE html>",
        "<html><head><meta charset='utf-8'>",
        f"<title>{title}</title>",
        "<style>table{border-collapse:collapse;width:100%}td,th{border:1px solid #ccc;padding:6px}</style>",
        "</head><body>",
        f"<h1>{title}</h1>",
        f"<p>Offer: {report['offer_id']} — {report['summary']['total_keywords']} mots-clés</p>",
        "<table><thead><tr><th>Terme</th><th>Catégorie</th><th>Poids</th><th>Niveau</th></tr></thead>",
        "<tbody>" + "".join(rows) + "</tbody></table>",
        "</body></html>",
    ]
    return "\n".join(html)


def render_report(profile: Any, **kwargs: Any) -> dict[str, Any]:
    return build_report(profile, **kwargs)


def generate_report(*args: Any, **kwargs: Any) -> dict[str, Any]:
    return build_report(*args, **kwargs)


def keyword_report(*args: Any, **kwargs: Any) -> dict[str, Any]:
    return build_report(*args, **kwargs)


# aliases
def report(*args: Any, **kwargs: Any) -> dict[str, Any]:
    return build_report(*args, **kwargs)


def html_report(*args: Any, **kwargs: Any) -> str:
    return render_html(*args, **kwargs)


def json_report(*args: Any, **kwargs: Any) -> str:
    return render_json(*args, **kwargs)


__all__ = [
    "build_report",
    "render_json",
    "to_json",
    "render_html",
    "render_report",
    "generate_report",
    "keyword_report",
    "report",
    "html_report",
    "json_report",
]
