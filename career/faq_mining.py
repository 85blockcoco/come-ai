"""Sector FAQ mining from job offers (SPEC-031).

Pure, local, deterministic: clusters offer descriptions by sector/family and
produces a :class:`SectorFaq` with top terms, likely questions and profile
answers.  No network, no secrets.
"""

from __future__ import annotations

import re
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from typing import Any, Iterable

_STOPWORDS = {
    "le", "la", "les", "de", "du", "des", "un", "une", "et", "ou", "en", "au",
    "aux", "ce", "se", "sa", "son", "sur", "par", "pour", "dans", "avec", "sans",
    "the", "a", "an", "and", "or", "of", "to", "in", "on", "for", "with", "at",
    "by", "is", "are", "be", "as", "it", "this", "that", "from",
}

_QUESTION_TEMPLATES = [
    "Pouvez-vous décrire votre expérience en {term} ?",
    "Quels outils maîtrisez-vous pour {term} ?",
    "Comment abordez-vous {term} dans un contexte professionnel ?",
]


@dataclass
class SectorFaq:
    sector: str
    top_terms: list[tuple[str, int]] = field(default_factory=list)
    likely_questions: list[str] = field(default_factory=list)
    profile_answers: dict[str, list[str]] = field(default_factory=dict)


def _tokenize(text: str) -> list[str]:
    text = (text or "").lower()
    # keep alphanumeric + accented letters
    tokens = re.findall(r"[a-zàâäéèêëïîôöùûüç0-9][a-zàâäéèêëïîôöùûüç0-9\-]{2,}", text)
    return [t for t in tokens if t not in _STOPWORDS]


def cluster_intents(offers: Iterable[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    """Group offers by sector/family. Returns {sector: [offers]}."""
    groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for offer in offers:
        if not isinstance(offer, dict):
            continue
        sector = str(offer.get("sector") or offer.get("family") or offer.get("category") or "general").strip().lower()
        if not sector:
            sector = "general"
        groups[sector].append(offer)
    return dict(groups)


def mine_sector_faq(
    offers: Iterable[dict[str, Any]],
    *,
    profile_terms: Iterable[str] | None = None,
    top_n: int = 10,
) -> list[SectorFaq]:
    """Mine a list of sector FAQs from job offers.

    Each offer is expected to have at least ``sector`` and ``description`` (or
    ``text``).  Returns one :class:`SectorFaq` per sector, sorted by sector.
    """
    groups = cluster_intents(offers)
    profile_set = {str(t).lower().strip() for t in (profile_terms or []) if str(t).strip()}
    result: list[SectorFaq] = []
    for sector in sorted(groups):
        offers_in = groups[sector]
        counter: Counter[str] = Counter()
        for offer in offers_in:
            text = offer.get("description") or offer.get("text") or offer.get("requirements") or ""
            counter.update(_tokenize(str(text)))
        top_terms = counter.most_common(top_n)

        # Likely questions derived from top terms.
        likely_questions: list[str] = []
        seen_q: set[str] = set()
        for term, _freq in top_terms[:5]:
            for tmpl in _QUESTION_TEMPLATES:
                q = tmpl.format(term=term)
                if q not in seen_q:
                    seen_q.add(q)
                    likely_questions.append(q)
                    if len(likely_questions) >= 5:
                        break
            if len(likely_questions) >= 5:
                break

        # Profile answers: map each question to profile terms that appear in
        # the offer's top terms.
        profile_answers: dict[str, list[str]] = {}
        for q in likely_questions:
            # include profile terms that are top terms
            ans_terms = [t for t in profile_set if t in {tt[0] for tt in top_terms}]
            profile_answers[q] = sorted(ans_terms)

        result.append(SectorFaq(
            sector=sector,
            top_terms=top_terms,
            likely_questions=likely_questions,
            profile_answers=profile_answers,
        ))
    return result


def expected_questions(sector_faq: SectorFaq) -> list[str]:
    """Return the likely questions for a sector FAQ (convenience)."""
    return list(sector_faq.likely_questions)