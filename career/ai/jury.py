"""Jury / scoring for the AI Arena."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any


@dataclass
class Jury:
    style: str = "deterministic"

    def score(self, request: Any, response: Any) -> float:
        return score_response(request, response, style=self.style)

    def score_responses(self, request: Any, responses: list[Any]) -> dict[str, float]:
        return score_responses(request, responses, style=self.style)

    def verdict(self, request: Any, responses: list[Any]) -> dict[str, Any]:
        return jury_verdict(request, responses, style=self.style)


def _as_response(response: Any) -> Any:
    return response


def _content(response: Any) -> dict[str, Any]:
    content = getattr(response, "content", response)
    if isinstance(content, dict):
        return content
    if isinstance(content, str):
        return {"text": content}
    if isinstance(content, list):
        return {"items": content}
    return {}


def _bullets(content: dict[str, Any]) -> list[str]:
    for key in ("merged_bullets", "bullets", "ideas", "keywords", "items", "suggestions"):
        value = content.get(key)
        if isinstance(value, list):
            return [str(x) for x in value if str(x).strip()]
        if isinstance(value, str) and value.strip():
            return [value.strip()]
    # fallback: split text into sentences
    text = content.get("text")
    if isinstance(text, str) and text.strip():
        return [s.strip() for s in re.split(r"[.;]\s+", text) if s.strip()][:8]
    return []


def _evidence_ids(content: dict[str, Any]) -> list[str]:
    for key in ("evidence_ids", "evidence", "sources", "profile_ids", "citations"):
        value = content.get(key)
        if isinstance(value, list):
            return [str(x) for x in value]
        if isinstance(value, str) and value.strip():
            return [value.strip()]
    return []


def score_response(request: Any, response: Any, *, style: str = "deterministic") -> float:
    """Deterministic score in [0, 1]."""
    content = _content(response)
    score = 0.0
    if content:
        score += 0.15
    bullets = _bullets(content)
    score += min(0.35, 0.05 * len(bullets))
    ids = _evidence_ids(content)
    if ids:
        score += 0.2
    # Task-specific bonuses.
    task_type = getattr(request, "task_type", None)
    if task_type == "keywords":
        kw = content.get("keywords") or content.get("bullets") or []
        if isinstance(kw, list) and len(kw) >= 3:
            score += 0.1
    elif task_type in {"reformulate", "letter"}:
        text = content.get("text") or content.get("letter") or ""
        if isinstance(text, str) and len(text) >= 40:
            score += 0.1
    elif task_type == "score":
        if isinstance(content.get("score"), (int, float)):
            score += 0.1
    # Latency bonus (faster is slightly better, but bounded).
    latency = getattr(response, "latency_ms", 0.0)
    try:
        if float(latency) <= 1000:
            score += 0.05
    except (TypeError, ValueError):
        pass
    # Cached penalty small (prefer fresh? keep neutral)
    if getattr(response, "cached", False):
        score -= 0.02
    # Clamp.
    return max(0.0, min(1.0, score))


def score_responses(request: Any, responses: list[Any], *, style: str = "deterministic") -> dict[str, float]:
    scores: dict[str, float] = {}
    for resp in responses or []:
        provider = getattr(resp, "provider", None) or (resp.get("provider") if isinstance(resp, dict) else "unknown")
        scores[str(provider)] = score_response(request, resp, style=style)
    return scores


def jury_verdict(request: Any, responses: list[Any], *, style: str = "deterministic") -> dict[str, Any]:
    scores = score_responses(request, responses, style=style)
    if not scores:
        return {"winner": "", "scores": scores, "disagreement": 0.0}
    winner = max(scores, key=lambda k: scores[k])
    vals = list(scores.values())
    disagreement = (max(vals) - min(vals)) if len(vals) > 1 else 0.0
    return {"winner": winner, "scores": scores, "disagreement": disagreement}


def select_winner(scores: dict[str, float]) -> str:
    if not scores:
        return ""
    return max(scores, key=lambda k: scores[k])


def merge_bullets(responses: list[Any], *, limit: int = 10) -> list[str]:
    """Best-of fusion of bullets across responses, ordered by jury score (input order tie-break)."""
    seen: set[str] = set()
    result: list[str] = []
    # Flatten in input order; callers may pre-sort by score.
    for resp in responses or []:
        content = _content(resp)
        for bullet in _bullets(content):
            key = bullet.strip().lower()
            if key and key not in seen:
                seen.add(key)
                result.append(bullet.strip())
                if len(result) >= limit:
                    return result
    return result


def disagreement_of(scores: dict[str, float]) -> float:
    vals = list(scores.values())
    if len(vals) < 2:
        return 0.0
    return max(vals) - min(vals)


def blind_judge(request: Any, responses: list[Any], *, style: str = "deterministic") -> dict[str, Any]:
    return jury_verdict(request, responses, style=style)


# Aliases.
jury_score = score_response
score = score_response
evaluate = jury_verdict
consensus = merge_bullets
best_of = merge_bullets
