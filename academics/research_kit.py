"""Kit de recherche académique (NAGE BALANCE 8H — Worker D).

Plan de recherche avec placeholder (jamais d'invention), formats de citation
deterministes, verification citations/claims, methodes de devoirs en
scaffolding (etapes seulement, jamais la reponse finale) et detection de
paraphrase par n-grammes de 5 mots.  Deterministe, stdlib only.
"""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field
from typing import Any, Iterable

_WORD_RE = re.compile(r"\w+", re.UNICODE)
_SENTENCE_RE = re.compile(r"(?<=[.!?])\s+")
_YEAR_RE = re.compile(r"\b(?:19|20)\d{2}\b")
_PLACEHOLDER_TITLE = "[À COMPLÉTER]"

_STOPWORDS = {
    "les", "des", "une", "que", "pour", "avec", "dans", "sur", "est", "sont",
    "aux", "son", "ses", "par", "plus", "être", "cela", "cette", "donc",
    "leur", "nos", "vos", "mais", "chez", "entre", "vers", "tout", "tous",
}

_VALID_STYLES = ("apa", "mla", "harvard")
_VALID_PROBLEM_TYPES = ("derivative", "integral", "annuity", "npv", "statistics", "equation")

_NGRAM = 5
_MIN_CLAIM_WORDS = 5


# ----------------------------------------------------------------------- utils


def _words(text: str) -> list[str]:
    return [w for w in _WORD_RE.findall((text or "").lower()) if len(w) >= 3]


def _significant(text: str) -> set[str]:
    return {w for w in _words(text) if w not in _STOPWORDS}


# --------------------------------------------------------------------- outline


@dataclass
class SectionDraft:
    index: int
    title: str
    facts: list[str] = field(default_factory=list)
    notes: str = ""
    placeholder: bool = False


@dataclass
class ResearchOutline:
    topic: str
    sections: list[SectionDraft]
    facts_used: list[str]
    missing_facts: list[str]
    checks: list[str] = field(default_factory=list)
    ok: bool = True


def build_outline(
    topic: str,
    sections: Iterable[str],
    facts: list[str] | None = None,
) -> ResearchOutline:
    """Construit un plan de recherche deterministe.

    Regles :
    - un titre de section vide (apres strip) est remplace par un placeholder
      ``[À COMPLÉTER]``  — jamais d'invention de contenu ;
    - chaque fait est attribue a la section partageant le plus de mots
      significatifs (>= 3 lettres) ; egalite -> premiere section du plan ;
    - un fait sans correspondance part dans ``missing_facts``.
    """
    topic_clean = (topic or "").strip()
    checks: list[str] = []
    section_list = list(sections or [])
    fact_list = [f for f in (facts or []) if (f or "").strip()]

    if not topic_clean:
        checks.append("titre de recherche (topic) vide — à compléter")

    sec_words = [_significant((s or "").strip()) for s in section_list]
    assigned: list[list[str]] = [[] for _ in section_list]
    facts_used: list[str] = []
    missing_facts: list[str] = []
    for fact in fact_list:
        f_words = _significant(fact)
        best_i, best_overlap = -1, 0
        for i, sw in enumerate(sec_words):
            overlap = len(f_words & sw)
            if overlap > best_overlap:  # tie -> ordre du plan conservé
                best_i, best_overlap = i, overlap
        if best_i >= 0:
            assigned[best_i].append(fact)
            facts_used.append(fact)
        else:
            missing_facts.append(fact)

    drafts: list[SectionDraft] = []
    for i, raw in enumerate(section_list):
        title = (raw or "").strip()
        placeholder = not title
        if placeholder:
            title = _PLACEHOLDER_TITLE
            checks.append(
                f"section {i + 1} vide — placeholder inséré, aucune invention"
            )
        drafts.append(
            SectionDraft(
                index=i + 1,
                title=title,
                facts=list(assigned[i]),
                notes=(
                    "placeholder : section vide — à compléter avec des faits "
                    "sourcés, aucune invention."
                    if placeholder
                    else ""
                ),
                placeholder=placeholder,
            )
        )

    n = len(drafts)
    checks.append(f"plan ordonné : {n} sections (indices 1 à {n})")
    if fact_list:
        checks.append(
            f"faits attribués : {len(facts_used)}/{len(fact_list)} "
            f"({len(missing_facts)} sans correspondance)"
        )

    ok = bool(topic_clean) and not any(d.placeholder for d in drafts)
    return ResearchOutline(
        topic=topic_clean,
        sections=drafts,
        facts_used=facts_used,
        missing_facts=missing_facts,
        checks=checks,
        ok=ok,
    )


# ------------------------------------------------------------------- citations


def citation_format(
    author: str,
    year: int | str,
    title: str,
    source: str,
    style: str = "apa",
) -> str:
    """Formate une reference bibliographique (styles apa | mla | harvard)."""
    style_norm = (style or "").strip().lower()
    if style_norm not in _VALID_STYLES:
        raise ValueError(
            f"style de citation inconnu: '{style}'. "
            f"styles valides: {', '.join(_VALID_STYLES)}"
        )
    a, t, s = (author or "").strip(), (title or "").strip(), (source or "").strip()
    if style_norm == "apa":
        return f"{a} ({year}). {t}. {s}."
    if style_norm == "mla":
        # évite le point double si l'auteur finit déjà par un point
        a_mla = a[:-1].strip() if a.endswith(".") else a
        return f'{a_mla}. "{t}." {s}, {year}.'
    return f"{a} ({year}) '{t}', {s}."


@dataclass
class CitationCheckInfo:
    unused: list[str]
    uncovered_claims: list[str]


def _citation_key(citation: str) -> tuple[str, str] | None:
    """Extrait (nom, annee) d'une reference : 'Smith, J. (2024). ...'."""
    head = (citation or "").split("(", 1)[0].split(",", 1)[0].strip()
    m = _YEAR_RE.search(citation or "")
    if not head or not m:
        return None
    return head.lower(), m.group(0)


def _in_text_found(sentence_low: str, key: tuple[str, str]) -> bool:
    name, year = key
    return name in sentence_low and year in sentence_low


def citation_check(text: str, citations: Iterable[str]) -> CitationCheckInfo:
    """Verifie citations et claims, de facon simple et deterministe.

    - une citation est « utilisée » si son nom et son année apparaissent
      tous deux dans le texte (marqueur in-text du type (Author, Year)) ;
    - une phrase (>= 5 mots) est un claim : il est « couvert » si une
      citation y est détectée, sinon il part dans ``uncovered_claims``.
    """
    text_low = (text or "").lower()
    keys = [k for k in (_citation_key(c) for c in (citations or [])) if k]

    unused = [
        c
        for c in (citations or [])
        for k in [_citation_key(c)]
        if k is not None
        and not (k[0] in text_low and k[1] in text_low)
    ]

    uncovered: list[str] = []
    for i, sent in enumerate(s for s in _SENTENCE_RE.split(text) if s.strip()):
        s_low = sent.strip().lower()
        if len(_words(s_low)) < _MIN_CLAIM_WORDS:
            continue
        covered = any(_in_text_found(s_low, k) for k in keys)
        if not covered:
            uncovered.append(f"claim {i + 1}: {sent.strip()}")

    return CitationCheckInfo(unused=unused, uncovered_claims=uncovered)


# -------------------------------------------------------------- homework steps


def _derivative_steps() -> list[dict[str, Any]]:
    return [
        {"step": 1, "action": "identifier la fonction f(x) et la variable concernée"},
        {"step": 2, "action": "rappeler les règles de dérivation : puissance, produit, quotient, chaîne"},
        {"step": 3, "action": "dériver terme à terme, une règle à la fois"},
        {"step": 4, "action": "simplifier l'expression obtenue"},
        {"step": 5, "action": "vérifier le domaine et le signe de la dérivée"},
    ]


def _integral_steps() -> list[dict[str, Any]]:
    return [
        {"step": 1, "action": "identifier l'intégrale, la variable et les bornes"},
        {"step": 2, "action": "chercher une primitive : table des primitives, substitution, intégration par parties"},
        {"step": 3, "action": "appliquer la méthode choisie étape par étape"},
        {"step": 4, "action": "évaluer la primitive à la borne inférieure puis à la borne supérieure"},
        {"step": 5, "action": "simplifier et contrôler le signe / l'ordre de grandeur"},
    ]


def _annuity_steps() -> list[dict[str, Any]]:
    return [
        {"step": 1, "action": "identifier : versement périodique, début ou fin de période, taux, nombre de périodes"},
        {"step": 2, "action": "convertir le taux annuel en taux périodique cohérent"},
        {"step": 3, "action": "choisir la formule (valeur actuelle ou valeur future) selon la question"},
        {"step": 4, "action": "substituer les données dans la formule, sans calculer de résultat"},
        {"step": 5, "action": "vérifier la cohérence (n ou taux plus grand ⇒ valeur plus grande)"},
    ]


def _npv_steps() -> list[dict[str, Any]]:
    return [
        {"step": 1, "action": "lister les flux de trésorerie par période (dont l'investissement initial au départ)"},
        {"step": 2, "action": "choisir / justifier le taux d'actualisation"},
        {"step": 3, "action": "actualiser chaque flux avec la même formule (même exposant t)"},
        {"step": 4, "action": "additionner les valeurs actualisées"},
        {"step": 5, "action": "interpréter le signe du résultat et la décision associée"},
    ]


def _statistics_steps() -> list[dict[str, Any]]:
    return [
        {"step": 1, "action": "identifier la série de données et la statistique demandée (moyenne, médiane, écart-type)"},
        {"step": 2, "action": "ordonner les données et compter les observations"},
        {"step": 3, "action": "appliquer la formule étape par étape (somme, division, racine selon le cas)"},
        {"step": 4, "action": "interpréter le résultat : tendance centrale, dispersion, valeurs atypiques"},
        {"step": 5, "action": "contre-vérifier avec un second calcul ou un graphique"},
    ]


def _equation_steps() -> list[dict[str, Any]]:
    return [
        {"step": 1, "action": "identifier le type : linéaire, quadratique, système"},
        {"step": 2, "action": "mettre en forme standard / isoler la variable d'un côté"},
        {"step": 3, "action": "appliquer la méthode adaptée : discriminant, substitution, mêmes opérations des deux côtés"},
        {"step": 4, "action": "résoudre puis vérifier chaque solution dans l'équation d'origine"},
        {"step": 5, "action": "écrire l'ensemble des solutions sous forme claire"},
    ]


_BUILDERS = {
    "derivative": _derivative_steps,
    "integral": _integral_steps,
    "annuity": _annuity_steps,
    "npv": _npv_steps,
    "statistics": _statistics_steps,
    "equation": _equation_steps,
}


def homework_steps(problem_type: str, level: str) -> dict[str, Any]:
    """Donne la METHODE (etapes) pour un type de probleme — jamais la reponse.

    ``level`` est restitue tel quel dans le resultat pour adapter le ton de
    l'aide, mais les étapes restent identiques et deterministes.
    """
    ptype = (problem_type or "").strip().lower()
    if ptype not in _VALID_PROBLEM_TYPES:
        raise ValueError(
            f"type de problème inconnu: '{problem_type}'. "
            f"types valides: {', '.join(_VALID_PROBLEM_TYPES)}"
        )
    steps = _BUILDERS[ptype]()
    return {
        "problem_type": ptype,
        "level": (level or "").strip(),
        "steps": steps,
        "note": (
            "méthode uniquement : la réponse finale est à construire par "
            "l'étudiant, étape par étape."
        ),
    }


# ----------------------------------------------------------------- paraphrase


@dataclass
class ParaphraseCheck:
    ratio: float
    verdict: str
    shared_spans: int


def _tokens(text: str) -> list[str]:
    return _WORD_RE.findall((text or "").lower())


def paraphrase_check(a: str, b: str) -> ParaphraseCheck:
    """Ratio de réutilisation : n-grammes de 5 mots consécutifs communs.

    ratio = mots de ``b`` couverts par une séquence de 5 mots consécutifs
    présente aussi dans ``a`` / nombre total de mots de ``b``  (0..1).
    verdict = "reuse élevée" si ratio > 0.6, "reuse partielle" si > 0.25,
    sinon "faible".
    """
    ta, tb = _tokens(a), _tokens(b)
    if len(tb) < _NGRAM:
        return ParaphraseCheck(ratio=0.0, verdict="faible", shared_spans=0)
    grams_a = {
        tuple(ta[i : i + _NGRAM]) for i in range(len(ta) - _NGRAM + 1)
    }
    covered = [False] * len(tb)
    spans = 0
    for i in range(len(tb) - _NGRAM + 1):
        if tuple(tb[i : i + _NGRAM]) in grams_a:
            spans += 1
            for j in range(i, i + _NGRAM):
                covered[j] = True
    ratio = round(sum(covered) / len(tb), 4)
    if ratio > 0.6:
        verdict = "reuse élevée"
    elif ratio > 0.25:
        verdict = "reuse partielle"
    else:
        verdict = "faible"
    return ParaphraseCheck(ratio=ratio, verdict=verdict, shared_spans=spans)


def to_dict(p: ParaphraseCheck | CitationCheckInfo) -> dict[str, Any]:
    return asdict(p)
