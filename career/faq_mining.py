"""Sector FAQ mining from job offers (SPEC-031).

The module is deliberately local-first and deterministic: it reads only the
offers and profile the caller supplies, never a network service, a model or the
clock.  It groups offer expectations by sector / job family, ranks the recurring
terms, derives probable questions from the intents found in the requirements,
and attaches *verbatim* profile excerpts as candidate answer elements.

No fact is invented: when the profile contains no evidence for a question, the
answer list is empty rather than filled with a plausible-looking sentence.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
import re
from typing import Any

from .models import clean_text, normalized_text

__all__ = [
    "IntentCluster",
    "SectorFaq",
    "INTENT_LABELS",
    "MAX_OFFERS",
    "MAX_QUESTIONS",
    "MAX_TOP_TERMS",
    "cluster_intents",
    "expected_questions",
    "mine_all_sector_faqs",
    "mine_sector_faq",
    "profile_answer_elements",
    "question_for_intent",
]

# Bounds keep one hostile or accidental request from turning into an expensive
# local computation.  They are intentionally larger than the fixtures and the
# normal number of stored offers.
MAX_OFFERS = 200
MAX_OFFER_TEXT = 20_000
MAX_PROFILE_ITEMS = 200
MAX_PROFILE_ITEM_CHARS = 400
MAX_TOP_TERMS = 100
MAX_QUESTIONS = 50

DEFAULT_TOP_TERMS = 20
DEFAULT_MAX_QUESTIONS = 8

_SECTOR_KEYS = ("sector", "job_family", "family", "industry", "domain", "metier")
_OFFER_TEXT_KEYS = ("requirements", "description_original", "description", "notes")
_PROFILE_TEXT_KEYS = (
    "evidence",
    "experience",
    "skills",
    "languages",
    "education",
    "projects",
    "certifications",
    "availability",
    "achievements",
    "notes",
    "summary",
    "about",
)
_PROFILE_COMMA_KEYS = frozenset({"skills", "languages"})
_PROFILE_ITEM_KEYS = ("text", "value", "description", "detail", "label", "title")

# Words that carry no expectation on their own.  They are removed from
# ``top_terms`` only; intent detection still sees the raw requirement text.
_STOPWORDS = frozenset(
    """
    a an and are as at be been being but by can could did do does for from had has have
    he her here him his how i if in into is it its me more most must my no not of on
    or our ours she should so some than that the their theirs them then there these they
    this those to too us was we were what when where which who will with would you your
    yours
    au aux avec ce ces cet cette dans de des du elle elles en est et eu il ils je la le
    les leur leurs lui ma mais me meme mes moi mon ne nos notre nous on ou par pas pour
    qu que qui sa se ses son sont sur ta te tes toi ton tous tout toute toutes tu un une
    vos votre vous y
    ability able advanced etc excellent experience good knowledge plus required require
    requires skill skills strong using via work working
    company companies candidate candidates internship internships offer offers posting
    position role stage
    """.split()
)

_TOKEN_RE = re.compile(r"[a-z][a-z0-9]{2,}")

# A closed, versioned intent vocabulary.  It is a heuristic, not a model: every
# match is explainable by looking at the words in the offer requirements.
INTENT_LABELS: dict[str, str] = {
    "financial_modelling": "modélisation financière et valorisation",
    "accounting": "comptabilité et états financiers",
    "data_analysis": "analyse de données",
    "tools": "outils métier",
    "communication": "communication et présentation",
    "teamwork": "travail d'équipe",
    "languages": "langues de travail",
    "availability": "disponibilité et durée",
    "rigor": "rigueur et fiabilité des chiffres",
    "market_knowledge": "connaissance des marchés",
    "deal_experience": "expérience de transaction",
    "planning_forecasting": "budget et prévisions",
    "sector_knowledge": "connaissance du secteur",
    "compliance": "conformité et confidentialité",
}

INTENT_KEYWORDS: dict[str, tuple[str, ...]] = {
    "financial_modelling": (
        "financial model",
        "financial models",
        "financial modelling",
        "financial modeling",
        "modele financier",
        "modeles financiers",
        "modelisation financiere",
        "dcf",
        "valuation",
        "valorisation",
        "lbo",
        "comparable",
        "comparables",
        "three statement",
        "three statements",
    ),
    "accounting": (
        "accounting",
        "accountancy",
        "comptabilite",
        "comptable",
        "ifrs",
        "gaap",
        "financial statements",
        "etats financiers",
        "bilan",
        "profit and loss",
    ),
    "data_analysis": (
        "data analysis",
        "analyse de donnees",
        "sql",
        "python",
        "pandas",
        "analytics",
        "data science",
        "statistics",
        "statistiques",
    ),
    "tools": (
        "excel",
        "powerpoint",
        "bloomberg",
        "tableau",
        "vba",
        "power bi",
        "office suite",
        "google sheets",
    ),
    "communication": (
        "communication",
        "presentation",
        "presentations",
        "presenting",
        "client",
        "clients",
        "stakeholder",
        "stakeholders",
        "partie prenante",
        "parties prenantes",
        "reporting",
        "writing",
        "redaction",
        "public speaking",
    ),
    "teamwork": (
        "teamwork",
        "team work",
        "team player",
        "collaboration",
        "collaborative",
        "equipe",
        "travail d equipe",
    ),
    "languages": (
        "english",
        "french",
        "german",
        "spanish",
        "italian",
        "language",
        "languages",
        "langue",
        "langues",
        "anglais",
        "francais",
        "allemand",
        "espagnol",
        "bilingue",
        "fluent",
        "courant",
    ),
    "availability": (
        "availability",
        "available",
        "disponible",
        "disponibilite",
        "start date",
        "date de debut",
        "duration",
        "duree",
        "six month",
        "six months",
        "6 month",
        "6 months",
        "six mois",
        "january",
        "janvier",
        "february",
        "fevrier",
        "march",
        "mars",
        "april",
        "avril",
    ),
    "rigor": (
        "attention to detail",
        "detail oriented",
        "rigor",
        "rigueur",
        "rigorous",
        "deadline",
        "deadlines",
        "accuracy",
        "accurate",
        "precis",
        "precise",
        "qualite",
    ),
    "market_knowledge": (
        "market",
        "markets",
        "marche",
        "marches",
        "macro",
        "macroeconomic",
        "macroeconomics",
        "equity research",
        "economics",
        "economie",
        "conjoncture",
        "trading",
    ),
    "deal_experience": (
        "deal",
        "deals",
        "transaction",
        "transactions",
        "due diligence",
        "portfolio",
        "acquisition",
        "acquisitions",
        "investment",
        "investments",
        "private equity",
        "mandat",
        "operation",
    ),
    "planning_forecasting": (
        "budget",
        "budgets",
        "budgeting",
        "forecast",
        "forecasts",
        "forecasting",
        "prevision",
        "previsions",
        "management reporting",
        "planning",
        "business plan",
    ),
    "sector_knowledge": (
        "sector",
        "secteur",
        "industry",
        "industrie",
        "why finance",
        "pourquoi la finance",
    ),
    "compliance": (
        "compliance",
        "conformite",
        "confidentiality",
        "confidentialite",
        "regulatory",
        "regulation",
        "kyc",
        "aml",
        "anti money laundering",
    ),
}

_QUESTION_BY_INTENT: dict[str, str] = {
    "financial_modelling": (
        "Peux-tu décrire un modèle financier que tu as construit et expliquer les "
        "hypothèses que tu as dû justifier ?"
    ),
    "accounting": "Quelle est ton expérience des états financiers et des normes comptables ?",
    "data_analysis": "Quel outil d'analyse de données as-tu utilisé, et sur quel cas concret ?",
    "tools": "Quels outils métier maîtrises-tu, et peux-tu donner un exemple de livrable produit ?",
    "communication": (
        "Comment as-tu présenté une analyse complexe à un client ou à une partie prenante ?"
    ),
    "teamwork": "Décris un travail d'équipe où tu as dû coordonner plusieurs contributions.",
    "languages": "Dans quelles langues as-tu travaillé ou étudié, et à quel niveau ?",
    "availability": "Quelles sont tes dates de disponibilité et la durée de stage recherchée ?",
    "rigor": "Comment garantis-tu la fiabilité de tes chiffres sous contrainte de délai ?",
    "market_knowledge": "Quel développement de marché récent as-tu suivi, et comment l'as-tu analysé ?",
    "deal_experience": (
        "As-tu participé à une transaction ou à un projet de bout en bout ? Quel était ton rôle ?"
    ),
    "planning_forecasting": (
        "Comment as-tu construit un budget ou une prévision, et quelles hypothèses as-tu vérifiées ?"
    ),
    "sector_knowledge": (
        "Pourquoi ce secteur t'intéresse-t-il, et que connais-tu de ses métiers et de ses exigences ?"
    ),
    "compliance": (
        "Comment prends-tu en compte les règles de conformité et de confidentialité dans ton travail ?"
    ),
}

# Pre-normalise once so matching never depends on accents, case or punctuation.
_NORMALIZED_KEYWORDS: dict[str, tuple[str, ...]] = {
    intent: tuple(
        keyword for keyword in (normalized_text(item) for item in keywords) if keyword
    )
    for intent, keywords in INTENT_KEYWORDS.items()
}


@dataclass(frozen=True)
class IntentCluster:
    """One recurring expectation found in a group of offers."""

    intent: str
    label: str
    count: int
    offer_ids: tuple[str, ...]
    examples: tuple[str, ...]


@dataclass
class SectorFaq:
    """A sector-level FAQ mined from offers.

    Attributes:
        sector: The sector / job family covered by this FAQ.
        top_terms: ``(term, frequency)`` pairs, sorted by frequency then term.
        likely_questions: Deterministic probable questions, ordered by intent
            frequency then intent identifier.
        profile_answers: Mapping ``question -> verbatim profile excerpts``.
            The list is empty when the profile holds no matching evidence.
    """

    sector: str
    top_terms: list[tuple[str, int]] = field(default_factory=list)
    likely_questions: list[str] = field(default_factory=list)
    profile_answers: dict[str, list[str]] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return {
            "sector": self.sector,
            "top_terms": [[term, count] for term, count in self.top_terms],
            "likely_questions": list(self.likely_questions),
            "profile_answers": {
                question: list(items) for question, items in self.profile_answers.items()
            },
        }

    # Kept as an alias: the Career router already serialises other modules with
    # ``to_dict`` and client code should not need to know which method is used.
    def to_dict(self) -> dict[str, Any]:
        return self.as_dict()


def _bounded_int(value: Any, default: int, maximum: int) -> int:
    try:
        number = int(value)
    except (TypeError, ValueError):
        number = default
    return max(0, min(number, maximum))


def _clean_offers(offers: Any) -> list[Mapping[str, Any]]:
    if offers is None:
        return []
    if isinstance(offers, Mapping):
        candidates: Iterable[Any] = (offers,)
    elif isinstance(offers, (str, bytes, bytearray)):
        return []
    else:
        try:
            candidates = iter(offers)
        except TypeError:
            return []
    cleaned: list[Mapping[str, Any]] = []
    for offer in candidates:
        if isinstance(offer, Mapping):
            cleaned.append(offer)
        if len(cleaned) >= MAX_OFFERS:
            break
    return cleaned


def _offer_sector(offer: Mapping[str, Any]) -> str:
    for key in _SECTOR_KEYS:
        value = clean_text(offer.get(key), limit=160)
        if value:
            return value
    return "Non précisé"


def _offer_text(offer: Mapping[str, Any]) -> str:
    for key in _OFFER_TEXT_KEYS:
        value = offer.get(key)
        if isinstance(value, str):
            text = clean_text(value, limit=MAX_OFFER_TEXT)
        elif isinstance(value, (list, tuple)):
            text = clean_text(" ".join(str(item) for item in value), limit=MAX_OFFER_TEXT)
        else:
            text = ""
        if text:
            return text
    return ""


def _offer_identifier(offer: Mapping[str, Any], index: int) -> str:
    for key in ("id", "source_id", "official_url"):
        value = clean_text(offer.get(key), limit=200)
        if value:
            return value
    return f"offer-{index + 1}"


def _blob(text: str) -> str:
    return f" {normalized_text(text)} "


def _contains_keywords(blob: str, keywords: Iterable[str]) -> bool:
    return any(f" {keyword} " in blob for keyword in keywords if keyword)


def _is_offer_mapping(value: Any) -> bool:
    """Distinguish an offer from a pre-computed ``{"intent": ...}`` entry."""
    if not isinstance(value, Mapping) or "intent" in value:
        return False
    return any(
        key in value
        for key in (*_OFFER_TEXT_KEYS, *_SECTOR_KEYS, "id", "title", "company", "official_url")
    )


def _sentences(text: str) -> list[str]:
    parts = re.split(r"(?<=[.!?])\s+|\n+", text)
    return [clean_text(part, limit=MAX_PROFILE_ITEM_CHARS) for part in parts if clean_text(part)]


def _first_matching_sentence(sentences: Iterable[str], keywords: Iterable[str]) -> str:
    fallback = ""
    for sentence in sentences:
        if not fallback:
            fallback = sentence
        if _contains_keywords(_blob(sentence), keywords):
            return clean_text(sentence, limit=240)
    return clean_text(fallback, limit=240)


def cluster_intents(
    offers: Any,
    *,
    min_count: int = 1,
    max_examples: int = 2,
) -> list[IntentCluster]:
    """Return the recurring expectations found in ``offers``.

    An intent is counted at most once per offer, so copying the same keyword
    twenty times into one requirement cannot make it look like a sector-wide
    expectation.  Results are sorted by ``(-count, intent)`` and are therefore
    stable across runs and machines.
    """
    cleaned = _clean_offers(offers)
    threshold = max(1, _bounded_int(min_count, 1, MAX_OFFERS))
    example_limit = _bounded_int(max_examples, 2, 10)
    counts: Counter[str] = Counter()
    offer_ids: dict[str, list[str]] = {}
    examples: dict[str, list[str]] = {}

    for index, offer in enumerate(cleaned):
        text = _offer_text(offer)
        blob = _blob(text)
        if not blob.strip():
            continue
        identifier = _offer_identifier(offer, index)
        sentences = _sentences(text)
        for intent, keywords in _NORMALIZED_KEYWORDS.items():
            if not _contains_keywords(blob, keywords):
                continue
            counts[intent] += 1
            offer_ids.setdefault(intent, []).append(identifier)
            bucket = examples.setdefault(intent, [])
            if len(bucket) < example_limit:
                example = _first_matching_sentence(sentences, keywords)
                if example and example not in bucket:
                    bucket.append(example)

    clusters = [
        IntentCluster(
            intent=intent,
            label=INTENT_LABELS.get(intent, intent),
            count=count,
            offer_ids=tuple(offer_ids.get(intent, ())),
            examples=tuple(examples.get(intent, ())),
        )
        for intent, count in counts.items()
        if count >= threshold
    ]
    clusters.sort(key=lambda cluster: (-cluster.count, cluster.intent))
    return clusters


def question_for_intent(intent: str) -> str:
    """Return the stable question template for ``intent`` (``""`` if unknown)."""
    return _QUESTION_BY_INTENT.get(str(intent), "")


def _question_pairs(
    intents: Any,
    *,
    max_questions: int = DEFAULT_MAX_QUESTIONS,
) -> list[tuple[str, str]]:
    limit = _bounded_int(max_questions, DEFAULT_MAX_QUESTIONS, MAX_QUESTIONS)
    if limit == 0:
        return []
    if isinstance(intents, Mapping):
        items: list[Any] = [intents]
    elif isinstance(intents, (str, bytes, bytearray)):
        items = [intents]
    else:
        try:
            items = list(intents)
        except TypeError:
            return []

    # ``expected_questions`` also accepts raw offers (as documented).  Mine
    # those first so callers are not required to know about IntentCluster.
    offer_items = [item for item in items if _is_offer_mapping(item)]
    if offer_items:
        items = [
            *cluster_intents(offer_items),
            *(item for item in items if not _is_offer_mapping(item)),
        ]

    pairs: list[tuple[str, str]] = []
    seen: set[str] = set()
    for item in items:
        if isinstance(item, IntentCluster):
            intent = item.intent
        elif isinstance(item, Mapping):
            intent = str(item.get("intent", ""))
        else:
            intent = str(item)
        question = question_for_intent(intent)
        if question and question not in seen:
            seen.add(question)
            pairs.append((intent, question))
        if len(pairs) >= limit:
            break
    return pairs


def expected_questions(
    intents: Any,
    *,
    sector: str = "",
    max_questions: int = DEFAULT_MAX_QUESTIONS,
) -> list[str]:
    """Derive probable questions from intent clusters (or intent identifiers).

    ``intents`` may be the output of :func:`cluster_intents`, an iterable of
    intent names, or a list of offers (in which case it is clustered first).
    ``sector`` is accepted for API symmetry; questions stay generic enough to
    avoid asserting unverified company facts.
    """
    del sector  # reserved for future locale/sector-specific wording
    return [question for _, question in _question_pairs(intents, max_questions=max_questions)]


def _split_profile_text(value: str, *, comma: bool) -> list[str]:
    text = clean_text(value, limit=MAX_OFFER_TEXT)
    parts = re.split(r"[\n\r•|;]+", text)
    if comma:
        parts = [piece for part in parts for piece in re.split(r",(?:\s+|$)", part)]
    return [clean_text(part, limit=MAX_PROFILE_ITEM_CHARS) for part in parts if clean_text(part)]


def _flatten_profile_value(value: Any, *, comma: bool) -> list[str]:
    if isinstance(value, str):
        return _split_profile_text(value, comma=comma)
    if isinstance(value, Mapping):
        for key in _PROFILE_ITEM_KEYS:
            nested = value.get(key)
            if isinstance(nested, str) and nested.strip():
                return _split_profile_text(nested, comma=comma)
        return []
    if isinstance(value, (list, tuple)):
        flattened: list[str] = []
        for item in value:
            flattened.extend(_flatten_profile_value(item, comma=comma))
        return flattened
    return []


def _profile_evidence(profile: Any) -> list[str]:
    """Flatten a profile into ordered, de-duplicated evidence excerpts."""
    if profile is None:
        return []
    if isinstance(profile, str):
        raw_values = _split_profile_text(profile, comma=False)
    elif isinstance(profile, Mapping):
        raw_values = []
        for key in _PROFILE_TEXT_KEYS:
            if key in profile:
                raw_values.extend(
                    _flatten_profile_value(profile[key], comma=key in _PROFILE_COMMA_KEYS)
                )
    elif isinstance(profile, (list, tuple)):
        raw_values = []
        for item in profile:
            raw_values.extend(_flatten_profile_value(item, comma=False))
    else:
        return []

    evidence: list[str] = []
    seen: set[str] = set()
    for value in raw_values:
        item = clean_text(value, limit=MAX_PROFILE_ITEM_CHARS)
        key = normalized_text(item)
        if len(key) < 2 or key in seen:
            continue
        seen.add(key)
        evidence.append(item)
        if len(evidence) >= MAX_PROFILE_ITEMS:
            break
    return evidence


def profile_answer_elements(profile: Any, intent: str, *, limit: int = 3) -> list[str]:
    """Return verbatim profile excerpts relevant to ``intent``.

    Relevance is the number of distinct keywords from the intent vocabulary
    found in the excerpt; ties keep the profile's own order.  Nothing is
    generated or paraphrased, so an empty list honestly means "no evidence".
    """
    keywords = _NORMALIZED_KEYWORDS.get(str(intent), ())
    maximum = _bounded_int(limit, 3, 10)
    if not keywords or maximum == 0:
        return []

    ranked: list[tuple[int, int, str]] = []
    for position, item in enumerate(_profile_evidence(profile)):
        blob = _blob(item)
        hits = sum(1 for keyword in keywords if f" {keyword} " in blob)
        if hits:
            ranked.append((-hits, position, item))
    ranked.sort(key=lambda entry: (entry[0], entry[1]))
    return [item for _, _, item in ranked[:maximum]]


def _top_terms(offers: Iterable[Mapping[str, Any]], *, limit: int) -> list[tuple[str, int]]:
    counter: Counter[str] = Counter()
    for offer in offers:
        counter.update(
            token
            for token in _TOKEN_RE.findall(normalized_text(_offer_text(offer)))
            if token not in _STOPWORDS
        )
    ordered = sorted(counter.items(), key=lambda item: (-item[1], item[0]))
    return ordered[:limit]


def _group_offers(offers: Iterable[Mapping[str, Any]]) -> dict[str, dict[str, Any]]:
    groups: dict[str, dict[str, Any]] = {}
    for offer in offers:
        sector = _offer_sector(offer)
        key = normalized_text(sector) or "non precise"
        group = groups.setdefault(key, {"sector": sector, "offers": []})
        group["offers"].append(offer)
    return groups


def mine_sector_faq(
    offers: Any,
    profile: Any = None,
    *,
    sector: str | None = None,
    top_n: int = DEFAULT_TOP_TERMS,
    max_questions: int = DEFAULT_MAX_QUESTIONS,
    min_intent_count: int = 1,
) -> SectorFaq:
    """Mine one sector FAQ from ``offers``.

    When ``sector`` is omitted, the most frequent sector is used (ties broken
    alphabetically), which keeps a one-call UI useful without depending on
    dictionary order.  Use :func:`mine_all_sector_faqs` to get every sector.
    """
    cleaned = _clean_offers(offers)
    term_limit = _bounded_int(top_n, DEFAULT_TOP_TERMS, MAX_TOP_TERMS)
    question_limit = _bounded_int(max_questions, DEFAULT_MAX_QUESTIONS, MAX_QUESTIONS)

    requested = clean_text(sector, limit=160) if sector is not None else ""
    groups = _group_offers(cleaned)
    if requested:
        key = normalized_text(requested)
        group = groups.get(key)
        sector_name = requested
        selected = group["offers"] if group else []
    elif groups:
        key = sorted(
            groups,
            key=lambda item: (-len(groups[item]["offers"]), groups[item]["sector"].casefold()),
        )[0]
        group = groups[key]
        sector_name = group["sector"]
        selected = group["offers"]
    else:
        sector_name = ""
        selected = []

    clusters = cluster_intents(selected, min_count=min_intent_count)
    pairs = _question_pairs(clusters, max_questions=question_limit)
    answers = {
        question: profile_answer_elements(profile, intent)
        for intent, question in pairs
    }
    return SectorFaq(
        sector=sector_name,
        top_terms=_top_terms(selected, limit=term_limit),
        likely_questions=[question for _, question in pairs],
        profile_answers=answers,
    )


def mine_all_sector_faqs(
    offers: Any,
    profile: Any = None,
    *,
    top_n: int = DEFAULT_TOP_TERMS,
    max_questions: int = DEFAULT_MAX_QUESTIONS,
    min_intent_count: int = 1,
) -> list[SectorFaq]:
    """Mine one FAQ per sector, ordered by offer count then sector name."""
    cleaned = _clean_offers(offers)
    groups = _group_offers(cleaned)
    ordered = sorted(
        groups.values(),
        key=lambda group: (
            -len(group["offers"]),
            group["sector"].casefold(),
            group["sector"],
        ),
    )
    return [
        mine_sector_faq(
            group["offers"],
            profile,
            sector=group["sector"],
            top_n=top_n,
            max_questions=max_questions,
            min_intent_count=min_intent_count,
        )
        for group in ordered
    ]
