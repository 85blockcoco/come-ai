"""Targeted interview preparation built from one stored offer and one profile.

SPEC-010 turns facts the local Career workspace already holds — the
requirements a posting states and the profile the person entered — into a
preparation that is specific to that offer: technical and behavioural
questions, questions on the gaps between the offer and the profile, recruiter
questions, a company factsheet limited to what the offer actually says, and a
timed simulation loop with structured, deterministic feedback.

The module is local-first and deterministic: no model, no network, no clock in
the scoring and no invented fact.  A company fact the offer does not state
stays unknown, a profile skill that is not written down is never used as
evidence, and the feedback describes the answer against the exercise only — it
is never a prediction of a hiring outcome.

Every correction quotes the pedagogical source it comes from.  The finance
banks cite the standard finance references (Rosenbaum & Pearl, Damodaran,
Hull, Horngren, Kaplan & Atkinson, Hilton, Mosteller); the standard mode cites
the behavioural-interview method it applies.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field as dataclass_field
from typing import Any, Callable, Iterable, Literal, Mapping, Sequence

from .application_prep import prepare_application
from .models import clean_text, normalized_text
from .offer_requirements import analyze_offer
from workspace_core import UserFacingError


QuestionCategory = Literal["technical", "behavioral", "gap", "recruiter"]
Difficulty = Literal["easy", "medium", "hard"]
FeedbackScore = Literal["excellent", "good", "needs_improvement", "insufficient"]

MODES: tuple[str, ...] = ("standard", "finance")
CATEGORIES: tuple[str, ...] = ("technical", "behavioral", "gap", "recruiter")

MAX_TECHNICAL_QUESTIONS = 8
MAX_BEHAVIORAL_QUESTIONS = 6
MAX_GAP_QUESTIONS = 6
MAX_RECRUITER_QUESTIONS = 8
MAX_SENSITIVE_POINTS = 8
MAX_ANSWER_CHARS = 6_000

# The local Career workspace holds a single candidate profile.  ``user_profile``
# is the documented identifier for it; the empty value means the same record.
LOCAL_PROFILE_IDS: frozenset[str] = frozenset({"", "user_profile", "local", "profil_local"})

# Words that prove nothing on their own.  A requirement matching only on
# "experience" would create a false sense of correspondence.
_GENERIC_TOKENS: frozenset[str] = frozenset(
    {
        "and",
        "are",
        "avec",
        "bien",
        "cette",
        "comme",
        "comment",
        "dans",
        "dans",
        "des",
        "dont",
        "elle",
        "entre",
        "est",
        "etre",
        "from",
        "have",
        "into",
        "just",
        "les",
        "leur",
        "like",
        "mais",
        "more",
        "not",
        "nous",
        "onto",
        "our",
        "pour",
        "pourquoi",
        "que",
        "quel",
        "qui",
        "sans",
        "ses",
        "son",
        "sont",
        "sous",
        "sur",
        "the",
        "this",
        "tous",
        "tout",
        "une",
        "vous",
        "with",
        "your",
    }
)

# Structure markers used to read the shape of an answer.  The list is
# bilingual on purpose: a French candidate answering a French offer must not
# be penalised for not using English transition words.
_STRUCTURE_MARKERS: tuple[str, ...] = (
    "d abord",
    "premier",
    "premiere",
    "ensuite",
    "puis",
    "enfin",
    "parce que",
    "donc",
    "ainsi",
    "toutefois",
    "neanmoins",
    "first",
    "second",
    "then",
    "finally",
    "because",
    "therefore",
    "however",
    "as a result",
)

# Claims a candidate commonly makes without a local proof.  They are detected
# as sentences, then checked against the profile; an unsupported claim is
# reported, never rewritten.
_CLAIM_PATTERNS: tuple[str, ...] = (
    r"\bj[' ]ai\s+(?:dirig[ée]|gér[ée]|pilot[ée]|conduit|men[ée]|d[ée]ploy[ée])\b",
    r"\bj[' ]ai\s+(?:augment[ée]|r[ée]duit|am[ée]lior[ée]|divis[ée]|optimis[ée])\b",
    r"\bj[' ]ai\s+lead\b",
    r"\bfort(?:e)?\s+exp[ée]rience\b",
    r"\b(?:expert|experte|sp[ée]cialiste|ma[îi]trise|masterise)\s+(?:en|de|du)\b",
    r"\bplus\s+de\s+\d+\s+ans\b",
    r"\b\d+\s*%\s*(?:de\s+)?(?:croissance|rentabilit[ée]|marge|performance|reduction|reduction)\b",
)

_LEVEL_MARKERS: tuple[str, ...] = ("a1", "a2", "b1", "b2", "c1", "c2", "niveau", "avance", "courant", "intermediaire")

_CULTURE_VOCABULARY: tuple[str, ...] = (
    "autonomie",
    "équipe",
    "équipes",
    "international",
    "innovation",
    "formation",
    "mentorat",
    "tutorat",
    "client",
    "clients",
    "data",
    "digitale",
    "responsabilité",
    "startup",
    "scale-up",
    "stage",
    "apprentissage",
    "engagement",
    "collaboration",
    "agilité",
    "sustainability",
    "impact",
)

# The pedagogical reference of the behavioural method applied in standard mode.
BEHAVIORAL_SOURCE = (
    "Kim, *The Manager's Book of Questions: The 100 Best Questions to Ask the Interviewer* "
    "(méthode STAR : Situation, Tâche, Action, Résultat)"
)


@dataclass(frozen=True)
class InterviewQuestion:
    """One prepared question with the points a strong answer must cover."""

    id: str
    category: QuestionCategory
    question: str
    expected_elements: list[str]
    related_evidence: list[str] | None
    related_requirement: str | None
    difficulty: Difficulty
    time_estimate_seconds: int


@dataclass(frozen=True)
class CompanyFactsheet:
    """What the offer itself says about the company — never more."""

    name: str
    sector: str
    size: str
    recent_news: list[str]
    culture_keywords: list[str]
    interview_process: list[str] | None
    sources: list[str]


@dataclass
class InterviewPrepSession:
    """A preparation session built for one offer and one candidate profile."""

    session_id: str
    offer_id: int
    profile_id: str
    technical_questions: list[InterviewQuestion]
    behavioral_questions: list[InterviewQuestion]
    gap_questions: list[InterviewQuestion]
    sensitive_points: list[str]
    recruiter_questions: list[str]
    company_factsheet: CompanyFactsheet
    created_at: str


@dataclass(frozen=True)
class SimulationFeedback:
    """The deterministic reading of one rehearsal answer."""

    question_id: str
    user_answer: str
    score: FeedbackScore
    strengths: list[str]
    missing_elements: list[str]
    unproven_claims: list[str]
    suggested_structure: str
    retry_prompt: str
    pedagogical_source: str | None


@dataclass(frozen=True)
class PrepQuestion:
    """Internal record: the public question plus its deterministic match keys."""

    question: InterviewQuestion
    keyword_groups: tuple[tuple[str, ...], ...] = ()
    pedagogical_source: str | None = None
    suggested_structure: str = ""
    evidence_quotes: tuple[str, ...] = ()
    bank: str = ""


@dataclass
class Preparation:
    """A session plus the internal records the simulation needs."""

    session: InterviewPrepSession
    questions: dict[str, PrepQuestion] = dataclass_field(default_factory=dict)
    offer: dict[str, Any] = dataclass_field(default_factory=dict)
    mode: str = "standard"

    def to_payload(self) -> dict[str, Any]:
        return {
            "session": serialize_session(self.session),
            "questions": {
                identifier: _serialize_prep_question(record) for identifier, record in self.questions.items()
            },
            "offer": dict(self.offer),
            "mode": self.mode,
        }

    @classmethod
    def from_payload(cls, payload: Mapping[str, Any]) -> "Preparation":
        session = _session_from_payload(payload.get("session") or {})
        records = {
            identifier: _prep_question_from_payload(record)
            for identifier, record in (payload.get("questions") or {}).items()
        }
        return cls(
            session=session,
            questions=records,
            offer=dict(payload.get("offer") or {}),
            mode=clean_text(payload.get("mode"), limit=40) or "standard",
        )


@dataclass(frozen=True)
class PrepContext:
    """Read-only access to the two local inputs a preparation needs."""

    load_offer: Callable[[str], dict[str, Any]]
    load_profile: Callable[[str], dict[str, Any]]


_DEFAULT_CONTEXT: PrepContext | None = None


def bind_default_context(context: PrepContext | None) -> None:
    """Bind the local resolver used when no explicit context is supplied.

    The web layer binds the running service here so that
    ``generate(offer_id, profile_id, mode)`` resolves the local records on its
    own.  Tests may pass an explicit context instead.
    """
    global _DEFAULT_CONTEXT
    _DEFAULT_CONTEXT = context


def default_context() -> PrepContext | None:
    return _DEFAULT_CONTEXT


# ---------------------------------------------------------------------------
# Question banks
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class _BankQuestion:
    identifier: str
    bank: str
    question: str
    expected_elements: tuple[str, ...]
    difficulty: Difficulty
    time_estimate_seconds: int
    source: str
    keywords: tuple[str, ...] = ()


FINANCE_BANKS: dict[str, tuple[_BankQuestion, ...]] = {
    "m_and_a": (
        _BankQuestion(
            "ma_process",
            "m_and_a",
            "Décris le processus d'une cession d'entreprise, du travail préparatoire jusqu'à la closing.",
            (
                "Travail préparatoire : qualité des comptes, projections de performance, organisation des données",
                "Marketing de l'opération et sélection des acquéreurs contacted",
                "Lettre d'intention, offres chiffrées et négociation des conditions",
                "Closing : conditions suspensives, garanties, séquestre et publication",
            ),
            "medium",
            150,
            "Rosenbaum & Pearl, *Investment Banking: Valuation, Leveraged Buyouts, and Mergers & Acquisitions*, "
            "partie « M&A Process ».",
            ("m&a", "fusion", "acquisition", "cession", "r&d", "merger", "talent", "sell", "buy"),
        ),
        _BankQuestion(
            "ma_due_diligence",
            "m_and_a",
            "Quelles sont les grandes diligences d'un acquéreur sur une cible industrielle, et comment se construit "
            "la liste rouge (red flags) ?",
            (
                "Diligence commerciale : marché, clients, concurrence et cohérence du plan d'affaires",
                "Diligence financière : qualité des flux, besoin en fonds de roulement et structure de la dette",
                "Diligence juridique, fiscale, sociale et environnementale",
                "Red flags et traduction de chaque risque en impact sur la valeur ou le prix",
            ),
            "hard",
            180,
            "Rosenbaum & Pearl, *Investment Banking*, partie « Due Diligence » ; "
            "Damodaran, *Investment Valuation*, chapitre « The Dark Side of Valuation ».",
            ("due diligence", "diligence", "red flag", "acquisition", "cible"),
        ),
        _BankQuestion(
            "ma_earnout",
            "m_and_a",
            "Comment fonctionne un earn-out et quels sont les risques réels pour l'acquéreur comme pour le vendeur ?",
            (
                "Mécanique : paiement différé et indexé sur des indicateurs de performance",
                "Indicateurs : EBITDA, chiffre d'affaires ou free cash flow, et leur définition contractuelle",
                "Risques : manipulation des indicateurs et capacité de financement du vendeur",
                "Protections : plafonds, accelerated earn-out et conditions de levée",
            ),
            "hard",
            150,
            "Damodaran, *Investment Valuation*, chapitre « The Dark Side of Valuation » (earn-out et traitement "
            "des passifs).",
            ("earn", "earnout", "earn-out", "contingent", "cession", "acquisition"),
        ),
        _BankQuestion(
            "ma_reps_warranties",
            "m_and_a",
            "Que sont les représentations et garanties dans un contrat de cession, et comment se construisent-elles ?",
            (
                "Déclaration de l'état des actifs, des passifs et des comptes à la date de cession",
                "Portée, durée et mécanisme qui déclenche la garantie",
                "Responsabilité : plafond, franchise et délai de prescription",
                "Exclusions usuelles et clauses anticorruption",
            ),
            "hard",
            150,
            "Rosenbaum & Pearl, *Investment Banking*, partie « M&A Process » (garanties et indemnités) ; "
            "Brealey, Myers & Allen, *Principles of Corporate Finance*, chapitre "
            "« Mergers and the Market for Corporate Control ».",
            ("garantie", "représentation", "warranty", "indemnite", "cession"),
        ),
    ),
    "valuation": (
        _BankQuestion(
            "val_dcf",
            "valuation",
            "Explique une valorisation par actualisation des flux de trésorerie disponibles (DCF), de la projection "
            "jusqu'à la valeur des capitaux propres.",
            (
                "Projection de la performance opérationnelle et dérivation du flux disponible non endetté",
                "Actualisation au coût moyen pondéré du capital (WACC)",
                "Valeur terminale : méthode retenue et hypothèse de croissance",
                "Passage de la valeur d'entreprise à la valeur des capitaux propres via la dette nette",
            ),
            "medium",
            180,
            "Rosenbaum & Pearl, *Investment Banking*, partie « Valuation » ; "
            "Damodaran, *Investment Valuation*, chapitre « Valuing the Firm ».",
            ("dcf", "valorisation", "valuation", "wacc", "actualisation", "flux"),
        ),
        _BankQuestion(
            "val_multiples",
            "valuation",
            "Compare les multiples EV/EBITDA et P/E : que comparent-ils, et quand l'un est-il trompeur ?",
            (
                "EV/EBITDA : mesure opérationnelle avant intérêts comparée à une valeur de structure neutre",
                "P/E : résultat net pour l'actionnaire comparé à la valeur des capitaux propres",
                "Effet du levier et des éléments non récurrents sur la comparabilité des multiples",
                "Ajustements : éléments extracomptables, dettes hors bilan, croissance",
            ),
            "medium",
            150,
            "Rosenbaum & Pearl, *Investment Banking*, partie « Valuation » (multiples et sociétés comparables).",
            ("multiple", "ebitda", "ratio", "valorisation", "comparables"),
        ),
        _BankQuestion(
            "val_control_premium",
            "valuation",
            "Qu'est-ce qu'une prime de contrôle et comment la justifies-tu avec des chiffres ?",
            (
                "Définition : valeur du contrôle par rapport à la valeur du minoritaire",
                "Justification par les synergies et le pouvoir de décision, pas par une règle automatique",
                "Ordre de grandeur observé sur le marché et ce qui l'explique",
                "Ce qui ferait qu'une prime annoncée ne soit pas justifiée",
            ),
            "hard",
            120,
            "Damodaran, *Investment Valuation*, chapitre « The Value of Control ».",
            ("prime", "controle", "minoritaire", "synergie", "valorisation"),
        ),
        _BankQuestion(
            "val_terminal_value",
            "valuation",
            "Quel est le poids de la valeur terminale dans un DCF et comment rendre cette hypothèse robuste ?",
            (
                "Poids relatif de la valeur terminale dans la valeur d'entreprise",
                "Sensibilité à la croissance à long terme et au taux d'actualisation",
                "Alternatives : multiple de sortie ou période d'explicitation plus longue",
                "Test de cohérence : rendements implicites et comparabilité des flux",
            ),
            "hard",
            150,
            "Damodaran, *Investment Valuation*, chapitre « Valuing the Firm » (hypothèses de long terme et "
            "sensibilités).",
            ("terminal", "perpetuite", "perpetuity", "dcf", "sensibilite", "wacc"),
        ),
    ),
    "lbo": (
        _BankQuestion(
            "lbo_structure",
            "lbo",
            "Structure un LBO : sources et usages, dette senior et mezzanine, et equity.",
            (
                "Sources et usages : prix d'acquisition, frais, refinancement de la dette existante",
                "Structure de la dette : senior, mezzanine, sûretés et covenants",
                "Equity : montant, sources de fonds et dilution",
                "Test de cohérence : multiple d'entrée, multiple de sortie et niveau de levier soutenable",
            ),
            "hard",
            180,
            "Rosenbaum & Pearl, *Investment Banking*, partie « Leveraged Buyouts » (sources and uses, "
            "structure de la dette).",
            ("lbo", "ratchet", "buyout", "private equity", "levier", "leverage"),
        ),
        _BankQuestion(
            "lbo_returns",
            "lbo",
            "Comment calcule-t-on l'IRR et le MOIC d'un LBO, et qu'est-ce qui les améliore réellement ?",
            (
                "IRR : flux de trésorerie du sponsor et taux de rendement annuel",
                "MOIC : multiple de sortie rapporté au multiple d'entrée",
                "Leviers : croissance de l'EBITDA, expansion de marge, remboursement de la dette",
                "Distinction entre création de valeur opérationnelle et effet de levier",
            ),
            "hard",
            150,
            "Rosenbaum & Pearl, *Investment Banking*, partie « Leveraged Buyouts » (rendements) ; "
            "Damodaran, *Investment Valuation*, chapitre « Valuing Equity in Private Firms ».",
            ("irr", "moic", "lbo", "rendement", "return", "private equity"),
        ),
        _BankQuestion(
            "lbo_cash_sweep",
            "lbo",
            "Explique le fonctionnement d'un cash sweep et son effet sur le désendettement d'un LBO.",
            (
                "Mécanique : part de la trésorerie libre affectée au remboursement de la dette",
                "Trigger : seuil de dette ou test de covenant",
                "Effet sur le calendrier de remboursement et sur les intérêts payés",
                "Contrepartie : liquidité disponible pour l'exploitation ou la croissance",
            ),
            "hard",
            120,
            "Rosenbaum & Pearl, *Investment Banking*, partie « Leveraged Buyouts » (structure de la dette et "
            "cash sweep).",
            ("cash sweep", "sweep", "remboursement", "lbo", "dette", "deleveraging"),
        ),
        _BankQuestion(
            "lbo_refinancing",
            "lbo",
            "Quels sont les risques de refinancement d'un LBO et comment les anticiper ?",
            (
                "Risque de refinancement : échéance de la dette et conditions de marché à cette date",
                "Risque de taux : sensibilité du service de la dette à la courbe",
                "Mesures de protection : amortissement, clauses de covenant, options de refinancement",
                "Scénario de stress : performance dégradée et effet sur la structure de capital",
            ),
            "hard",
            150,
            "Rosenbaum & Pearl, *Investment Banking*, partie « Leveraged Buyouts » (refinancement et gestion du "
            "risque de taux).",
            ("refinancement", "refinancing", "lbo", "taux", "covenant", "dette"),
        ),
    ),
    "markets": (
        _BankQuestion(
            "mk_greeks",
            "markets",
            "Explique le delta, le gamma, le vega et le theta d'une option, et comment on les utilise pour se couvrir.",
            (
                "Sensibilité de prix à chaque facteur : spot, temps, volatilité",
                "Gamma : convexité et effet d'un mouvement de spot",
                "Vega et theta : comportement face au temps et à la volatilité implicite",
                "Usage : dimensionner une couverture et suivre le risque résiduel",
            ),
            "hard",
            150,
            "Hull, *Options, Futures and Other Derivatives*, chapitre « The Greeks ».",
            ("greek", "delta", "gamma", "vega", "theta", "option", "volatilite"),
        ),
        _BankQuestion(
            "mk_volatility",
            "markets",
            "Qu'est-ce que la volatilité implicite et qu'est-ce que la smile de volatilité révèle ?",
            (
                "Volatilité implicite : volatilité déduite du prix de marché, non observée directement",
                "Skew et term structure de la volatilité",
                "Facteurs de la smile : niveau de taux, pression sur le marché, taille des strikes",
                "Limite : une smile observée ne dit pas seule quelle volatilité se matérialisera",
            ),
            "hard",
            150,
            "Hull, *Options, Futures and Other Derivatives*, chapitre « The Volatility Smile ».",
            ("volatilite", "implicite", "smile", "skew", "option", "marche"),
        ),
        _BankQuestion(
            "mk_structured",
            "markets",
            "Qu'est-ce qu'un produit structuré et quels sont les risques pour l'acheteur ?",
            (
                "Définition : exposition construite à partir d'un sous-jacent et d'un mécanisme de participation",
                "Payoff : participation à la hausse, à la baisse, et flooring",
                "Risques : issuer, liquidité, valorisation et change",
                "Alternatives : replication statique ou dynamique de l'exposition",
            ),
            "hard",
            150,
            "Hull, *Options, Futures and Other Derivatives*, chapitre « Exotic Options » et chapitre « Static "
            "Replication of Derivatives ».",
            ("structure", "produit", "barriere", "knock", "exotic", "option"),
        ),
        _BankQuestion(
            "mk_hedging",
            "markets",
            "Comment dimensionnes-tu une couverture d'une position d'actions avec des options ?",
            (
                "Nombre de contrats à partir du delta et de la taille de la position",
                "Vérification du budget de prime et du coût de roulement",
                "Effet gamma : la couverture doit être réajustée quand le spot bouge",
                "Alternative : couverture statique par produits linéaires",
            ),
            "hard",
            150,
            "Hull, *Options, Futures and Other Derivatives*, chapitre « The Greeks ».",
            ("hedg", "couverture", "delta", "option", "contrat"),
        ),
    ),
    "derivatives": (
        _BankQuestion(
            "dr_forward",
            "derivatives",
            "Décris un contrat forward et un forward de taux : engageant, valeur à l'échéance et rôle dans le bilan.",
            (
                "Définition : engagement d'achat ou de vente à une date et un prix fixés aujourd'hui",
                "Valeur à l'échéance et asymétrie des gains et pertes",
                "Cash flow d collars et de forwards sur taux",
                "Distinction avec un future : engagement bilatéral et règlement",
            ),
            "medium",
            120,
            "Hull, *Options, Futures and Other Derivatives*, chapitre « Forward and Forward Futures ».",
            ("forward", "futur", "taux", "swap", "derive"),
        ),
        _BankQuestion(
            "dr_swap",
            "derivatives",
            "Explique la mécanique d'un swap de taux et d'un swap de devises.",
            (
                "Swap de taux : échange fixe contre variable et valeur du coupon",
                "Swap de devises : échanges de principals et de coupons",
                "Valorisation : parité, actualisation et profils de risque",
                "Usages : couverture d'un risque de taux ou de change",
            ),
            "hard",
            150,
            "Hull, *Options, Futures and Other Derivatives*, chapitre « Swaps ».",
            ("swap", "taux", "change", "devise", "derive"),
        ),
        _BankQuestion(
            "dr_option_payoff",
            "derivatives",
            "Décris le profil de paiement d'une call et d'une put à l'échéance, et la parité put-call.",
            (
                "Call : gain illimité à la hausse, perte limitée au premium",
                "Put : gain limité à la hausse, perte illimitée à la baisse",
                "Parité put-call : relation entre call, put, spot, taux et dividendes",
                "Lien avec la couverture et la valeur d'une option de protection",
            ),
            "medium",
            120,
            "Hull, *Options, Futures and Other Derivatives*, chapitre « Options » (profils de paiement) et "
            "chapitre « Put-Call Parity ».",
            ("call", "put", "option", "parite", "payoff", "echeance"),
        ),
    ),
    "fpa": (
        _BankQuestion(
            "fpa_budgeting",
            "fpa",
            "Décris le processus de budgeting annuel et son lien avec le prévisionnel glissant.",
            (
                "Construction du budget : hypothèses, prix, volumes et structure de coûts",
                "Rôles : élaboration, consolidation, arbitrage et validation",
                "Suivi : reporting périodique et analyse des écarts",
                "Lien avec la trésorerie et le besoin en fonds de roulement",
            ),
            "medium",
            150,
            "Hilton, *Managerial Accounting: Creating Value in a Dynamic Business Environment*, chapitres "
            "« Profit Planning » et « Budgeting ».",
            ("budget", "forecast", "previsionnel", "fpa", "controle", "variance"),
        ),
        _BankQuestion(
            "fpa_forecasting",
            "fpa",
            "Construis un prévisionnel : quels sont les drivers, et comment passes-tu d'hypothèses à un résultat ?",
            (
                "Drivers : volumes, prix, taux de marge et coûts fixes variables",
                "Construction du compte de résultat prévisionnel à partir des drivers",
                "Lien avec le plan de trésorerie et le besoin en fonds de roulement",
                "Scénarios : base, haut et bas, et variables les plus sensibles",
            ),
            "medium",
            150,
            "Hilton, *Managerial Accounting*, chapitre « Profit Planning » ; "
            "Kaplan & Atkinson, *Advanced Management Accounting*, chapitre « Profit Planning and Budgetary "
            "Planning ».",
            ("previsionnel", "forecast", "driver", "budget", "fpa", "scenario"),
        ),
        _BankQuestion(
            "fpa_variance",
            "fpa",
            "Quelle est la différence entre un écart sur prix et un écart sur volume ?",
            (
                "Écart sur prix : impact de l'écart unitaire appliqué au volume réel",
                "Écart sur volume : impact de l'écart de volume au prix standard",
                "Lecture : un écart de volume peut être un choix de gestion, pas une erreur",
                "Action corrective : responsable, cause racine et suivi",
            ),
            "hard",
            150,
            "Horngren, *Cost Accounting: A Managerial Emphasis*, chapitre « Standard Costs and Variances ».",
            ("ecart", "variance", "prix", "volume", "standard", "controle de gestion"),
        ),
    ),
    "controle_gestion": (
        _BankQuestion(
            "cg_standards",
            "controle_gestion",
            "Qu'est-ce qu'un coût standard, comment l'établit-on et à quoi sert-il ?",
            (
                "Définition : coût attendu pour une unité de produit ou de service",
                "Établissement : analyse du temps, des prix et des quantités de référence",
                "Usage : pilotage, budgétation et comparaison réel / standard",
                "Limites : un standard figé perd sa valeur si les conditions changent",
            ),
            "medium",
            120,
            "Horngren, *Cost Accounting: A Managerial Emphasis*, chapitre « Standard Costs and Variances ».",
            ("cout", "standard", "controle de gestion", "budget", "variance"),
        ),
        _BankQuestion(
            "cg_variance_decomposition",
            "controle_gestion",
            "Décompose un écart global sur coûts standards en écarts élémentaires.",
            (
                "Écart sur prix et écart sur quantité au niveau du coût d'achat",
                "Écart sur main-d'œuvre : taux et efficience",
                "Écart sur coûts indirects : budget et allocation",
                "Utilisation : identifier la cause racine et le responsable",
            ),
            "hard",
            150,
            "Horngren, *Cost Accounting: A Managerial Emphasis*, chapitre « Standard Costs and Variances ».",
            ("ecart", "variance", "standard", "controle de gestion", "efficience", "quantite"),
        ),
        _BankQuestion(
            "cg_transfer_pricing",
            "controle_gestion",
            "À quoi sert un prix de transfert et quelles méthodes sont possibles ?",
            (
                "Objectifs : inciter, mesurer la performance et fixer une politique de groupe",
                "Méthodes : prix de marché, coûts complets, coûts variables incrémentaux",
                "Effets sur les décisions des centres amont et aval",
                "Risques de manipulation et conditions de cohérence du groupe",
            ),
            "hard",
            150,
            "Kaplan & Atkinson, *Advanced Management Accounting*, chapitre « Responsibility Accounting and "
            "Transfer Pricing ».",
            ("prix de transfert", "transfer pricing", "centre", "controle de gestion", "responsabilite"),
        ),
    ),
    "probabilites": (
        _BankQuestion(
            "pr_monte_carlo",
            "probabilites",
            "Explique le principe de la simulation de Monte-Carlo appliquée à une valorisation.",
            (
                "Principe : tirages aléatoires des variables d'entrée et agrégation des résultats",
                "Distribution des entrées et traitement des corrélations",
                "Lecture des sorties : médiane, intervalle de confiance, percentiles",
                "Limites : temps de calcul, qualité des distributions et modèle sous-jacent",
            ),
            "hard",
            150,
            "Hull, *Options, Futures and Other Derivatives*, chapitre « Simulation Methods ».",
            ("monte carlo", "simulation", "probabilite", "aleatoire", "volatilite"),
        ),
        _BankQuestion(
            "pr_expectation_variance",
            "probabilites",
            "Calcule l'espérance et la variance d'un portefeuille de deux actifs et explique ce qu'elles impliquent.",
            (
                "Espérance comme moyenne pondérée des rendements",
                "Variance pondérée et covariance entre les deux actifs",
                "Rôle de la corrélation dans le risque du portefeuille",
                "Limite : moments statistics ne suffisent pas à décrire une distribution",
            ),
            "hard",
            150,
            "Ross, Westerfield & Jaffe, *Corporate Finance*, chapitre « Risk and Return ».",
            ("esperance", "variance", "covariance", "portefeuille", "probabilite", "rendement"),
        ),
        _BankQuestion(
            "pr_brainteasers",
            "probabilites",
            "Résous un problème de probabilités classique d'entretien finance, en exposant le raisonnement.",
            (
                "Énoncé des données du problème et schéma des cas possibles",
                "Calcul par probabilités conditionnelles ou par combinaison",
                "Vérification du résultat par une seconde méthode",
                "Clarté du raisonnement : c'est lui qui est évalué autant que le chiffre",
            ),
            "medium",
            120,
            "Mosteller, *Fifty Challenging Problems in Probability* ; "
            "Ross, Westerfield & Jaffe, *Corporate Finance*, chapitre « Risk and Return ».",
            ("probabilite", "brainteaser", "hasard", "pigeonhole", "montee", "paris"),
        ),
    ),
}

FINANCE_BANK_LABELS: dict[str, str] = {
    "m_and_a": "M&A",
    "valuation": "Valuation",
    "lbo": "LBO",
    "markets": "Marchés",
    "derivatives": "Produits dérivés",
    "fpa": "FP&A",
    "controle_gestion": "Contrôle de gestion",
    "probabilites": "Probabilités",
}


@dataclass(frozen=True)
class _BankItem:
    identifier: str
    question: str
    expected_elements: tuple[str, ...]
    difficulty: Difficulty
    time_estimate_seconds: int
    structure: str


_TECHNICAL_STRUCTURE = (
    "Approche structurée : définition du concept, mécanisme ou calcul clé, application concrète, "
    "puis limite ou cas d'échec."
)
_GAP_STRUCTURE = (
    "Structure STAR adaptée à un écart : situation et exigence de l'offre, ce que tu as réellement fait, "
    "comment tu apprends, et ce que tu ferais pour réduire l'écart."
)
_BEHAVIORAL_STRUCTURE = (
    "Structure STAR : Situation (contexte et enjeu), Tâche (ton rôle précis), Action (ce que tu as fait, "
    "comment), Résultat (résultat vérifiable et apprentissage)."
)

_BEHAVIORAL_BANK: tuple[_BankItem, ...] = (
    _BankItem(
        "behavioral_self_introduction",
        "Présente-toi en 90 secondes : formation actuelle, une expérience factuelle, et le lien précis avec ce poste.",
        (
            "Annonce ta formation actuelle et ton domaine",
            "Cite une expérience, un projet ou un stage avec ta responsabilité concrète",
            "Donne un résultat ou une production vérifiable de cette expérience",
            "Termine par le lien précis entre ton parcours et le poste visé",
        ),
        "easy",
        90,
        _BEHAVIORAL_STRUCTURE,
    ),
    _BankItem(
        "behavioral_teamwork",
        "Raconte une situation où tu as dû coopérer avec quelqu'un dont la méthode différait de la tienne.",
        (
            "Décris la situation, l'équipe et l'enjeu",
            "Explique la différence d'approche et le désaccord",
            "Décris ton action concrète pour faire avancer le travail",
            "Donne le résultat et ce que tu en as appris",
        ),
        "medium",
        120,
        _BEHAVIORAL_STRUCTURE,
    ),
    _BankItem(
        "behavioral_conflict",
        "Raconte une situation de désaccord sur une décision dans ton équipe.",
        (
            "Décris le contexte et la décision en jeu",
            "Présente les positions divergentes et l'enjeu réel",
            "Décris comment tu as argumenté et arbitré",
            "Donne le résultat de la décision et son issue",
        ),
        "medium",
        120,
        _BEHAVIORAL_STRUCTURE,
    ),
    _BankItem(
        "behavioral_failure",
        "Raconte une erreur ou un échec, et ce que tu en as fait.",
        (
            "Décris le contexte et l'objectif qui n'a pas été atteint",
            "Assume l'erreur sans minimiser et sans rejeter la faute",
            "Décris la cause racine et les mesures correctives mises en place",
            "Donne le résultat après correction et ce que tu as changé durablement",
        ),
        "hard",
        120,
        _BEHAVIORAL_STRUCTURE,
    ),
    _BankItem(
        "behavioral_initiative",
        "Raconte une initiative que tu as prise sans qu'elle t'ait été demandée.",
        (
            "Décris le problème repéré et pourquoi il comptait",
            "Explique pourquoi tu as pris l'initiative et avec quel risque",
            "Décris ce que tu as mis en place concrètement",
            "Donne le résultat mesurable et ce que l'équipe a repris ensuite",
        ),
        "medium",
        120,
        _BEHAVIORAL_STRUCTURE,
    ),
    _BankItem(
        "behavioral_learning",
        "Quelle compétence as-tu dû apprendre récemment, et comment as-tu vérifié que tu la maîtrisais ?",
        (
            "Explique le contexte et le niveau initial",
            "Décris la méthode d'apprentissage réellement suivie",
            "Décris la preuve de progression (exercice, projet, résultat)",
            "Dis ce qui n'est pas encore maîtrisé",
        ),
        "medium",
        120,
        _BEHAVIORAL_STRUCTURE,
    ),
    _BankItem(
        "behavioral_priority",
        "Comment as-tu arbitré entre deux urgences avec des délais contradictoires ?",
        (
            "Décris les deux urgences et leurs contraintes de délai",
            "Explique les critères de priorisation utilisés",
            "Décris les arbitrages concrets et la communication faite",
            "Donne le résultat sur les deux sujets et ce que tu as appris",
        ),
        "hard",
        120,
        _BEHAVIORAL_STRUCTURE,
    ),
    _BankItem(
        "behavioral_pressure",
        "Raconte une situation de pression (deadline court, incident, chiffre) que tu as dû gérer.",
        (
            "Décris la pression et son origine factuelle",
            "Explique ce que tu as priorisé et ce que tu as dépriorisé",
            "Décris les actions conduites sous contrainte de temps",
            "Donne le résultat et les mesures prises pour éviter la récurrence",
        ),
        "hard",
        120,
        _BEHAVIORAL_STRUCTURE,
    ),
)

_RECRUITER_BANK: tuple[str, ...] = (
    "Quelles sont les métriques de réussite attendues sur les trois premiers mois du poste ?",
    "Comment ce poste s'inscrit-il dans l'équipe, et avec quels interlocuteurs travailles-tu au quotidien ?",
    "Quels outils, modèles ou référentiels sont utilisés au quotidien sur ce poste ?",
    "Comment l'entreprise mesure et suit-elle la performance de ce poste (rituels, reporting, revue) ?",
    "Quelles sont les étapes du processus de sélection et les délais annoncés entre chaque étape ?",
    "Quels sont les principaux défis que l'équipe cherche à traiter sur les six prochains mois ?",
    "Quelle part du travail est analytique, et quelle part est relationnelle ou projetuelle ?",
    "Comment l'entreprise accompagne-t-elle l'intégration et la montée en compétences sur ce poste ?",
)


# ---------------------------------------------------------------------------
# Small deterministic helpers
# ---------------------------------------------------------------------------


# Short, domain-specific terms are meaningful evidence even though their
# normalized spelling is shorter than the conservative four-character
# threshold below.  Keep this an explicit allowlist.
_SHORT_DOMAIN_TOKENS: frozenset[str] = frozenset(
    {"api", "aws", "cfa", "dcf", "erp", "evm", "fcf", "git", "irr", "lbo", "moic", "nda", "sap", "sql", "tpv", "vba"}
)

# Verbs that open an expected element.  They describe the answer's shape, not
# its content, so they are dropped when the match keys are computed.
_LEADING_VERBS: frozenset[str] = frozenset(
    {
        "analyse",
        "cite",
        "compare",
        "decris",
        "decrire",
        "decouvre",
        "detaille",
        "donne",
        "enonce",
        "explique",
        "formule",
        "ici",
        "indique",
        "montre",
        "presente",
        "precise",
        "signale",
    }
)


def _distinctive_tokens(text: str) -> tuple[str, ...]:
    tokens = [
        token
        for token in normalized_text(text).split()
        if (len(token) >= 4 or token in _SHORT_DOMAIN_TOKENS)
        and token not in _GENERIC_TOKENS
        and not token.isdigit()
    ]
    return tuple(dict.fromkeys(tokens))


def _element_tokens(text: str) -> tuple[str, ...]:
    """Match keys of one expected element, without its leading verb."""
    tokens = list(_distinctive_tokens(text))
    if tokens and tokens[0] in _LEADING_VERBS:
        tokens = tokens[1:]
    return tuple(tokens) or _distinctive_tokens(text)


def _profile_fields(profile: Mapping[str, Any] | None) -> tuple[str, ...]:
    profile = profile or {}
    return (
        "skills",
        "experience",
        "education",
        "languages",
        "eligibility",
    )


def _profile_blob(profile: Mapping[str, Any] | None) -> str:
    profile = profile or {}
    parts = [clean_text(profile.get(field), limit=6_000) for field in _profile_fields(profile)]
    return " ".join(part for part in parts if part)


def _profile_segments(profile: Mapping[str, Any] | None) -> list[tuple[str, str]]:
    """Return ``(field, verbatim excerpt)`` pairs from the profile fields."""
    profile = profile or {}
    segments: list[tuple[str, str]] = []
    for field in _profile_fields(profile):
        value = clean_text(profile.get(field), limit=6_000)
        if not value:
            continue
        for line in value.splitlines():
            for sentence in re.split(r"(?<=[.;\n])\s+", line):
                sentence = sentence.strip(" •-–*")
                if sentence:
                    segments.append((field, sentence[:300]))
    return segments


def _evidence_id(field: str, quote: str) -> str:
    digest = hashlib.sha256(f"{field}|{quote}".encode("utf-8")).hexdigest()
    return f"ev_{field}_{digest[:10]}"


def _find_evidence(profile: Mapping[str, Any] | None, tokens: Sequence[str]) -> tuple[str, str, str] | None:
    """Return the first verbatim profile excerpt supporting ``tokens``."""
    if not tokens:
        return None
    wanted = set(tokens)
    for field, segment in _profile_segments(profile):
        normalized_segment = normalized_text(segment)
        if not normalized_segment:
            continue
        hits = sorted(token for token in wanted if f" {token} " in f" {normalized_segment} ")
        if hits:
            return field, segment, _evidence_id(field, segment)
    return None


def _requirement_index(offer: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
    """Map normalized requirement texts to their provenance record."""
    analysis = analyze_offer(dict(offer))
    index: dict[str, dict[str, Any]] = {}
    for record in analysis.get("requirements", []):
        key = normalized_text(record.get("text"))
        if key and key not in index:
            index[key] = record
    return index


def _requirement_id(index: Mapping[str, dict[str, Any]], text: str) -> str | None:
    """Resolve a requirement id from a free requirement statement."""
    key = normalized_text(text)
    record = index.get(key)
    if record:
        return str(record.get("id") or "") or None
    for candidate_key, candidate in index.items():
        if candidate_key and (candidate_key in key or key in candidate_key):
            return str(candidate.get("id") or "") or None
    return None


def _offer_blob(offer: Mapping[str, Any]) -> str:
    parts = [
        clean_text(offer.get("requirements"), limit=20_000),
        clean_text(offer.get("description_original"), limit=30_000),
        clean_text(offer.get("job_family"), limit=160),
        clean_text(offer.get("title"), limit=300),
    ]
    return " ".join(part for part in parts if part)


def _bank_affinity(offer: Mapping[str, Any]) -> list[tuple[str, int]]:
    """Rank the finance banks by the words the offer actually uses."""
    blob = normalized_text(_offer_blob(offer))
    scored: list[tuple[str, int]] = []
    for bank, questions in FINANCE_BANKS.items():
        keywords = {keyword for question in questions for keyword in question.keywords}
        score = sum(1 for keyword in keywords if f" {normalized_text(keyword)} " in f" {blob} ")
        scored.append((bank, score))
    scored.sort(key=lambda item: (-item[1], list(FINANCE_BANKS).index(item[0])))
    return scored


def _bank_source(bank: str) -> str:
    questions = FINANCE_BANKS.get(bank)
    return questions[0].source if questions else ""


def _difficulty_for(modality: str, has_evidence: bool) -> str:
    if not has_evidence:
        return "hard"
    if modality == "preferred":
        return "easy"
    return "medium"


# ---------------------------------------------------------------------------
# Question builders
# ---------------------------------------------------------------------------


def _make_question(
    identifier: str,
    category: str,
    question: str,
    expected_elements: Iterable[str],
    *,
    related_evidence: list[str] | None = None,
    related_requirement: str | None = None,
    difficulty: str = "medium",
    time_estimate_seconds: int = 120,
    keyword_groups: Iterable[Iterable[str]] | None = None,
    pedagogical_source: str | None = None,
    suggested_structure: str = "",
    evidence_quotes: Iterable[str] = (),
    bank: str = "",
) -> PrepQuestion:
    elements = [clean_text(element, limit=300) for element in expected_elements if clean_text(element, limit=300)]
    groups = tuple(tuple(group) for group in keyword_groups) if keyword_groups is not None else tuple(
        _element_tokens(element) for element in elements
    )
    public = InterviewQuestion(
        id=identifier,
        category=category,  # type: ignore[arg-type]
        question=clean_text(question, limit=600),
        expected_elements=elements,
        related_evidence=list(related_evidence) if related_evidence else None,
        related_requirement=related_requirement,
        difficulty=difficulty,  # type: ignore[arg-type]
        time_estimate_seconds=int(time_estimate_seconds),
    )
    return PrepQuestion(
        question=public,
        keyword_groups=groups,
        pedagogical_source=pedagogical_source,
        suggested_structure=suggested_structure,
        evidence_quotes=tuple(evidence_quotes),
        bank=bank,
    )


def _technical_questions(
    offer: Mapping[str, Any],
    profile: Mapping[str, Any],
    index: Mapping[str, dict[str, Any]],
    mode: str,
) -> list[PrepQuestion]:
    """Technical questions taken from the requirements the offer states."""
    records: list[PrepQuestion] = []
    analysis = analyze_offer(dict(offer))
    candidates = [
        record
        for record in analysis.get("requirements", [])
        if record.get("category") in {"technical_skill", "experience", "other", "language"}
        and not record.get("injection_suspect")
        and not record.get("negated")
    ]
    # Mandatory statements first, then contextual ones, then preferences.
    modality_rank = {"required": 0, "contextual": 1, "unknown": 2, "preferred": 3}
    candidates.sort(key=lambda record: (modality_rank.get(str(record.get("modality")), 2), str(record.get("id"))))
    for record in candidates:
        text = clean_text(record.get("text"), limit=300)
        if len(text) < 8:
            continue
        tokens = _distinctive_tokens(text)
        evidence = _find_evidence(profile, tokens)
        related_evidence = [evidence[2]] if evidence else None
        bank_source = _source_for_requirement(text, mode)
        source = bank_source["source"] if bank_source else None
        bank = bank_source["bank"] if bank_source else ""
        records.append(
            _make_question(
                f"tech_{record.get('id')}",
                "technical",
                f"L’offre mentionne « {text} ». Comment l’appliques-tu concrètement sur ce poste : "
                "quelle est ta démarche, et où cette démarche s’arrête-t-elle ?",
                (
                    f"Présente la démarche que tu suivrais pour appliquer « {text} »",
                    "Cite un outil, une méthode ou un calcul précis que tu maîtrises",
                    "Explique le mécanisme ou le raisonnement sous-jacent",
                    "Signale une limite, un risque ou un cas où ta méthode ne s’applique pas",
                ),
                related_evidence=related_evidence,
                related_requirement=str(record.get("id") or "") or None,
                difficulty=_difficulty_for(str(record.get("modality")), bool(evidence)),
                time_estimate_seconds=150,
                pedagogical_source=source,
                suggested_structure=_TECHNICAL_STRUCTURE,
                evidence_quotes=[evidence[1]] if evidence else (),
                bank=bank,
            )
        )
        if len(records) >= MAX_TECHNICAL_QUESTIONS:
            break
    return records


def _source_for_requirement(text: str, mode: str) -> Any:
    """Return the pedagogical source of the closest finance bank, if any."""
    if mode != "finance":
        return None
    normalized = normalized_text(text)
    best_bank = ""
    best_score = 0
    for bank, questions in FINANCE_BANKS.items():
        score = sum(
            1
            for question in questions
            for keyword in question.keywords
            if f" {normalized_text(keyword)} " in f" {normalized} "
        )
        if score > best_score:
            best_score = score
            best_bank = bank
    if not best_bank:
        return None
    return {"source": _bank_source(best_bank), "bank": best_bank}


def _finance_technical_questions(offer: Mapping[str, Any]) -> list[PrepQuestion]:
    """Technical questions drawn from the eight specialised finance banks."""
    ranking = _bank_affinity(offer)
    selected_banks = [bank for bank, _ in ranking[:3]]
    records: list[PrepQuestion] = []
    for bank in selected_banks:
        questions = FINANCE_BANKS[bank]
        for bank_question in questions[:2]:
            records.append(
                _make_question(
                    f"fin_{bank_question.identifier}",
                    "technical",
                    bank_question.question,
                    bank_question.expected_elements,
                    difficulty=bank_question.difficulty,
                    time_estimate_seconds=bank_question.time_estimate_seconds,
                    pedagogical_source=bank_question.source,
                    suggested_structure=_TECHNICAL_STRUCTURE,
                    bank=bank,
                )
            )
        if len(records) >= MAX_TECHNICAL_QUESTIONS:
            break
    return records


def _behavioral_questions(mode: str) -> list[PrepQuestion]:
    source = BEHAVIORAL_SOURCE if mode != "finance" else f"{BEHAVIORAL_SOURCE} ; Rosenbaum & Pearl, *Investment Banking*, introduction « How to Think about Finance »."
    records: list[PrepQuestion] = []
    for item in _BEHAVIORAL_BANK[:MAX_BEHAVIORAL_QUESTIONS]:
        records.append(
            _make_question(
                item.identifier,
                "behavioral",
                item.question,
                item.expected_elements,
                difficulty=item.difficulty,
                time_estimate_seconds=item.time_estimate_seconds,
                pedagogical_source=source,
                suggested_structure=item.structure,
            )
        )
    return records


def _gap_questions(
    offer: Mapping[str, Any],
    profile: Mapping[str, Any],
    intake: Mapping[str, Any] | None,
    index: Mapping[str, dict[str, Any]],
) -> list[PrepQuestion]:
    """Questions on the requirements the profile does not prove yet."""
    preparation = prepare_application(dict(profile or {}), dict(intake or {}), dict(offer))
    records: list[PrepQuestion] = []
    for item in preparation.get("unverified_elements", []):
        text = clean_text(item.get("requirement"), limit=300)
        if len(text) < 8:
            continue
        requirement_id = _requirement_id(index, text)
        records.append(
            _make_question(
                f"gap_{requirement_id or hashlib.sha256(text.encode('utf-8')).hexdigest()[:12]}",
                "gap",
                f"L’offre demande « {text} », et je n’ai trouvé aucune preuve comparable dans ton profil local. "
                "Comment as-tu traité ce sujet, et que ferais-tu pour le démontrer ?",
                (
                    "Explique ce que tu as réellement fait sur un sujet proche, sans rien inventer",
                    f"Montre que tu as compris l’exigence « {text} » et ce qu’elle implique concrètement",
                    "Décris une méthode de mise en place que tu suis réellement",
                    "Explique ce que tu ferais pour transformer cet écart en compétence vérifiable",
                    "Dis ce que tu ne sais pas faire et qui resterait à découvrir",
                ),
                related_requirement=requirement_id,
                difficulty="hard",
                time_estimate_seconds=150,
                suggested_structure=_GAP_STRUCTURE,
            )
        )
        if len(records) >= MAX_GAP_QUESTIONS:
            break
    return records


def _recruiter_questions(
    offer: Mapping[str, Any],
    index: Mapping[str, dict[str, Any]],
) -> list[str]:
    """Questions the candidate can ask, general ones plus offer-targeted ones."""
    questions: list[str] = list(_RECRUITER_BANK)
    analysis = analyze_offer(dict(offer))
    targeted = [
        record
        for record in analysis.get("requirements", [])
        if record.get("modality") in {"required", "contextual"}
        and not record.get("injection_suspect")
        and not record.get("negated")
    ]
    for record in targeted[:3]:
        text = clean_text(record.get("text"), limit=200)
        if len(text) < 8:
            continue
        questions.append(
            f"L’offre mentionne « {text} » : quelles sont les attentes concrètes sur ce point "
            "dès les premières semaines ?"
        )
    return questions[:MAX_RECRUITER_QUESTIONS]


def _sensitive_points(
    offer: Mapping[str, Any],
    profile: Mapping[str, Any],
    index: Mapping[str, dict[str, Any]],
) -> list[str]:
    """Points of the CV a recruiter is likely to probe, all verifiable locally."""
    points: list[str] = []
    profile = profile or {}
    if not clean_text(profile.get("skills"), limit=4_000):
        points.append("Aucune compétence n’est renseignée dans ton profil : le recruteur ne peut rien vérifier.")
    experience = clean_text(profile.get("experience"), limit=6_000)
    if experience and not re.search(r"\d", experience):
        points.append(
            "Tes expériences ne contiennent aucun chiffre : quantifie un résultat vérifiable "
            "(volume, délai, pourcentage) sans rien inventer."
        )
    if not clean_text(profile.get("education"), limit=1_000):
        points.append("Aucune formation n’est renseignée : précise ton diplôme et ton niveau d’études.")
    languages = clean_text(profile.get("languages"), limit=2_000)
    if languages and not any(marker in normalized_text(languages) for marker in _LEVEL_MARKERS):
        points.append(
            "Tes langues ne mentionnent aucun niveau (A1–C2) : le recruteur ne peut pas évaluer ta maîtrise."
        )
    eligibility = normalized_text(profile.get("eligibility"))
    if not eligibility or eligibility in {"unknown", "inconnu"}:
        points.append(
            "Ton éligibilité (autorisation de travail, mobilité) n’est pas renseignée : "
            "une offre peut la tester, et le silence sera interprété."
        )
    analysis = analyze_offer(dict(offer))
    for record in analysis.get("requirements", []):
        if record.get("modality") != "required" or record.get("injection_suspect"):
            continue
        text = clean_text(record.get("text"), limit=200)
        if len(text) < 8:
            continue
        tokens = _distinctive_tokens(text)
        if not tokens:
            continue
        if _find_evidence(profile, tokens) is None:
            points.append(
                f"L’exigence « {text} » n’a aucune preuve dans ton profil : c’est ton point de vigilance n°1."
            )
            break
    return points[:MAX_SENSITIVE_POINTS]


def _company_factsheet(offer: Mapping[str, Any]) -> CompanyFactsheet:
    """Build the factsheet from the offer only; unknown stays unknown."""
    company = clean_text(offer.get("company"), limit=240) or "Entreprise non renseignée"
    sector = clean_text(offer.get("job_family"), limit=160)
    if not sector or sector == "À préciser":
        sector = clean_text(offer.get("title"), limit=160) or "Secteur non renseigné par l’offre"
    blob = normalized_text(_offer_blob(offer))
    culture_keywords = [
        keyword
        for keyword in _CULTURE_VOCABULARY
        if f" {normalized_text(keyword)} " in f" {blob} "
    ]
    interview_process: list[str] | None = []
    for line in clean_text(offer.get("description_original"), limit=30_000).splitlines():
        stripped = line.strip()
        if len(stripped) < 12:
            continue
        lowered = normalized_text(stripped)
        if "entretien" in lowered and ("process" in lowered or "etape" in lowered or "steps" in lowered):
            interview_process.append(stripped[:300])
        if interview_process and len(interview_process) >= 4:
            break
    if not interview_process:
        interview_process = None
    sources: list[str] = []
    official_url = clean_text(offer.get("official_url"), limit=2_000)
    if official_url:
        sources.append(official_url)
    source_name = clean_text(offer.get("source_name"), limit=160)
    source_id = clean_text(offer.get("source_id"), limit=240)
    if source_name or source_id:
        sources.append(f"{source_name}{' · ' if source_name and source_id else ''}{source_id}".strip(" ·"))
    sources.append("Offre locale Career (career_data)")
    return CompanyFactsheet(
        name=company,
        sector=sector,
        size="Non renseignée par l’offre",
        recent_news=[],
        culture_keywords=culture_keywords,
        interview_process=interview_process,
        sources=sources,
    )


# ---------------------------------------------------------------------------
# Public build API
# ---------------------------------------------------------------------------


def build_preparation(
    offer_id: str,
    profile_id: str,
    mode: str = "standard",
    *,
    offer: Mapping[str, Any] | None = None,
    profile: Mapping[str, Any] | None = None,
    intake: Mapping[str, Any] | None = None,
    context: PrepContext | None = None,
    session_id: str | None = None,
    created_at: str | None = None,
) -> Preparation:
    """Build one targeted preparation from a stored offer and one profile."""
    normalized_mode = clean_text(mode, limit=40).lower() or "standard"
    if normalized_mode not in MODES:
        raise UserFacingError("Le mode de préparation d’entretien doit être standard ou finance.")
    normalized_profile_id = clean_text(profile_id, limit=80) or "user_profile"
    if normalized_profile_id.lower() not in LOCAL_PROFILE_IDS:
        raise UserFacingError("Ce profil candidat n’existe pas dans l’espace Career local.")
    resolver = context or default_context()
    if offer is None or profile is None:
        if resolver is None:
            raise UserFacingError(
                "Aucune source locale n’est liée à la préparation d’entretien : "
                "fournis l’offre et le profil, ou un contexte de résolution."
            )
        offer = resolver.load_offer(clean_text(offer_id, limit=80)) if offer is None else offer
        profile = resolver.load_profile(normalized_profile_id) if profile is None else profile
    offer = dict(offer or {})
    profile = dict(profile or {})
    if not offer:
        raise UserFacingError("Cette offre Career n’existe pas.")

    index = _requirement_index(offer)
    technical = _technical_questions(offer, profile, index, normalized_mode)
    if normalized_mode == "finance":
        finance_records = _finance_technical_questions(offer)
        technical = (finance_records + technical)[:MAX_TECHNICAL_QUESTIONS]
    behavioral = _behavioral_questions(normalized_mode)
    gaps = _gap_questions(offer, profile, intake, index)
    sensitive = _sensitive_points(offer, profile, index)
    recruiter = _recruiter_questions(offer, index)
    factsheet = _company_factsheet(offer)

    session = InterviewPrepSession(
        session_id=clean_text(session_id, limit=80) or "interview_prep_session",
        offer_id=clean_text(offer.get("id"), limit=80) or clean_text(offer_id, limit=80),
        profile_id=normalized_profile_id,
        technical_questions=[record.question for record in technical],
        behavioral_questions=[record.question for record in behavioral],
        gap_questions=[record.question for record in gaps],
        sensitive_points=sensitive,
        recruiter_questions=recruiter,
        company_factsheet=factsheet,
        created_at=clean_text(created_at, limit=64),
    )
    records: dict[str, PrepQuestion] = {}
    for record in (*technical, *behavioral, *gaps):
        records[record.question.id] = record
    return Preparation(
        session=session,
        questions=records,
        offer={
            "id": clean_text(offer.get("id"), limit=80),
            "company": clean_text(offer.get("company"), limit=240),
            "title": clean_text(offer.get("title"), limit=300),
            "official_url": clean_text(offer.get("official_url"), limit=2_000),
        },
        mode=normalized_mode,
    )


def generate(
    offer_id: str,
    profile_id: str,
    mode: str = "standard",
    **kwargs: Any,
) -> InterviewPrepSession:
    """Return the preparation session for one offer and one candidate profile."""
    return build_preparation(offer_id, profile_id, mode, **kwargs).session


# ---------------------------------------------------------------------------
# Simulation
# ---------------------------------------------------------------------------


def _covered(element_tokens: Sequence[str], answer_tokens: set[str]) -> bool:
    if not element_tokens:
        return False
    hits = [token for token in element_tokens if token in answer_tokens]
    if not hits:
        return False
    strong = [token for token in element_tokens if len(token) >= 5]
    if strong:
        return any(token in strong for token in hits) or len(hits) >= 2
    return True


def _detect_claims(answer: str) -> list[str]:
    claims: list[str] = []
    for sentence in re.split(r"(?<=[.!?;])\s+|\n+", answer):
        stripped = sentence.strip()
        if len(stripped) < 12:
            continue
        for pattern in _CLAIM_PATTERNS:
            if re.search(pattern, stripped, flags=re.IGNORECASE):
                claims.append(stripped[:300])
                break
    return claims


def _claim_is_supported(claim: str, profile_blob: str, evidence_quotes: Sequence[str]) -> bool:
    """A claim is supported when the profile carries its own content signals."""
    support_blob = normalized_text(f"{profile_blob} {' '.join(evidence_quotes)}")
    numbers = re.findall(r"\d+(?:[.,]\d+)?\s*%?", claim)
    if numbers:
        for number in numbers:
            normalized_number = normalized_text(number)
            if normalized_number and f" {normalized_number} " in f" {support_blob} ":
                return True
        return False
    tokens = _element_tokens(claim)
    if not tokens:
        return True
    profile_tokens = set(support_blob.split())
    hits = [token for token in tokens if token in profile_tokens]
    # One shared word is not a proof: a claim needs at least two content
    # signals present in the profile before it is considered supported.
    return len(hits) >= 2


def _structure_label(category: str) -> str:
    if category == "behavioral":
        return _BEHAVIORAL_STRUCTURE
    if category == "gap":
        return _GAP_STRUCTURE
    return _TECHNICAL_STRUCTURE


def simulate(
    preparation: Preparation,
    question_id: str,
    user_answer: str,
    *,
    profile: Mapping[str, Any] | None = None,
) -> SimulationFeedback:
    """Return the deterministic reading of one rehearsal answer."""
    identifier = clean_text(question_id, limit=120)
    record = preparation.questions.get(identifier)
    if record is None:
        raise UserFacingError("Cette question d’entretien préparée est inconnue de la session.")
    answer = clean_text(user_answer, limit=MAX_ANSWER_CHARS)
    if len(answer) < 3:
        raise UserFacingError("Écris une réponse avant de demander le retour de la simulation.")
    question = record.question
    answer_tokens = set(normalized_text(answer).split())
    words = re.findall(r"[\wÀ-ÿ'-]+", answer)
    word_count = len(words)

    covered: list[str] = []
    missing: list[str] = []
    for element, group in zip(question.expected_elements, record.keyword_groups):
        if _covered(group, answer_tokens):
            covered.append(element)
        else:
            missing.append(element)

    total = max(1, len(question.expected_elements))
    coverage = len(covered) / total
    markers = sum(1 for marker in _STRUCTURE_MARKERS if f" {normalized_text(marker)} " in f" {normalized_text(answer)} ")
    structure = min(100, 35 + 20 * markers)
    length_score = 20 if word_count < 15 else 55 if word_count < 40 else 85 if word_count <= 400 else 60

    strengths: list[str] = []
    if covered:
        strengths.append(f"Tu couvres {len(covered)} point(s) attendu(s) sur {len(question.expected_elements)}.")
    if word_count >= 40:
        strengths.append("Ta réponse est assez développée pour être évaluable.")
    if structure >= 70:
        strengths.append("Ta réponse est explicite : le fil du raisonnement se suit.")
    if re.search(r"\d", answer):
        strengths.append("Tu appuies ta réponse sur des éléments chiffrés.")

    unproven: list[str] = []
    profile_blob = _profile_blob(profile)
    for claim in _detect_claims(answer):
        if not _claim_is_supported(claim, profile_blob, record.evidence_quotes):
            unproven.append(
                f"« {claim} » : aucune trace correspondante dans ton profil local, "
                "ne l’affirme pas en entretien sans une preuve vérifiable."
            )

    if coverage >= 0.8 and structure >= 70 and length_score >= 85:
        score = "excellent"
    elif coverage >= 0.5 and length_score >= 55:
        score = "good"
    elif covered or length_score >= 55:
        score = "needs_improvement"
    else:
        score = "insufficient"

    structure_label = record.suggested_structure or _structure_label(question.category)
    if missing:
        retry_prompt = (
            f"Reprends la question en traitant explicitement le point manquant : « {missing[0]} ». "
            "Garde une structure Situation / Tâche / Action / Résultat et appuie-toi sur un fait vérifiable."
        )
    else:
        retry_prompt = (
            "Tu couvres les points attendus : rejoue la réponse en 30 secondes pour vérifier que "
            "l’exemple est concret, chiffré et rattaché au poste de l’offre."
        )
    return SimulationFeedback(
        question_id=question.id,
        user_answer=answer,
        score=score,
        strengths=strengths,
        missing_elements=missing,
        unproven_claims=unproven,
        suggested_structure=structure_label,
        retry_prompt=retry_prompt,
        pedagogical_source=record.pedagogical_source,
    )


# ---------------------------------------------------------------------------
# Serialization
# ---------------------------------------------------------------------------


def _serialize_prep_question(record: PrepQuestion) -> dict[str, Any]:
    return {
        "question": {
            "id": record.question.id,
            "category": record.question.category,
            "question": record.question.question,
            "expected_elements": list(record.question.expected_elements),
            "related_evidence": list(record.question.related_evidence or []),
            "related_requirement": record.question.related_requirement,
            "difficulty": record.question.difficulty,
            "time_estimate_seconds": record.question.time_estimate_seconds,
        },
        "keyword_groups": [list(group) for group in record.keyword_groups],
        "pedagogical_source": record.pedagogical_source,
        "suggested_structure": record.suggested_structure,
        "evidence_quotes": list(record.evidence_quotes),
        "bank": record.bank,
    }


def _prep_question_from_payload(payload: Mapping[str, Any]) -> PrepQuestion:
    question = payload.get("question") or {}
    return PrepQuestion(
        question=InterviewQuestion(
            id=clean_text(question.get("id"), limit=120),
            category=clean_text(question.get("category"), limit=40) or "technical",  # type: ignore[arg-type]
            question=clean_text(question.get("question"), limit=600),
            expected_elements=[clean_text(item, limit=300) for item in question.get("expected_elements") or []],
            related_evidence=[clean_text(item, limit=120) for item in question.get("related_evidence") or []] or None,
            related_requirement=clean_text(question.get("related_requirement"), limit=120) or None,
            difficulty=clean_text(question.get("difficulty"), limit=40) or "medium",  # type: ignore[arg-type]
            time_estimate_seconds=int(question.get("time_estimate_seconds") or 120),
        ),
        keyword_groups=tuple(tuple(group) for group in payload.get("keyword_groups") or []),
        pedagogical_source=clean_text(payload.get("pedagogical_source"), limit=400) or None,
        suggested_structure=clean_text(payload.get("suggested_structure"), limit=600),
        evidence_quotes=tuple(clean_text(item, limit=300) for item in payload.get("evidence_quotes") or []),
        bank=clean_text(payload.get("bank"), limit=80),
    )


def _session_from_payload(payload: Mapping[str, Any]) -> InterviewPrepSession:
    factsheet = payload.get("company_factsheet") or {}
    return InterviewPrepSession(
        session_id=clean_text(payload.get("session_id"), limit=80),
        offer_id=clean_text(payload.get("offer_id"), limit=80),  # type: ignore[arg-type]
        profile_id=clean_text(payload.get("profile_id"), limit=80),
        technical_questions=[_question_from_payload(item) for item in payload.get("technical_questions") or []],
        behavioral_questions=[_question_from_payload(item) for item in payload.get("behavioral_questions") or []],
        gap_questions=[_question_from_payload(item) for item in payload.get("gap_questions") or []],
        sensitive_points=[clean_text(item, limit=300) for item in payload.get("sensitive_points") or []],
        recruiter_questions=[clean_text(item, limit=300) for item in payload.get("recruiter_questions") or []],
        company_factsheet=CompanyFactsheet(
            name=clean_text(factsheet.get("name"), limit=240),
            sector=clean_text(factsheet.get("sector"), limit=240),
            size=clean_text(factsheet.get("size"), limit=120),
            recent_news=[clean_text(item, limit=300) for item in factsheet.get("recent_news") or []],
            culture_keywords=[clean_text(item, limit=120) for item in factsheet.get("culture_keywords") or []],
            interview_process=(
                [clean_text(item, limit=300) for item in factsheet.get("interview_process") or []]
                if factsheet.get("interview_process") is not None
                else None
            ),
            sources=[clean_text(item, limit=400) for item in factsheet.get("sources") or []],
        ),
        created_at=clean_text(payload.get("created_at"), limit=64),
    )


def _question_from_payload(payload: Mapping[str, Any]) -> InterviewQuestion:
    return InterviewQuestion(
        id=clean_text(payload.get("id"), limit=120),
        category=clean_text(payload.get("category"), limit=40) or "technical",  # type: ignore[arg-type]
        question=clean_text(payload.get("question"), limit=600),
        expected_elements=[clean_text(item, limit=300) for item in payload.get("expected_elements") or []],
        related_evidence=[clean_text(item, limit=120) for item in payload.get("related_evidence") or []] or None,
        related_requirement=clean_text(payload.get("related_requirement"), limit=120) or None,
        difficulty=clean_text(payload.get("difficulty"), limit=40) or "medium",  # type: ignore[arg-type]
        time_estimate_seconds=int(payload.get("time_estimate_seconds") or 120),
    )


def serialize_question(
    record: PrepQuestion,
) -> dict[str, Any]:
    """Serialize one prepared question with its pedagogical context."""
    payload = dict(_serialize_prep_question(record)["question"])
    payload.update(
        {
            "keyword_groups": [list(group) for group in record.keyword_groups],
            "pedagogical_source": record.pedagogical_source,
            "suggested_structure": record.suggested_structure,
            "evidence_quotes": list(record.evidence_quotes),
            "bank": record.bank,
            "bank_label": FINANCE_BANK_LABELS.get(record.bank, ""),
        }
    )
    return payload


def serialize_session(session: InterviewPrepSession) -> dict[str, Any]:
    """Serialize the public contract of a preparation session."""
    return {
        "session_id": session.session_id,
        "offer_id": session.offer_id,
        "profile_id": session.profile_id,
        "technical_questions": [
            {
                "id": question.id,
                "category": question.category,
                "question": question.question,
                "expected_elements": list(question.expected_elements),
                "related_evidence": list(question.related_evidence or []),
                "related_requirement": question.related_requirement,
                "difficulty": question.difficulty,
                "time_estimate_seconds": question.time_estimate_seconds,
            }
            for question in session.technical_questions
        ],
        "behavioral_questions": [
            {
                "id": question.id,
                "category": question.category,
                "question": question.question,
                "expected_elements": list(question.expected_elements),
                "related_evidence": list(question.related_evidence or []),
                "related_requirement": question.related_requirement,
                "difficulty": question.difficulty,
                "time_estimate_seconds": question.time_estimate_seconds,
            }
            for question in session.behavioral_questions
        ],
        "gap_questions": [
            {
                "id": question.id,
                "category": question.category,
                "question": question.question,
                "expected_elements": list(question.expected_elements),
                "related_evidence": list(question.related_evidence or []),
                "related_requirement": question.related_requirement,
                "difficulty": question.difficulty,
                "time_estimate_seconds": question.time_estimate_seconds,
            }
            for question in session.gap_questions
        ],
        "sensitive_points": list(session.sensitive_points),
        "recruiter_questions": list(session.recruiter_questions),
        "company_factsheet": {
            "name": session.company_factsheet.name,
            "sector": session.company_factsheet.sector,
            "size": session.company_factsheet.size,
            "recent_news": list(session.company_factsheet.recent_news),
            "culture_keywords": list(session.company_factsheet.culture_keywords),
            "interview_process": (
                list(session.company_factsheet.interview_process)
                if session.company_factsheet.interview_process is not None
                else None
            ),
            "sources": list(session.company_factsheet.sources),
        },
        "created_at": session.created_at,
    }


def serialize_feedback(feedback: SimulationFeedback) -> dict[str, Any]:
    """Serialize the public contract of a simulation feedback."""
    return {
        "question_id": feedback.question_id,
        "user_answer": feedback.user_answer,
        "score": feedback.score,
        "strengths": list(feedback.strengths),
        "missing_elements": list(feedback.missing_elements),
        "unproven_claims": list(feedback.unproven_claims),
        "suggested_structure": feedback.suggested_structure,
        "retry_prompt": feedback.retry_prompt,
        "pedagogical_source": feedback.pedagogical_source,
    }


def render_markdown(preparation: Preparation, simulations: Sequence[Mapping[str, Any]] = ()) -> str:
    """Render the preparation as the local Markdown subset used for exports.

    Only headings, bullets and paragraphs are produced, so the result can be
    written as Markdown or as a PDF by ``career.document_export`` without any
    external or executable content.
    """
    session = preparation.session
    factsheet = session.company_factsheet
    company = clean_text(preparation.offer.get("company"), limit=240) or factsheet.name
    title = clean_text(preparation.offer.get("title"), limit=300) or "Poste ciblé"
    lines: list[str] = [
        f"# Préparation d'entretien — {company} — {title}",
        "",
        "Préparation locale et déterministe, construite à partir de l'offre sélectionnée et de ton profil. "
        "Elle n'invente aucun fait et ne prédit aucun résultat de recrutement.",
        "",
        f"- Entreprise : {company}",
        f"- Poste : {title}",
        f"- Mode : {preparation.mode}",
        f"- Session : {session.session_id}",
        f"- Créée le : {session.created_at}",
        "",
    ]

    def question_block(index: int, record: PrepQuestion) -> list[str]:
        question = record.question
        block = [f"### {index}. {question.question}", ""]
        block.append(f"- Difficulté : {question.difficulty} · Temps conseillé : {question.time_estimate_seconds} s")
        if question.related_requirement:
            block.append(f"- Exigence liée : {question.related_requirement}")
        if question.related_evidence:
            block.append(f"- Preuves profil : {', '.join(question.related_evidence)}")
        for quote in record.evidence_quotes:
            block.append(f"- Extrait de profil : « {quote} »")
        for element in question.expected_elements:
            block.append(f"- Attendu : {element}")
        if record.pedagogical_source:
            block.append(f"- Source pédagogique : {record.pedagogical_source}")
        block.append(f"- Structure suggérée : {record.suggested_structure}")
        block.append("")
        return block

    for title_text, records in (
        ("Questions techniques", [preparation.questions[q.id] for q in session.technical_questions if q.id in preparation.questions]),
        ("Questions comportementales", [preparation.questions[q.id] for q in session.behavioral_questions if q.id in preparation.questions]),
        ("Questions sur les écarts CV / offre", [preparation.questions[q.id] for q in session.gap_questions if q.id in preparation.questions]),
    ):
        lines.append(f"## {title_text}")
        lines.append("")
        if not records:
            lines.append("- Aucune question dans cette catégorie pour cette offre.")
            lines.append("")
            continue
        for index, record in enumerate(records, start=1):
            lines.extend(question_block(index, record))

    lines.append("## Points sensibles du CV")
    lines.append("")
    if session.sensitive_points:
        lines.extend(f"- {point}" for point in session.sensitive_points)
    else:
        lines.append("- Aucun point sensible détecté à partir des données locales.")
    lines.append("")

    lines.append("## Questions à poser au recruteur")
    lines.append("")
    if session.recruiter_questions:
        lines.extend(f"- {question}" for question in session.recruiter_questions)
    else:
        lines.append("- Aucune question préparée.")
    lines.append("")

    lines.append("## Fiche entreprise")
    lines.append("")
    lines.append(f"- Entreprise : {factsheet.name}")
    lines.append(f"- Secteur : {factsheet.sector}")
    lines.append(f"- Taille : {factsheet.size}")
    lines.append(
        "- Actualités : aucune donnée locale disponible "
        "(cet outil ne consult aucun service externe pour cette section)."
    )
    lines.append(
        "- Mots-clés de culture : "
        + (", ".join(factsheet.culture_keywords) if factsheet.culture_keywords else "aucun mot-clé détecté dans l’offre")
    )
    if factsheet.interview_process:
        lines.append("- Process d'entretien mentionné dans l'offre :")
        lines.extend(f"  {step}" for step in factsheet.interview_process)
    else:
        lines.append("- Process d'entretien : non renseigné par l'offre.")
    lines.append("- Sources : " + ", ".join(factsheet.sources))
    lines.append("")

    lines.append("## Historique des simulations")
    lines.append("")
    if simulations:
        for entry in simulations:
            feedback = entry.get("feedback") or {}
            created_at = clean_text(entry.get("created_at"), limit=64)
            question_id = clean_text(entry.get("question_id"), limit=120)
            score = clean_text(feedback.get("score") or entry.get("score"), limit=40)
            lines.append(f"- {created_at} · {question_id} · score : {score}")
    else:
        lines.append("- Aucune simulation enregistrée pour cette préparation.")
    lines.append("")
    return "\n".join(lines)


__all__ = [
    "BEHAVIORAL_SOURCE",
    "CATEGORIES",
    "CompanyFactsheet",
    "FINANCE_BANKS",
    "FINANCE_BANK_LABELS",
    "InterviewPrepSession",
    "InterviewQuestion",
    "LOCAL_PROFILE_IDS",
    "MODES",
    "PrepContext",
    "PrepQuestion",
    "Preparation",
    "SimulationFeedback",
    "bind_default_context",
    "build_preparation",
    "default_context",
    "generate",
    "render_markdown",
    "serialize_feedback",
    "serialize_question",
    "serialize_session",
    "simulate",
]
