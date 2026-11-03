"""Progressive, corpus-derived quiz questions and chapter mastery."""

from __future__ import annotations

import hashlib
import json
import re
import sqlite3
from functools import wraps
from threading import RLock
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from .ingest import CorpusIndex


def _sqlite_locked(method):
    @wraps(method)
    def wrapper(self, *args, **kwargs):
        with self._lock:
            return method(self, *args, **kwargs)
    return wrapper


@dataclass(frozen=True)
class QuizQuestion:
    question_id: str
    chapter: str
    prompt: str
    options: list[str]
    correct_index: int
    difficulty: str
    citation: dict[str, Any]
    explanation: str = ""
    exam_tags: tuple[str, ...] = ()

    def public(self) -> dict[str, Any]:
        payload = asdict(self)
        payload.pop("correct_index")
        payload.pop("explanation")
        payload["exam_tags"] = list(self.exam_tags)
        return payload


@dataclass(frozen=True)
class _QuestionSeed:
    prompt: str
    options: tuple[str, ...]
    correct_index: int
    citation_query: str
    explanation: str
    citation_source_contains: str = ""
    exam_tags: tuple[str, ...] = ()


_QUESTION_BANK: dict[str, tuple[_QuestionSeed, ...]] = {
    "TOPIC 1": (
        _QuestionSeed(
            "Pourquoi un VC finance-t-il souvent une startup par étapes ?",
            (
                "Pour conditionner les tranches aux jalons, réduire l’incertitude et garder l’option d’arrêter ou de poursuivre.",
                "Pour garantir aux fondateurs une valorisation identique à chaque tour.",
                "Pour supprimer tout risque d’agence et toute dilution future.",
                "Pour remplacer l’analyse du marché par une garantie de rendement.",
            ), 0, "staged financing milestones reduce uncertainty option abandon",
            "Le cours relie le financement par étapes aux jalons, à la réduction des asymétries d’information et à l’option de ne pas financer la suite si les résultats sont faibles.",
            "Topic_1_",
        ),
        _QuestionSeed(
            "Quelles raisons expliquent ensemble le financement par étapes en capital-risque ?",
            (
                "Inciter à atteindre des jalons, apprendre sur l’entreprise et conserver l’option d’arrêter si les résultats sont faibles.",
                "Garantir la valorisation future et supprimer tout risque d’agence.",
                "Éliminer toute dilution et assurer le rendement de l’investisseur.",
                "Remplacer l’analyse de l’entreprise par une garantie contractuelle de sortie.",
            ), 0, "staged financing effort information asymmetry abandon milestones",
            "Le sujet réunit trois logiques : inciter à l’effort, apprendre sur le fondateur et garder l’option d’arrêter. La bonne réponse n’en retient pas une seule isolément.",
            "Topic_1_",
            ("VC25-Q01",),
        ),
        _QuestionSeed(
            "Quel risque les investisseurs doivent-ils surveiller lorsque les financements sont conditionnés à des jalons très courts ?",
            (
                "Les fondateurs peuvent privilégier des indicateurs immédiats au détriment de la valeur à long terme.",
                "Les jalons suppriment le besoin d’examiner les résultats de l’entreprise.",
                "Les investisseurs perdent automatiquement tous leurs droits de gouvernance.",
                "La société doit distribuer ses revenus avant d’atteindre ses objectifs.",
            ), 0, "milestone based contracting perverse incentives short term measurable goals long term value",
            "Des jalons mal conçus peuvent inciter l’équipe à optimiser des objectifs mesurables à court terme plutôt que la valeur durable de l’entreprise.",
            "Topic_5_",
            ("VC25-Q02",),
        ),
        _QuestionSeed(
            "À quoi sert principalement le tour seed par rapport à une Series A ?",
            (
                "Construire et valider le produit avant de financer sa mise à l’échelle.",
                "Financer une sortie secondaire des investisseurs historiques.",
                "Remplacer les investisseurs en capital par de la dette senior.",
                "Distribuer des dividendes avant l’atteinte du product-market fit.",
            ), 0, "seed stage build validate product Series A scale",
            "Le cours distingue le seed, centré sur la construction et la validation du produit, de la Series A qui finance la croissance et la mise à l’échelle.",
            "Topic_1_",
            ("VC25-Q03",),
        ),
    ),
    "TOPIC 2": (
        _QuestionSeed(
            "Quels sont les quatre axes de lignes de la Venture Evaluation Matrix du cours ?",
            (
                "Value proposition, industry, strategy, competitive advantage.",
                "Revenue, EBITDA, leverage, exit multiple.",
                "Seed, Series A, Series B, IPO.",
                "Product, valuation, liquidation preference, board rights.",
            ), 0, "Venture Evaluation Matrix Value Proposition Industry Strategy Competitive Advantage",
            "La matrice organise l’analyse en value proposition, industry, strategy et competitive advantage, puis la décline selon le client, l’entreprise, l’entrepreneur et l’attractivité.",
            "Topic_2_",
        ),
        _QuestionSeed(
            "Dans l’analyse du marché, que représente le SOM ?",
            (
                "La part de marché que l’entreprise peut raisonnablement capter dans son marché adressable.",
                "La totalité des dépenses mondiales dans une catégorie.",
                "Le revenu déjà reconnu en comptabilité.",
                "La valeur de sortie après application du hurdle rate.",
            ), 0, "TAM total addressable SAM serviceable available SOM obtainable market",
            "Le cours distingue TAM, SAM et SOM pour passer du marché total au marché servi puis à la part obtenable par la startup.",
            "Topic_2_",
        ),
    ),
    "TOPIC 3": (
        _QuestionSeed(
            "Une startup reçoit 1,2 M€ contre 20 % du capital après investissement. Quelle est sa valorisation post-money ?",
            ("6,0 M€", "4,8 M€", "5,0 M€", "7,2 M€"), 0,
            "post-money valuation investment ownership fraction formula",
            "Post-money = investissement / fraction détenue = 1,2 / 20 % = 6,0 M€. Pre-money = 6,0 − 1,2 = 4,8 M€.",
        ),
        _QuestionSeed(
            "Un VC investit 5 M$, vise une sortie de 50 M$ dans 5 ans et exige 40 % d’IRR. Quelle ownership initiale approche le VC method ?",
            ("54 %", "38 %", "26 %", "14 %"), 0,
            "VC ownership 54% CCM 1.4^5 5.378 post-money valuation 9.297",
            "MOIC requis = (1 + 40 %)⁵ = 5,378. Le produit requis à la sortie vaut 5 × 5,378 = 26,89 M$. Ownership = 26,89 / 50 = 53,8 %, soit environ 54 %.",
            "VC_final_exam_2025_solutions",
            ("VC25-Q16",),
        ),
        _QuestionSeed(
            "Un investissement réalise un CCM de 13,8x en 5 ans. Quel IRR annuel composé est approximativement obtenu ?",
            ("69 %", "38 %", "13,8 %", "276 %"), 0,
            "CCM 13.8 IRR 13.8^(1/5) 69%",
            "IRR = CCM^(1/n) − 1 = 13,8^(1/5) − 1, soit environ 69 % par an.",
        ),
        _QuestionSeed(
            "Une startup a 5 millions d’actions fondateurs. Le VC investit 2 M$ dans une valorisation post-money de 8 M$ et exige un pool d’options de 20 % post-money. Quelle répartition donne le corrigé du cours ?",
            ("Fondateurs 55 % · pool 20 % · VC 25 %", "Fondateurs 60 % · pool 20 % · VC 20 %", "Fondateurs 50 % · pool 25 % · VC 25 %", "Fondateurs 65 % · pool 20 % · VC 15 %"), 0,
            "startup 5m founder shares VC invests 2m 8m post-money valuation 20% post-money options pool founders 55%",
            "La part du VC est 2/8 = 25 %. Le pool représente 20 %. Le solde revient aux fondateurs : 100 % − 25 % − 20 % = 55 %. Le corrigé fournit aussi les nombres d’actions correspondants.",
            "VC_final_exam_2025_solutions",
            ("VC25-Q17",),
        ),
        _QuestionSeed(
            "Avec 5 millions d’actions fondateurs, 55 % de détention finale pour les fondateurs et un pool de 20 %, quel tableau d’actions correspond au corrigé ?",
            (
                "Total 9,091 millions · pool 1,818 million · VC 2,273 millions.",
                "Total 8 millions · pool 2 millions · VC 1 million.",
                "Total 10 millions · pool 2 millions · VC 3 millions.",
                "Total 5 millions · pool 1 million · VC 1 million.",
            ), 0, "founder shares 5m option pool 1.818182 VC shares 2.272727 total shares 9.090909",
            "Si 5 millions d’actions représentent 55 %, le total est 5/0,55 = 9,091 millions. Le pool vaut 20 % (1,818 million) et la part VC 25 % (2,273 millions).",
            "VC_final_exam_2025_solutions",
            ("VC25-Q17-SHARES",),
        ),
        _QuestionSeed(
            "Un fonds investit 5 M$ pour des préférentielles convertibles à raison de 2 actions ordinaires chacune. Il détient 1 million de préférentielles; après conversion, 15 millions d’actions existent, puis l’IPO en émet 3 millions. Quelle part détient-il après l’IPO ?",
            ("11 %", "13,3 %", "10 %", "20 %"), 0,
            "Miller Venture Capital 5 million investment 8 years 1 million convertible preferred 2 common shares 15 million shares IPO 3 million 11%",
            "La conversion donne 2 millions d’actions ordinaires. Après l’IPO, le total est 15 + 3 = 18 millions; la participation est 2/18 = 11,1 %, soit 11 %.",
            "VC_final_exam_2025_solutions",
            ("VC25-Q18-OWNERSHIP",),
        ),
        _QuestionSeed(
            "Dans le même cas, les 2 millions d’actions valent 25 $ chacune après 8 ans. Quel IRR annualisé approche le résultat du corrigé ?",
            ("33 %", "25 %", "10 %", "50 %"), 0,
            "Miller 2m common shares stock $25 50m cash on cash 10x IRR 8 years 33%",
            "La valeur de sortie est 2m × 25 $ = 50 M$. Le CCM est 50/5 = 10x. L’IRR composé sur 8 ans est 10^(1/8) − 1, environ 33 %.",
            "VC_final_exam_2025_solutions",
            ("VC25-Q18-IRR",),
        ),
        _QuestionSeed(
            "Que signifie une base de capitalisation fully diluted lorsqu’un pool d’options est pris en compte ?",
            (
                "Les options sont supposées exercées pour inclure les actions potentielles dans le calcul des pourcentages.",
                "Seules les options abandonnées sont ajoutées au nombre d’actions.",
                "Les actions des fondateurs sont exclues du calcul.",
                "Les actions potentielles sont comptées seulement après la sortie.",
            ), 0, "fully diluted stock options assumed converted common shares",
            "Sur une base fully diluted, les options sont traitées comme si elles étaient exercées afin d’inclure les actions potentielles dans la cap table.",
            "Topic_3_",
            ("VC25-Q05",),
        ),
        _QuestionSeed(
            "Quelles sont les quatre entrées de base du Venture Capital Method ?",
            (
                "Montant investi, délai jusqu’à la sortie, valeur de sortie attendue et hurdle rate.",
                "Montant investi, nombre de tours, taux sans risque et prime de marché.",
                "Revenus actuels, EBITDA, dette et dividendes.",
                "Nombre d’employés, impôts, cash burn et taux de croissance historique.",
            ), 0, "venture capital valuation model investment time to exit exit value hurdle rate",
            "Le modèle part du montant investi, de l’horizon de sortie, de la valeur à la sortie et du rendement cible. Il utilise ces entrées pour remonter à une valeur post-money et à une ownership requise.",
            "Topic_3_",
            ("VC25-Q06",),
        ),
        _QuestionSeed(
            "Lors d’une levée avec un investissement positif, comment la pre-money se compare-t-elle à la post-money ?",
            (
                "Elle est inférieure : post-money = pre-money + nouvel investissement.",
                "Elle est toujours supérieure à la post-money.",
                "Elles sont égales, quelle que soit la somme levée.",
                "La comparaison dépend uniquement du nombre de tours futurs.",
            ), 0, "pre-money valuation lower than post-money investment pre money post money",
            "La post-money comprend le nouvel apport : pre-money = post-money − investissement. Pour un apport positif, la pre-money est donc plus basse.",
            "Topic_3_",
            ("VC25-Q07",),
        ),
        _QuestionSeed(
            "Dans le VCM simple, quel élément n’est pas une entrée directe du calcul de l’ownership requise ?",
            (
                "La préférence de liquidation, qui détermine le partage contractuel des produits.",
                "La valeur de sortie attendue.",
                "Le temps jusqu’à la sortie.",
                "Le hurdle rate.",
            ), 0, "venture capital method required ownership liquidation preference exit value time hurdle",
            "Le VCM de base utilise l’investissement, la durée, le hurdle et la valeur de sortie. Les préférences de liquidation modifient les produits contractuels et doivent être analysées séparément.",
            "Topic_3_",
            ("VC25-Q09",),
        ),
        _QuestionSeed(
            "Dans le calcul multi-tours du sujet, si la Series C pre-money est 1 800 M$ et le multiple cible depuis la Series B est 4x, quelle est la Series B post-money ?",
            ("450 M$", "7 200 M$", "1 800 M$", "400 M$"), 0,
            "Series C pre-money 1800 Series B target multiple 4 post-money 450",
            "On remonte les tours à rebours : post-money Series B = pre-money Series C / multiple cible = 1 800 / 4 = 450 M$.",
            "VC_final_exam_2025_solutions",
            ("VC25-Q19-ROUND-VALUATION",),
        ),
        _QuestionSeed(
            "Après le calcul à rebours des tours Seed, A, B et C du corrigé, quelle part fully diluted reste aux fondateurs à la sortie ?",
            ("47 %", "53 %", "25 %", "10 %"), 0,
            "Series C 2000 exit 6000 founders fully diluted ownership 47 percent",
            "Les tours diluent successivement les fondateurs. Le corrigé aboutit à 47 % à la sortie; il faut multiplier les rétentions successives plutôt qu’additionner les ownership des tours.",
            "VC_final_exam_2025_solutions",
            ("VC25-Q19-EXIT-OWNERSHIP",),
        ),
        _QuestionSeed(
            "Dans le cas Magical Genie du corrigé, avec 75 % de probabilité pour le scénario 1, quelle offre maximise la richesse finale espérée du fondateur ?",
            ("XY : 5,625 M$", "VW : 5,333 M$", "VW : 6,000 M$", "XY : 4,000 M$"), 0,
            "Magical Genie founder expected ownership expected final wealth VW XY scenario probability 75% 5.625 5.333",
            "Le corrigé compare les deux offres sous les scénarios de financement et retient XY : ownership espérée 56,25 % et richesse finale espérée 5,625 M$, contre 5,333 M$ pour VW.",
            "PEVC_final_exam_2024_solutions",
            ("VC25-Q21-WEALTH",),
        ),
        _QuestionSeed(
            "Avec une probabilité de 75 % pour le scénario 1, quelle ownership finale espérée le fondateur obtient-il avec l’offre XY ?",
            ("56,25 %", "53,33 %", "75 %", "25 %"), 0,
            "XY founder expected ownership 56.25 percent scenario one 75 percent VC final exam 2025",
            "L’ownership attendue est la moyenne pondérée des résultats : 75 % × 66,67 % + 25 % × 25 % = 56,25 %. À une sortie de 10 M$, cela correspond à une richesse attendue de 5,625 M$.",
            "VC_final_exam_2025_solutions",
            ("VC25-Q21-OWNERSHIP",),
        ),
    ),
    "TOPIC 4": (
        _QuestionSeed(
            "Quel est le rôle principal d’une clause anti-dilution dans un term sheet ?",
            (
                "Ajuster la protection économique d’un investisseur si un tour ultérieur est réalisé à un prix inférieur.",
                "Empêcher toute émission future d’actions, y compris aux salariés.",
                "Garantir que la valeur de l’entreprise ne baisse jamais.",
                "Remplacer automatiquement une préférence de liquidation par des actions ordinaires.",
            ), 0, "anti-dilution protection down round weighted average conversion price",
            "La protection anti-dilution ajuste généralement le prix de conversion selon les termes négociés lors d’un tour à la baisse. Elle ne supprime pas toute dilution.",
            "",
            ("VC25-Q10",),
        ),
        _QuestionSeed(
            "Avec une convertible note dotée d’un valuation cap et d’un discount, quel prix de conversion sert habituellement l’investisseur ?",
            (
                "Le prix le plus favorable entre celui issu du cap et celui issu du discount, selon les termes du contrat.",
                "Toujours le prix le plus élevé des deux.",
                "Le prix de l’action ordinaire à la sortie, sans tenir compte du tour qualifié.",
                "Aucun prix : la note ne peut jamais se convertir en equity.",
            ), 0, "convertible note valuation cap discount conversion price lower price",
            "Le cap et le discount donnent deux méthodes de conversion. Le contrat précise leur application, souvent en retenant le prix qui donne davantage d’actions à l’investisseur.",
            "",
            ("VC25-Q15",),
        ),
        _QuestionSeed(
            "Pourquoi un fondateur peut-il accepter une valorisation plus basse si elle s’accompagne de protections mieux équilibrées ?",
            (
                "Valorisation et protections influencent ensemble le risque supporté et le rendement économique attendu.",
                "Les protections garantissent que la valorisation montera.",
                "Une valorisation basse empêche toute dilution future.",
                "Les protections éliminent tout besoin de négocier la gouvernance.",
            ), 0, "lower valuation stronger protective provisions risk expected return term sheet",
            "Les conditions économiques et les droits de protection doivent être évalués ensemble : elles répartissent le risque et le rendement sans garantir le succès.",
            "Topic_4_",
            ("VC25-Q08",),
        ),
        _QuestionSeed(
            "Quelle clause permet aux fondateurs d’acquérir progressivement le droit de conserver une partie de leurs actions ?",
            (
                "Le reverse vesting, qui conditionne la conservation des actions au temps et parfois aux conditions de départ.",
                "Le pay-to-play, qui impose aux investisseurs de participer aux tours futurs.",
                "Le drag-along, qui encadre une vente de la société.",
                "Le valuation cap, qui limite le prix de conversion d’une note.",
            ), 0, "reverse vesting founders earn back shares over time cliff",
            "Le cours décrit un calendrier courant de 48 mois avec un cliff de 12 mois : un quart devient acquis au cliff, sous réserve des clauses de départ applicables.",
            "Topic_4_",
            ("VC25-Q11",),
        ),
        _QuestionSeed(
            "Selon les clauses du sujet, combien d’actions restent acquises après un an si le fondateur est licencié pour faute ?",
            ("0", "1 million", "3 millions", "4 millions"), 0,
            "vesting lost on dismissal with cause 48 months 12 month cliff one year founder shares",
            "La clause de départ pour faute fait perdre les droits acquis dans ce cas. Le cliff ordinaire de 12 mois ne neutralise pas la règle de déchéance pour faute; le corrigé donne 0 action conservée.",
            "Topic_4_",
            ("VC25-Q14",),
        ),
        _QuestionSeed(
            "À quoi sert une clause pay-to-play dans un term sheet ?",
            (
                "À conditionner le maintien de certains droits préférentiels à une participation pro rata aux financements futurs.",
                "À garantir aux fondateurs un prix fixe lors du prochain tour.",
                "À réserver les nouveaux tours aux investisseurs entrants.",
                "À empêcher la conversion des actions préférentielles.",
            ), 0, "pay to play anti-dilution liquidation preference participate pro rata future funding",
            "Le cours précise que certains droits, par exemple l’anti-dilution ou une préférence multiple, peuvent dépendre de la participation pro rata de l’investisseur au tour suivant.",
            "Topic_4_",
            ("VC25-Q12",),
        ),
        _QuestionSeed(
            "Dans le cas comparatif du sujet, quelle combinaison de clauses distingue correctement les term sheets Alpha et Mega ?",
            (
                "Alpha : weighted-average anti-dilution et deux sièges fondateurs; Mega : full-ratchet et deux sièges investisseurs.",
                "Alpha : full-ratchet et deux sièges investisseurs; Mega : weighted-average et deux sièges fondateurs.",
                "Les deux offres ont la même anti-dilution et la même composition du conseil.",
                "Mega n’accorde ni préférence de liquidation ni pool d’options.",
            ), 0, "Alpha weighted average Mega full ratchet board founders investor seats",
            "Le corrigé donne Alpha en weighted-average avec deux sièges communs/fondateurs, et Mega en full-ratchet avec deux sièges investisseurs. Les clauses doivent être comparées selon la priorité des fondateurs, pas réduites au seul chiffre de valorisation.",
            "VC_final_exam_2025_solutions",
            ("VC25-Q20-A",),
        ),
        _QuestionSeed(
            "À une sortie de 10 M$, quel payoff donne le corrigé pour Alpha et Mega dans le cas de préférentielles du sujet ?",
            ("Alpha 4,44 M$ · Mega 8 M$", "Alpha 4 M$ · Mega 6 M$", "Alpha 8 M$ · Mega 4,44 M$", "Alpha 10 M$ · Mega 10 M$"), 0,
            "Alpha Mega 10m exit payoff non participating participating preferred 4.44 8",
            "Alpha choisit entre sa préférence de 4 M$ et la conversion à 44,4 % de 10 M$, soit 4,44 M$. Mega reçoit 6 M$ de préférence puis 50 % des 4 M$ restants, soit 8 M$.",
            "VC_final_exam_2025_solutions",
            ("VC25-Q20-B",),
        ),
        _QuestionSeed(
            "Mega investit 6 M$ à 1 $ par action. En full ratchet, si le tour suivant émet à 0,90 $, combien d’actions ordinaires ses préférentielles donnent-elles à la conversion ?",
            ("6,67 millions", "6 millions", "5,4 millions", "0,67 million"), 0,
            "Mega full ratchet issue price 0.90 preferred shares convert 6.67 million",
            "Le full ratchet ajuste le prix de conversion au nouveau prix de 0,90 $. Les 6 M$ d’investissement correspondent alors à 6 / 0,90 = 6,67 millions d’actions.",
            "VC_final_exam_2025_solutions",
            ("VC25-Q20-C",),
        ),
    ),
    "TOPIC 5": (
        _QuestionSeed(
            "Pourquoi un fonds de VC peut-il choisir une juridiction de common law pour ses contrats ?",
            (
                "Les précédents et l’exécution judiciaire peuvent renforcer la prévisibilité des droits négociés.",
                "La common law supprime tout risque de litige et toute obligation réglementaire.",
                "Elle garantit toujours un impôt plus faible sur le carried interest.",
                "Elle interdit les clauses de gouvernance et de protection des investisseurs.",
            ), 0, "common law case based judicial precedent enforcement term sheet LP agreements",
            "Le support associe les systèmes de common law aux précédents et à une exécution fiable des term sheets et accords d’actionnaires; cela ne rend pas les droits absolus ni les litiges impossibles.",
            "Topic_5_",
            ("VC25-Q04",),
        ),
        _QuestionSeed(
            "Quelle comparaison résume le mieux les tendances décrites entre contrats VC américains et européens continentaux ?",
            (
                "Les contrats américains sont souvent plus juridiques et protecteurs; en Europe continentale, les relations et le financement par étapes jouent davantage.",
                "Les contrats européens utilisent toujours plus de clauses de protection qu’aux États-Unis.",
                "Les deux systèmes sont identiques dès qu’un contrat est rédigé en anglais.",
                "Les fonds américains évitent les conseils d’administration et le suivi formel.",
            ), 0, "US continental Europe VC contracts legalistic trust staged financing",
            "Le cours décrit des tendances comparatives : contrats plus formels et contractualisés en common law, approche plus relationnelle et financement par étapes en systèmes civilistes. Ce sont des tendances, pas des règles universelles.",
            "Topic_5_",
            ("VC25-Q13",),
        ),
        _QuestionSeed(
            "À quoi servent principalement les droits de gouvernance et de suivi du VC ?",
            (
                "Suivre l’entreprise, obtenir l’information prévue et participer aux décisions réservées convenues.",
                "Garantir au VC la gestion quotidienne de toutes les équipes.",
                "Remplacer les obligations d’information des fondateurs par un rendement garanti.",
                "Éviter toute discussion sur la stratégie de sortie.",
            ), 0, "board governance monitoring information rights reserved matters venture capital",
            "Le cours décrit le monitoring, l’accès à l’information et les droits de décision du conseil ou des investisseurs selon les accords conclus.",
        ),
        _QuestionSeed(
            "Pourquoi un fonds VC doit-il préparer une stratégie de sortie ?",
            (
                "La sortie permet de réaliser et distribuer les retours aux investisseurs du fonds.",
                "Elle fixe automatiquement la valorisation de chaque tour précédent.",
                "Elle élimine le besoin de gouvernance avant l’exit.",
                "Elle garantit que chaque startup sera vendue par IPO.",
            ), 0, "exit strategies venture capital return proceeds limited partners IPO trade sale",
            "Les sorties, par exemple vente industrielle ou IPO lorsque cela convient, réalisent la valeur et permettent au fonds de retourner les produits aux LPs.",
        ),
    ),
}


class QuizEngine:
    def __init__(self, index: CorpusIndex, db_path: str | Path):
        self.index = index
        self._lock = RLock()
        path = Path(db_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(path), check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute(
            """CREATE TABLE IF NOT EXISTS quiz_attempts (
                id INTEGER PRIMARY KEY AUTOINCREMENT, question_id TEXT NOT NULL, chapter TEXT NOT NULL,
                correct INTEGER NOT NULL, difficulty TEXT NOT NULL
            )"""
        )
        self._conn.execute(
            """CREATE TABLE IF NOT EXISTS quiz_questions (
                question_id TEXT PRIMARY KEY, chapter TEXT NOT NULL, prompt TEXT NOT NULL, options_json TEXT NOT NULL,
                correct_index INTEGER NOT NULL, difficulty TEXT NOT NULL, citation_json TEXT NOT NULL,
                exam_tags_json TEXT NOT NULL DEFAULT '[]'
            )"""
        )
        columns = {row[1] for row in self._conn.execute("PRAGMA table_info(quiz_questions)")}
        if "explanation" not in columns:
            self._conn.execute("ALTER TABLE quiz_questions ADD COLUMN explanation TEXT NOT NULL DEFAULT ''")
        if "exam_tags_json" not in columns:
            self._conn.execute("ALTER TABLE quiz_questions ADD COLUMN exam_tags_json TEXT NOT NULL DEFAULT '[]'")
        self._conn.commit()

    @_sqlite_locked
    def close(self) -> None:
        self._conn.close()

    @_sqlite_locked
    def _mastery_row(self, chapter: str) -> tuple[int, int]:
        chapter = self._canonical_chapter(chapter)
        row = self._conn.execute("SELECT COUNT(*) total, SUM(correct) correct FROM quiz_attempts WHERE chapter = ?", (chapter,)).fetchone()
        return int(row["total"] or 0), int(row["correct"] or 0)

    @_sqlite_locked
    def mastery(self, chapter: str) -> dict[str, Any]:
        chapter = self._canonical_chapter(chapter)
        total, correct = self._mastery_row(chapter)
        seeds = _QUESTION_BANK.get(chapter, ())
        attempts_required = len(seeds) or 2
        answered_prompts = {
            row["prompt"]
            for row in self._conn.execute(
                """SELECT DISTINCT question.prompt FROM quiz_attempts AS attempt
                   JOIN quiz_questions AS question ON question.question_id = attempt.question_id
                   WHERE attempt.chapter = ?""",
                (chapter,),
            ).fetchall()
        }
        seed_prompts = {seed.prompt for seed in seeds}
        covered_prompts = answered_prompts & seed_prompts
        covered = len(covered_prompts) if seeds else min(total, attempts_required)
        exam_tags = sorted({tag for seed in seeds for tag in seed.exam_tags})
        covered_exam_tags = sorted({tag for seed in seeds if seed.prompt in covered_prompts for tag in seed.exam_tags})
        score = round(correct / total, 4) if total else 0.0
        return {
            "chapter": chapter,
            "attempts": total,
            "correct": correct,
            "attempts_required": attempts_required,
            "covered": covered,
            "coverage_required": attempts_required,
            "exam_tags_covered": covered_exam_tags,
            "exam_tags_total": exam_tags,
            "score": score,
            "mastered": bool(covered >= attempts_required and score >= 0.8),
        }

    @_sqlite_locked
    def difficulty(self, chapter: str) -> str:
        score = self.mastery(chapter)["score"]
        return "foundation" if score < 0.5 else "consolidation" if score < 0.8 else "challenge"

    @staticmethod
    def _answer_sentence(text: str) -> str:
        value = re.split(r"(?<=[.!?])\s+|\n+", text.strip())[0].strip()
        return value[:600]

    @staticmethod
    def _canonical_chapter(chapter: str) -> str:
        match = re.match(r"^\s*topic\s*(\d+)\b", str(chapter), re.IGNORECASE)
        return f"TOPIC {match.group(1)}" if match else str(chapter).strip()

    @_sqlite_locked
    def next_question(self, chapter: str, *, difficulty: str | None = None, sequence: int = 0) -> QuizQuestion | None:
        chapter = self._canonical_chapter(str(chapter or "").strip())
        if not chapter:
            return None
        chosen_difficulty = difficulty or self.difficulty(chapter)
        section_hits = self.index.chunks_for_section(chapter)
        if chapter.lower().startswith(("topic ", "chapter ", "section ")) and not section_hits:
            return None
        attempts = self._conn.execute("SELECT COUNT(*) FROM quiz_attempts WHERE chapter = ?", (chapter,)).fetchone()[0]
        seeds = _QUESTION_BANK.get(chapter)
        if seeds:
            answered_prompts = {
                row["prompt"]
                for row in self._conn.execute(
                    """SELECT DISTINCT question.prompt FROM quiz_attempts AS attempt
                       JOIN quiz_questions AS question ON question.question_id = attempt.question_id
                       WHERE attempt.chapter = ?""",
                    (chapter,),
                ).fetchall()
            }
            unseen_seeds = [seed for seed in seeds if seed.prompt not in answered_prompts]
            if unseen_seeds:
                seed = unseen_seeds[0]
            else:
                seed = seeds[(int(attempts) + max(0, sequence)) % len(seeds)]
            hits = self.index.search(seed.citation_query, limit=20)
            chapter_number = re.search(r"\d+", chapter)
            topic_token = chapter_number.group(0) if chapter_number else ""
            topic_files = [
                hit for hit in hits
                if topic_token and re.search(rf"topic[_ -]?{topic_token}(?:[_ -]|\.|$)", Path(hit.source_path).name, re.IGNORECASE)
            ]
            topic_sections = [hit for hit in hits if chapter_number and re.search(rf"\btopic\s*{topic_token}\b", hit.section, re.IGNORECASE)]
            source_hint = seed.citation_source_contains.casefold()
            hinted_hits = [hit for hit in hits if source_hint and source_hint in Path(hit.source_path).name.casefold()]
            chunk = (hinted_hits or topic_files or topic_sections or hits)[0] if hits else None
            if chunk is None:
                return None
            options = list(seed.options)
            digest = hashlib.sha256(f"{chapter}:{attempts}:{sequence}:{seed.prompt}:{chosen_difficulty}".encode()).hexdigest()[:24]
            offset = int(digest[:2], 16) % len(options)
            rotated = options[offset:] + options[:offset]
            question = QuizQuestion(digest, chapter, seed.prompt, rotated, (seed.correct_index - offset) % len(options), chosen_difficulty, chunk.citation(), seed.explanation, seed.exam_tags)
            self._save_question(question)
            return question
        chunks = section_hits[:8] if section_hits else self.index.search(chapter, limit=8)
        if not chunks:
            return None
        chunk = chunks[int(attempts) % len(chunks)]
        answer = self._answer_sentence(chunk.text)
        distractors = list(dict.fromkeys(self._answer_sentence(item.text) for item in chunks if item.chunk_id != chunk.chunk_id))
        options = [answer] + [item for item in distractors if item and item != answer][:2]
        fillers = ["Cette affirmation n’est pas soutenue par l’extrait consulté.", "L’extrait ne permet pas de conclure cela."]
        for filler in fillers:
            if len(options) >= 3:
                break
            options.append(filler)
        digest = hashlib.sha256(f"{chapter}:{chunk.chunk_id}:{attempts}:{chosen_difficulty}".encode()).hexdigest()[:24]
        # Deterministic rotation keeps tests and offline sessions reproducible while
        # preventing the correct answer from always being displayed first.
        offset = int(digest[:2], 16) % len(options)
        rotated = options[offset:] + options[:offset]
        question = QuizQuestion(digest, chapter, f"Quel énoncé est directement soutenu par le cours pour « {chapter} » ?", rotated, rotated.index(answer), chosen_difficulty, chunk.citation(), "Relis l’extrait cité et identifie le passage qui établit directement cette affirmation.")
        self._save_question(question)
        return question

    @_sqlite_locked
    def _save_question(self, question: QuizQuestion) -> None:
        self._conn.execute("INSERT OR REPLACE INTO quiz_questions(question_id,chapter,prompt,options_json,correct_index,difficulty,citation_json,explanation,exam_tags_json) VALUES(?,?,?,?,?,?,?,?,?)", (question.question_id, question.chapter, question.prompt, json.dumps(question.options, ensure_ascii=False), question.correct_index, question.difficulty, json.dumps(question.citation, ensure_ascii=False), question.explanation, json.dumps(question.exam_tags, ensure_ascii=False)))
        self._conn.commit()

    @_sqlite_locked
    def answer(self, question_id: str, option_index: int) -> dict[str, Any]:
        row = self._conn.execute("SELECT * FROM quiz_questions WHERE question_id = ?", (question_id,)).fetchone()
        if row is None:
            raise KeyError("Question de quiz introuvable dans la session locale.")
        options = json.loads(row["options_json"])
        if not isinstance(option_index, int) or not 0 <= option_index < len(options):
            raise ValueError("Réponse de quiz invalide.")
        correct = option_index == int(row["correct_index"])
        self._conn.execute("INSERT INTO quiz_attempts(question_id,chapter,correct,difficulty) VALUES(?,?,?,?)", (question_id, row["chapter"], int(correct), row["difficulty"]))
        self._conn.commit()
        return {
            "question_id": question_id,
            "correct": correct,
            "feedback": "Bonne réponse." if correct else "Pas encore. Compare ton choix à la correction et à la source.",
            "correct_answer": options[int(row["correct_index"])],
            "explanation": row["explanation"],
            "citation": json.loads(row["citation_json"]),
            "exam_tags": json.loads(row["exam_tags_json"] or "[]"),
            "mastery": self.mastery(row["chapter"]),
            "local_only": True,
        }

    @_sqlite_locked
    def all_mastery(self, chapters: list[str]) -> list[dict[str, Any]]:
        return [self.mastery(chapter) for chapter in chapters]

    @_sqlite_locked
    def dashboard(self, chapters: list[str]) -> dict[str, Any]:
        notions = self.all_mastery(chapters)
        expected_exam_tags = sorted({tag for chapter in chapters for seed in _QUESTION_BANK.get(self._canonical_chapter(chapter), ()) for tag in seed.exam_tags})
        covered_exam_tags = sorted({tag for item in notions for tag in item["exam_tags_covered"]})
        expected_tag_set = set(expected_exam_tags)
        covered_tag_set = set(covered_exam_tags) & expected_tag_set
        weak_points = sorted(
            (item for item in notions if not item["mastered"]),
            key=lambda item: (item["score"], item["attempts"], item["chapter"]),
        )
        return {
            "notions": notions,
            "weak_points": weak_points,
            "mastered_count": sum(1 for item in notions if item["mastered"]),
            "total_count": len(notions),
            "overall_score": round(sum(item["score"] for item in notions) / len(notions), 4) if notions else 0.0,
            "exam_objectives": {
                "label": "Sujet VC 2025 historique",
                "covered": len(covered_tag_set),
                "total": len(expected_tag_set),
                "percent": round(len(covered_tag_set) / len(expected_tag_set) * 100) if expected_tag_set else 0,
                "covered_ids": sorted(covered_tag_set),
                "missing_ids": sorted(expected_tag_set - covered_tag_set),
                "local_only": True,
            },
            "local_only": True,
        }


__all__ = ["QuizEngine", "QuizQuestion"]
