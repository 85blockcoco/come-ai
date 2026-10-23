"""Scoring helpers for reformulated experience bullets (SPEC-020).

Combines:
- an ATS score derived from keyword coverage + structural sanity;
- keyword coverage against the offer's required keywords;
- a jury score (heuristic stand-in for the multi-AI arena, SPEC-017).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Iterable


@dataclass(frozen=True, slots=True)
class ScoreResult:
    ats_score: float
    keyword_hits: list[str] = field(default_factory=list)
    coverage: float = 0.0
    jury_score: float = 0.0
    notes: list[str] = field(default_factory=list)


def _tokenize(text: str) -> set[str]:
    return set(re.findall(r"[a-zA-ZÀ-ÿ0-9+#.]{2,}", text.lower()))


def keyword_hits(text: str, keywords: Iterable[str]) -> list[str]:
    low = text.lower()
    hits: list[str] = []
    for kw in keywords:
        kw = kw.strip()
        if not kw:
            continue
        if kw.lower() in low:
            hits.append(kw)
    return hits


def keyword_coverage(text: str, keywords: Iterable[str]) -> float:
    kws = [k for k in keywords if k.strip()]
    if not kws:
        return 1.0
    hits = keyword_hits(text, kws)
    return len(hits) / len(kws)


def ats_score(text: str, keywords: Iterable[str] = (), evidence: str = "") -> float:
    """Deterministic ATS score in [0, 1] for a single bullet."""
    cov = keyword_coverage(text, keywords)
    # length sanity: prefer 80-220 chars
    n = len(text)
    if n < 40:
        length_factor = 0.5
    elif n <= 220:
        length_factor = 1.0
    else:
        length_factor = max(0.4, 1.0 - (n - 220) / 400.0)
    # action verb bonus
    from career.exp_constraints import _first_word, ACTION_VERBS

    verb = _first_word(text)
    verb_bonus = 0.1 if verb in ACTION_VERBS else 0.0
    score = 0.6 * cov + 0.3 * length_factor + verb_bonus
    # cap
    return round(min(1.0, max(0.0, score)), 4)


def jury_score(text: str, keywords: Iterable[str] = (), evidence: str = "") -> float:
    """Heuristic jury score in [0, 1] (stand-in for multi-AI arena)."""
    cov = keyword_coverage(text, keywords)
    # reward quantified results
    from career.exp_constraints import _numeric_tokens

    has_number = bool(_numeric_tokens(text) & _numeric_tokens(evidence)) if evidence else bool(_numeric_tokens(text))
    quant_bonus = 0.15 if has_number else 0.0
    # conciseness
    conc = 1.0 if len(text) <= 200 else max(0.5, 1.0 - (len(text) - 200) / 300.0)
    score = 0.5 * cov + 0.25 * conc + quant_bonus + 0.1
    return round(min(1.0, max(0.0, score)), 4)


def score_bullet(text: str, keywords: Iterable[str] = (), evidence: str = "") -> ScoreResult:
    hits = keyword_hits(text, keywords)
    cov = keyword_coverage(text, keywords)
    a = ats_score(text, keywords, evidence)
    j = jury_score(text, keywords, evidence)
    notes: list[str] = []
    if cov < 0.5:
        notes.append("faible couverture mots-clés")
    if len(text) > 220:
        notes.append("bullet long")
    return ScoreResult(
        ats_score=a,
        keyword_hits=hits,
        coverage=round(cov, 4),
        jury_score=j,
        notes=notes,
    )
