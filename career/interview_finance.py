"""Versioned finance interview bank + deterministic local rubric simulator.

Companion of :mod:`career.finance_lexicon` for the finance sector layer
(CVBOOST-76 / SPEC-041).  Everything is local and deterministic:

- ``QUESTION_BANK`` — a versioned bank of ≥ 120 questions split across four
  families (corporate valuation, markets, corporate finance, behavioral) and
  three seniority levels, editable in plain Python literals.
- ``draw_sequence`` — picks and orders questions for a role/seniority using a
  stable seed (explicit or derived), never a model call.
- ``score_answer`` — a local rubric (completeness, structure, precision) with
  deterministic weights and human-readable feedback.  It is feedback on one
  free-form answer against one question; it is never an external AI grade nor
  a recruiting prediction.
- ``faq_entries`` — flat question records for the FAQ module (CVBOOST-66) to
  display finance preparation entries.
"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import random
from typing import Any, Iterable

from .finance_lexicon import resolve_role
from .models import normalized_text

BANK_VERSION = "1.1.0"

FAMILIES: dict[str, str] = {
    "corporate": "Corporate / valorisation (DCF, comps, accretion, LBO)",
    "markets": "Marchés (FX, taux, pricing)",
    "corporate_finance": "Corporate finance (BFR, IFRS, comptabilité)",
    "behavioral": "Behavioral (STAR, motivation)",
}

SENIORITY_LEVELS: tuple[str, ...] = ("stage", "analyst", "associate")
_SENIORITY_RANK = {level: rank for rank, level in enumerate(SENIORITY_LEVELS)}

RUBRIC_WEIGHTS = {"completeness": 0.5, "structure": 0.3, "precision": 0.2}

MIN_ANSWER_WORDS = 8

_STRUCTURE_MARKERS: dict[str, tuple[str, ...]] = {
    "fr": ("d abord", "premier", "premiere", "ensuite", "puis", "enfin", "parce que",
           "donc", "cependant", "ainsi", "en resume", "conclusion"),
    "en": ("first", "second", "then", "finally", "because", "therefore", "however",
           "as a result", "in summary", "to conclude"),
}


@dataclass(frozen=True)
class FinanceQuestion:
    """One versioned interview question.

    ``keyword_groups`` drive the completeness axis of the rubric: each group
    is a set of acceptable synonyms for one reference idea of the answer.
    """

    id: str
    family: str
    topic: str
    seniority: str
    prompt_fr: str
    prompt_en: str
    keyword_groups: tuple[tuple[str, ...], ...]
    reference_points: tuple[str, ...]


def _q(
    identifier: str,
    family: str,
    topic: str,
    seniority: str,
    prompt_fr: str,
    prompt_en: str,
    groups: Iterable[Iterable[str]],
    points: Iterable[str],
) -> FinanceQuestion:
    if isinstance(groups, str):
        raise TypeError("_q attend des groupes sous forme d'itérables de chaînes")
    return FinanceQuestion(
        id=identifier,
        family=family,
        topic=topic,
        seniority=seniority,
        prompt_fr=prompt_fr,
        prompt_en=prompt_en,
        keyword_groups=tuple(tuple(group) for group in groups),
        reference_points=tuple((points,) if isinstance(points, str) else points),
    )


QUESTION_BANK: tuple[FinanceQuestion, ...] = (
    # --- corporate / DCF -----------------------------------------------------
    _q("corp_dcf_01", "corporate", "dcf", "stage",
       "À quoi sert une valorisation DCF et quelles sont ses grandes étapes ?",
       "What is a DCF valuation used for and what are its main steps?",
       (("flux", "cash flow", "fcf", "tresorerie"), ("actualis", "discount", "wacc"), ("valeur", "valuation")),
       ("Projeter les flux disponibles, les actualiser au WACC, additionner la valeur terminale.")),
    _q("corp_dcf_02", "corporate", "dcf", "stage",
       "Qu'est-ce que le free cash flow et comment le calcule-t-on simplement ?",
       "What is free cash flow and how do you compute it simply?",
       (("ebit", "resultat operationnel", "operating"), ("impot", "tax", "is"), ("capex", "investissement", "bfr")),
       ("EBIT après impôt, plus amortissements, moins capex et variation de BFR.")),
    _q("corp_dcf_03", "corporate", "dcf", "stage",
       "Pourquoi actualise-t-on les flux futurs dans un DCF ?",
       "Why do you discount future cash flows in a DCF?",
       (("temps", "temps", "horizon"), ("risque", "prime de risque", "incertitude"), ("wacc", "coût du capital", "cout du capital")),
       ("Un euro futur vaut moins qu'un euro présent ; le taux reflète le risque et le coût du capital.")),
    _q("corp_dcf_04", "corporate", "dcf", "analyst",
       "Comment calculeriez-vous le WACC et quelles en sont les limites ?",
       "How would you compute the WACC and what are its limitations?",
       (("poids", "poids", "structure"), ("cout", "cost", "equity", "dette", "debt"), ("limite", "hypothese", "hypothèse")),
       ("Moyenne pondérée du coût des capitaux propres et de la dette après impôt ; sensible aux hypothèses.")),
    _q("corp_dcf_05", "corporate", "dcf", "analyst",
       "Quelles sont les deux méthodes de calcul de la valeur terminale d'un DCF ?",
       "What are the two methods to compute a DCF terminal value?",
       (("perpetuite", "perpetuity", "gordon"), ("multiple", "sortie", "exit"), ("hypothese", "assumption", "croissance")),
       ("Croissance à l'infini (Gordon) ou multiple de sortie ; toujours vérifier la cohérence entre les deux.")),
    _q("corp_dcf_06", "corporate", "dcf", "analyst",
       "Comment passe-t-on de la valeur d'entreprise à la valeur des capitaux propres ?",
       "How do you bridge from enterprise value to equity value?",
       (("dette", "debt", "dette nette"), ("tresorerie", "cash"), ("minoritaire", "minority", "pension")),
       ("EV + trésorerie − dette nette − créances minoritaires et autres ajustements.")),
    _q("corp_dcf_07", "corporate", "dcf", "associate",
       "Un DCF donne une valeur très supérieure au marché : comment investigatez-vous l'écart ?",
       "A DCF gives a value far above market: how do you investigate the gap?",
       (("hypothese", "hypothèses", "assumption"), ("sensibilite", "sensibilité", "sensitivity"), ("marche", "comps", "marché")),
       ("Revoir croissance, marges, WACC ; tester des sensibilités ; comparer aux multiples de marché.")),
    _q("corp_dcf_08", "corporate", "dcf", "associate",
       "Quel effet une hausse de taux de 100 bp a-t-elle sur un DCF ?",
       "What effect does a 100 bp rate increase have on a DCF?",
       (("wacc", "actualis", "discount"), ("valeur", "valuation", "baisse"), ("sensibilite", "duration", "sensibilité")),
       ("Le WACC monte, les valeurs actualisées baissent, surtout la valeur terminale ; quantifier avec une sensibilité.")),
    _q("corp_dcf_09", "corporate", "dcf", "analyst",
       "Pourquoi un DCF est-il dit « intrinsèque » par rapport aux multiples ?",
       "Why is a DCF called intrinsic compared with multiples?",
       (("intrinseque", "intrinsèque", "intrinsic"), ("flux", "cash flow"), ("marche", "comps", "marché")),
       ("Le DCF valorise les flux propres de l'entreprise ; les multiples reflètent les prix du marché.")),
    _q("corp_dcf_10", "corporate", "dcf", "stage",
       "Qu'est-ce que la valeur terminale et pourquoi représente-t-elle souvent la moitié de la valeur ?",
       "What is terminal value and why is it often half the value?",
       (("terminale", "terminal"), ("horizon", "projection"), ("part", "moitie", "moitié")),
       ("C'est la valeur au-delà de l'horizon projeté ; sensible à la croissance et au taux, elle domine souvent le total.")),
    _q("corp_dcf_11", "corporate", "dcf", "analyst",
       "Qu'est-ce que le flux disponible pour les actionnaires (FCFE) par rapport au FCFF ?",
       "What is FCFE compared with FCFF?",
       (("fcff", "firm", "entreprise"), ("fcfe", "actionnaire", "equity"), ("dette", "emprunt", "remboursement")),
       ("Le FCFF sert tous les apporteurs de capitaux ; le FCFE reste aux actionnaires après dette et emprunts.")),
    _q("corp_dcf_12", "corporate", "dcf", "associate",
       "Comment traiteriez-vous une entreprise non rentable dans un DCF ?",
       "How would you treat an unprofitable company in a DCF?",
       (("marge", "croissance", "payback"), ("horizon", "normalis"), ("scenarios", "scénarios")),
       ("Projeter la montée en marge sur un horizon plus long, ou basculer sur d'autres méthodes et scénarios.")),
    # --- corporate / comps ---------------------------------------------------
    _q("corp_comps_01", "corporate", "comps", "stage",
       "Qu'est-ce qu'une analyse de comparables (« comps ») ?",
       "What is a trading comparables analysis?",
       (("comparables", "comps", "pairs"), ("multiple", "ebitda", "ebit"), ("marche", "marché", "market")),
       ("Comparer les multiples de sociétés similaires cotées pour déduire une fourchette de valeur.")),
    _q("corp_comps_02", "corporate", "comps", "stage",
       "Pourquoi utilise-t-on EV/EBITDA plutôt que P/E pour comparer des entreprises ?",
       "Why use EV/EBITDA rather than P/E to compare companies?",
       (("structure", "capital", "dette"), ("ebitda", "exploitation", "operating"), ("pe", "p e", "equity")),
       ("EV/EBITDA est neutre à la structure de capital ; P/E dépend de l'effet de levier et de l'impôt.")),
    _q("corp_comps_03", "corporate", "comps", "stage",
       "Citez trois critères pour choisir un panel de comparables.",
       "Name three criteria to select a peer group.",
       (("secteur", "sector", "activite"), ("taille", "size", "chiffre d affaires"), ("croissance", "marge", "geographie")),
       ("Même secteur, taille comparable, profil de croissance et de marge similaire.")),
    _q("corp_comps_04", "corporate", "comps", "analyst",
       "Qu'est-ce qu'un multiple de transactions passées et en quoi diffère-t-il des comps de marché ?",
       "What is a precedent transaction multiple and how does it differ from trading comps?",
       (("transaction", "acquisition", "acquéreur"), ("prime", "premium", "controle"), ("marche", "comps")),
       ("Les transactions passées intègrent une prime de contrôle et des synergies ; elles sont souvent plus élevées.")),
    _q("corp_comps_05", "corporate", "comps", "analyst",
       "Comment ajustez-vous des comparables dont les exercices ne coïncident pas ?",
       "How do you handle peers whose fiscal years do not align?",
       (("calendaris", "calendris", "pro forma"), ("ltm", "douze mois", "ntm"), ("coherence", "cohérence")),
       ("Recaler sur LTM ou NTM, ou sur le même exercice pro forma ; documenter la convention.")),
    _q("corp_comps_06", "corporate", "comps", "analyst",
       "Un comparable a une croissance bien supérieure : comment l'intégrer au panel ?",
       "A peer grows much faster: how do you integrate it into the panel?",
       (("croissance", "growth"), ("ecarter", "exclure", "ajuster"), ("mediane", "médiane", "median")),
       ("L'exclure ou l'ajuster, et privilégier la médiane pour limiter les effets extrêmes.")),
    _q("corp_comps_07", "corporate", "comps", "associate",
       "Quels pièges voyez-vous dans un multiple EV/EBITDA négatif ou très élevé ?",
       "What pitfalls do you see with a negative or very high EV/EBITDA multiple?",
       (("ebitda", "negatif", "faible"), ("distors", "biais", "outlier"), ("interpret", "analyse")),
       ("EBITDA déprimé ou non récurrent ; analyser la normalisation avant de conclure.")),
    # --- corporate / accretion ----------------------------------------------
    _q("corp_accretion_01", "corporate", "accretion", "analyst",
       "Quand une acquisition est-elle dilutive au résultat par action ?",
       "When is an acquisition dilutive to EPS?",
       (("action", "eps", "resultat par action"), ("dette", "financement", "actions"), ("synergie", "cout", "coût")),
       ("Quand le résultat net acquis est inférieur au coût de financement et à la dilution du nombre d'actions.")),
    _q("corp_accretion_02", "corporate", "accretion", "analyst",
       "Décrivez la mécanique d'un modèle d'accrétion/dilution simple.",
       "Describe the mechanics of a simple accretion/dilution model.",
       (("prix", "acquisition", "offre"), ("financement", "dette", "actions"), ("resultat", "eps", "pro forma")),
       ("Prix payé, structure de financement, résultat pro forma combiné, nouvel EPS par action.")),
    _q("corp_accretion_03", "corporate", "accretion", "associate",
       "Pourquoi payer en actions est-il moins accréteur qu'en cash en général ?",
       "Why is a share-funded deal generally less accretive than a cash deal?",
       (("actions", "nouveles", "nouvelles"), ("dilution", "nombre"), ("cash", "interet", "intérêt")),
       ("De nouvelles actions sont émises ; le cash coûte un intérêt après impôt souvent plus faible.")),
    _q("corp_accretion_04", "corporate", "accretion", "associate",
       "Quel rôle jouent les synergies dans l'accrétion et quel risque présentent-elles ?",
       "What role do synergies play in accretion and what risk do they carry?",
       (("synergie", "synergies"), ("cout", "coût", "revenu"), ("realisation", "execution", "risque")),
       ("Elles améliorent le résultat combiné, mais leur réalisation est incertaine et souvent tardive.")),
    _q("corp_accretion_05", "corporate", "accretion", "analyst",
       "Comment le goodwill naît-il dans une acquisition ?",
       "How does goodwill arise in an acquisition?",
       (("prix", "juste valeur", "fair value"), ("actif net", "actifs", "reprise"), ("goodwill")),
       ("Goodwill = prix payé moins juste valeur de l'actif net repris ; non amortissable mais testé.")),
    # --- corporate / LBO ------------------------------------------------------
    _q("corp_lbo_01", "corporate", "lbo", "stage",
       "Qu'est-ce qu'un LBO et quels sont ses leviers de rendement ?",
       "What is an LBO and what are its return levers?",
       (("dette", "levier", "leverage"), ("ebitda", "croissance", "marge"), ("multiple", "sortie", "exit")),
       ("Croissance de l'EBITDA, désendettement et évolution du multiple de sortie.")),
    _q("corp_lbo_02", "corporate", "lbo", "stage",
       "Pourquoi le private equity préfère-t-il les entreprises générant du cash ?",
       "Why does private equity prefer cash-generating companies?",
       (("cash", "tresorerie", "trésorerie"), ("dette", "rembours", "desendette"), ("interet", "intérêt")),
       ("Le cash sert à rembourser la dette et à financer la croissance sans nouvel apport.")),
    _q("corp_lbo_03", "corporate", "lbo", "analyst",
       "Quels sont les éléments clés d'une feuille LBO simplifiée ?",
       "What are the key parts of a simple LBO model?",
       (("entree", "entree", "entry"), ("dette", "schedule", "remboursement"), ("sortie", "exit", "retour", "irr")),
       ("Prix d'entrée et structure de dette, génération de cash, scénario de sortie et TRI.")),
    _q("corp_lbo_04", "corporate", "lbo", "analyst",
       "Quels risques vérifiez-vous avant de lever la dette d'un LBO ?",
       "Which risks do you check before raising LBO debt?",
       (("covenant", "clause"), ("downside", "scenarios", "scénarios"), ("interet", "taux", "intérêt")),
       ("Covenants, génération de cash en scénario adverse, coût et structure du taux.")),
    _q("corp_lbo_05", "corporate", "lbo", "associate",
       "Comment calcule-t-on le TRI d'un LBO et quelles hypothèses le rendent fragile ?",
       "How is LBO IRR computed and which assumptions make it fragile?",
       (("irr", "tri", "retour"), ("sortie", "exit", "multiple"), ("hypothese", "sensibilite")),
       ("Le TRI dépend surtout du multiple de sortie et de la dette : tester les sensibilités.")),
    _q("corp_comps_08", "corporate", "comps", "stage",
       "Qu'est-ce qu'un multiple EV/Sales et quand l'utilise-t-on ?",
       "What is an EV/Sales multiple and when is it used?",
       (("chiffre", "sales", "ca"), ("perte", "ebitda negatif"), ("croissance")),
       ("Utile pour les sociétés peu rentables ou en forte croissance, complété par des comps de marge.")),
    _q("corp_comps_09", "corporate", "comps", "stage",
       "Qu'est-ce que la décote de holding dans un comps de conglomérat ?",
       "What is the holding discount in a conglomerate peer set?",
       (("conglomerat", "conglomérat"), ("decote", "décote"), ("nav", "somme")),
       ("Le marché valorise moins que la somme des parties, faute de transparence et de flexibilité du capital.")),
    _q("corp_comps_10", "corporate", "comps", "analyst",
       "Comment construisez-vous une somme de parties (SOTP) ?",
       "How do you build a sum-of-the-parts (SOTP) valuation?",
       (("segment", "division", "metier"), ("multiple", "nav"), ("decote", "consolidation")),
       ("Valoriser chaque segment avec ses propres comps, puis appliquer décote de holding et déconsolidation.")),
    _q("corp_comps_11", "corporate", "comps", "analyst",
       "Pourquoi les multiples de croissance élevée sont-ils plus élevés ?",
       "Why do high-growth companies trade at higher multiples?",
       (("croissance", "growth"), ("durée", "value", "actualis"), ("comparab")),
       ("Une croissance plus longue du flux justifie un prix par unité de profit plus élevé, à risque égal.")),
    _q("corp_comps_12", "corporate", "comps", "associate",
       "Comment vérifiez-vous la cohérence d'un panel de comps entre secteurs cycliques et défensifs ?",
       "How do you keep a peer set coherent between cyclical and defensive sectors?",
       (("cyclique", "defensif", "conjoncture"), ("normalis", "moyenne cycles"), ("mix", "segment")),
       ("Séparer les profils ou normaliser sur moyenne de cycle ; ne jamais mélanger sans ajustement.")),
    _q("corp_accretion_06", "corporate", "accretion", "stage",
       "Qu'est-ce que l'accrétion au résultat par action en une phrase ?",
       "What is EPS accretion in one sentence?",
       (("eps", "resultat par action"), ("hausse", "augmentation"), ("acquisition")),
       ("Une opération est accrétrice quand le nouvel EPS après acquisition est supérieur à l'ancien.")),
    _q("corp_accretion_07", "corporate", "accretion", "stage",
       "Qu'est-ce que le price paid sur un multiple d'acquisition ?",
       "What is the price paid multiple in an acquisition?",
       (("prix", "ev"), ("ebitda", "metrique"), ("annonce", "cible")),
       ("Le multiple implicite payé : EV de l'offre divisé par la métrique de la cible.")),
    _q("corp_accretion_08", "corporate", "accretion", "analyst",
       "Comment les frais de transaction entrent-ils dans un modèle d'accrétion ?",
       "How do transaction fees enter an accretion model?",
       (("frais", "fees", "conseil"), ("capitalise", "amortis"), ("pontable", "pontable", "writeup")),
       ("Ils sont capitalisés et amortis, ou passés en charges ; ils pèsent sur le résultat pro forma.")),
    _q("corp_accretion_09", "corporate", "accretion", "analyst",
       "Qu'est-ce que l'écriture de réévaluation (write-up) d'actifs et son effet ?",
       "What is an asset write-up and its effect?",
       (("reevalu", "réévalu", "write up"), ("amortis", "supplementaire"), ("impot", "differe")),
       ("La juste valeur des actifs repris crée des amortissements supplémentaires et un impôt différé.")),
    _q("corp_accretion_10", "corporate", "accretion", "associate",
       "Comment tester la sensibilité d'une accretion au prix payé ?",
       "How do you test accretion sensitivity to the price paid?",
       (("sensibilite", "tableau", "data"), ("prix", "multiple"), ("seuil", "breakeven")),
       ("Un tableau à deux entrées prix × financement révèle le seuil d'accrétion (breakeven).")),
    _q("corp_accretion_11", "corporate", "accretion", "associate",
       "Pourquoi une opération accrétrice peut-elle rester une mauvaise décision ?",
       "Why can an accretive deal still be a bad decision?",
       (("valeur", "creation", "npv"), ("strategie", "stratégique"), ("prix", "paye", "payé")),
       ("L'accrétion comptable ignore le prix payé et la création de valeur ; une opération chère peut rester accrétrice.")),
    _q("corp_accretion_12", "corporate", "accretion", "associate",
       "Quel est l'effet d'un crédit d'impôt différé sur l'accrétion ?",
       "What is the effect of a deferred tax asset on accretion?",
       (("impot", "differé", "differre"), ("actif", "dta"), ("resultat")),
       ("Un actif d'impôt différé réduit la charge fiscale future et améliore le résultat pro forma.")),
    _q("corp_lbo_06", "corporate", "lbo", "stage",
       "Qu'est-ce qu'un covenant bancaire et à quoi sert-il ?",
       "What is a bank covenant and what is it for?",
       (("covenant", "clause"), ("ratio", "levier"), ("alerte", "renegociation")),
       ("Une clause contractuelle qui plafonne le levier ou protège la liquidité ; sa violation déclenche une renégociation.")),
    _q("corp_lbo_07", "corporate", "lbo", "stage",
       "Qu'est-ce que le prix d'entrée implicite d'un LBO ?",
       "What is the implied entry price of an LBO?",
       (("entree", "ev"), ("ebitda", "multiple"), ("dette", "equity")),
       ("EV d'entrée divisé par l'EBITDA : somme de la dette et des fonds propres investis.")),
    _q("corp_lbo_08", "corporate", "lbo", "analyst",
       "Comment la dette senior se différencie-t-elle du mezzanine dans un LBO ?",
       "How does senior debt differ from mezzanine in an LBO?",
       (("senior", "priorite"), ("mezzanine", "subordonne"), ("coupon", "piquet", "kicker")),
       ("La dette senior est prioritaire et moins chère ; la mezzanine est subordonnée avec coupon élevé ou equity kicker.")),
    _q("corp_lbo_09", "corporate", "lbo", "analyst",
       "Qu'est-ce qu'un test de couverture des intérêts (interest cover) ?",
       "What is an interest coverage test?",
       (("ebitda", "interet"), ("couverture", "ratio"), ("seuil", "covenant")),
       ("EBITDA divisé par les intérêts : un ratio bas signale la sensibilité à une hausse de taux.")),
    _q("corp_lbo_10", "corporate", "lbo", "associate",
       "Comment un exit multiple inférieur à l'entry multiple affecte-t-il le TRI ?",
       "How does an exit multiple below the entry multiple affect IRR?",
       (("multiple", "contraction"), ("irr", "tri"), ("dette", "desendette")),
       ("La contraction du multiple pèse sur le TRI, partiellement compensée par le désendettement et l'EBITDA.")),
    _q("corp_lbo_11", "corporate", "lbo", "associate",
       "Qu'est-ce qu'un management package (roll-over, earn-out) dans un LBO ?",
       "What is a management package (roll-over, earn-out) in an LBO?",
       (("management", "dirigeant"), ("rollover", "reinvest"), ("earn out", "bonus")),
       ("Les dirigeants réinvestissent et perçoivent un plan partageant la valeur créée à la sortie.")),
    _q("corp_lbo_12", "corporate", "lbo", "associate",
       "Pourquoi la duration de la dette importe-t-elle au moment de la sortie ?",
       "Why does debt maturity matter at exit time?",
       (("maturite", "refinancement"), ("sortie", "fenetre", "window"), ("refinanc")),
       ("Une dette qui arrive à échéance avant la sortie force un refinancement ou une vente contrainte.")),
    # --- markets / FX ---------------------------------------------------------
    _q("mkt_fx_01", "markets", "fx", "stage",
       "Qu'est-ce qu'une paire de devises et que signifie EUR/USD = 1,10 ?",
       "What is a currency pair and what does EUR/USD = 1.10 mean?",
       (("paire", "pair"), ("base", "euro"), ("cotation", "quote")),
       ("Un euro s'échange contre 1,10 dollar ; la première devise est la base.")),
    _q("mkt_fx_02", "markets", "fx", "stage",
       "Qu'est-ce que le pip et le spread sur le marché des changes ?",
       "What are a pip and the spread in FX markets?",
       (("pip", "point"), ("spread", "bid", "ask"), ("liquidite", "liquidité")),
       ("Le pip est l'incrément de cotation ; le spread sépare achat et vente et reflète la liquidité.")),
    _q("mkt_fx_03", "markets", "fx", "stage",
       "Qu'est-ce qu'une couverture de change simple pour un exportateur ?",
       "What is a simple FX hedge for an exporter?",
       (("forward", "terme"), ("risque", "exposition"), ("couverture", "hedge")),
       ("Vendre à terme le montant de la créance pour figurer le taux de conversion.")),
    _q("mkt_fx_04", "markets", "fx", "analyst",
       "Qu'est-ce que la parité couverte entre taux et forward FX ?",
       "What is covered interest parity between rates and FX forwards?",
       (("forward", "terme"), ("taux", "differentiel", "differentiels"), ("arbitrage")),
       ("Le forward suit le différentiel de taux ; tout écart crée un arbitrage sans risque.")),
    _q("mkt_fx_05", "markets", "fx", "analyst",
       "Comment une hausse de taux de la Fed affecte-t-elle le dollar ?",
       "How does a Fed rate hike affect the dollar?",
       (("taux", "hike", "hausse"), ("capital", "flux", "rendement"), ("dollar", "usd")),
       ("Des rendements plus élevés attirent les capitaux et soutiennent le dollar, toutes choses égales.")),
    _q("mkt_fx_06", "markets", "fx", "associate",
       "Quels risques de change pour une entreprise facturant en dollars et vendant en euros ?",
       "What FX risks face a company billing in dollars and selling in euros?",
       (("exposition", "transaction"), ("marge", "translation"), ("couverture", "hedging")),
       ("Risque de transaction sur les encaisses dollars et de translation sur les comptes consolidés.")),
    # --- markets / rates ------------------------------------------------------
    _q("mkt_rates_01", "markets", "rates", "stage",
       "Quelle est la relation entre le prix d'une obligation et son taux ?",
       "What is the relationship between a bond's price and its yield?",
       (("prix", "obligation", "bond"), ("taux", "yield", "rendement"), ("inverse")),
       ("Elles varient en sens inverse : le prix monte quand le taux baisse.")),
    _q("mkt_rates_02", "markets", "rates", "stage",
       "Qu'est-ce que la maturité d'une obligation et la courbe des taux ?",
       "What are a bond's maturity and the yield curve?",
       (("maturite", "maturité", "échéance"), ("courbe", "curve"), ("taux")),
       ("La maturité est l'échéance de remboursement ; la courbe relie les taux aux maturités.")),
    _q("mkt_rates_03", "markets", "rates", "analyst",
       "Que signifie une courbe des taux inversée ?",
       "What does an inverted yield curve signal?",
       (("inversee", "inversée", "inverted"), ("recession", "croissance", "ralentissement"), ("anticipation", "expectation")),
       ("Les taux courts dépassent les longs : le marché anticipe un ralentissement et des baisses de taux.")),
    _q("mkt_rates_04", "markets", "rates", "analyst",
       "Qu'est-ce que le duration d'une obligation et pourquoi est-il important ?",
       "What is a bond's duration and why does it matter?",
       (("duration", "sensibilite"), ("taux", "variation"), ("maturite", "coupon")),
       ("La duration mesure la sensibilité du prix aux taux : plus elle est longue, plus le risque taux est fort.")),
    _q("mkt_rates_05", "markets", "rates", "associate",
       "Comment le resserrement quantitatif influence-t-il les taux longs ?",
       "How does quantitative tightening influence long rates?",
       (("qt", "resserrement", "balance"), ("offre", "demande"), ("prime", "term premium", "terme")),
       ("Moins d'achats de la banque centrale élargit l'offre nette et relève la prime de terme.")),
    # --- markets / pricing ----------------------------------------------------
    _q("mkt_pricing_01", "markets", "pricing", "stage",
       "Qu'est-ce qu'un ordre au marché et un ordre à cours limité ?",
       "What are a market order and a limit order?",
       (("marche", "marché", "execution"), ("limite", "prix"), ("risque")),
       ("L'ordre au marché s'exécute immédiatement au meilleur prix ; l'ordre limité fixe un prix plafond ou plancher.")),
    _q("mkt_pricing_02", "markets", "pricing", "stage",
       "Qu'est-ce que le bid-ask spread et d'où vient-il ?",
       "What is the bid-ask spread and where does it come from?",
       (("bid", "ask", "achat"), ("vente", "spread"), ("risque", "inventaire", "adverse")),
       ("Il rémunère le teneur de marché pour le risque d'inventaire et la sélection adverse.")),
    _q("mkt_pricing_03", "markets", "pricing", "analyst",
       "Comment estimer le juste prix d'une option avec un arbre binomial ?",
       "How do you price an option with a binomial tree?",
       (("arbre", "tree", "binomial"), ("neutre", "risque", "risk neutral"), ("actualis", "discount")),
       ("Construire l'arbre, évaluer en probabilité neutre au risque, actualiser pas à pas.")),
    _q("mkt_pricing_04", "markets", "pricing", "analyst",
       "Pourquoi la volatilité est-elle l'entrée la plus sensible d'un prix d'option ?",
       "Why is volatility the most sensitive input of an option price?",
       (("volatilite", "volatilité", "vol"), ("convexe", "gamma"), ("incertitude")),
       ("Le prix dépend du mouvement anticipé, difficile à observer ; la convexité amplifie son effet.")),
    _q("mkt_pricing_05", "markets", "pricing", "associate",
       "Comment le slippage apparaît-il lors de l'exécution de gros ordres ?",
       "How does slippage appear when executing large orders?",
       (("impact", "marche", "marché"), ("liquidite", "carnet", "book"), ("decoupage", "slicing")),
       ("Les gros ordres consomment le carnet et déplacent le prix ; on découpe l'exécution pour la limiter.")),
    _q("mkt_fx_07", "markets", "fx", "analyst",
       "Qu'est-ce que le triangle des devises (cross rates) et comment l'utiliser ?",
       "What is the FX cross rate and how do you use it?",
       (("croise", "cross"), ("dollar", "intermediaire"), ("arbitrage")),
       ("Un cross se déduit des deux paires contre le dollar ; un écart crée un arbitrage.")),
    _q("mkt_fx_08", "markets", "fx", "analyst",
       "Qu'est-ce qu'une option de change et quels usages pour une entreprise ?",
       "What is an FX option and what corporate uses does it have?",
       (("option", "prime", "premium"), ("protection", "participation"), ("taux d exercice", "strike")),
       ("Elle protège d'un mouvement défavorable en gardant le bénéfice du favorable, contre une prime.")),
    _q("mkt_fx_09", "markets", "fx", "associate",
       "Comment la NDF diffère-t-elle d'un forward livrable ?",
       "How does an NDF differ from a deliverable forward?",
       (("ndf", "non livre"), ("reglement", "settlement"), ("devise", "controle", "capital")),
       ("La NDF se règle en cash sur le différentiel, utile quand la devise n'est pas librement livrable.")),
    _q("mkt_fx_10", "markets", "fx", "associate",
       "Qu'est-ce que le carry trade et quel est son risque principal ?",
       "What is the carry trade and its main risk?",
       (("carry", "differentiel"), ("taux", "rendement"), ("retournement", "volatilite")),
       ("Emprunter en devise basse pour investir en devise haute ; le risque est un retournement brutal du change.")),
    _q("mkt_fx_11", "markets", "fx", "stage",
       "Qu'est-ce que la parité du pouvoir d'achat (PPP) en change ?",
       "What is purchasing power parity in FX?",
       (("pouvoir", "achat"), ("inflation", "prix"), ("long terme")),
       ("À long terme, le change suit l'écart d'inflation entre deux zones ; un repère, pas un outil de trading.")),
    _q("mkt_fx_12", "markets", "fx", "stage",
       "Qu'est-ce qu'un desk FX et quels clients sert-il ?",
       "What does an FX desk do and whom does it serve?",
       (("desk", "salle"), ("client", "corporate", "institutionnel"), ("liquidity", "prix")),
       ("Il cote, couvre et structure le risque de change pour corporates et institutionnels.")),
    _q("mkt_rates_06", "markets", "rates", "stage",
       "Qu'est-ce qu'un coupon zéro (zero coupon) et pourquoi est-il plus sensible aux taux ?",
       "What is a zero coupon and why is it more rate sensitive?",
       (("zero", "coupon"), ("actualis", "une fois"), ("duration")),
       ("Tout le flux est payé à l'échéance : sa duration vaut sa maturité, d'où une sensibilité maximale.")),
    _q("mkt_rates_07", "markets", "rates", "analyst",
       "Qu'est-ce que le spread de crédit et que mesure-t-il ?",
       "What is a credit spread and what does it measure?",
       (("spread", "credit"), ("defaut", "risque"), ("prime", "liquidite")),
       ("La rémunération additionnelle du risque de défaut et de liquidité par rapport au taux sans risque.")),
    _q("mkt_rates_08", "markets", "rates", "analyst",
       "Qu'est-ce qu'un swap de taux et à quoi sert-il pour une entreprise ?",
       "What is an interest rate swap and what is it for?",
       (("swap", "fixe", "flottant"), ("couverture", "exposition"), ("notionnel")),
       ("Échanger un taux fixe contre flottant pour transformer l'exposition de la dette.")),
    _q("mkt_rates_09", "markets", "rates", "associate",
       "Comment la convexité complète-t-elle la duration pour les gros mouvements de taux ?",
       "How does convexity complement duration for large rate moves?",
       (("convexite", "courbure"), ("duration", "lineaire"), ("correction")),
       ("La duration est une approximation linéaire ; la convexité corrige la courbure pour les grands écarts.")),
    _q("mkt_pricing_06", "markets", "pricing", "stage",
       "Qu'est-ce que la valeur temps d'une option ?",
       "What is the time value of an option?",
       (("intrinseque", "intrinsèque"), ("temps", "prime"), ("maturite")),
       ("La part de la prime au-dessus de la valeur intrinsèque, qui rémunère le mouvement restant jusqu'à l'échéance.")),
    _q("mkt_pricing_07", "markets", "pricing", "stage",
       "Qu'est-ce qu'un call et un put en une phrase chacun ?",
       "What are a call and a put, one sentence each?",
       (("call", "achat"), ("put", "vente"), ("exercise", "echeance")),
       ("Le call donne le droit d'acheter au strike ; le put le droit de vendre.")),
    _q("mkt_pricing_08", "markets", "pricing", "analyst",
       "Qu'est-ce que le delta d'une option et comment s'en sert-on pour couvrir ?",
       "What is an option's delta and how is it used for hedging?",
       (("delta", "sensibilite"), ("sous jacent", "sous-jacent"), ("couverture", "delta hedging")),
       ("Le delta mesure la sensibilité au sous-jacent ; on couvre en compensant cette exposition.")),
    _q("mkt_pricing_09", "markets", "pricing", "analyst",
       "Qu'est-ce qu'une surface de volatilité et que révèle le smile ?",
       "What is a volatility surface and what does the smile reveal?",
       (("surface", "volatilite"), ("smile", "skew"), ("prix", "marche")),
       ("La volatilité implicite varie par strike et maturité ; le smile révèle la demande de protection extrême.")),
    # --- corporate finance / working capital ---------------------------------
    _q("cf_wc_01", "corporate_finance", "working capital", "stage",
       "Qu'est-ce que le besoin en fonds de roulement (BFR) ?",
       "What is working capital need (BFR)?",
       (("bfr", "besoin", "fonds"), ("cycle", "exploitation"), ("stocks", "clients", "fournisseurs")),
       ("C'est le besoin de financing du cycle d'exploitation : stocks + créances − dettes fournisseurs.")),
    _q("cf_wc_02", "corporate_finance", "working capital", "stage",
       "Comment une hausse des délais clients affecte-t-elle la trésorerie ?",
       "How does longer customer payment terms affect cash?",
       (("clients", "délai", "delai"), ("tresorerie", "cash"), ("bfr")),
       ("Les créances restent plus longtemps ouvertes : le BFR monte et la trésorerie se dégrade.")),
    _q("cf_wc_03", "corporate_finance", "working capital", "analyst",
       "Quelles leviers pour réduire un BFR sans casser l'activité ?",
       "Which levers reduce working capital without hurting the business?",
       (("stocks", "rotation"), ("fournisseurs", "délai", "delai"), ("recouvrement", "facturation")),
       ("Rotation des stocks, négociation des délais fournisseurs, facturation et recouvrement plus rapides.")),
    _q("cf_wc_04", "corporate_finance", "working capital", "analyst",
       "Pourquoi le BFR saisonnier se finance-t-il par crédit court terme ?",
       "Why is seasonal working capital funded by short-term debt?",
       (("saisonnier", "saisonalite", "saisonnalité"), ("court terme", "ct"), ("revolving", "rcf")),
       ("Le besoin est temporaire : un revolving court terme évite d'immobiliser une dette longue.")),
    _q("cf_wc_05", "corporate_finance", "working capital", "associate",
       "Comment le BFR entre-t-il dans un modèle de valorisation ?",
       "How does working capital enter a valuation model?",
       (("variation", "bfr"), ("flux", "fcf"), ("prevision", "forecast")),
       ("La variation de BFR est déduite du free cash flow ; la prévision suit le cycle et la croissance.")),
    # --- corporate finance / IFRS --------------------------------------------
    _q("cf_ifrs_01", "corporate_finance", "ifrs", "stage",
       "Qu'est-ce que les normes IFRS et pourquoi sont-elles utilisées ?",
       "What are IFRS standards and why are they used?",
       (("ifrs", "norme", "normes"), ("comparab", "international"), ("reporting")),
       ("Référentiel comptable international rendant les comptes comparables entre pays et sociétés cotées.")),
    _q("cf_ifrs_02", "corporate_finance", "ifrs", "analyst",
       "Quelle différence entre amortissement comptable et dépréciation IFRS ?",
       "What is the difference between depreciation and IFRS impairment?",
       (("amortis", "plan"), ("depreci", "perte de valeur", "test"), ("recuperable", "recoverable")),
       ("L'amortissement étale un coût sur la durée d'usage ; la dépréciation constate une perte de valeur constatée.")),
    _q("cf_ifrs_03", "corporate_finance", "ifrs", "analyst",
       "Comment les contrats de location sont-ils traités en IFRS 16 ?",
       "How are leases treated under IFRS 16?",
       (("droit", "d'utilisation", "right of use"), ("actif", "bilan"), ("dette", "lease")),
       ("Le preneur inscrit un droit d'utilisation et une dette de location au bilan.")),
    _q("cf_ifrs_04", "corporate_finance", "ifrs", "associate",
       "Quel impact IFRS 16 a-t-il sur l'EBITDA et l'analyse de levier ?",
       "What impact does IFRS 16 have on EBITDA and leverage analysis?",
       (("ebitda", "explosion", "hausse"), ("dette", "lease", "location"), ("comparab")),
       ("L'EBITDA remonte car le loyer devient amortissement et intérêts ; la dette apparente augmente.")),
    _q("cf_wc_06", "corporate_finance", "working capital", "stage",
       "Qu'est-ce que la différence entre BFR et fonds de roulement ?",
       "What is the difference between working capital need and working capital?",
       (("bfr", "besoin"), ("fr", "fonds de roulement"), ("financement", "long terme")),
       ("Le fonds de roulement est la ressource durable ; le BFR le besoin du cycle ; leur écart se verse en trésorerie.")),
    _q("cf_wc_07", "corporate_finance", "working capital", "stage",
       "Comment le délai fournisseurs agit-il comme source de financement ?",
       "How do supplier payment terms act as a funding source?",
       (("fournisseur", "delai", "délai"), ("credit", "gratuit"), ("bfr")),
       ("Payer plus tard finance gratuitement le cycle, jusqu'au point où escomptes et tensions fournisseurs coûtent.")),
    _q("cf_wc_08", "corporate_finance", "working capital", "analyst",
       "Qu'est-ce que l'affacturage (factoring) et son coût ?",
       "What is factoring and its cost?",
       (("factoring", "affacturage"), ("creance", "cession"), ("cout", "frais")),
       ("Céder ses créances contre trésorerie immédiate ; le coût combine commission et avance non utilisée.")),
    _q("cf_wc_09", "corporate_finance", "working capital", "analyst",
       "Comment calculez-vous le délai moyen de paiement clients (DSO) ?",
       "How do you compute days sales outstanding (DSO)?",
       (("dso", "delai"), ("creance", "encours"), ("chiffre", "ca")),
       ("Créances clients divisées par le CA quotidien : le nombre de jours de ventes encore non encaissés.")),
    _q("cf_wc_10", "corporate_finance", "working capital", "associate",
       "Quels arbitrages entre réduction de stocks et risque de rupture ?",
       "What is the trade-off between cutting inventory and stockout risk?",
       (("stock", "rotation"), ("rupture", "service"), ("previsions", "safety")),
       ("Réduire le stock améliore la trésorerie mais expose la vente : calibrer avec un stock de sécurité mesuré.")),
    _q("cf_ifrs_05", "corporate_finance", "ifrs", "stage",
       "Qu'est-ce que la juste valeur en IFRS ?",
       "What is fair value under IFRS?",
       (("juste valeur", "fair value"), ("marche", "transaction"), ("niveau", "hierarchie")),
       ("Le prix recevable dans une transaction normale entre acteurs du marché, mesuré par une hiérarchie de niveaux.")),
    _q("cf_ifrs_06", "corporate_finance", "ifrs", "stage",
       "Qu'est-ce qu'un actif immatériel en IFRS et comment est-il comptabilisé ?",
       "What is an intangible asset under IFRS and how is it booked?",
       (("immat", "brevet", "logiciel"), ("separe", "acquis"), ("developp", "capex")),
       ("Les immatériels acquis sont capitalisés ; la recherche reste en charges, le développement parfois capitalisable.")),
    _q("cf_ifrs_07", "corporate_finance", "ifrs", "analyst",
       "Qu'est-ce que le test de dépréciation du goodwill (IFRS) et sa fréquence ?",
       "What is the goodwill impairment test and how often is it done?",
       (("goodwill", "uga"), ("test", "recuperable"), ("annuel", "trigger")),
       ("Chaque an au minimum, ou dès un indice de perte : comparer la valeur recouvrable de l'UGA à sa valeur nette.")),
    _q("cf_ifrs_08", "corporate_finance", "ifrs", "analyst",
       "Comment les instruments financiers sont-ils classés en IFRS 9 ?",
       "How are financial instruments classified under IFRS 9?",
       (("ifrs 9", "classification"), ("amorti", "juste valeur"), ("resultat", "oci")),
       ("Trois modèles : coût amorti, juste valeur par résultat ou par OCI, selon le modèle d'activité et les flux.")),
    _q("cf_ifrs_09", "corporate_finance", "ifrs", "associate",
       "Qu'est-ce qu'une provision IFRS et quand la reconnaître ?",
       "What is an IFRS provision and when is it recognised?",
       (("provision", "obligation"), ("probable", "estimable"), ("passif")),
       ("Une obligation probable d'origine passée, mesurable de façon fiable, non pas une simple charge future.")),
    _q("cf_ifrs_10", "corporate_finance", "ifrs", "associate",
       "Comment l'IFRS affecte-t-elle l'analyse des acquisitions (purchase price allocation) ?",
       "How does IFRS affect acquisition analysis (purchase price allocation)?",
       (("ppa", "allocation"), ("actif net", "juste valeur"), ("goodwill", "intangible")),
       ("L'allocation du prix aux justes valeurs détermine le goodwill et les amortissements futurs de l'ensemble.")),
    # --- corporate finance / accounting --------------------------------------
    _q("cf_acct_01", "corporate_finance", "accounting", "stage",
       "Citez les trois états financiers principaux et leur lien.",
       "Name the three core financial statements and how they link.",
       (("bilan", "balance sheet"), ("resultat", "income", "p&l"), ("flux", "cash flow")),
       ("Le bilan photographie le patrimoine ; le compte de résultat explique la performance ; les flux relient trésorerie et résultats.")),
    _q("cf_acct_02", "corporate_finance", "accounting", "stage",
       "Quelle différence entre chiffre d'affaires, EBITDA et résultat net ?",
       "What is the difference between revenue, EBITDA and net income?",
       (("chiffre", "revenue", "ca"), ("ebitda", "exploitation"), ("net", "impot", "interet")),
       ("Le CA mesure l'activité ; l'EBITDA la performance opérationnelle ; le net ce qui reste après tous les coûts.")),
    _q("cf_acct_03", "corporate_finance", "accounting", "analyst",
       "Comment une hausse de 10 d'amortissement traverse-t-elle les trois états ?",
       "How does an extra 10 of depreciation flow through the three statements?",
       (("resultat", "net", "impot"), ("cash", "flux"), ("bilan", "actif", "immobilisation")),
       ("Le net baisse de 7,5 après impôt ; le cash remonte via le réajustement ; le bilan s'équilibre.")),
    _q("cf_acct_04", "corporate_finance", "accounting", "analyst",
       "Qu'est-ce que la créance douteuse et comment la provisionner ?",
       "What is a doubtful receivable and how is it provisioned?",
       (("creance", "client"), ("provision", "perte"), ("probabilite", "probabilité")),
       ("Une créance incertaine est dépréciée par la perte attendue, en déduction du résultat.")),
    _q("cf_acct_05", "corporate_finance", "accounting", "associate",
       "Pourquoi un bénéfice net positif peut-il coexister avec une trésorerie faible ?",
       "Why can positive net income coexist with weak cash?",
       (("bfr", "stock", "client"), ("amortis", "non monétaire"), ("investissement", "capex")),
       ("Le BFR consomme du cash, les amortissements ne sont pas décaissés et le capex pèse sur la trésorerie.")),
    _q("cf_acct_06", "corporate_finance", "accounting", "stage",
       "Qu'est-ce qu'un actif et un passif au bilan en une phrase chacun ?",
       "What are an asset and a liability, one sentence each?",
       (("actif", "ressource"), ("passif", "obligation", "dette"), ("bilan")),
       ("L'actif est une ressource contrôlée générant des avantages ; le passif une obligation résultant d'événements passés.")),
    _q("cf_acct_07", "corporate_finance", "accounting", "stage",
       "Qu'est-ce qu'un compte de résultat consolidé ?",
       "What is a consolidated income statement?",
       (("consolid", "groupe"), ("filiale", "controle"), ("part minoritaire")),
       ("Il regroupe la maison mère et ses filiales contrôlées, en isolant la part des minoritaires.")),
    _q("cf_acct_08", "corporate_finance", "accounting", "analyst",
       "Qu'est-ce que la comptabilisation des revenus en pourcentage d'avancement ?",
       "What is percentage-of-completion revenue recognition?",
       (("avancement", "progression"), ("revenu", "contrat"), ("estimation", "coût")),
       ("Le revenu suit l'avancement du contrat, mesuré par coûts engagés ou jalons, avec estimation à revoir.")),
    _q("cf_acct_09", "corporate_finance", "accounting", "analyst",
       "Qu'est-ce que le résultat courant et le résultat exceptionnel ?",
       "What are recurring and exceptional income?",
       (("courant", "operationnel"), ("exceptionnel", "non recurrent"), ("analyse", "normalis")),
       ("Le courant provient de l'activité habituelle ; l'exceptionnel est non récurrent : séparer pour projeter.")),
    _q("cf_acct_10", "corporate_finance", "accounting", "associate",
       "Comment le leasing opérationnel impacte-t-il les ratios de rentabilité avant IFRS 16 ?",
       "How did operating leasing affect profitability ratios before IFRS 16?",
       (("loyer", "charge"), ("ebitda", "hors bilan"), ("comparab")),
       ("Le loyer pesait en charges d'exploitation hors bilan : l'EBITDA paraissait meilleur qu'en IFRS 16.")),
    # --- behavioral / STAR ----------------------------------------------------
    _q("beh_star_01", "behavioral", "star", "stage",
       "Racontez une situation où vous avez respecté une échéance serrée (méthode STAR).",
       "Tell about a time you met a tight deadline using the STAR method.",
       (("situation", "contexte"), ("tache", "action"), ("resultat", "result")),
       ("Situation, tâche, action concrète et résultat mesurable : rester factuel et concis.")),
    _q("beh_star_02", "behavioral", "star", "stage",
       "Décrivez un travail d'équipe où vous avez résolu un désaccord.",
       "Describe a team experience where you resolved a disagreement.",
       (("equipe", "team"), ("desaccord", "désaccord", "conflit"), ("solution", "resultat")),
       ("Écouter, comparer les faits, proposer un critère objectif et conclure sur le résultat commun.")),
    _q("beh_star_03", "behavioral", "star", "stage",
       "Parlez d'une erreur professionnelle et de ce que vous en avez appris.",
       "Talk about a professional mistake and what you learned.",
       (("erreur", "mistake"), ("responsabil", "reconnaiss"), ("apprentissage", "correctif")),
       ("Assumer, corriger, transformer en procédure ou contrôle évitant la répétition.")),
    _q("beh_star_04", "behavioral", "star", "analyst",
       "Racontez une analyse que vous avez défendue face à une objection senior.",
       "Tell about an analysis you defended against senior pushback.",
       (("analyse", "model"), ("objection", "question"), ("preuve", "donnee", "donnée")),
       ("Rester sur les faits, apporter une preuve chiffrée, ajuster si l'objection est fondée.")),
    _q("beh_star_05", "behavioral", "star", "analyst",
       "Donnez un exemple de priorisation sous forte charge de travail.",
       "Give an example of prioritising under heavy workload.",
       (("charge", "deadline", "pression"), ("priorite", "priorité", "classement"), ("resultat", "livrable")),
       ("Trier par impact et échéance, communiquer les arbitrages, livrer et mesurer le résultat.")),
    _q("beh_star_06", "behavioral", "star", "associate",
       "Décrivez un projet où vous avez piloté plusieurs parties prenantes.",
       "Describe a project where you managed multiple stakeholders.",
       (("partie", "stakeholder", "pilote"), ("attente", "alignement"), ("livrable", "resultat")),
       ("Cartographier les attentes, cadencer la communication et sécuriser la décision finale.")),
    _q("beh_star_07", "behavioral", "star", "associate",
       "Racontez une négociation difficile et le compromis atteint.",
       "Tell about a difficult negotiation and the compromise reached.",
       (("negociation", "négociation"), ("position", "interet", "intérêt"), ("compromis", "accord")),
       ("Séparer les positions des intérêts, chercher la zone d'accord et documenter l'accord.")),
    _q("beh_star_08", "behavioral", "star", "associate",
       "Parlez d'une décision que vous avez prise avec des données incomplètes.",
       "Talk about a decision made with incomplete data.",
       (("donnee", "donnée", "incomplete"), ("hypothese", "risque"), ("decision", "resultat")),
       ("Expliciter les hypothèses, mesurer le risque, décider et revenir sur l'écart au résultat.")),
    # --- behavioral / fit -------------------------------------------------------
    _q("beh_fit_01", "behavioral", "fit", "stage",
       "Pourquoi la finance et pourquoi ce métier en particulier ?",
       "Why finance and why this job in particular?",
       (("motivation", "pourquoi"), ("metier", "role", "poste"), ("fait", "concret", "exemple")),
       ("Un déclencheur factuel, une compétence à développer, une idée claire du quotidien du métier.")),
    _q("beh_fit_02", "behavioral", "fit", "stage",
       "Qu'avez-vous appris de votre dernière expérience qui sert ce poste ?",
       "What did you learn in your last experience that serves this role?",
       (("experience", "stage"), ("competence", "skill"), ("lien", "poste")),
       ("Deux apprentissages concrets reliés explicitement à deux exigences de l'offre.")),
    _q("beh_fit_03", "behavioral", "fit", "analyst",
       "Comment vous tenez-vous informé de l'actualité des marchés ?",
       "How do you keep up with market news?",
       (("source", "presse", "quotidien"), ("exemple", "recent", "récent"), ("lecture", "analyse")),
       ("Citer des sources précises et un fait récent avec sa lecture personnelle, pas une généralité.")),
    _q("beh_fit_04", "behavioral", "fit", "analyst",
       "Où vous voyez-vous dans cinq ans et pourquoi est-ce réaliste ?",
       "Where do you see yourself in five years and why is it realistic?",
       (("objectif", "vision"), ("etape", "étape", "plan"), ("realis", "réalis")),
       ("Un objectif cohérent avec le métier, des étapes vérifiables, sans promesse invérifiable.")),
    _q("beh_fit_05", "behavioral", "fit", "associate",
       "Pourquoi cette entreprise et qu'attendez-vous de ses valeurs ?",
       "Why this company and what do you expect from its values?",
       (("entreprise", "societe"), ("valeur", "culture"), ("fait", "verifie", "vérifié")),
       ("Un fait vérifié sur l'entreprise, relié à un choix professionnel, sans flatterie générique.")),
    _q("beh_fit_06", "behavioral", "fit", "associate",
       "Comment gérez-vous le stress d'une période de résultats ou de clôture ?",
       "How do you handle stress during earnings or closing season?",
       (("stress", "pression"), ("organisation", "methode", "méthode"), ("equilibre", "resultat")),
       ("Méthode de travail, découpage des tâches, communication des points bloquants tôt.")),
    _q("beh_star_09", "behavioral", "star", "stage",
       "Racontez une situation où vous avez appris un outil seul et vite.",
       "Tell about a time you learned a tool quickly on your own.",
       (("outil", "tool", "apprentissage"), ("delai", "délai", "autonomie"), ("resultat", "usage")),
       ("Objectif précis, ressources mobilisées, premier livrable concret produit avec l'outil.")),
    _q("beh_star_10", "behavioral", "star", "stage",
       "Décrivez une situation où vous avez détecté une erreur avant qu'elle n'atteigne le client.",
       "Describe a time you caught a mistake before it reached the client.",
       (("erreur", "controle", "vérification"), ("detection", "relecture"), ("correction", "resultat")),
       ("Le contrôle qui a attrapé l'erreur, la correction, et le réflexe durable mis en place.")),
    _q("beh_star_11", "behavioral", "star", "analyst",
       "Parlez d'un moment où vous avez dit non à une demande irréaliste.",
       "Talk about a time you said no to an unrealistic request.",
       (("demande", "delai", "charge"), ("arbitrage", "explication"), ("alternat", "resultat")),
       ("Expliquer la contrainte avec des faits, proposer une alternative, tenir la décision.")),
    _q("beh_star_12", "behavioral", "star", "analyst",
       "Racontez une amélioration de process que vous avez proposée et obtenue.",
       "Tell about a process improvement you proposed and got adopted.",
       (("process", "probleme"), ("proposition", "prototype"), ("gain", "adoption")),
       ("Le point de douleur mesuré, la solution testée à petite échelle, le gain après adoption.")),
    _q("beh_star_13", "behavioral", "star", "associate",
       "Décrivez une situation où vous avez formé ou encadré un collègue.",
       "Describe a time you trained or mentored a colleague.",
       (("formation", "accompagne"), ("methode", "document"), ("resultat", "autonomie")),
       ("Un plan simple, des documents réutilisables, un indicateur d'autonomie atteinte.")),
    _q("beh_star_14", "behavioral", "star", "associate",
       "Racontez une analyse où vous avez changé d'avis devant les données.",
       "Tell about an analysis where the data changed your mind.",
       (("hypothese", "attente"), ("donnee", "donnée", "preuve"), ("revision", "conclusion")),
       ("L'hypothèse initiale, l'évidence contradictoire, la révision assumée et sa conséquence.")),
    _q("beh_star_15", "behavioral", "star", "associate",
       "Parlez d'une fois où vous avez défendu l'intérêt de votre équipe auprès d'un tiers.",
       "Talk about a time you stood up for your team with a third party.",
       (("equipe", "interet"), ("tiers", "client", "management"), ("argument", "resultat")),
       ("Des faits et non des émotions, un argument d'intérêt commun, un résultat tangible pour l'équipe.")),
    _q("beh_fit_07", "behavioral", "fit", "stage",
       "Quelle étape de votre formation prépare le mieux ce poste, et pourquoi ?",
       "Which part of your education best prepares this role, and why?",
       (("cours", "formation"), ("competence", "skill"), ("lien", "poste")),
       ("Une matière ou un projet précis, la compétence exercée, son usage direct dans le rôle.")),
    _q("beh_fit_08", "behavioral", "fit", "stage",
       "Que connaissez-vous des étapes de recrutement en banque et comment vous y préparez-vous ?",
       "What do you know about banking recruiting steps and how do you prepare?",
       (("etapes", "entretien", "process"), ("preparation", "reseau", "candidature"), ("exemple", "concret")),
       ("Nommer les étapes, citer une préparation concrète par étape, sans prétendre connaître des codes internes.")),
    _q("beh_fit_09", "behavioral", "fit", "analyst",
       "Quelle actualité financière récente a retenu votre attention et pourquoi ?",
       "Which recent financial news caught your attention and why?",
       (("fait", "chiffre", "evenement"), ("lecture", "impact"), ("source", "verifie")),
       ("Un fait daté et sourcé, son canal de transmission, et une limite de votre lecture.")),
    _q("beh_fit_10", "behavioral", "fit", "analyst",
       "Comment expliquez-vous une décision d'embauche risquée dans votre parcours ?",
       "How do you explain a risky career decision in your background?",
       (("decision", "parcours"), ("rationnel", "apprentissage"), ("coherence", "resultat")),
       ("Le raisonnement du moment, ce qu'il a produit, et le fil conducteur jusqu'au poste visé.")),
    _q("beh_fit_11", "behavioral", "fit", "associate",
       "Que ferez-vous vos premières semaines si nous vous recrutons ?",
       "What will you do in your first weeks if we hire you?",
       (("ecoute", "observation"), ("livrable", "rapide"), ("question", "process")),
       ("Comprendre les process, produire un premier livrable utile, poser les bonnes questions tôt.")),
    _q("beh_fit_12", "behavioral", "fit", "associate",
       "Quelle expérience de management ou de coordination avez-vous déjà ?",
       "What management or coordination experience do you have?",
       (("coordination", "management"), ("responsabil", "pilote"), ("resultat", "equipe")),
       ("Une coordination factuelle, sa taille (personnes, périmètre), et le résultat livré.")),
    _q("beh_fit_13", "behavioral", "fit", "associate",
       "Pourquoi changer de poste maintenant, et qu'attendez-vous concrètement du suivant ?",
       "Why change roles now, and what do you concretely expect from the next one?",
       (("motivation", "moment"), ("attente", "suivant"), ("coherence", "realis")),
       ("Un motif de départ factuel et respectueux, une attente mesurable, une cohérence de parcours.")),
)

assert len(QUESTION_BANK) >= 120, "La banque doit compter au moins 120 questions"


def _stable_seed(role: str | None, seniority: str | None, count: int) -> int:
    """Derive a run-stable seed from the request, without Python's salted hash()."""
    material = f"{role or ''}|{seniority or ''}|{count}".encode("utf-8")
    return int.from_bytes(hashlib.sha256(material).digest()[:8], "big")


# Lexicon role families (finance_lexicon.FAMILIES) -> question families.
# A role maps to the family its interviews actually drill; unknown roles stay
# broad rather than guessed.
ROLE_QUESTION_FAMILIES: dict[str, str] = {
    "m&a": "corporate",
    "fpa": "corporate_finance",
    "ecm_dcm": "corporate",
    "coverage": "corporate",
    "risk": "markets",
    "quant": "markets",
    "treasury": "corporate_finance",
    "audit": "corporate_finance",
    "lbo_pe": "corporate",
    "equity_research": "corporate",
}


def _role_family(role: str | None) -> str | None:
    if not role:
        return None
    canonical = resolve_role(role)
    if not canonical:
        return None
    from .finance_lexicon import ROLES

    lexicon_family = ROLES[canonical][0]
    return ROLE_QUESTION_FAMILIES.get(lexicon_family)


def filter_questions(
    family: str | None = None,
    seniority: str | None = None,
    topic: str | None = None,
) -> list[FinanceQuestion]:
    """Deterministically filter the bank; unknown family/level raise ``ValueError``."""
    if family is not None and family not in FAMILIES:
        raise ValueError(f"Famille inconnue : {family!r}")
    if seniority is not None and seniority not in _SENIORITY_RANK:
        raise ValueError(f"Seniorité inconnue : {seniority!r}")
    topic_key = normalized_text(topic) if topic else ""
    return [
        question
        for question in QUESTION_BANK
        if (family is None or question.family == family)
        and (seniority is None or question.seniority == seniority)
        and (not topic_key or normalized_text(question.topic) == topic_key)
    ]


def draw_sequence(
    role: str | None = None,
    seniority: str | None = None,
    count: int = 5,
    seed: int | None = None,
) -> list[FinanceQuestion]:
    """Pick and order ``count`` questions for a role/seniority, deterministically.

    The pool keeps every question at or below the requested seniority, so a
    stage sequence never includes associate material.  The draw is seeded —
    explicitly or derived from the request — then ordered from easiest to
    hardest, so the sequence reads like a progressive interview.  An unknown
    role simply broadens the pool to every family (no guess, no crash).
    """
    if count < 0:
        raise ValueError("count doit être positif")
    level_rank = _SENIORITY_RANK.get(seniority or "associate")
    if seniority is not None and level_rank is None:
        raise ValueError(f"Seniorité inconnue : {seniority!r}")
    family = _role_family(role)
    pool = [
        question
        for question in QUESTION_BANK
        if (family is None or question.family == family)
        and (level_rank is None or _SENIORITY_RANK[question.seniority] <= level_rank)
    ]
    if not pool:
        return []
    effective_seed = seed if seed is not None else _stable_seed(role, seniority, count)
    rng = random.Random(effective_seed)
    picked = rng.sample(pool, min(count, len(pool)))
    picked.sort(key=lambda question: (_SENIORITY_RANK[question.seniority], question.id))
    return picked


def _answer_feedback(completeness: float, structure: float, too_short: bool) -> list[str]:
    feedback: list[str] = []
    if too_short:
        feedback.append("Réponse trop courte : développe au moins quelques phrases.")
    if completeness < 1.0:
        feedback.append("Couvre les idées de référence manquantes listées ci-dessous.")
    if structure < 0.5:
        feedback.append("Structure la réponse (annonce le plan, articule avec « ensuite », « donc », conclue).")
    if not feedback:
        feedback.append("Réponse complète et structurée ; vérifie chaque chiffre énoncé.")
    return feedback


def score_answer(question: FinanceQuestion, answer: Any) -> dict[str, Any]:
    """Local deterministic rubric for one free-form answer.

    Axes: ``completeness`` (share of the question's reference idea-groups
    present), ``structure`` (reasoning markers and length) and ``precision``
    (distinct concrete terms and numbers).  Scores are in ``[0, 100]`` with
    fixed weights; the same input always returns the same score.  This is not
    an external AI grade and not a recruiting prediction.
    """
    text = normalized_text(answer)
    words = text.split() if text else []
    too_short = len(words) < MIN_ANSWER_WORDS
    if too_short:
        completeness = structure = precision = 0.0
        missing = [group[0] for group in question.keyword_groups]
    else:
        covered = 0
        missing: list[str] = []
        for group in question.keyword_groups:
            if any(normalized_text(alias) in text for alias in group):
                covered += 1
            else:
                missing.append(group[0])
        completeness = covered / len(question.keyword_groups) if question.keyword_groups else 1.0
        markers = sum(1 for marker in _STRUCTURE_MARKERS["fr"] + _STRUCTURE_MARKERS["en"] if marker in text)
        length_factor = min(1.0, len(words) / 60)
        structure = min(1.0, markers / 3) * 0.7 + length_factor * 0.3
        matched_terms = {
            alias
            for group in question.keyword_groups
            for alias in group
            if normalized_text(alias) in text
        }
        has_numbers = any(character.isdigit() for character in text)
        precision = min(1.0, (len(matched_terms) / 4) + (0.2 if has_numbers else 0.0))
    overall = round(
        100 * (RUBRIC_WEIGHTS["completeness"] * completeness + RUBRIC_WEIGHTS["structure"] * structure + RUBRIC_WEIGHTS["precision"] * precision)
    )
    return {
        "question_id": question.id,
        "completeness": round(100 * completeness),
        "structure": round(100 * structure),
        "precision": round(100 * precision),
        "overall": overall,
        "missing_keywords": missing,
        "too_short": too_short,
        "feedback": _answer_feedback(completeness, structure, too_short),
    }


def faq_entries(topic: str | None = None) -> list[dict[str, str]]:
    """Flat question records for the FAQ module (CVBOOST-66) to display."""
    return [
        {
            "id": question.id,
            "family": question.family,
            "topic": question.topic,
            "seniority": question.seniority,
            "prompt_fr": question.prompt_fr,
            "prompt_en": question.prompt_en,
        }
        for question in filter_questions(topic=topic)
    ]


__all__ = [
    "BANK_VERSION",
    "FAMILIES",
    "FinanceQuestion",
    "MIN_ANSWER_WORDS",
    "QUESTION_BANK",
    "RUBRIC_WEIGHTS",
    "SENIORITY_LEVELS",
    "draw_sequence",
    "faq_entries",
    "filter_questions",
    "score_answer",
]
