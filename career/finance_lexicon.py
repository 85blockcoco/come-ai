"""Versioned local finance lexicon for offer parsing, matching and ATS tailoring.

Everything here is a static, user-editable vocabulary committed in the repo:
no network call, no model call, no hidden scoring.  The lexicon answers three
needs of the finance sector layer (CVBOOST-76 / SPEC-041):

- ``expand(text)`` — detect finance vocabulary in free text (offers, job
  titles, connector payloads) and report what matched and in which family,
  so offer mining and the FAQ module can stay sector-aware.
- ``score_profile(profile_text, role)`` — measure how much of the skill set
  expected for a finance role the user's profile actually shows, for the
  matching module (CVBOOST-21).
- ``keywords_for(role)`` — the canonical terms and synonyms an ATS-tailored
  CV (CVBOOST-54) should contain for that role.

All lookups are accent- and case-insensitive, deterministic and sorted: the
same input always yields the same output.  Data is plain Python literals so
the user can edit it without touching logic.
"""

from __future__ import annotations

import unicodedata
from typing import Any

LEXICON_VERSION = "1.0.0"

#: Kinds of vocabulary stored in the lexicon.
KINDS = ("role", "skill", "certification", "office", "anglicism")

#: Role families used across the finance layer (offers, matching, interviews).
FAMILIES = (
    "m&a",
    "fpa",
    "ecm_dcm",
    "coverage",
    "risk",
    "quant",
    "treasury",
    "audit",
    "lbo_pe",
    "equity_research",
)

# --- Roles -----------------------------------------------------------------
# canonical role -> (family, aliases).  Aliases cover French, English and the
# French anglicisms actually used in job postings.
ROLES: dict[str, tuple[str, tuple[str, ...]]] = {
    "M&A Analyst": (
        "m&a",
        ("m&a analyst", "m&a analyste", "analyste m&a", "m&a", "m&a analyst",
         "fusions acquisitions", "fusions-acquisitions", "fusions et acquisitions",
         "m & a", "ma analyst", "mergers and acquisitions", "merger and acquisition"),
    ),
    "FP&A Analyst": (
        "fpa",
        ("fp&a", "fp&a analyst", "fpa", "fpa analyst", "financial planning",
         "financial planning and analysis", "planning financier", "controleur financier",
         "controle de gestion", "contrôleur financier", "controleur de gestion financier"),
    ),
    "ECM Analyst": (
        "ecm_dcm",
        ("ecm", "ecm analyst", "equity capital markets", "marches actions", "marchés actions",
         "equity capital market"),
    ),
    "DCM Analyst": (
        "ecm_dcm",
        ("dcm", "dcm analyst", "debt capital markets", "marches de taux", "marchés de taux",
         "debt capital market"),
    ),
    "Coverage Banker": (
        "coverage",
        ("coverage", "coverage banker", "couverture", "banque d affaires", "banque d'affaires",
         "ibd coverage", "investment banking coverage", "secteur coverage", "coverage industriels"),
    ),
    "Risk Analyst": (
        "risk",
        ("risk analyst", "analyste risque", "analyste de risque", "risk", "risk management",
         "gestion des risques", "market risk", "risque de marche", "risque de marché",
         "credit risk", "risque de credit", "risque de crédit", "operational risk", "risque operationnel"),
    ),
    "Quant Analyst": (
        "quant",
        ("quant", "quantitative analyst", "quantitatif", "quantitative researcher",
         "chercheur quantitatif", "quantitative developer", "quant dev"),
    ),
    "Treasury Analyst": (
        "treasury",
        ("treasury", "tresorerie", "trésorerie", "treasury analyst", "analyste tresorerie",
         "analyste de trésorerie", "cash management", "gestion de tresorerie"),
    ),
    "Audit Consultant": (
        "audit",
        ("audit", "auditeur", "auditeur financier", "audit financier", "audit conseil",
         "external audit", "audit externe", "commissaire aux comptes", "cac"),
    ),
    "LBO Analyst": (
        "lbo_pe",
        ("lbo", "lbo analyst", "leveraged buyout", "private equity", "capital investissement",
         "pe analyst", "buyout", "fonds d investissement", "fund analyst"),
    ),
    "Private Equity Analyst": (
        "lbo_pe",
        ("private equity analyst", "analyste private equity", "analyste capital investissement",
         "pe investment analyst"),
    ),
    "Equity Research Analyst": (
        "equity_research",
        ("equity research", "recherche actions", "equity analyst", "analyste actions",
         "sell side research", "recherche vendeuse"),
    ),
}

# --- Skills ----------------------------------------------------------------
SKILLS: dict[str, tuple[str, ...]] = {
    "DCF": ("dcf", "discounted cash flow", "actualisation des flux", "valeur actuelle nette",
            "van", "flux de tresorerie actualises", "flux de trésorerie actualisés"),
    "LBO": ("lbo", "leveraged buyout", "buyout", "capital investissement", "effet de levier"),
    "comps": ("comps", "comparables", "trading comps", "multiples", "multiple d ebitda",
              "multiple d'ebitda", "multiples de valorisation", "precedent transactions",
              "transactions comparables"),
    "merger model": ("merger model", "modele de fusion", "modèle de fusion", "accretion",
                     "accretion dilution", "accrétion", "synergies"),
    "Excel/VBA": ("excel", "vba", "macro excel", "tableau croise", "tableau croisé dynamique"),
    "Python": ("python", "pandas", "numpy", "scipy"),
    "SQL": ("sql", "requetes sql", "base de donnees", "base de données"),
    "Bloomberg": ("bloomberg", "bloomberg terminal", "terminal bloomberg"),
    "S&P Capital IQ": ("capital iq", "s&p capital iq", "sp capital iq", "snl", "factset",
                       "refinitiv", " Pitchbook", "pitchbook"),
    "financial modeling": ("modelisation financiere", "modélisation financière",
                           "financial modeling", "modelisation", "business plan",
                           "budget forecast", "forecast", "budgetisation"),
    "IFRS": ("ifrs", "normes ifrs", "gaap", "us gaap"),
    "working capital": ("working capital", "bfr", "besoin en fonds de roulement",
                        "capacite d autofinancement", "cafd", "fonds de roulement"),
    "valuation": ("valuation", "valorisation", "evaluer une entreprise", "evaluation d entreprise"),
    "FX": ("fx", "change", "devises", "forex", "taux de change", "currency"),
    "rates": ("taux", "rates", "courbe des taux", "credit spread", "spread de credit"),
}

# --- Certifications ---------------------------------------------------------
CERTIFICATIONS: dict[str, tuple[str, ...]] = {
    "CFA": ("cfa", "cfa level 1", "cfa level 2", "cfa level 3", "cfa niveau 1", "cfa niveau 2",
            "cfa niveau 3", "chartered financial analyst"),
    "ACCA": ("acca", "association of chartered certified accountants"),
    "CAIA": ("caia", "chartered alternative investment analyst"),
    "PRM": ("prm", "professional risk manager"),
}

# --- Offices (finance hubs) --------------------------------------------------
OFFICES: dict[str, tuple[str, ...]] = {
    "Paris": ("paris", "la defense", "la défense", "paris la defense"),
    "London": ("london", "londres", "the city", "canary wharf"),
    "Frankfurt": ("frankfurt", "francfort"),
    "Luxembourg": ("luxembourg",),
    "New York": ("new york", "nyc", "manhattan", "wall street"),
    "Geneva": ("geneva", "geneve", "genève"),
    "Zurich": ("zurich", "zurick"),
    "Milan": ("milan", "milano"),
    "Madrid": ("madrid",),
    "Amsterdam": ("amsterdam",),
    "Dubai": ("dubai", "dubaï"),
    "Singapore": ("singapore", "singapour"),
    "Hong Kong": ("hong kong", "hongkong"),
}

# --- Anglicisms common in French finance postings ----------------------------
ANGLICISMS: dict[str, tuple[str, ...]] = {
    "sell-side": ("sell side", "sell-side", "cote vendeur"),
    "buy-side": ("buy side", "buy-side", "cote acheteur"),
    "front office": ("front office",),
    "middle office": ("middle office",),
    "back office": ("back office",),
    "deal": ("deal", "deals", "deal flow", "dealflow"),
    "pitch": ("pitch", "pitch book", "pitchbook"),
    "roadshow": ("roadshow",),
    "data room": ("data room", "dataroom", "salle de donnees"),
    "term sheet": ("term sheet", "termsheet", "lettre d intention", "loi"),
    "due diligence": ("due diligence", "diligence raisonnable", "dd"),
    "headcount": ("headcount", "effectif"),
    "underwriting": ("underwriting", "prise ferme"),
    "hedge": ("hedge", "hedging", "couverture de risque"),
}

# Expected skill/certification coverage per role, used by ``score_profile`` and
# ``keywords_for``.  Every entry must reference keys of SKILLS/CERTIFICATIONS
# (enforced by tests).
ROLE_REQUIREMENTS: dict[str, dict[str, tuple[str, ...]]] = {
    "M&A Analyst": {
        "skills": ("DCF", "comps", "merger model", "financial modeling", "Excel/VBA", "valuation"),
        "certifications": ("CFA",),
    },
    "FP&A Analyst": {
        "skills": ("financial modeling", "Excel/VBA", "working capital"),
        "certifications": (),
    },
    "ECM Analyst": {
        "skills": ("valuation", "comps", "Excel/VBA", "financial modeling"),
        "certifications": ("CFA",),
    },
    "DCM Analyst": {
        "skills": ("rates", "valuation", "Excel/VBA", "financial modeling"),
        "certifications": ("CFA",),
    },
    "Coverage Banker": {
        "skills": ("valuation", "comps", "financial modeling", "Excel/VBA"),
        "certifications": (),
    },
    "Risk Analyst": {
        "skills": ("rates", "FX", "Excel/VBA", "Python"),
        "certifications": ("PRM",),
    },
    "Quant Analyst": {
        "skills": ("Python", "SQL", "rates", "FX"),
        "certifications": (),
    },
    "Treasury Analyst": {
        "skills": ("working capital", "Excel/VBA", "FX"),
        "certifications": (),
    },
    "Audit Consultant": {
        "skills": ("IFRS", "working capital", "Excel/VBA"),
        "certifications": ("ACCA",),
    },
    "LBO Analyst": {
        "skills": ("LBO", "valuation", "comps", "financial modeling", "Excel/VBA"),
        "certifications": (),
    },
    "Private Equity Analyst": {
        "skills": ("LBO", "valuation", "comps", "financial modeling"),
        "certifications": (),
    },
    "Equity Research Analyst": {
        "skills": ("comps", "valuation", "financial modeling", "Excel/VBA"),
        "certifications": ("CFA",),
    },
}

_ALIAS_INDEX: dict[str, tuple[str, str, str]] = {}
"""Normalised alias -> (canonical, kind, family), built once at import."""


def _normalize(text: Any) -> str:
    """Lowercase, de-accent and tokenise like :func:`career.models.normalized_text`."""
    value = unicodedata.normalize("NFKD", str(text or "").lower())
    value = "".join(character for character in value if not unicodedata.combining(character))
    cleaned = "".join(character if character.isalnum() else " " for character in value)
    return " ".join(cleaned.split())


def _register(canonical: str, kind: str, family: str, aliases: tuple[str, ...]) -> None:
    for alias in aliases:
        key = _normalize(alias)
        if not key:
            continue
        _ALIAS_INDEX.setdefault(key, (canonical, kind, family))


for _canonical, (_family, _aliases) in ROLES.items():
    _register(_canonical, "role", _family, (_canonical, *_aliases))
for _canonical, _aliases in SKILLS.items():
    _register(_canonical, "skill", "skills", (_canonical, *_aliases))
for _canonical, _aliases in CERTIFICATIONS.items():
    _register(_canonical, "certification", "certifications", (_canonical, *_aliases))
for _canonical, _aliases in OFFICES.items():
    _register(_canonical, "office", "offices", (_canonical, *_aliases))
for _canonical, _aliases in ANGLICISMS.items():
    _register(_canonical, "anglicism", "anglicisms", (_canonical, *_aliases))

# Longest keys first so "cfa level 1" is preferred over a bare "cfa" match.
_SORTED_ALIASES: tuple[tuple[str, str, str, str], ...] = tuple(
    sorted(
        ((key, *entry) for key, entry in _ALIAS_INDEX.items()),
        key=lambda item: (-len(item[0]), item[0]),
    )
)


def _contains(haystack: str, needle: str) -> bool:
    return f" {needle} " in f" {haystack} "


def resolve_role(role: Any) -> str:
    """Canonical role name for free text, or ``''`` when nothing matches.

    Never guesses: an unknown role returns an empty string so callers can
    surface the gap instead of silently scoring against the wrong job.
    """
    key = _normalize(role)
    if not key:
        return ""
    for alias in _sorted_aliases_for("role"):
        if _contains(key, alias):
            return _ALIAS_INDEX[alias][0]
    return ""


def _sorted_aliases_for(kind: str) -> tuple[str, ...]:
    return tuple(key for key, _canonical, entry_kind, _family in _SORTED_ALIASES if entry_kind == kind)


def expand(text: Any) -> dict[str, Any]:
    """Detect finance vocabulary in free text.

    Returns ``{"matches": [...], "familles": [...], "counts": {...}}`` where
    each match records the ``canonical`` term, its ``kind`` (role, skill,
    certification, office, anglicism), the ``family`` and the ``alias`` that
    matched.  Matches are de-duplicated per alias and sorted for stability.
    """
    haystack = _normalize(text)
    if not haystack:
        return {"matches": [], "familles": [], "counts": {kind: 0 for kind in KINDS}}
    seen_aliases: set[str] = set()
    raw_matches: list[dict[str, str]] = []
    for key, canonical, kind, family in _SORTED_ALIASES:
        if key in seen_aliases or not _contains(haystack, key):
            continue
        seen_aliases.add(key)
        raw_matches.append({"canonical": canonical, "kind": kind, "family": family, "alias": key})
    # One entry per concept: the longest matching alias wins, whatever the
    # phrasing of the text ("analyste m&a" and "m&a" are the same match).
    best: dict[tuple[str, str], dict[str, str]] = {}
    for match in raw_matches:
        key = (match["kind"], match["canonical"])
        current = best.get(key)
        if current is None or len(match["alias"]) > len(current["alias"]):
            best[key] = match
    matches = sorted(best.values(), key=lambda match: (match["kind"], match["canonical"], match["alias"]))
    familles = sorted({match["family"] for match in matches})
    counts = {kind: sum(1 for match in matches if match["kind"] == kind) for kind in KINDS}
    return {"matches": matches, "familles": familles, "counts": counts}


def _role_expected_elements(role: str) -> tuple[tuple[str, ...], tuple[str, ...]]:
    canonical = resolve_role(role)
    requirements = ROLE_REQUIREMENTS.get(canonical, {})
    return requirements.get("skills", ()), requirements.get("certifications", ())


def _element_matches(profile: str, canonical: str, aliases: tuple[str, ...]) -> bool:
    return any(_contains(profile, _normalize(alias)) for alias in (canonical, *aliases))


def score_profile(profile_text: Any, role: str) -> dict[str, Any]:
    """Coverage of the expected finance skill set for ``role``.

    Returns ``{"role", "coverage", "present", "missing", "certifications"}``.
    ``coverage`` is a float in ``[0, 1]``: the share of expected skills and
    certifications found in the profile text.  Raises ``LookupError`` when the
    role is unknown — scoring against a guessed job is never acceptable.
    """
    canonical = resolve_role(role)
    if not canonical:
        raise LookupError(f"Rôle finance inconnu : {role!r}")
    haystack = _normalize(profile_text)
    skill_keys, cert_keys = _role_expected_elements(canonical)
    present: list[str] = []
    missing: list[str] = []
    for key in skill_keys:
        found = _element_matches(haystack, key, SKILLS[key])
        (present if found else missing).append(key)
    certifications = {key: _element_matches(haystack, key, CERTIFICATIONS[key]) for key in cert_keys}
    expected = len(skill_keys) + len(cert_keys)
    covered = len(present) + sum(1 for found in certifications.values() if found)
    coverage = covered / expected if expected else 1.0
    return {
        "role": canonical,
        "coverage": round(coverage, 4),
        "present": present,
        "missing": missing,
        "certifications": certifications,
    }


def keywords_for(role: str) -> list[str]:
    """ATS keywords for ``role``: role, family terms, skills and synonyms.

    The list is de-duplicated, title-cased canonically and deterministic, so
    an ATS-tailored CV (CVBOOST-54) can inject it verbatim.
    """
    canonical = resolve_role(role)
    if not canonical:
        raise LookupError(f"Rôle finance inconnu : {role!r}")
    family = ROLES[canonical][0]
    terms: list[str] = []
    for candidate in (canonical, *_ALIAS_SORTED_FAMILY_TERMS(family, canonical)):
        if candidate.lower() not in {term.lower() for term in terms}:
            terms.append(candidate)
    return terms


def _ALIAS_SORTED_FAMILY_TERMS(family: str, canonical: str) -> tuple[str, ...]:
    """Canonical role/skill/certification terms relevant to ``family``."""
    terms: list[str] = [canonical]
    for other, (other_family, _aliases) in ROLES.items():
        if other_family == family and other != canonical:
            terms.append(other)
    skill_keys, cert_keys = _role_expected_elements(canonical)
    for key in (*skill_keys, *cert_keys):
        terms.append(key)
    for alias in ROLES[canonical][1]:
        terms.append(alias)
    return tuple(terms)


__all__ = [
    "ANGLICISMS",
    "CERTIFICATIONS",
    "FAMILIES",
    "KINDS",
    "LEXICON_VERSION",
    "OFFICES",
    "ROLES",
    "ROLE_REQUIREMENTS",
    "SKILLS",
    "expand",
    "keywords_for",
    "resolve_role",
    "score_profile",
]
