"""Deterministic STAR interview simulator for one Career offer.

The simulator is local-first and explainable.  Questions are derived from the
offer the person explicitly selected (title, company, sector and written
requirements).  Nothing is sent to a provider, no candidate fact is invented,
and the evidence prompts only point to proofs the person must supply.

The STAR worksheet is a self-assessment tool.  Its score describes how
*complete and specific* an answer draft is; it never predicts the outcome of a
real interview.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import json
from pathlib import Path
import re
from typing import Any, Iterable, Literal, Mapping


QuestionKind = Literal["behavior", "technical", "motivation", "company"]
KINDS: tuple[QuestionKind, ...] = ("behavior", "technical", "motivation", "company")
MIN_QUESTIONS = 12
MAX_QUESTIONS = 40
DEFAULT_QUESTION_LIMIT = 16

STAR_PARTS: tuple[str, ...] = ("situation", "task", "action", "result")
_STAR_WEIGHTS: dict[str, float] = {
    "situation": 0.18,
    "task": 0.13,
    "action": 0.27,
    "result": 0.32,
}
_FULL_CREDIT_WORDS = 10
_MAX_FIELD_CHARS = 4_000
_MAX_EVIDENCE_ITEMS = 4

_PART_LABELS: dict[str, dict[str, str]] = {
    "fr": {
        "situation": "Situation",
        "task": "Tâche",
        "action": "Action",
        "result": "Résultat",
    },
    "en": {
        "situation": "Situation",
        "task": "Task",
        "action": "Action",
        "result": "Result",
    },
}

# Canonical keyword -> accepted spellings -> broad domain -> usable in a
# technical question.  The list is closed on purpose: an unknown acronym in an
# offer must never be turned into a made-up question.
_KEYWORD_LIBRARY: tuple[tuple[str, tuple[str, ...], str, bool], ...] = (
    ("Excel", ("excel", "tableur", "spreadsheet", "vba"), "finance", True),
    (
        "modélisation financière",
        (
            "modélisation financière",
            "modelisation financiere",
            "financial modelling",
            "financial modeling",
            "valuation",
            "valorisation",
            "dcf",
            "lbo",
        ),
        "finance",
        True,
    ),
    ("comptabilité", ("comptabilité", "comptabilite", "accounting", "ifrs"), "finance", True),
    ("Bloomberg", ("bloomberg", "terminal bloomberg", "bloomberg terminal"), "finance", True),
    ("M&A", ("m&a", "m a", "fusions acquisitions", "mergers acquisitions"), "finance", False),
    ("private equity", ("private equity", "capital investissement"), "finance", False),
    ("trading", ("trading", "marchés financiers", "marches financiers"), "finance", False),
    ("gestion des risques", ("gestion des risques", "risk management", "risque de marché"), "finance", False),
    ("gestion de portefeuille", ("gestion de portefeuille", "portfolio management"), "finance", False),
    ("Python", ("python",), "data", True),
    ("SQL", ("sql", "requêtes sql", "requetes sql"), "data", True),
    ("Power BI", ("power bi", "powerbi"), "data", True),
    ("Tableau", ("tableau software", "tableau desktop"), "data", True),
    ("analyse de données", ("analyse de données", "analyse de donnees", "data analysis", "analytics"), "data", True),
    ("machine learning", ("machine learning", "apprentissage automatique"), "data", True),
    ("statistiques", ("statistiques", "statistics", "statistical"), "data", True),
    ("pandas", ("pandas", "numpy"), "data", True),
    ("étude de marché", ("étude de marché", "etude de marche", "market research"), "consulting", True),
    ("gestion de projet", ("gestion de projet", "project management", "chef de projet"), "consulting", True),
    ("PowerPoint", ("powerpoint", "power point"), "consulting", True),
    ("communication", ("communication", "communication écrite", "communication orale"), "consulting", False),
    ("travail en équipe", ("travail en équipe", "travail en equipe", "teamwork", "team work"), "consulting", False),
    ("négociation", ("négociation", "negociation", "negotiation"), "consulting", False),
    ("présentation", ("présentation", "presentation", "presenting"), "consulting", False),
    ("leadership", ("leadership", "encadrement"), "consulting", False),
    ("anglais", ("anglais", "english"), "general", False),
    ("français", ("français", "francais", "french"), "general", False),
    ("allemand", ("allemand", "german", "deutsch"), "general", False),
    ("marketing", ("marketing", "growth"), "marketing", False),
    ("supply chain", ("supply chain", "logistique", "operations"), "operations", False),
)

_TECHNICAL_TERMS: frozenset[str] = frozenset(
    keyword for keyword, _aliases, _domain, technical in _KEYWORD_LIBRARY if technical
)
_SOFT_TERMS: frozenset[str] = frozenset(
    keyword for keyword, _aliases, _domain, technical in _KEYWORD_LIBRARY if not technical
)

_SECTOR_LABELS: dict[str, dict[str, str]] = {
    "finance": {"fr": "la finance", "en": "finance"},
    "data": {"fr": "la data et l’analyse", "en": "data and analytics"},
    "consulting": {"fr": "le conseil", "en": "consulting"},
    "marketing": {"fr": "le marketing", "en": "marketing"},
    "operations": {"fr": "les opérations", "en": "operations"},
    "general": {"fr": "le secteur de l’offre", "en": "the offer’s sector"},
}

_EVIDENCE_BASE: dict[str, dict[str, tuple[str, ...]]] = {
    "behavior": {
        "fr": (
            "Un exemple daté (stage, projet, association, emploi)",
            "Ton action personnelle, distincte de celle du groupe",
            "Le résultat observé, si possible chiffré ou vérifiable",
        ),
        "en": (
            "A dated example (internship, project, association, job)",
            "Your own action, distinct from the group’s",
            "The observed result, quantified or verifiable when possible",
        ),
    },
    "technical": {
        "fr": (
            "Une preuve d’usage (livrable, modèle, code, note ou certification)",
            "Le contexte réel et les contraintes de l’exercice",
            "Une limite ou un arbitrage que tu peux expliquer",
        ),
        "en": (
            "Proof of use (deliverable, model, code, memo or certificate)",
            "The real context and the exercise’s constraints",
            "A limitation or trade-off you can explain",
        ),
    },
    "motivation": {
        "fr": (
            "Un élément vérifié sur l’entreprise ou l’offre",
            "Un lien factuel avec ton parcours",
            "Une raison personnelle qui ne dépend pas uniquement de l’employeur",
        ),
        "en": (
            "A verified fact about the company or the offer",
            "A factual link with your background",
            "A personal reason that does not depend only on the employer",
        ),
    },
    "company": {
        "fr": (
            "Une source officielle (site, rapport annuel, offre publiée)",
            "Un fait daté, jamais une rumeur",
            "Une question ouverte à poser à l’équipe",
        ),
        "en": (
            "An official source (website, annual report, published offer)",
            "A dated fact, never a rumour",
            "An open question to ask the team",
        ),
    },
}


@dataclass(frozen=True, slots=True)
class InterviewQuestion:
    """One deterministic practice question for an offer."""

    id: str
    kind: QuestionKind
    question: str
    evidence_needed: list[str]

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "kind": self.kind,
            "question": self.question,
            "evidence_needed": list(self.evidence_needed),
        }


@dataclass
class StarWorksheet:
    """Guided STAR draft; ``completeness`` is recalculated on construction."""

    question_id: str
    situation: str = ""
    task: str = ""
    action: str = ""
    result: str = ""
    evidence_checked: list[str] = field(default_factory=list)
    completeness: float = field(init=False, default=0.0)

    def __post_init__(self) -> None:
        self.question_id = clean_field(self.question_id, limit=200)
        for part in STAR_PARTS:
            setattr(self, part, clean_field(getattr(self, part), limit=_MAX_FIELD_CHARS))
        self.evidence_checked = _dedupe(
            clean_field(item, limit=240) for item in self.evidence_checked if clean_field(item, limit=240)
        )[:20]
        self.completeness = round(
            sum(_part_ratio(getattr(self, part)) for part in STAR_PARTS) / len(STAR_PARTS),
            3,
        )

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {"question_id": self.question_id}
        for part in STAR_PARTS:
            payload[part] = getattr(self, part)
        payload["evidence_checked"] = list(self.evidence_checked)
        payload["completeness"] = self.completeness
        return payload


@dataclass(frozen=True, slots=True)
class _OfferContext:
    title: str
    company: str
    sector: str
    sector_label: str
    keywords: tuple[str, ...]

    def role_label(self, lang: str) -> str:
        return self.title or ("this role" if lang == "en" else "ce poste")


def clean_field(value: Any, *, limit: int = _MAX_FIELD_CHARS) -> str:
    """Bounded text cleaning shared by the module and the REST layer."""

    if value is None:
        return ""
    if not isinstance(value, str):
        value = str(value)
    text = value.replace("\x00", "").strip()
    return text[:limit]


def build_question_set(
    offer: Mapping[str, Any] | None,
    *,
    seed: int = 0,
    limit: int = DEFAULT_QUESTION_LIMIT,
    language: str = "fr",
    count: int | None = None,
) -> list[InterviewQuestion]:
    """Build at least :data:`MIN_QUESTIONS` questions covering the four kinds.

    The same ``offer`` and ``seed`` always produce the same ordered list.  A
    different seed rotates each kind and changes which offer keywords drive the
    technical questions, without ever dropping a kind.
    """

    context = _offer_context(offer)
    lang = _language(language)
    value = _seed_value(seed)
    if count is not None:
        limit = count
    bounded_limit = _limit_value(limit)

    pools = {
        "behavior": _behavior_questions(context, lang),
        "technical": _technical_questions(context, lang, value),
        "motivation": _motivation_questions(context, lang),
        "company": _company_questions(context, lang),
    }
    rotated = {kind: _rotate(pool, value) for kind, pool in pools.items()}

    ordered: list[InterviewQuestion] = []
    depth = 0
    while len(ordered) < bounded_limit:
        added = False
        for kind in KINDS:
            if depth < len(rotated[kind]):
                ordered.append(rotated[kind][depth])
                added = True
                if len(ordered) >= bounded_limit:
                    break
        if not added:
            break
        depth += 1
    return ordered


def build_worksheet(
    question: InterviewQuestion,
    *,
    situation: str = "",
    task: str = "",
    action: str = "",
    result: str = "",
    evidence_checked: Iterable[Any] = (),
) -> StarWorksheet:
    """Create a worksheet bound to one known question."""

    if not isinstance(question, InterviewQuestion):
        raise TypeError("Une fiche STAR doit être liée à une InterviewQuestion.")
    return StarWorksheet(
        question_id=question.id,
        situation=situation,
        task=task,
        action=action,
        result=result,
        evidence_checked=list(evidence_checked),
    )


def evidence_checklist(
    question: InterviewQuestion,
    *,
    checked: Iterable[Any] = (),
) -> list[dict[str, Any]]:
    """Return the question’s evidence prompt with an explicit checked flag."""

    checked_set = {_normalize(item) for item in checked if _normalize(item)}
    return [
        {"label": item, "checked": _normalize(item) in checked_set}
        for item in question.evidence_needed
    ]


def self_score(
    worksheet: StarWorksheet,
    *,
    question: InterviewQuestion | None = None,
    language: str = "fr",
) -> dict[str, Any]:
    """Score the *structure* of a STAR draft from 0 to 100.

    Formula (documented so the result is never opaque):

    * each part earns ``weight × ratio`` where ``ratio`` grows linearly from 0
      to 1 over ten words (weights: situation 18, task 13, action 27,
      result 32 — 90 points maximum);
    * a quantified result adds 6 points and a clearly personal action adds 4;
    * the total is capped at 100.

    ``question`` only enables the evidence-coverage part; passing ``None``
    scores the texts alone.
    """

    lang = _language(language)
    parts: dict[str, dict[str, Any]] = {}
    score = 0.0
    for part in STAR_PARTS:
        ratio = _part_ratio(getattr(worksheet, part))
        points = round(100 * _STAR_WEIGHTS[part] * ratio)
        score += points
        parts[part] = {
            "label": _PART_LABELS[lang][part],
            "words": _word_count(getattr(worksheet, part)),
            "ratio": round(ratio, 3),
            "points": points,
            "max_points": round(100 * _STAR_WEIGHTS[part]),
        }

    quantified_result = bool(re.search(r"\d", worksheet.result))
    personal_action = _has_personal_action(worksheet.action, lang)
    if quantified_result:
        score += 6
    if personal_action:
        score += 4
    bounded_score = max(0, min(100, round(score)))

    advice: list[str] = []
    for part in STAR_PARTS:
        if parts[part]["ratio"] < 0.5:
            advice.append(_short_part_advice(part, lang))
    if worksheet.result and not quantified_result:
        advice.append(
            "Ajoute un résultat chiffré ou un changement observable pour rendre la réponse vérifiable."
            if lang == "fr"
            else "Add a quantified result or an observable change so the answer can be verified."
        )
    if worksheet.action and not personal_action:
        advice.append(
            "Distingue clairement ce que tu as fait personnellement de ce que l’équipe a fait."
            if lang == "fr"
            else "Clearly separate what you personally did from what the team did."
        )

    evidence_checked = list(worksheet.evidence_checked)
    evidence_missing: list[str] = []
    evidence_coverage: float | None = None
    checklist: list[dict[str, Any]] = []
    if question is not None:
        checklist = evidence_checklist(question, checked=evidence_checked)
        evidence_missing = [item["label"] for item in checklist if not item["checked"]]
        evidence_coverage = (
            round((len(checklist) - len(evidence_missing)) / len(checklist), 3) if checklist else 1.0
        )
        if evidence_missing:
            advice.append(
                "Preuves encore manquantes : " + " ; ".join(evidence_missing)
                if lang == "fr"
                else "Missing evidence: " + "; ".join(evidence_missing)
            )

    return {
        "score": bounded_score,
        "label": _score_label(bounded_score, lang),
        "completeness": worksheet.completeness,
        "parts": parts,
        "quality_flags": {
            "quantified_result": quantified_result,
            "personal_action": personal_action,
        },
        "evidence_checked": evidence_checked,
        "evidence_missing": evidence_missing,
        "evidence_coverage": evidence_coverage,
        "advice": advice,
        "disclaimer": (
            "Auto-évaluation locale de la structure STAR ; elle ne prédit pas la qualité perçue par un recruteur."
            if lang == "fr"
            else "Local self-assessment of the STAR structure; it does not predict how a recruiter will perceive the answer."
        ),
    }


# ---------------------------------------------------------------------------
# Offer analysis
# ---------------------------------------------------------------------------


def _text(value: Any, *, limit: int = 20_000, depth: int = 0) -> str:
    """Turn bounded offer values into text without stringifying mappings."""

    if depth > 3 or value is None:
        return ""
    if isinstance(value, str):
        return clean_field(value, limit=limit)
    if isinstance(value, (int, float)):
        return str(value)
    if isinstance(value, (list, tuple, set)):
        return clean_field(" ".join(_text(item, limit=limit, depth=depth + 1) for item in value), limit=limit)
    return ""


def _offer_context(offer: Mapping[str, Any] | None) -> _OfferContext:
    values: Mapping[str, Any] = offer if isinstance(offer, Mapping) else {}
    title = _text(values.get("title") or values.get("role") or values.get("job_title"), limit=300)
    company = _text(values.get("company") or values.get("employer"), limit=240)
    raw_sector = _text(
        values.get("sector") or values.get("industry") or values.get("job_family") or values.get("domain"),
        limit=160,
    )
    haystack = " ".join(
        (
            title,
            raw_sector,
            _text(values.get("requirements"), limit=12_000),
            _text(values.get("description_original") or values.get("description"), limit=30_000),
            _text(values.get("skills") or values.get("competencies") or values.get("keywords"), limit=4_000),
            _text(values.get("city"), limit=160),
            _text(values.get("country"), limit=120),
        )
    )
    keywords = _keywords(haystack)
    domain = _domain(haystack, keywords)
    sector_label = raw_sector or _SECTOR_LABELS[domain]["fr"]
    return _OfferContext(
        title=title,
        company=company,
        sector=domain,
        sector_label=sector_label,
        keywords=tuple(keywords),
    )


def _keywords(text: str) -> list[str]:
    padded = f" {_normalize(text)} "
    found: list[str] = []
    for keyword, aliases, _domain_name, _technical in _KEYWORD_LIBRARY:
        if any(f" {_normalize(alias)} " in padded for alias in aliases):
            found.append(keyword)
    return found


def _domain(text: str, keywords: list[str]) -> str:
    counts: dict[str, int] = {}
    for keyword in keywords:
        for canonical, _aliases, domain, _technical in _KEYWORD_LIBRARY:
            if canonical == keyword:
                counts[domain] = counts.get(domain, 0) + 1
                break
    normalized = _normalize(text)
    for domain, markers in (
        ("finance", ("finance", "banque", "banking", "investissement", "investment")),
        ("data", ("data", "données", "donnees", "analytics", "informatique")),
        ("consulting", ("conseil", "consulting", "strategy", "stratégie", "strategie")),
        ("marketing", ("marketing", "growth", "communication")),
        ("operations", ("supply chain", "logistique", "operations", "opérations", "industriel")),
    ):
        if any(f" {marker} " in f" {normalized} " for marker in markers):
            counts[domain] = counts.get(domain, 0) + 1
    if not counts:
        return "general"
    return max(sorted(counts), key=lambda name: counts[name])


# ---------------------------------------------------------------------------
# Question pools
# ---------------------------------------------------------------------------


def _behavior_questions(context: _OfferContext, lang: str) -> list[InterviewQuestion]:
    soft = _first_soft(context.keywords)
    if lang == "en":
        questions = [
            (
                "behavior:deadline",
                "Tell me about a time you had to deliver important work under time pressure. What was the situation, your task, what you did, and the result?",
            ),
            (
                "behavior:mistake",
                "Describe a mistake or disagreement in a project. How did you handle it, and what did you change afterwards?",
            ),
            (
                "behavior:learning",
                "Give an example of a skill you had to learn quickly for a project. How did you learn it and prove that it worked?",
            ),
            (
                "behavior:alignment",
                "Tell me about a time you had to align several people with different priorities. What did you do and what happened?",
            ),
        ]
    else:
        questions = [
            (
                "behavior:deadline",
                "Raconte une situation où tu as dû livrer un travail important sous contrainte de temps. Quelle était la situation, ta tâche, ton action et le résultat ?",
            ),
            (
                "behavior:mistake",
                "Décris une erreur ou un désaccord dans un projet. Comment l’as-tu géré et qu’as-tu changé ensuite ?",
            ),
            (
                "behavior:learning",
                "Donne un exemple d’une compétence que tu as dû apprendre rapidement pour un projet. Comment l’as-tu apprise et prouvée ?",
            ),
            (
                "behavior:alignment",
                "Raconte une situation où tu as dû aligner plusieurs personnes aux priorités différentes. Qu’as-tu fait et qu’en est-il résulté ?",
            ),
        ]
    result: list[InterviewQuestion] = []
    for identifier, text in questions:
        if soft and identifier == "behavior:learning":
            text = (
                f"Donne un exemple où « {soft} » a été déterminant dans un projet. "
                "Décris la situation, ta tâche, ton action personnelle et le résultat vérifiable."
                if lang == "fr"
                else f"Give an example where “{soft}” was decisive in a project. "
                "Describe the situation, your task, your own action and the verifiable result."
            )
        result.append(
            InterviewQuestion(
                id=identifier,
                kind="behavior",
                question=text,
                evidence_needed=_evidence(
                    "behavior", lang, keyword=soft if identifier == "behavior:learning" else None
                ),
            )
        )
    return result


def _technical_questions(context: _OfferContext, lang: str, seed: int) -> list[InterviewQuestion]:
    technical = [keyword for keyword in context.keywords if keyword in _TECHNICAL_TERMS]
    selected: list[str] = []
    if technical:
        offset = seed % len(technical)
        rotated = technical[offset:] + technical[:offset]
        selected = rotated[:4]

    questions: list[InterviewQuestion] = []
    for index, keyword in enumerate(selected):
        slug = _slug(keyword)
        evidence = _evidence("technical", lang, keyword=keyword)
        if index % 2 == 0:
            text = (
                f"How have you actually used “{keyword}” in a project or internship? "
                "Describe the context, your own action, and a result that can be checked."
                if lang == "en"
                else f"Comment as-tu utilisé « {keyword} » concrètement dans un projet ou un stage ? "
                "Décris le contexte, ton action personnelle et un résultat vérifiable."
            )
            identifier = f"technical:keyword:{slug}:practice"
        else:
            text = (
                f"A recruiter asks you to explain “{keyword}” to a non-specialist. "
                "How do you proceed, and what proof of your command of it can you cite?"
                if lang == "en"
                else f"Un recruteur te demande d’expliquer « {keyword} » à une personne non spécialiste. "
                "Comment procèdes-tu, et quelle preuve de ta maîtrise peux-tu citer ?"
            )
            identifier = f"technical:keyword:{slug}:explain"
        questions.append(InterviewQuestion(identifier, "technical", text, evidence))

    questions.append(_sector_technical_question(context, lang))
    questions.extend(_generic_technical_questions(lang))
    return questions


def _sector_technical_question(context: _OfferContext, lang: str) -> InterviewQuestion:
    if lang == "en":
        prompts = {
            "finance": "How would you assess a company’s financial health in three steps? State the inputs, the calculation and the limitation.",
            "data": "How would you check the quality of a dataset before analysing it? Name the checks and what you would reject.",
            "consulting": "How would you structure a recommendation into three key messages for a client?",
            "marketing": "How would you measure whether a marketing campaign actually worked?",
            "operations": "How would you find and prioritise a bottleneck in an operational process?",
            "general": "How do you approach a problem you have never encountered before?",
        }
    else:
        prompts = {
            "finance": "Comment évaluerais-tu la santé financière d’une entreprise en trois étapes ? Précise les données, le calcul et la limite de ton analyse.",
            "data": "Comment vérifierais-tu la qualité d’un jeu de données avant de l’analyser ? Cite les contrôles et ce que tu refuserais d’utiliser.",
            "consulting": "Comment structurerais-tu une recommandation en trois messages clés pour un client ?",
            "marketing": "Comment mesurerais-tu si une campagne marketing a réellement fonctionné ?",
            "operations": "Comment identifierais-tu et prioriserais-tu un goulot d’étranglement dans un processus opérationnel ?",
            "general": "Comment abordes-tu un problème que tu n’as jamais rencontré auparavant ?",
        }
    return InterviewQuestion(
        id=f"technical:sector:{context.sector}",
        kind="technical",
        question=prompts[context.sector],
        evidence_needed=_evidence("technical", lang),
    )


def _generic_technical_questions(lang: str) -> list[InterviewQuestion]:
    if lang == "en":
        return [
            InterviewQuestion(
                "technical:quality-check",
                "technical",
                "How do you verify your own work before handing it over? Give a concrete control you always run.",
                _evidence("technical", lang),
            ),
            InterviewQuestion(
                "technical:trade-off",
                "technical",
                "Describe a technical trade-off you had to make. What did you give up, and why was that acceptable?",
                _evidence("technical", lang),
            ),
            InterviewQuestion(
                "technical:learning-plan",
                "technical",
                "For a skill required by this offer that you do not fully master yet, what is your concrete learning plan?",
                _evidence("technical", lang),
            ),
        ]
    return [
        InterviewQuestion(
            "technical:quality-check",
            "technical",
            "Comment vérifies-tu ton propre travail avant de le rendre ? Donne un contrôle concret que tu appliques systématiquement.",
            _evidence("technical", lang),
        ),
        InterviewQuestion(
            "technical:trade-off",
            "technical",
            "Décris un arbitrage technique que tu as dû faire. Qu’as-tu abandonné, et pourquoi était-ce acceptable ?",
            _evidence("technical", lang),
        ),
        InterviewQuestion(
            "technical:learning-plan",
            "technical",
            "Pour une compétence demandée par cette offre que tu ne maîtrises pas encore, quel est ton plan d’apprentissage concret ?",
            _evidence("technical", lang),
        ),
    ]


def _motivation_questions(context: _OfferContext, lang: str) -> list[InterviewQuestion]:
    company = context.company or ("cette entreprise" if lang == "fr" else "this company")
    role = context.role_label(lang)
    if lang == "en":
        texts = [
            (
                "motivation:company-choice",
                f"Why this role at {company} rather than a similar role elsewhere?",
            ),
            (
                "motivation:field",
                f"What genuinely motivates you in {context.sector_label}, and what evidence shows it?",
            ),
            (
                "motivation:growth",
                f"Where do you want to progress in the next twelve months, and how would {role} contribute to it?",
            ),
        ]
    else:
        texts = [
            (
                "motivation:company-choice",
                f"Pourquoi ce poste chez {company} plutôt qu’un poste similaire ailleurs ?",
            ),
            (
                "motivation:field",
                f"Qu’est-ce qui te motive réellement dans {context.sector_label}, et quelle preuve peux-tu en donner ?",
            ),
            (
                "motivation:growth",
                f"Dans quel domaine veux-tu progresser dans les douze prochains mois, et en quoi {role} y contribue-t-il ?",
            ),
        ]
    return [InterviewQuestion(identifier, "motivation", text, _evidence("motivation", lang)) for identifier, text in texts]


def _company_questions(context: _OfferContext, lang: str) -> list[InterviewQuestion]:
    company = context.company or ("cette entreprise" if lang == "fr" else "this company")
    role = context.role_label(lang)
    if lang == "en":
        texts = [
            (
                "company:positioning",
                f"What do you know about {company} and its position in its market? Cite one verified fact, not an impression.",
            ),
            (
                "company:value",
                f"Based on the offer, how does {role} create value for {company}?",
            ),
            (
                "company:priorities",
                f"What risks or priorities do you see for {company} in {context.sector_label}, and what would you ask the team?",
            ),
        ]
    else:
        texts = [
            (
                "company:positioning",
                f"Que sais-tu de {company} et de son positionnement sur son marché ? Cite un fait vérifié, pas une impression.",
            ),
            (
                "company:value",
                f"D’après l’offre, comment {role} crée-t-il de la valeur pour {company} ?",
            ),
            (
                "company:priorities",
                f"Quels risques ou priorités identifies-tu pour {company} dans {context.sector_label}, et quelle question poserais-tu à l’équipe ?",
            ),
        ]
    return [InterviewQuestion(identifier, "company", text, _evidence("company", lang)) for identifier, text in texts]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _evidence(kind: QuestionKind, lang: str, *, keyword: str | None = None) -> list[str]:
    base = list(_EVIDENCE_BASE[kind][lang])
    if not keyword:
        return _dedupe(base)[:_MAX_EVIDENCE_ITEMS]
    keyword_item = (
        f"Une preuve d’usage de « {keyword} » (projet, stage, certification ou livrable)"
        if lang == "fr"
        else f"Proof that you used “{keyword}” (project, internship, certificate or deliverable)"
    )
    # The keyword proof replaces the generic proof-of-use prompt instead of
    # stacking two nearly identical checklist lines.
    if kind == "technical":
        base = base[1:]
    return _dedupe([keyword_item, *base])[:_MAX_EVIDENCE_ITEMS]


def _first_soft(keywords: tuple[str, ...]) -> str | None:
    for keyword in keywords:
        if keyword in _SOFT_TERMS:
            return keyword
    return None


def _part_ratio(text: str) -> float:
    words = _word_count(text)
    if not words:
        return 0.0
    return min(1.0, words / _FULL_CREDIT_WORDS)


def _word_count(text: str) -> int:
    return len(re.findall(r"[0-9A-Za-zÀ-ÖØ-öø-ÿ]+", text))


def _has_personal_action(action: str, lang: str) -> bool:
    padded = f" {_normalize(action)} "
    markers = (" j ai ", " je ", " moi ") if lang == "fr" else (" i ", " my ", " me ")
    return any(marker in padded for marker in markers)


def _short_part_advice(part: str, lang: str) -> str:
    if lang == "en":
        return f"Develop the {_PART_LABELS['en'][part].lower()} with a concrete, verifiable detail (about ten words minimum)."
    return (
        f"Développe la partie {_PART_LABELS['fr'][part].lower()} avec un détail concret et vérifiable "
        "(une dizaine de mots minimum)."
    )


def _score_label(score: int, lang: str) -> str:
    if lang == "en":
        if score >= 80:
            return "Solid structure"
        if score >= 50:
            return "Partial structure — strengthen it"
        return "To complete"
    if score >= 80:
        return "Structure solide"
    if score >= 50:
        return "Structure partielle — à renforcer"
    return "À compléter"


def _language(value: Any) -> str:
    text = clean_field(value, limit=16).casefold()
    return "en" if text.startswith("en") else "fr"


def _seed_value(value: Any) -> int:
    try:
        number = int(value)
    except (TypeError, ValueError):
        return 0
    return abs(number) % 1_000_003


def _limit_value(value: Any) -> int:
    try:
        number = int(value)
    except (TypeError, ValueError):
        number = DEFAULT_QUESTION_LIMIT
    return max(MIN_QUESTIONS, min(MAX_QUESTIONS, number))


def _rotate(items: Iterable[InterviewQuestion], seed: int) -> list[InterviewQuestion]:
    ordered = list(items)
    if not ordered:
        return ordered
    offset = seed % len(ordered)
    return ordered[offset:] + ordered[:offset]


def _normalize(value: Any) -> str:
    text = clean_field(value, limit=4_000).casefold()
    text = re.sub(r"[\u0300-\u036f]", "", text)
    return re.sub(r"[^a-z0-9]+", " ", text).strip()


def _slug(value: str) -> str:
    return _normalize(value).replace(" ", "-") or "general"


def _dedupe(items: Iterable[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for item in items:
        if item and item not in seen:
            seen.add(item)
            result.append(item)
    return result


# ---------------------------------------------------------------------------
# Compatibility helpers
# ---------------------------------------------------------------------------

_FIXTURES_FILE = (
    Path(__file__).resolve().parents[1] / "tests" / "fixtures" / "interview_offers_synthetic.json"
)


def load_fixtures() -> list[dict[str, Any]]:
    """Load the bundled synthetic offers (never real candidate data)."""

    with _FIXTURES_FILE.open("r", encoding="utf-8") as handle:
        payload = json.load(handle)
    if isinstance(payload, dict):
        payload = payload.get("offers", [])
    if not isinstance(payload, list):
        raise ValueError("interview fixture must be a list of offers")
    return [item for item in payload if isinstance(item, dict)]


def build_questions(*args: Any, **kwargs: Any) -> list[InterviewQuestion]:
    """Alias kept for callers that used the earlier helper name."""

    return build_question_set(*args, **kwargs)


def generate_question_set(*args: Any, **kwargs: Any) -> list[InterviewQuestion]:
    """Alias kept for callers that used the earlier helper name."""

    return build_question_set(*args, **kwargs)


def get_question_set(*args: Any, **kwargs: Any) -> list[InterviewQuestion]:
    """Alias kept for callers that used the earlier helper name."""

    return build_question_set(*args, **kwargs)


def load_interview_fixtures() -> list[dict[str, Any]]:
    """Alias kept for callers that used the earlier helper name."""

    return load_fixtures()


__all__ = [
    "DEFAULT_QUESTION_LIMIT",
    "InterviewQuestion",
    "KINDS",
    "MAX_QUESTIONS",
    "MIN_QUESTIONS",
    "STAR_PARTS",
    "StarWorksheet",
    "build_question_set",
    "build_questions",
    "build_worksheet",
    "clean_field",
    "evidence_checklist",
    "generate_question_set",
    "get_question_set",
    "load_fixtures",
    "load_interview_fixtures",
    "self_score",
]
