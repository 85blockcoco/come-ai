"""Deterministic extraction of weighted ATS keywords for a Career offer (SPEC-019).

Pure Python, local, no network, no model and no clock: analysing the same
offer always returns byte-identical results.  Offer text is treated as
untrusted data.

Modules:
- ``extract_keywords`` / aliases build a ``KeywordProfile`` from an offer dict
  or raw text, optionally enriched by profile, web research (SPEC-018) and
  arena consensus (SPEC-017) inputs.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Literal

from .models import clean_text, normalized_text

Category = Literal[
    "hard_skill",
    "soft_skill",
    "tool",
    "method",
    "domain",
    "language",
    "certification",
]
Kind = Literal["must", "nice", "implicit"]


@dataclass
class Keyword:
    """One weighted ATS keyword extracted from an offer."""

    term: str = ""
    normalized: str = ""
    category: Category = "hard_skill"
    weight: float = 0.0
    kind: Kind = "implicit"
    evidence_refs: list[str] = field(default_factory=list)
    synonyms: list[str] = field(default_factory=list)


@dataclass
class KeywordProfile:
    """Weighted keyword profile for one offer."""

    offer_id: str = ""
    keywords: list[Keyword] = field(default_factory=list)
    score_coverage: dict[str, Any] = field(default_factory=dict)
    gaps: list[Keyword] = field(default_factory=list)
    generated_at: str = ""


# ---------------------------------------------------------------- lexicons

_STOPWORDS: frozenset[str] = frozenset(
    {
        # generic / offer boilerplate
        "the", "and", "for", "with", "you", "your", "our", "are", "will",
        "this", "that", "have", "has", "not", "but", "from", "into", "about",
        "stage", "intern", "internship", "role", "job", "position", "offer",
        "required", "requirement", "requirements", "preferred", "bonus",
        "experience", "experiences", "years", "year", "month", "months",
        "minimum", "least", "plus", "very", "good", "strong", "advanced",
        "basic", "level", "levels", "ability", "able", "work", "working",
        "team", "teams", "company", "group", "candidate", "profile",
        "skills", "skill", "knowledge", "understanding", "background",
        "degree", "master", "bachelor", "university", "school", "education",
        "paris", "london", "milan", "luxembourg", "frankfurt", "geneva",
        "france", "europe", "remote", "hybrid", "office", "full", "time",
        "part", "contract", "cdi", "cdd", "vie",
        # fr
        "les", "des", "une", "pour", "avec", "vous", "votre", "notre",
        "dans", "sur", "par", "qui", "que", "est", "sont", "sera",
        "requis", "requise", "obligatoire", "apprecie", "appreciee",
        "maitrise", "bonne", "bon", "niveau", "minimum", "ans", "mois",
        "stage", "poste", "offre", "entreprise", "equipe", "profil",
        "competences", "competence", "experience", "formation",
        "diplome", "master", "licence", "ecole", "universite",
        # de
        "der", "die", "das", "und", "mit", "fur", "sie", "ihr", "unsere",
        "eine", "einen", "einer", "ist", "sind", "wird", "mindestens",
        "erforderlich", "voraussetzung", "kenntnisse", "erfahrung",
        "studium", "abschluss", "praktikum", "stelle",
        # it
        "il", "lo", "la", "le", "gli", "un", "una", "per", "con", "che",
        "sei", "sono", "richiesto", "richiesta", "competenze", "esperienza",
        "laurea", "stage", "tirocinio", "posto",
        # es
        "el", "la", "los", "las", "un", "una", "para", "con", "que",
        "es", "son", "requerido", "requerida", "competencias", "experiencia",
        "grado", "master", "practicas", "puesto",
    }
)

_STOPWORDS = _STOPWORDS | frozenset({
    "would", "be", "a", "an", "to", "of", "in", "for", "with", "required",
    "advanced", "bonus", "is", "are", "was", "were",
})
_LANGUAGE_TERMS: frozenset[str] = frozenset(
    {
        "english", "french", "german", "spanish", "italian", "mandarin",
        "portuguese", "dutch", "arabic", "chinese", "japanese", "russian",
        "anglais", "francais", "allemand", "espagnol", "italien",
        "portugais", "neerlandais", "arabe", "chinois", "japonais", "russe",
        "englisch", "franzosisch", "spanisch", "italienisch",
        "inglese", "francese", "spagnolo", "tedesco",
        "ingles", "espanol", "aleman", "italiano",
        "fluent", "bilingual", "native", "courant", "bilingue", "maternelle",
        "toeic", "ielts", "toefl", "c1", "c2", "b2", "b1",
    }
)

_TOOL_TERMS: frozenset[str] = frozenset(
    {
        "excel", "vba", "python", "sql", "powerbi", "power bi", "sas",
        "sap", "aws", "api", "java", "javascript", "matlab", "tableau",
        "bloomberg", "factset", "capital iq", "outlook", "office",
        "powerpoint", "word", "r", "stata", "spss", "qlik", "looker",
        "snowflake", "databricks", "git", "docker", "kubernetes", "linux",
        "jira", "confluence", "salesforce", "hubspot", "figma",
        "macros", "pivot", "vlookup",
    }
)

_METHOD_TERMS: frozenset[str] = frozenset(
    {
        "dcf", "lbo", "m&a", "valuation", "modeling", "modelling",
        "forecasting", "budgeting", "reconciliation", "audit",
        "due diligence", "financial modeling", "data analysis",
        "machine learning", "deep learning", "statistics", "regression",
        "agile", "scrum", "kanban", "six sigma", "lean",
        "accounting", "controlling", "reporting", "analysis",
        "structuration", "pricing", "hedging", "risk management",
    }
)

_SOFT_TERMS: frozenset[str] = frozenset(
    {
        "communication", "leadership", "teamwork", "autonomy", "autonomous",
        "rigor", "rigorous", "rigueur", "organization", "organised",
        "organised", "analytical", "analytic", "problem solving",
        "adaptability", "adaptable", "curiosity", "curious", "motivation",
        "motivated", "proactive", "initiative", "collaboration",
        "collaborative", "presentation", "public speaking", "negotiation",
        "time management", "stress management", "detail oriented",
    }
)

_CERT_TERMS: frozenset[str] = frozenset(
    {
        "cfa", "frm", "aca", "acca", "cpa", "cfa level", "aws certified",
        "pmp", "scrum master", "six sigma green belt", "toeic", "ielts",
        "bloomberg market concepts", "bmc",
    }
)

_DOMAIN_TERMS: frozenset[str] = frozenset(
    {
        "finance", "banking", "consulting", "trading", "asset management",
        "private equity", "investment banking", "m&a", "audit", "accounting",
        "data", "analytics", "technology", "engineering", "marketing",
        "operations", "strategy", "research", "quantitative",
    }
)

_SYNONYMS: dict[str, list[str]] = {
    "excel": ["microsoft excel", "advanced excel", "excel avance"],
    "python": ["python3", "py"],
    "sql": ["structured query language"],
    "power bi": ["powerbi"],
    "vba": ["visual basic for applications"],
    "english": ["anglais", "english language"],
    "french": ["francais", "french language"],
    "german": ["allemand", "german language"],
    "spanish": ["espagnol", "spanish language"],
    "italian": ["italien", "italian language"],
}


def _category_for(term: str) -> Category:
    t = term.strip().lower()
    if t in _LANGUAGE_TERMS:
        return "language"
    if t in _TOOL_TERMS:
        return "tool"
    if t in _METHOD_TERMS:
        return "method"
    if t in _SOFT_TERMS:
        return "soft_skill"
    if t in _CERT_TERMS:
        return "certification"
    if t in _DOMAIN_TERMS:
        return "domain"
    # multi-word containment checks
    for lex, cat in (
        (_LANGUAGE_TERMS, "language"),
        (_TOOL_TERMS, "tool"),
        (_METHOD_TERMS, "method"),
        (_SOFT_TERMS, "soft_skill"),
        (_CERT_TERMS, "certification"),
        (_DOMAIN_TERMS, "domain"),
    ):
        for item in lex:
            if item and (item in t or t in item):
                return cat  # type: ignore[return-value]
    return "hard_skill"


def _synonyms_for(term: str) -> list[str]:
    t = term.strip().lower()
    if t in _SYNONYMS:
        return list(_SYNONYMS[t])
    for key, values in _SYNONYMS.items():
        if t in values:
            return [key] + [v for v in values if v != t]
    return []


def _utc_now() -> str:
    try:
        from .models import utc_now as _utc

        return _utc()
    except Exception:
        return datetime.now(timezone.utc).isoformat(timespec="microseconds")


def _as_offer(offer: Any) -> dict[str, Any]:
    if offer is None:
        return {}
    if isinstance(offer, str):
        return {"description_original": offer}
    if not isinstance(offer, dict):
        return {"description_original": clean_text(offer)}
    return dict(offer)


def _sources(offer: dict[str, Any]) -> dict[str, str]:
    fields = [
        "title",
        "company",
        "job_family",
        "requirements",
        "description_original",
        "languages_required",
        "eligibility_requirement",
        "role_level",
        "city",
        "country",
    ]
    out: dict[str, str] = {}
    for field_name in fields:
        value = clean_text(offer.get(field_name), limit=30_000)
        if value:
            out[field_name] = value
    # extractor results may carry text-like fields
    for key in ("extractor_results", "conditions", "missions", "education"):
        value = offer.get(key)
        if isinstance(value, str) and value.strip():
            out[f"extractor_{key}"] = clean_text(value, limit=30_000)
        elif isinstance(value, list):
            joined = " ; ".join(clean_text(item) for item in value if item)
            if joined.strip():
                out[f"extractor_{key}"] = joined
    return out


def _normalize_list_of_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    if isinstance(value, (list, tuple, set)):
        return " ".join(clean_text(item) for item in value)
    if isinstance(value, dict):
        return " ".join(f"{k} {v}" for k, v in value.items())
    return clean_text(value)


def _candidate_terms(sources: dict[str, str]) -> dict[str, set[str]]:
    """Return mapping term -> set of source fields where it appears."""
    combined = " ".join(sources.values())
    norm_combined = normalized_text(combined)
    candidates: dict[str, set[str]] = {}

    def _add(term: str, field_name: str) -> None:
        t = normalized_text(term)
        if not t or len(t) < 3:
            return
        if t in _STOPWORDS:
            return
        candidates.setdefault(t, set()).add(field_name)

    # unigrams
    for field_name, text in sources.items():
        for token in normalized_text(text).split():
            if len(token) >= 3 and token not in _STOPWORDS:
                _add(token, field_name)

    _KNOWN = _LANGUAGE_TERMS | _TOOL_TERMS | _METHOD_TERMS | _SOFT_TERMS | _CERT_TERMS | _DOMAIN_TERMS

    # multi-word phrases: only known lexicon phrases actually present
    for phrase in _KNOWN:
        if " " in phrase and phrase in norm_combined:
            for field_name, text in sources.items():
                if phrase in normalized_text(text):
                    _add(phrase, field_name)
                    break

    # trigrams: only known multi-word phrases already in lexicon, present in text
    for phrase in _KNOWN:
        if phrase.count(" ") >= 2 and phrase in norm_combined:
            for field_name, text in sources.items():
                if phrase in normalized_text(text):
                    _add(phrase, field_name)
                    break


    return candidates


def _count_occurrences(text_norm: str, term_norm: str) -> int:
    if not term_norm:
        return 0
    padded = f" {text_norm} "
    needle = f" {term_norm} "
    count = 0
    start = 0
    while True:
        idx = padded.find(needle, start)
        if idx == -1:
            break
        count += 1
        start = idx + len(needle)
    # also count exact phrase at boundaries already covered; if none, try substring
    if count == 0 and term_norm in text_norm:
        count = text_norm.count(term_norm)
    return max(count, 1 if term_norm in text_norm else 0)


def _web_confirmed(term_norm: str, web_text_norm: str) -> bool:
    if not web_text_norm:
        return False
    return term_norm in web_text_norm


def _arena_boosted(term_norm: str, arena_text_norm: str) -> bool:
    if not arena_text_norm:
        return False
    return term_norm in arena_text_norm


def _extractor_terms(extractor_results: Any) -> list[str]:
    terms: list[str] = []
    if extractor_results is None:
        return terms
    if isinstance(extractor_results, str):
        terms.append(extractor_results)
    elif isinstance(extractor_results, (list, tuple, set)):
        for item in extractor_results:
            if isinstance(item, str):
                terms.append(item)
            elif isinstance(item, dict):
                for key in ("term", "keyword", "skill", "text", "value"):
                    if key in item and item[key]:
                        terms.append(str(item[key]))
            else:
                terms.append(str(item))
    elif isinstance(extractor_results, dict):
        for key, value in extractor_results.items():
            if isinstance(value, (list, tuple, set)):
                for item in value:
                    terms.append(str(item) if not isinstance(item, dict) else str(item.get("term", item.get("text", ""))))
            else:
                terms.append(str(value))
    return [t for t in terms if t.strip()]


def extract_keywords(
    offer: Any = None,
    *,
    text: str | None = None,
    profile: Any = None,
    web_results: Any = None,
    arena_results: Any = None,
    extractor_results: Any = None,
    offer_id: str | None = None,
    web_stack: Any = None,
    jury: Any = None,
) -> KeywordProfile:
    """Extract and weight ATS keywords from an offer.

    ``offer`` may be a dict (Career offer) or a raw text string.  Optional
    ``profile`` (dict or str), ``web_results``, ``arena_results`` and
    ``extractor_results`` enrich the profile.
    """

    if text is not None and offer is None:
        offer = text
    offer_dict = _as_offer(offer)
    if offer_id is not None:
        offer_dict = dict(offer_dict)
        offer_dict["id"] = offer_id
    oid = clean_text(offer_dict.get("id") or offer_dict.get("offer_id") or "", limit=120)

    # merge extractor results into offer dict for source tracking
    if extractor_results is not None:
        offer_dict = dict(offer_dict)
        offer_dict["extractor_results"] = extractor_results

    sources = _sources(offer_dict)
    if not sources and isinstance(offer, str):
        sources = {"description_original": clean_text(offer)}

    # incorporate extractor terms as a virtual source
    ext_terms = _extractor_terms(extractor_results)
    if ext_terms:
        sources = dict(sources)
        sources["extractor_results"] = " ; ".join(ext_terms)

    if web_stack is not None and web_results is None:
        web_results = web_stack
    if jury is not None and arena_results is None:
        arena_results = jury

    web_text = _normalize_list_of_text(web_results)
    arena_text = _normalize_list_of_text(arena_results)
    web_norm = normalized_text(web_text)
    arena_norm = normalized_text(arena_text)

    # candidate terms from offer + extractors
    candidates = _candidate_terms(sources)

    # add extractor terms explicitly (in case they are multi-word not in text)
    for term in ext_terms:
        t = normalized_text(term)
        if t and len(t) >= 3 and t not in _STOPWORDS:
            candidates.setdefault(t, set()).add("extractor_results")

    all_text_norm = normalized_text(" ".join(sources.values()))
    max_freq = 1
    freqs: dict[str, int] = {}
    for term in candidates:
        freqs[term] = _count_occurrences(all_text_norm, term)
    if freqs:
        max_freq = max(max(freqs.values()), 1)

    title_text = sources.get("title", "")
    requirements_text = sources.get("requirements", "")
    title_req_norm = normalized_text(title_text + " " + requirements_text)

    profile_text = ""
    if profile is not None:
        if isinstance(profile, dict):
            profile_text = " ".join(
                clean_text(profile.get(f), limit=20_000)
                for f in ("skills", "experience", "projects", "education", "languages", "notes", "eligibility")
            )
        else:
            profile_text = clean_text(profile, limit=40_000)
    profile_norm = normalized_text(profile_text)

    keywords: list[Keyword] = []
    for term_norm, fields in candidates.items():
        count = freqs.get(term_norm, 0)
        freq_offer = count / max_freq if max_freq else 0.0
        in_title_or_requirements = term_norm in title_req_norm or any(
            term_norm in normalized_text(sources.get(f, "")) for f in ("title", "requirements")
        )
        web_confirm = _web_confirmed(term_norm, web_norm)
        jury_boost = _arena_boosted(term_norm, arena_norm)

        weight = (
            0.5 * freq_offer
            + 0.2 * (1.0 if in_title_or_requirements else 0.0)
            + 0.2 * (1.0 if web_confirm else 0.0)
            + 0.1 * (1.0 if jury_boost else 0.0)
        )
        weight = max(0.0, min(1.0, weight))

        # kind threshold
        if weight >= 0.6 or (freq_offer >= 0.5 and in_title_or_requirements):
            kind: Kind = "must"
        elif weight >= 0.3:
            kind = "nice"
        else:
            kind = "implicit"

        term_display = term_norm  # normalized form used as term (lowercase)
        # try to recover original casing from sources
        # simple: use term_norm (acceptable)
        evidence_refs = [f"offer:{f}" for f in sorted(fields)]
        if web_confirm:
            evidence_refs.append("web:confirmed")
        if jury_boost:
            evidence_refs.append("arena:jury_boost")
        if not evidence_refs:
            evidence_refs = ["offer:combined"]

        kw = Keyword(
            term=term_display,
            normalized=term_norm,
            category=_category_for(term_norm),
            weight=round(weight, 4),
            kind=kind,
            evidence_refs=evidence_refs,
            synonyms=_synonyms_for(term_norm),
        )
        keywords.append(kw)

    # sort by weight desc then term
    keywords.sort(key=lambda k: (-k.weight, k.normalized))

    # coverage vs profile
    score_coverage: dict[str, Any] = {}
    category_totals: dict[str, int] = {}
    category_covered: dict[str, int] = {}
    for kw in keywords:
        category_totals[kw.category] = category_totals.get(kw.category, 0) + 1
        covered = False
        if profile_norm:
            if kw.normalized in profile_norm:
                covered = True
            else:
                for syn in kw.synonyms:
                    if syn and syn in profile_norm:
                        covered = True
                        break
        if covered:
            category_covered[kw.category] = category_covered.get(kw.category, 0) + 1

    all_cats = sorted(set(category_totals) | set(category_covered))
    for cat in all_cats:
        total = category_totals.get(cat, 0)
        covered = category_covered.get(cat, 0)
        score_coverage[cat] = {
            "total": total,
            "covered": covered,
            "missing": total - covered,
            "coverage_pct": round((covered / total * 100) if total else 0.0, 1),
        }
    total_all = len(keywords)
    covered_all = sum(1 for kw in keywords if (kw.normalized in profile_norm) or any(s in profile_norm for s in kw.synonyms))
    score_coverage["overall"] = {
        "total": total_all,
        "covered": covered_all,
        "missing": total_all - covered_all,
        "coverage_pct": round((covered_all / total_all * 100) if total_all else 0.0, 1),
    }

    gaps = [kw for kw in keywords if not (
        (kw.normalized in profile_norm) or any(s in profile_norm for s in kw.synonyms)
    )]

    return KeywordProfile(
        offer_id=oid,
        keywords=keywords,
        score_coverage=score_coverage,
        gaps=gaps,
        generated_at=_utc_now(),
    )


# aliases
def build_keyword_profile(*args: Any, **kwargs: Any) -> KeywordProfile:
    return extract_keywords(*args, **kwargs)


def analyze_keywords(*args: Any, **kwargs: Any) -> KeywordProfile:
    return extract_keywords(*args, **kwargs)


def extract(*args: Any, **kwargs: Any) -> KeywordProfile:
    return extract_keywords(*args, **kwargs)


def extract_keyword_profile(*args: Any, **kwargs: Any) -> KeywordProfile:
    return extract_keywords(*args, **kwargs)


def keywords_from_offer(*args: Any, **kwargs: Any) -> KeywordProfile:
    return extract_keywords(*args, **kwargs)


__all__ = [
    "Keyword",
    "KeywordProfile",
    "Category",
    "Kind",
    "extract_keywords",
    "build_keyword_profile",
    "analyze_keywords",
    "extract",
    "extract_keyword_profile",
    "keywords_from_offer",
]
