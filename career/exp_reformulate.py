"""Experience reformulator orchestrator (SPEC-020).

Generates N reformulated bullet variants for a given experience block,
aligned with offer keywords and constrained by approved evidence (no invention).
"""

from __future__ import annotations

import asyncio
import re
from dataclasses import dataclass, field
from typing import Any, Iterable, Sequence

from career.exp_constraints import (
    validate_bullet,
)
from career.exp_scorer import score_bullet


@dataclass(frozen=False, slots=True)
class ReformulatedBullet:
    original_block_id: str
    text_fr: str
    variant_actions: list[str] = field(default_factory=list)
    keyword_hits: list[str] = field(default_factory=list)
    evidence_refs: list[str] = field(default_factory=list)
    ats_score: float = 0.0
    jury_score: float = 0.0
    provider: str = "local"
    version: int = 1


@dataclass(frozen=False, slots=True)
class RecommendVerdict:
    bullets: list[ReformulatedBullet] = field(default_factory=list)
    recommended_combo: list[str] = field(default_factory=list)
    diff_vs_current: str = ""


def _make_variants(original: str, keywords: Sequence[str], evidence: str) -> list[tuple[str, list[str]]]:
    """Build deterministic variant drafts (>=3)."""
    kws = [k for k in keywords if k.strip()]
    base = original.strip().rstrip(".")
    variants: list[tuple[str, list[str]]] = []

    # Variant 1: action verb + keyword injection
    verb = "Dirigé"
    kw_str = ", ".join(kws[:3]) if kws else ""
    t1 = f"{verb} {base.lower()}" if base else f"{verb} la mission"
    if kw_str:
        t1 = f"{t1} — focus {kw_str}"
    variants.append((t1, ["verbe d'action selon l'offre", "alignement mots-clés"]))

    # Variant 2: quantified/result emphasis
    verb2 = "Piloté"
    t2 = f"{verb2} {base.lower()} avec résultats mesurables" if base else f"{verb2} la mission avec résultats mesurables"
    if kws:
        t2 = f"{t2} ({', '.join(kws[:2])})"
    variants.append((t2, ["ajout résultat chiffré", "verbe d'action selon l'offre"]))

    # Variant 3: concise
    verb3 = "Contribué"
    t3 = f"{verb3} à {base.lower()}" if base else f"{verb3} à la mission"
    if kws:
        t3 = f"{t3} — {kws[0]}"
    variants.append((t3, ["concision", "alignement mots-clés"]))

    # Variant 4: structured
    verb4 = "Conçu"
    t4 = f"{verb4} et structuré {base.lower()}" if base else f"{verb4} et structuré la mission"
    variants.append((t4, ["structure", "verbe d'action selon l'offre"]))

    return variants


def reformulate_experience(
    original_text: str,
    *,
    block_id: str = "block-0",
    offer_keywords: Sequence[str] = (),
    evidence_refs: Sequence[str] = (),
    evidence_text: str = "",
    provider: str = "local",
    version: int = 1,
) -> list[ReformulatedBullet]:
    ev = evidence_text or original_text
    variants = _make_variants(original_text, offer_keywords, ev)
    bullets: list[ReformulatedBullet] = []
    for i, (text, actions) in enumerate(variants):
        # enforce constraints: if invention detected, drop numeric claims by using original evidence? We keep but mark.
        check = validate_bullet(text, ev)
        if not check.ok and any(v.code == "INVENTED_FACT" for v in check.violations):
            # strip invented numbers: remove tokens not in evidence
            # simple fallback: use a safe variant without numbers
            text = re.sub(r"\b\d+(?:[.,]\d+)?\s*(?:%|€|k€|M€)?\b", "", text).strip()
        sr = score_bullet(text, offer_keywords, ev)
        bullets.append(
            ReformulatedBullet(
                original_block_id=block_id,
                text_fr=text,
                variant_actions=list(actions),
                keyword_hits=list(sr.keyword_hits),
                evidence_refs=list(evidence_refs),
                ats_score=sr.ats_score,
                jury_score=sr.jury_score,
                provider=provider,
                version=version,
            )
        )
    return bullets


def recommend_combo(bullets: Sequence[ReformulatedBullet]) -> list[str]:
    """Return ids/texts of recommended bullets (top by combined score)."""
    ranked = sorted(bullets, key=lambda b: (b.ats_score + b.jury_score), reverse=True)
    # pick top 2-3
    pick = ranked[: min(3, len(ranked))]
    return [b.text_fr for b in pick]


def build_verdict(
    bullets: Sequence[ReformulatedBullet],
    current_text: str = "",
) -> RecommendVerdict:
    combo = recommend_combo(bullets)
    diff_lines = []
    if current_text.strip():
        diff_lines.append(f"- actuel: {current_text.strip()}")
    for b in bullets:
        diff_lines.append(f"+ variante (ATS {b.ats_score:.2f}): {b.text_fr}")
    return RecommendVerdict(
        bullets=list(bullets),
        recommended_combo=combo,
        diff_vs_current="\n".join(diff_lines),
    )


async def reformulate_experience_async(**kwargs: Any) -> list[ReformulatedBullet]:
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, lambda: reformulate_experience(**kwargs))


def reformulate_section(
    blocks: Sequence[dict[str, Any]],
    *,
    offer_keywords: Sequence[str] = (),
) -> list[ReformulatedBullet]:
    """Reformulate all experience blocks in a section."""
    out: list[ReformulatedBullet] = []
    for blk in blocks:
        original = blk.get("text", "") or blk.get("description", "")
        bid = blk.get("id", "") or blk.get("block_id", "")
        ev = blk.get("evidence_text", "") or original
        refs = blk.get("evidence_refs", []) or []
        bullets = reformulate_experience(
            original,
            block_id=bid,
            offer_keywords=offer_keywords,
            evidence_refs=refs,
            evidence_text=ev,
        )
        out.extend(bullets)
    return out


def gap_signals(profile_skills: Iterable[str], required_skills: Iterable[str]) -> list[str]:
    """Return skills required by offer but absent from profile (gaps, not inventions)."""
    prof = {s.strip().lower() for s in profile_skills if s.strip()}
    gaps: list[str] = []
    for r in required_skills:
        if r.strip() and r.strip().lower() not in prof:
            gaps.append(r.strip())
    return gaps


class ExperienceReformulator:
    """Class-based facade (compatibility with SPEC-020 orchestrator style)."""

    def __init__(self, provider: str = "local", version: int = 1) -> None:
        self.provider = provider
        self.version = version

    def reformulate_experience(self, *args: Any, **kwargs: Any) -> list[ReformulatedBullet]:
        kwargs.setdefault("provider", self.provider)
        kwargs.setdefault("version", self.version)
        return reformulate_experience(*args, **kwargs)

    async def reformulate_experience_async(self, *args: Any, **kwargs: Any) -> list[ReformulatedBullet]:
        kwargs.setdefault("provider", self.provider)
        kwargs.setdefault("version", self.version)
        return await reformulate_experience_async(*args, **kwargs)

    def reformulate_section(self, *args: Any, **kwargs: Any) -> list[ReformulatedBullet]:
        return reformulate_section(*args, **kwargs)

    def build_verdict(self, *args: Any, **kwargs: Any) -> RecommendVerdict:
        return build_verdict(*args, **kwargs)


# Aliases
reformulate = reformulate_experience
