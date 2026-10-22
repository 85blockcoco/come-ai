"""Deterministic jury / scoring for AI Arena responses."""

from __future__ import annotations

from collections import Counter
from typing import Any
from .models import IARequest, IAResponse


def _bullets_from(content: Any) -> list[str]:
    if not isinstance(content, dict):
        return []
    for key in ("bullets", "merged_bullets", "ideas", "suggestions"):
        val = content.get(key)
        if isinstance(val, list):
            return [str(x).strip() for x in val if str(x).strip()]
    # fallback: any list of strings
    for val in content.values():
        if isinstance(val, list) and val and all(isinstance(x, str) for x in val):
            return [str(x).strip() for x in val if str(x).strip()]
    return []


def _has_ids(content: Any) -> bool:
    if not isinstance(content, dict):
        return False
    for key in ("evidence_ids", "profile_ids", "source_ids", "ids", "citations"):
        val = content.get(key)
        if isinstance(val, list) and val:
            return True
        if isinstance(val, str) and val.strip():
            return True
    return False


def score_one(request: IARequest, response: IAResponse) -> float:
    content = response.content if isinstance(response.content, dict) else {}
    bullets = _bullets_from(content)
    score = 0.3
    score += min(len(bullets), 8) * 0.07
    if _has_ids(content):
        score += 0.15
    # format validity
    if isinstance(response.content, dict) and response.content:
        score += 0.1
    # latency penalty (small, deterministic)
    latency = max(0.0, float(response.latency_ms or 0.0))
    score -= min(latency / 100000.0, 0.1)
    # empty penalty
    if not content:
        score = 0.0
    # clamp
    return max(0.0, min(1.0, score))


def score_responses(request: IARequest, responses: list[IAResponse]) -> dict[str, float]:
    scores: dict[str, float] = {}
    for r in responses:
        key = f"{r.provider}"
        # make unique if duplicate providers
        if key in scores:
            key = f"{r.provider}:{r.model}"
        scores[key] = round(score_one(request, r), 6)
    return scores


def _response_key(r: IAResponse, scores: dict[str, float]) -> str:
    key = r.provider
    if key not in scores:
        key = f"{r.provider}:{r.model}"
    return key


def merge_bullets(responses: list[IAResponse], *, max_items: int = 10) -> list[str]:
    # Count occurrences across providers, preserve first-seen order for ties.
    counts: Counter[str] = Counter()
    first_index: dict[str, int] = {}
    idx = 0
    for r in responses:
        for b in _bullets_from(r.content if isinstance(r.content, dict) else {}):
            if b not in first_index:
                first_index[b] = idx
                idx += 1
            counts[b] += 1
    # sort by count desc, then first appearance asc
    ordered = sorted(counts.keys(), key=lambda b: (-counts[b], first_index.get(b, 10**9)))
    out = []
    seen = set()
    for b in ordered:
        if b in seen:
            continue
        seen.add(b)
        out.append(b)
        if len(out) >= max_items:
            break
    return out


def compute_disagreement(responses: list[IAResponse]) -> float:
    if len(responses) < 2:
        return 0.0
    sets = []
    for r in responses:
        content = r.content if isinstance(r.content, dict) else {}
        sets.append(set(_bullets_from(content)))
    # pairwise jaccard
    sims = []
    for i in range(len(sets)):
        for j in range(i + 1, len(sets)):
            a, b = sets[i], sets[j]
            if not a and not b:
                sims.append(1.0)
                continue
            union = a | b
            inter = a & b
            sims.append(len(inter) / len(union) if union else 1.0)
    if not sims:
        return 0.0
    avg_sim = sum(sims) / len(sims)
    disagreement = 1.0 - avg_sim
    return max(0.0, min(1.0, disagreement))


def pick_winner(scores: dict[str, float], responses: list[IAResponse]) -> str:
    if not scores:
        return ""
    # tie-break: higher score, then lower latency, then provider name
    def key_for(provider_key: str) -> tuple:
        # find response
        resp = None
        for r in responses:
            k = r.provider
            if k == provider_key or f"{r.provider}:{r.model}" == provider_key:
                resp = r
                break
        latency = resp.latency_ms if resp else 0.0
        return (-scores.get(provider_key, 0.0), latency, provider_key)
    return min(scores.keys(), key=key_for)
