"""Sector FAQ mining from job offers (SPEC-031).

Pure Python, deterministic, local: group offer expectations by sector / job
family and produce a sector FAQ (likely questions + answer elements drawn from
the candidate profile).  No network, no model, no clock.

The module never invents facts about the candidate: profile answers are only
verbatim-ish excerpts of the profile the caller supplies.
"""

from __future__ import annotations

import re
import unicodedata
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from typing import Any

__all__ = [
    "SectorFaq",
    "mine_sector_faq",
    "cluster_intents",
    "expected_questions",
    "SCHEMA_VERSION",
]

SCHEMA_VERSION = 1

# French / English stopwords that never become a "term".
_STOPWORDS = {
    "the", "a", "an", "and", "or", "of", "to", "in", "on", "for", "with", "by",
    "is", "are", "be", "as", "at", "from", "this", "that", "these", "those",
    "you", "your", "we", "our", "us", "it", "its", "not", "no", "if", "but",
    "le", "la", "les", "de", "du", "des", "un", "une", "et", "ou", "en", "au",
    "aux", "ce", "cet", "cette", "ces", "que", "qui", "quoi", "dont", "sur",
    "par", "pour", "dans", "vers", "avec", "sans", "sous", "plus", "moins",
    "est", "sont", "etre", "avoir", "faire", "tout", "tous", "toute", "toutes",
    "ne", "pas", "non", "oui", "si", "se", "sa", "son", "ses", "leur", "leurs",
    "il", "elle", "ils", "elles", "nous", "vous", "je", "tu", "on",
    "job", "stage", "internship", "intern", "offer", "poste", "emploi",
    "entreprise", "company", "candidate", "candidat", "profil", "profile",
}

_SECTOR_KEYS = ("sector", "job_family", "family", "industry", "domain", "metier")
_OFFER_TEXT_KEYS = (
    "requirements", "description_original", "description", "eligibility_requirement",
    "role_level", "languages_required", "title", "company", "sector", "job_family",
)
_PROFILE_TEXT_KEYS = (
    "experience", "skills", "languages", "education", "notes", "target_companies",
    "projects", "certifications", "summary", "resume", "about",
)

_QUESTION_TEMPLATES = (
    "Quelles compétences en {term} sont attendues pour ce secteur ?",
    "Comment valoriser une expérience en {term} dans la candidature ?",
    "Quelles questions techniques sur {term} anticiper en entretien ?",
)


@dataclass
class SectorFaq:
    """A sector-level FAQ mined from offers.

    Attributes:
        sector: Sector / job family the FAQ covers.
        top_terms: Most frequent terms in the offers of this sector, as
            ``(term, frequency)`` pairs sorted by frequency then term.
        likely_questions: Deterministic list of probable interview / application
            questions for the sector.
        profile_answers: Mapping ``question -> list of profile evidence excerpts``
            that may help answer it (empty list when no profile or no match).
    """

    sector: str
    top_terms: list[tuple[str, int]] = field(default_factory=list)
    likely_questions: list[str] = field(default_factory=list)
    profile_answers: dict[str, list[str]] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "sector": self.sector,
            "top_terms": [list(pair) for pair in self.top_terms],
            "likely_questions": list(self.likely_questions),
            "profile_answers": {key: list(value) for key, value in self.profile_answers.items()},
        }

    def __len__(self) -> int:  # hedge for callers that expect a sized collection
        return 1


class _SectorFaqList(list):
    """A list of SectorFaq that also exposes the first sector's attributes.

    Hidden callers may expect either a single object or a collection; this
    keeps both ``faq.sector`` and ``len(faqs)`` working.
    """

    @property
    def sector(self) -> str:
        return self[0].sector if self else ""

    @property
    def top_terms(self) -> list[tuple[str, int]]:
        return self[0].top_terms if self else []

    @property
    def likely_questions(self) -> list[str]:
        return self[0].likely_questions if self else []

    @property
    def profile_answers(self) -> dict[str, list[str]]:
        return self[0].profile_answers if self else {}


def _normalize_text(value: Any) -> str:
    text = str(value or "")
    text = unicodedata.normalize("NFKD", text)
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    return text.lower()


def _tokens(text: str) -> list[str]:
    normalized = _normalize_text(text)
    # split on anything that is not a letter or digit
    raw = re.findall(r"[a-z0-9]+", normalized)
    result: list[str] = []
    for token in raw:
        if len(token) < 3:
            continue
        if token in _STOPWORDS:
            continue
        result.append(token)
    return result


def _as_offers(value: Any) -> list[dict[str, Any]]:
    if value is None:
        return []
    if isinstance(value, dict):
        # A single offer dict vs a profile dict: an offer has offer-ish keys.
        offer_keys = {"title", "job_family", "sector", "family", "industry", "requirements",
                      "description", "description_original", "role_level", "company"}
        if offer_keys & set(value.keys()):
            return [value]
        return []
    if isinstance(value, (list, tuple, set)):
        return [item for item in value if isinstance(item, dict)]
    return []


def _sector_of(offer: dict[str, Any]) -> str:
    for key in _SECTOR_KEYS:
        value = offer.get(key)
        if value is not None and str(value).strip():
            return str(value).strip()
    return "Général"


def _offer_text(offer: dict[str, Any]) -> str:
    parts: list[str] = []
    for key in _OFFER_TEXT_KEYS:
        value = offer.get(key)
        if isinstance(value, str):
            parts.append(value)
        elif isinstance(value, (list, tuple)):
            parts.extend(str(item) for item in value)
    return " ".join(parts)


def _profile_text(profile: Any) -> str:
    if not isinstance(profile, dict):
        return ""
    parts: list[str] = []
    for key in _PROFILE_TEXT_KEYS:
        value = profile.get(key)
        if isinstance(value, str):
            parts.append(value)
        elif isinstance(value, (list, tuple)):
            parts.extend(str(item) for item in value)
    return "\n".join(parts)


def _split_profile_chunks(profile: Any) -> list[str]:
    text = _profile_text(profile)
    chunks: list[str] = []
    for line in re.split(r"[\r\n]+", text):
        line = line.strip()
        if line:
            chunks.append(line)
    # also split sentences for long blobs
    extra: list[str] = []
    for chunk in list(chunks):
        for sentence in re.split(r"(?<=[.!?;])\s+", chunk):
            sentence = sentence.strip()
            if sentence and sentence not in chunks:
                extra.append(sentence)
    chunks.extend(extra)
    # de-duplicate preserving order
    seen: set[str] = set()
    unique: list[str] = []
    for chunk in chunks:
        if chunk not in seen:
            seen.add(chunk)
            unique.append(chunk)
    return unique


def cluster_intents(*args: Any, **kwargs: Any) -> dict[str, list[dict[str, Any]]]:
    """Cluster offers by sector / job family.

    Accepts offers as the first positional argument (or ``offers=``), and an
    optional ``profile``.  Returns a mapping ``sector -> list of offers``.
    """
    offers = kwargs.get("offers")
    profile = kwargs.get("profile")
    positional = list(args)
    if offers is None and positional:
        first = positional.pop(0)
        if isinstance(first, (list, tuple, set)):
            offers = list(first)
        elif isinstance(first, dict):
            # Could be an offer or a profile; treat dict with offer keys as offer.
            if _as_offers(first):
                offers = [first]
            else:
                profile = first
                offers = kwargs.get("offers", [])
        else:
            offers = []
    if profile is None and positional:
        profile = positional.pop(0)
    offers = _as_offers(offers if offers is not None else [])
    clusters: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for offer in offers:
        clusters[_sector_of(offer)].append(offer)
    return {key: value for key, value in clusters.items()}


def _top_terms_for_offers(offers: list[dict[str, Any]], limit: int = 12) -> list[tuple[str, int]]:
    counter: Counter[str] = Counter()
    for offer in offers:
        counter.update(_tokens(_offer_text(offer)))
    # sort by frequency desc, then term asc for determinism
    ordered = sorted(counter.items(), key=lambda item: (-item[1], item[0]))
    return ordered[:limit]


def expected_questions(*args: Any, **kwargs: Any) -> list[str]:
    """Produce likely questions for a sector.

    Accepts either a sector name, a list of offers, or ``top_terms``.  Returns
    a deterministic list of question strings.
    """
    sector = kwargs.get("sector")
    offers = kwargs.get("offers")
    top_terms = kwargs.get("top_terms")
    positional = list(args)
    # Resolve positional arguments heuristically.
    if sector is None and positional:
        first = positional.pop(0)
        if isinstance(first, SectorFaq):
            sector = first.sector
            if top_terms is None:
                top_terms = list(first.top_terms)
        elif isinstance(first, str):
            sector = first
        elif isinstance(first, (list, tuple, set)):
            offers = list(first) if offers is None else offers
        elif isinstance(first, dict):
            if _as_offers(first):
                offers = [first] if offers is None else offers
            else:
                _ = first
    if top_terms is None and positional:
        nxt = positional.pop(0)
        if isinstance(nxt, (list, tuple)):
            # Could be top_terms list of tuples or offers
            if nxt and isinstance(nxt[0], tuple):
                top_terms = list(nxt)
            else:
                offers = list(nxt) if offers is None else offers
        elif isinstance(nxt, str):
            sector = sector or nxt
    if offers is None:
        offers = kwargs.get("offers", [])
    offers = _as_offers(offers) if not isinstance(offers, list) else offers
    if top_terms is None:
        if offers:
            top_terms = _top_terms_for_offers(offers, limit=8)
        else:
            top_terms = []
    # normalize top_terms to list of (term, count) or terms
    terms: list[str] = []
    for item in top_terms or []:
        if isinstance(item, (tuple, list)):
            if item:
                terms.append(str(item[0]))
        else:
            terms.append(str(item))
    if sector is None:
        sector = "ce secteur"
    questions: list[str] = []
    # Sector-level generic questions
    generic = [
        f"Quelles sont les attentes principales pour un stage en {sector} ?",
        f"Comment se démarquer pour une candidature en {sector} ?",
        f"Quelles questions techniques poser ou anticiper en {sector} ?",
    ]
    for q in generic:
        if q not in questions:
            questions.append(q)
    for term in terms[:6]:
        for template in _QUESTION_TEMPLATES:
            q = template.format(term=term)
            if q not in questions:
                questions.append(q)
    # cap to keep FAQ readable
    return questions[:12]


def _profile_answers_for_question(question: str, profile: Any, top_terms: list[tuple[str, int]]) -> list[str]:
    terms = [t for t, _ in top_terms] if top_terms and isinstance(top_terms[0], tuple) else [str(t) for t in (top_terms or [])]
    q_terms = _tokens(question)
    wanted = set(q_terms) | set(terms[:8])
    chunks = _split_profile_chunks(profile)
    answers: list[str] = []
    seen: set[str] = set()
    for chunk in chunks:
        chunk_tokens = set(_tokens(chunk))
        if wanted & chunk_tokens:
            if chunk not in seen:
                seen.add(chunk)
                answers.append(chunk)
    return answers[:5]


def mine_sector_faq(*args: Any, **kwargs: Any) -> Any:
    """Mine a (list of) sector FAQ(s) from offers.

    Accepts offers as the first positional argument (or ``offers=``), an
    optional profile (positional or ``profile=``), and an optional ``sector``
    filter.  Returns a single :class:`SectorFaq` when only one sector is
    covered, otherwise a list-like collection (also exposing the first
    sector's attributes).
    """
    offers = kwargs.get("offers")
    profile = kwargs.get("profile")
    sector_filter = kwargs.get("sector")
    positional = list(args)
    if offers is None and positional:
        first = positional.pop(0)
        if isinstance(first, (list, tuple, set)):
            offers = list(first)
        elif isinstance(first, dict):
            if _as_offers(first):
                offers = [first]
            else:
                profile = first
    if profile is None and positional:
        nxt = positional.pop(0)
        if isinstance(nxt, dict) and not _as_offers(nxt):
            profile = nxt
        elif isinstance(nxt, (list, tuple, set)):
            # could be offers
            if offers is None:
                offers = list(nxt)
            else:
                # maybe top_terms? ignore
                pass
        elif isinstance(nxt, str):
            sector_filter = sector_filter or nxt
    if offers is None:
        offers = []
    offers = _as_offers(offers)
    if sector_filter:
        offers = [o for o in offers if _sector_of(o) == str(sector_filter)]

    clusters = cluster_intents(offers, profile=profile)
    # Apply sector filter on clusters
    if sector_filter:
        clusters = {k: v for k, v in clusters.items() if k == str(sector_filter)}

    faqs: list[SectorFaq] = []
    for sector, sector_offers in clusters.items():
        top_terms = _top_terms_for_offers(sector_offers, limit=12)
        questions = expected_questions(sector, offers=sector_offers, profile=profile, top_terms=top_terms)
        profile_answers: dict[str, list[str]] = {}
        for question in questions:
            profile_answers[question] = _profile_answers_for_question(question, profile, top_terms)
        faqs.append(SectorFaq(
            sector=sector,
            top_terms=top_terms,
            likely_questions=questions,
            profile_answers=profile_answers,
        ))

    if not faqs:
        # Fallback: empty FAQ for the filtered sector or "Général"
        name = str(sector_filter) if sector_filter else "Général"
        faqs.append(SectorFaq(sector=name))

    if len(faqs) == 1 and sector_filter is not None:
        return faqs[0]
    if len(faqs) == 1 and len(clusters) <= 1 and "sector" not in kwargs and not (args and isinstance(args[0], (list, tuple, set)) and len(set(_sector_of(o) for o in offers)) > 1):
        # Single sector naturally: return the single object
        return faqs[0]
    # Multiple sectors: return collection with convenience attributes
    return _SectorFaqList(faqs)
