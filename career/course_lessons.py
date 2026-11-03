"""Original French VC lessons mapped to the local course and past-paper bank."""

from __future__ import annotations

import sqlite3
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from threading import RLock
from typing import Any


VC_LESSONS: tuple[dict[str, Any], ...] = (
    {
        "id": "topic-1",
        "chapter": "TOPIC 1",
        "title": "Comprendre le capital-risque et son écosystème",
        "objective": "Situer le VC dans le financement des startups, reconnaître les acteurs et expliquer les étapes, les risques et la logique d’un fonds.",
        "recommended_exam": {"year": 2025, "question_id": "2025-A01"},
        "exam_question_ids": ["2023-A01", "2023-A03", "2023-B11", "2024-A01", "2024-A02", "2024-A03", "2024-A07", "2024-B20", "2025-A01", "2025-A03"],
        "sections": [
            {
                "title": "1. Pourquoi le capital-risque existe",
                "explain": "Une startup cherche à créer puis faire grandir une activité innovante dans un contexte de forte incertitude. Elle a souvent peu de revenus récurrents, peu de garanties et des besoins de développement importants : un prêt bancaire classique peut donc être difficile à obtenir. Le VC apporte du capital en échange d’une participation minoritaire et accepte un risque élevé en visant un gain important si quelques entreprises réussissent fortement. Le cours replace aussi le VC dans les tendances mondiales : les créations, le nombre de transactions et les montants levés varient selon les régions et les cycles. Ces graphiques décrivent une période et une source précises; ils ne donnent pas une règle intemporelle.",
                "key_ideas": [
                    "Le capital-risque est une stratégie d’investissement en fonds propres dans des entreprises jeunes ou en développement.",
                    "Les résultats suivent une logique de portefeuille : beaucoup d’investissements peuvent décevoir et un petit nombre de réussites peut représenter une grande part de la valeur.",
                    "Le support présente des taux élevés d’échec ou d’écart au plan initial. Ce sont des estimations liées à ses sources et périodes, pas une probabilité universelle pour chaque startup.",
                    "Le VC apporte aussi du conseil, des compétences, des réseaux, de la crédibilité et de l’aide pour les prochains tours.",
                    "Le financement peut accélérer la croissance, mais crée de la dilution, des attentes de rendement et une relation de gouvernance avec l’investisseur.",
                    "Pour le LP, le VC peut diversifier un portefeuille et viser un rendement élevé; il reste illiquide, incertain et très dispersé selon les fonds.",
                ],
                "example": {
                    "prompt": "Une startup pré-produit a besoin d’argent pour construire son prototype. Pourquoi une banque et un VC n’analysent-ils pas le même risque ?",
                    "steps": ["Repérer les flux : la startup n’a pas encore de recettes stables pour rembourser une dette.", "Repérer les garanties : ses actifs tangibles peuvent être limités.", "Repérer l’upside : le VC peut financer la croissance contre une part du capital et contribuer à la création de valeur."],
                    "answer": "La dette exige une capacité de remboursement relativement prévisible; le VC accepte une forte incertitude en échange d’un potentiel de rendement en capital et d’une participation minoritaire.",
                    "exam_refs": ["2023-A01"],
                },
                "sources": [{"file": "Topic 1 Introduction to venture capital and the VC ecosystem.pdf", "pages": "3–9, 15–23"}, {"file": "Sessions 5-6 Venture Capital.pdf", "pages": "2–4"}],
            },
            {
                "title": "2. Les acteurs et les étapes de financement",
                "explain": "Les sources évoluent avec la maturité. Les fondateurs, proches, business angels, incubateurs, accélérateurs et fonds seed peuvent intervenir très tôt; les fonds institutionnels financent les tours de croissance; les CVC ajoutent une logique stratégique; les organismes publics et les family offices ont leurs propres objectifs et contraintes. Le nom du tour n’est pas une règle universelle : il faut surtout lire le stade, les jalons, le besoin de financement et la traction.",
                "key_ideas": [
                    "Pré-seed : valider l’idée, l’équipe et la faisabilité; seed : développer le produit et tester le marché; Series A : commencer à mettre à l’échelle après les premiers signaux de product-market fit; B et C : accélérer la croissance et préparer la maturité.",
                    "Un incubateur accompagne souvent une idée très précoce sur une durée souple; un accélérateur propose un programme court, structuré et orienté vers la traction et les investisseurs.",
                    "Un VC est généralement minoritaire et actif; le growth equity intervient sur des entreprises plus matures; un buyout prend le contrôle d’entreprises plus établies.",
                    "Une levée doit financer un plan et des jalons jusqu’au prochain point de décision, en tenant compte du burn et du runway.",
                ],
                "procedure": ["Décrire le stade opérationnel, pas seulement le nom du tour.", "Identifier le prochain jalon vérifiable et le coût pour l’atteindre.", "Associer les investisseurs et instruments compatibles avec ce stade.", "Estimer le montant, la durée de runway et la dilution associée."],
                "example": {
                    "prompt": "Quel usage distinguerait le mieux un seed d’une Series A ?",
                    "steps": ["Au seed, vérifier que le produit répond à un besoin et obtenir les premiers signaux de demande.", "En Series A, financer une croissance plus répétable : équipe, distribution et opérations à l’échelle."],
                    "answer": "Le seed sert à construire et valider; la Series A sert principalement à faire croître une proposition qui a commencé à démontrer sa pertinence.",
                    "exam_refs": ["2024-A07", "2025-A03"],
                },
                "sources": [{"file": "Topic 1 Introduction to venture capital and the VC ecosystem.pdf", "pages": "24–34"}],
            },
            {
                "title": "3. Pourquoi les tours sont échelonnés",
                "explain": "Le financement par étapes permet de ne pas engager tout le capital dès le départ. Chaque tour peut dépendre de progrès observables. Cette structure crée des incitations, apporte de l’information au fur et à mesure et conserve l’option d’arrêter ou de continuer. Le contrat peut toutefois produire de mauvais comportements si les jalons récompensent seulement des résultats faciles à mesurer à court terme.",
                "key_ideas": ["Incitation à atteindre les jalons convenus.", "Apprentissage sur le marché, le produit et la capacité de l’équipe.", "Option de financer la suite, de changer de stratégie ou d’arrêter.", "Risque de court-termisme ou de sous-pivot quand les indicateurs sont mal choisis."],
                "procedure": ["Écrire un jalon observable et sous le contrôle raisonnable de l’équipe.", "Relier le jalon à la réduction d’une incertitude importante.", "Prévoir le prochain montant seulement après avoir vérifié les besoins et les résultats.", "Tester si le jalon pourrait pousser l’équipe à optimiser le chiffre plutôt que la valeur durable."],
                "example": {
                    "prompt": "Un tour ne libère la tranche suivante que si les ventes atteignent un objectif très court. Quel défaut faut-il tester ?",
                    "steps": ["Vérifier si le chiffre de vente mesure réellement l’adoption durable.", "Identifier les comportements possibles : promotions excessives, clients non récurrents, abandon du développement produit.", "Ajouter des indicateurs complémentaires et une décision qualitative de revue."],
                    "answer": "Un jalon unique et court peut détourner l’effort vers une métrique immédiate; il doit refléter le progrès économique réel.",
                    "exam_refs": ["2024-B20"],
                },
                "sources": [{"file": "Topic 1 Introduction to venture capital and the VC ecosystem.pdf", "pages": "25–29"}, {"file": "Topic 4 Term sheets, deal structuring and negotiation(1).pdf", "pages": "8–9"}],
            },
            {
                "title": "4. Fonds, rendement et durée",
                "explain": "Un fonds de VC collecte du capital auprès d’investisseurs (LPs) et le gérant le déploie au travers de sociétés de portefeuille. Les résultats d’un fonds ne se lisent pas avec un seul indicateur. Le MOIC mesure un multiple de capital; l’IRR tient compte du calendrier des flux; DPI mesure les sommes déjà distribuées; RVPI estime la valeur encore détenue; TVPI combine réalisé et résiduel. Le PIC compare le capital versé au capital engagé. La J-curve décrit des débuts souvent faibles avant les réalisations et distributions. Les pages de collecte comparent aussi les fonds par stade, la composition des investisseurs, les secteurs et l’origine géographique du capital. Les chiffres 2021–2025 sont des observations datées, pas des paramètres à mémoriser comme des lois économiques.",
                "formulas": ["MOIC = (valeur réalisée + valeur résiduelle non réalisée) / capital investi", "IRR : taux qui annule la valeur actuelle nette des flux datés", "DPI = distributions cumulées / capital versé (paid-in)", "RVPI = valeur résiduelle (NAV) / capital versé (paid-in)", "TVPI = DPI + RVPI", "PIC = capital versé / capital engagé"],
                "example": {
                    "prompt": "Un fonds a appelé 20 M€, distribué 15 M€ et conserve un NAV de 25 M€. Calcule DPI, RVPI et TVPI.",
                    "steps": ["DPI = 15 / 20 = 0,75x.", "RVPI = 25 / 20 = 1,25x.", "TVPI = 0,75x + 1,25x = 2,00x."],
                    "answer": "Le fonds a rendu 0,75x en cash, conserve 1,25x de valeur estimée et affiche un TVPI de 2,00x. La partie RVPI reste non réalisée et peut évoluer.",
                    "exam_refs": ["2024-A03"],
                },
                "sources": [{"file": "Topic 1 Introduction to venture capital and the VC ecosystem.pdf", "pages": "34–41"}, {"file": "Sessions 5-6 Venture Capital.pdf", "pages": "19–20"}],
            },
            {
                "title": "5. Comprendre les clôtures et le partage des distributions",
                "explain": "Un fonds collecte des engagements, effectue une première clôture lorsqu’il a atteint le minimum qui lui permet de commencer à investir, puis peut accueillir d’autres LP lors de clôtures suivantes. Les distributions suivent l’ordre prévu par le limited partnership agreement : le retour du capital, un éventuel rendement préférentiel, le catch-up du GP puis le partage du solde selon le carried interest convenu. La séquence exacte dépend du waterfall (whole-fund ou deal-by-deal), des définitions et des clauses de clawback.",
                "key_ideas": ["Un engagement de capital n’est pas identique à un appel de fonds ni à une distribution.", "Le hurdle est le rendement minimal défini au contrat; il ne garantit pas le rendement réel.", "Le catch-up attribue temporairement une part disproportionnée au GP après le hurdle afin d’atteindre le partage convenu.", "Les règles de calcul varient : lire les documents du fonds avant d’appliquer un waterfall."],
                "procedure": ["Lire si le calcul porte sur le fonds entier ou une seule opération.", "Rendre d’abord le capital selon les priorités contractuelles.", "Appliquer le rendement préférentiel, puis le catch-up si le contrat en prévoit un.", "Partager le reliquat selon le carried interest et vérifier les éventuels clawbacks."],
                "example": {
                    "prompt": "Un sujet décrit un fonds avec hurdle LP, catch-up GP et partage final 80/20. Dans quel ordre faut-il traiter une distribution ?",
                    "steps": ["Repérer le waterfall et confirmer s’il est whole-fund ou deal-by-deal.", "Rembourser le capital appelé/versé selon le rang contractuel.", "Servir le hurdle LP, puis le catch-up GP prévu.", "Partager le solde au ratio 80/20 et contrôler les clauses de clawback."],
                    "answer": "L’ordre doit être repris du contrat. Dans le schéma simplifié énoncé, le capital puis le hurdle précèdent le catch-up, puis le partage 80/20; les montants ne peuvent pas être calculés sans montant distribué et convention complète.",
                    "exam_refs": ["2023-B11", "2024-A01", "2024-A02"],
                },
                "sources": [{"file": "PEVC final exam 2024 solutions.pdf", "pages": "Q1–Q2, notions connexes"}, {"file": "PEVC final exam 2023 (1).pdf", "pages": "Q11, notion connexe"}],
            },
            {
                "title": "6. De la recherche d’une startup à la sortie",
                "explain": "Le travail du VC commence par le sourcing et la sélection, puis une diligence sur le produit, le marché, l’équipe, les projections et les besoins de financement. Après la négociation, le fonds soutient l’entreprise, aide à compléter l’équipe et peut syndiquer le tour avec un lead et des co-investisseurs. La relation mène à un événement de liquidité, par exemple une vente ou une introduction en bourse. Le choix de l’investisseur doit aussi tenir compte de sa thèse, de son horizon, de ses réseaux et de sa façon d’accompagner.",
                "key_ideas": ["Sourcing et sélection sont deux étapes différentes.", "La diligence d’une startup repose sur des preuves limitées et des hypothèses explicites.", "Le lead coordonne généralement la diligence et les conditions; les followers apportent capital, expertise ou réseau.", "F.I.R.E. présente le parcours comme recherche/sélection, structuration, apprentissage/gouvernance, puis liquidité.", "La grille F.U.E.L. invite à vérifier identité et structure de l’investisseur, ses objectifs, sa contribution et sa façon d’opérer."],
                "example": {
                    "prompt": "Deux fonds proposent le même montant. L’un a investi dans ton secteur et peut aider au recrutement; l’autre est plus connu mais n’a pas d’expérience pertinente. Comment comparer leur valeur au-delà du prix ?",
                    "steps": ["Appliquer F.U.E.L. : clarifier l’identité, la structure et les objectifs de chacun.", "Évaluer les ressources réellement mobilisables : expertise, recrutement, clients et réseau.", "Demander des exemples concrets de soutien et des références de fondateurs.", "Comparer la façon de travailler, les droits, l’horizon et la qualité de la relation."],
                    "answer": "Choisis à partir de preuves d’adéquation et de contribution, pas de la seule réputation. Le bon investisseur doit convenir au besoin et au stade de l’entreprise.",
                    "exam_refs": [],
                },
                "sources": [{"file": "Topic 1 Introduction to venture capital and the VC ecosystem.pdf", "pages": "42–49"}],
            },
        ],
    },
    {
        "id": "topic-2",
        "chapter": "TOPIC 2",
        "title": "Évaluer une startup et construire un plan crédible",
        "objective": "Passer d’une idée à une analyse argumentée de l’opportunité, de l’équipe, du marché et des besoins financiers.",
        "recommended_exam": {"year": 2023, "question_id": "2023-A11"},
        "exam_question_ids": ["2023-A07", "2023-A11", "2023-A13", "2024-A04"],
        "sections": [
            {
                "title": "1. Séparer opportunité, modèle et plan d’affaires",
                "explain": "L’opportunité décrit le problème ou le besoin non satisfait. Le modèle d’affaires explique comment l’entreprise crée et capture de la valeur : proposition, revenus, coûts et canaux. Le plan d’affaires organise l’exécution dans le temps, les ressources, les jalons et les prévisions. Une bonne idée n’est donc pas encore une preuve de demande ni une projection financière crédible.",
                "key_ideas": ["L’incertitude radicale rend les prévisions fragiles au début.", "La diligence cherche des preuves et des hypothèses à tester, pas seulement une histoire convaincante.", "Les projections doivent expliciter leurs moteurs opérationnels et leur horizon."],
                "example": {
                    "prompt": "Une équipe dit : « nous avons une idée innovante et un marché de 10 Md€ ». Quelles preuves manquent avant d’en faire une opportunité investissable ?",
                    "steps": ["Reformuler le problème client et identifier qui le rencontre.", "Vérifier que des clients l’ont confirmé et tester leur disposition à payer.", "Décrire le modèle de revenus, les coûts et le canal d’acquisition.", "Transformer les inconnues en hypothèses mesurables et jalons de test."],
                    "answer": "Une grande taille de marché et une idée ne prouvent ni la demande, ni la capacité à capturer la valeur, ni l’exécution. Il faut relier chaque affirmation à une preuve et à un test.",
                    "exam_refs": [],
                },
                "sources": [{"file": "Topic 2 Evaluating startups(1).pdf", "pages": "2–6, 19–23"}, {"file": "Gompers et al. 2020 How do venture capitalists make decisions.pdf"}],
            },
            {
                "title": "2. Utiliser la Venture Evaluation Matrix",
                "explain": "La matrice structure la revue autour de la proposition de valeur, de l’industrie, de la stratégie et de l’avantage concurrentiel. Elle examine neuf angles : besoin, solution, équipe; marché, concurrence, réseau; ventes, production, organisation. Elle oblige à distinguer la valeur pour le client, la possibilité de passer à l’échelle et la capacité de l’entreprise à capter cette valeur.",
                "key_ideas": ["Besoin : qui souffre du problème, avec quelle intensité et quelle disposition à payer ?", "Solution : le produit résout-il vraiment le problème, se distingue-t-il et peut-il être protégé ?", "Équipe : compétences, engagement, complémentarité et lacunes à combler.", "Marché : TAM, SAM et SOM, cycle de vie, adoption et effet de réseau.", "Concurrence et réseau : acteurs établis ou émergents, différenciation, accès aux ressources et crédibilité.", "Ventes, production, organisation : acquisition, tarification, développement, opérations, recrutement et gouvernance."],
                "procedure": ["Pour chaque cellule, écrire une hypothèse.", "Associer une preuve disponible ou un test à réaliser.", "Identifier le risque marché, technologie ou équipe.", "Décider de continuer, pivoter ou abandonner en indiquant ce qui ferait changer la conclusion."],
                "example": {
                    "prompt": "Une entreprise dit viser un marché de 20 Md€. Comment examiner si ce chiffre soutient réellement son potentiel ?",
                    "steps": ["Demander quelle part du marché correspond au problème résolu : TAM.", "Retirer les segments, géographies et clients non servis : SAM.", "Estimer les clients atteignables par le canal et la capacité réels : SOM.", "Comparer le SOM aux ventes projetées et aux preuves d’adoption."],
                    "answer": "La taille globale ne suffit pas; la prévision doit être cohérente avec les clients accessibles, le canal, la capacité et la vitesse d’adoption.",
                    "exam_refs": [],
                },
                "sources": [{"file": "Topic 2 Evaluating startups(1).pdf", "pages": "7–18"}, {"file": "Venture evaluation matrix.xlsx", "sheets": "VE Matrix; Spreadsheet Tool; Evaluation Table"}],
            },
            {
                "title": "3. Transformer des hypothèses en projections",
                "explain": "Une prévision utile révèle les leviers et le besoin de financement; elle ne prétend pas connaître l’avenir. Pour les revenus, une approche bottom-up part de la capacité, des volumes et du prix net. Une approche top-down part de la taille du marché et de la part atteignable. Les deux se confrontent. Les sources comprennent les clients et fournisseurs, les données de l’entreprise et les recherches secondaires.",
                "formulas": ["Revenu bottom-up = unités vendues × prix net", "Revenu top-down = taille du marché × part atteinte × taux de réalisation", "Marge brute = (revenus − COGS) / revenus"],
                "example": {
                    "prompt": "Dans le cas Workhorse, 7 000 WonderFoal sont vendus en 2027 au prix net de 330,60 $. Estime le revenu et explique ce qu’il faut vérifier ensuite.",
                    "steps": ["Calculer le revenu : 7 000 × 330,60 $ = 2 314 200 $.", "Comparer ce volume à la capacité et au plan de distribution.", "Comparer le prix net au prix catalogue après remises et retours.", "Vérifier le coût unitaire, la marge et le financement du stock."],
                    "answer": "Le revenu projeté est d’environ 2,314 M$. Il reste à vérifier les unités vendues, le prix réalisé, la production et le besoin en fonds de roulement.",
                    "exam_refs": [],
                },
                "sources": [{"file": "Topic 2 Evaluating startups(1).pdf", "pages": "20–26"}, {"file": "Class assignments - solutions.xlsx", "sheets": "3. NextBigThing; 3. Sky-π"}],
            },
            {
                "title": "4. Modéliser coûts, trésorerie et besoin de financement",
                "explain": "Le modèle distingue coût des ventes, charges opérationnelles, investissement et fonds de roulement. Le compte de résultat explique marges et rentabilité; le tableau de flux explique l’usage du cash et la survie. Les simplifications peuvent être utiles, mais omettre le bilan ou le besoin en fonds de roulement peut cacher une crise de liquidité. Le besoin levé aujourd’hui doit amener l’entreprise jusqu’au prochain jalon avec une marge de sécurité.",
                "key_ideas": ["COGS : coûts directs liés à la production ou au service.", "OPEX : dépenses nécessaires à l’exploitation, notamment équipe, vente, R&D et administration.", "CAPEX : achats d’actifs ou investissements capitalisés.", "NWC : créances et stocks moins dettes fournisseurs; sa croissance consomme du cash.", "Burn rate : rythme de consommation du cash; runway : durée estimée avant épuisement de la trésorerie."],
                "procedure": ["Construire les revenus à partir des volumes et prix.", "Projeter COGS et marge brute; calculer les OPEX depuis le plan d’équipe et les activités.", "Ajouter CAPEX, variation de NWC, impôts et autres flux.", "Calculer le déficit de trésorerie maximal, le runway et le financement requis jusqu’au prochain jalon."],
                "example": {
                    "prompt": "Dans le cas Workhorse, 7 000 unités sont vendues au prix net de 330,60 $. Calcule le chiffre d’affaires, puis indique deux éléments qui changent le besoin de financement.",
                    "steps": ["Chiffre d’affaires = 7 000 × 330,60 $ = 2 314 200 $.", "Soustraire les coûts directs pour obtenir la marge brute.", "Ajouter les dépenses d’exploitation et les investissements nécessaires.", "Tenir compte des stocks, créances et délais fournisseurs : une hausse du fonds de roulement consomme de la trésorerie."],
                    "answer": "Le chiffre d’affaires projeté est 2,3142 M$. La marge brute, les OPEX, les CAPEX et le fonds de roulement déterminent si cette croissance génère du cash ou nécessite un financement supplémentaire.",
                    "exam_refs": [],
                },
                "sources": [{"file": "Topic 2 Evaluating startups(1).pdf", "pages": "27–36"}, {"file": "Class assignments - solutions.xlsx", "sheets": "3. PhD student; 3. Sky-π"}],
            },
            {
                "title": "5. Faire de la matrice une décision",
                "explain": "La matrice n’est ni un score objectif de vérité ni un substitut à la diligence. Une bonne synthèse relie chaque risque à une preuve, une conséquence financière et un prochain test. Des forces peuvent justifier de continuer; des faiblesses réparables peuvent mener à pivoter; une absence persistante de besoin ou une barrière insurmontable peut conduire à abandonner.",
                "key_ideas": ["La matrice aide les fondateurs à prioriser les hypothèses, et les VCs à structurer le screening et la diligence.", "Les poids d’un outil d’évaluation reflètent des choix de jugement; ils ne sont pas des probabilités de succès.", "Une recommandation doit distinguer faits, hypothèses et informations manquantes."],
                "example": {
                    "prompt": "La solution fonctionne en test, mais aucun client n’a accepté de payer et le coût d’acquisition paraît élevé. Donne une décision provisoire et le prochain test qui pourrait la faire changer.",
                    "steps": ["Séparer le fait observé (test technique réussi) des hypothèses (demande, prix et acquisition).", "Identifier la faiblesse la plus importante : preuve de demande et économie d’acquisition.", "Proposer un test rapide avec des clients cibles et une offre payante mesurable.", "Décider de continuer, pivoter ou abandonner selon un seuil fixé à l’avance."],
                    "answer": "La conclusion reste provisoire. Le test doit réduire une incertitude décisive et le seuil de décision doit être défini avant d’observer le résultat.",
                    "exam_refs": [],
                },
                "sources": [{"file": "Topic 2 Evaluating startups(1).pdf", "pages": "11–13, 18–19"}, {"file": "Venture evaluation matrix.xlsx", "sheets": "Spreadsheet Tool; Evaluation Table"}, {"file": "Class assignments - solutions.xlsx", "sheets": "3 TriplexGo; 3. Aliboy"}, {"file": "Homework Assignment 2026.xlsx", "sheets": "Docklane Systems; Vale Robotics"}],
            },
        ],
    },
    {
        "id": "topic-3",
        "chapter": "TOPIC 3",
        "title": "Valorisation, propriété et rendement",
        "objective": "Résoudre une valorisation de tour, reconstruire une cap table et relier participation, dilution et rendement à la sortie.",
        "recommended_exam": {"year": 2025, "question_id": "2025-B16"},
        "exam_question_ids": ["2023-A04", "2023-A05", "2023-A10", "2023-A14", "2023-A15", "2023-C16", "2024-A08", "2024-A09", "2024-A10", "2024-B18", "2024-C23", "2025-A05", "2025-A06", "2025-A07", "2025-A09", "2025-B16", "2025-B17", "2025-B18", "2025-B19", "2025-C21"],
        "sections": [
            {
                "title": "1. Distinguer pre-money, post-money et prix par action",
                "explain": "Le pre-money est la valeur négociée avant l’arrivée du nouveau cash. Le post-money l’ajoute. Si l’investissement I achète une part F de la société après le tour, alors le post-money se déduit de I/F. Avec N actions avant le tour, le prix par action se calcule à partir de la base pre-money retenue.",
                "formulas": ["Post-money = pre-money + investissement", "Post-money = investissement / part de l’investisseur", "Pre-money = post-money − investissement", "Prix/action = pre-money / actions pre-money fully diluted", "Actions nouvelles = investissement / prix par action"],
                "procedure": ["Lire si la valorisation donnée est pre-money ou post-money.", "Calculer celle qui manque sans mélanger le cash avant et après le tour.", "Définir la base d’actions, y compris les options si le calcul est fully diluted.", "Calculer le prix puis les actions émises et vérifier que les pourcentages somment à 100 %."],
                "example": {
                    "prompt": "Une entreprise vaut 12 M$ pre-money et reçoit 3 M$. Elle a 4 millions d’actions fully diluted avant le tour. Calcule le post-money, le prix par action, les actions nouvelles et la part de l’investisseur.",
                    "steps": ["Post-money = 12 + 3 = 15 M$.", "Prix par action = 12 M$ / 4 M d’actions = 3 $.", "Actions nouvelles = 3 M$ / 3 $ = 1 M d’actions.", "Part de l’investisseur = 1 / (4 + 1) = 20 %. Vérifier : 3 M$ / 15 M$ = 20 %."],
                    "answer": "Le post-money est 15 M$, le prix est 3 $ par action, l’investisseur reçoit 1 million d’actions et détient 20 % après le tour. Hypothèse : la base fully diluted de 4 millions est la base pre-money retenue et il n’y a ni pool additionnel ni convertible.",
                    "exam_refs": ["2023-A04", "2024-A08", "2025-A07"],
                },
                "sources": [{"file": "Topic 3 Valuation, ownership and returns(1).pdf", "pages": "2–3"}],
            },
            {
                "title": "2. Comprendre la négociation de valorisation",
                "explain": "La valorisation est négociée entre des parties aux intérêts différents. À chèque égal, une valorisation post-money plus élevée donne moins d’actions au nouvel investisseur; celui-ci peut donc préférer une valorisation plus basse. Le prix dépend aussi de la qualité de l’opportunité, du contexte de marché, de la concurrence entre investisseurs, des ressources stratégiques et de la structure des conditions. Les taux, l’appétit pour le risque et la liquidité modifient les multiples et le hurdle; il faut distinguer ces effets des fondamentaux propres à l’entreprise.",
                "key_ideas": ["Le prix ne résume pas le contrat : préférences, contrôle, option pool, vesting et droits futurs peuvent changer la valeur économique.", "Un même taux de croissance prévu peut produire une valorisation différente selon les taux d’actualisation et les comparables disponibles.", "Une concurrence crédible entre offres peut améliorer le pouvoir de négociation, mais chaque offre doit être comparée sur l’ensemble de ses clauses."],
                "procedure": ["Séparer les hypothèses propres à la startup des conditions de marché.", "Comparer le prix et la dilution selon la même base d’actions.", "Traduire chaque droit et préférence en résultats dans plusieurs scénarios.", "Expliquer quelles hypothèses, si elles changent, feraient changer la recommandation."],
                "example": {
                    "prompt": "Les taux montent et les multiples des comparables baissent. Pour un même montant investi, quels effets peuvent apparaître sur la valeur du tour et la part demandée ?",
                    "steps": ["Une hausse du taux d’actualisation/hurdle réduit la valeur actuelle des flux ou de la sortie attendue.", "Une baisse des multiples comparables peut réduire la valeur de sortie estimée.", "Dans le VCM simple, une valeur de sortie plus basse ou un hurdle plus élevé réduit le post-money implicite.", "À investissement fixé, l’investisseur peut alors demander une part plus importante; distinguer cette pression de la qualité opérationnelle propre à la startup."],
                    "answer": "Sous ces hypothèses, la valeur implicite tend à baisser et l’ownership nécessaire à augmenter. L’ampleur dépend des hypothèses, du contrat et de la négociation; ce n’est pas une règle mécanique pour toutes les entreprises.",
                    "exam_refs": ["2024-B18"],
                },
                "sources": [{"file": "Topic 3 Valuation, ownership and returns(1).pdf", "pages": "12–14"}, {"file": "PEVC final exam 2024 solutions.pdf", "pages": "Q18"}],
            },
            {
                "title": "3. Construire une cap table fully diluted",
                "explain": "La cap table indique qui détient combien d’actions et de propriété avant puis après un tour. Sur une base fully diluted, les actions potentielles sont prises en compte comme si les options, warrants et convertibles se transformaient en actions selon les hypothèses retenues. Le pool d’options est souvent inclus dans la base pre-money : il dilue les détenteurs existants avant l’investissement du nouvel investisseur.",
                "formulas": ["Total post-money = actions fondateurs + pool + actions investisseur", "Part d’un détenteur = ses actions / total fully diluted", "Si les fondateurs représentent F et détiennent N actions : total = N / F"],
                "example": {
                    "prompt": "Les fondateurs ont 5 millions d’actions; le VC investit 2 M$ à 8 M$ post-money; un pool de 20 % post-money est demandé.",
                    "steps": ["Ownership VC = 2 / 8 = 25 %.", "Ownership fondateurs = 100 % − 25 % − 20 % = 55 %.", "Total fully diluted = 5 / 55 % = 9,091 M d’actions.", "Pool = 20 % × 9,091 = 1,818 M; VC = 25 % × 9,091 = 2,273 M."],
                    "answer": "La table se réconcilie : 55 % fondateurs + 20 % pool + 25 % VC = 100 %. Le plan d’options peut diluer davantage les fondateurs qu’ils ne l’anticipent.",
                    "exam_refs": ["2025-B17"],
                },
                "sources": [{"file": "Topic 3 Valuation, ownership and returns(1).pdf", "pages": "4–7"}, {"file": "Class assignments - solutions.xlsx", "sheets": "3. Aliboy"}, {"file": "Homework Assignment 2026.xlsx", "sheets": "Vale Robotics"}],
            },
            {
                "title": "4. Suivre dilution et rendement jusqu’à la sortie",
                "explain": "À chaque tour, les nouvelles actions augmentent le dénominateur et diluent les détenteurs qui ne réinvestissent pas. La part d’un ancien investisseur après un nouveau tour devient sa part précédente multipliée par la fraction qui n’a pas été vendue au nouveau tour. À la sortie, le rendement dépend de la part détenue, du montant investi et du temps.",
                "formulas": ["Part post-tour = actions détenues / total fully diluted post-tour", "Produit de sortie = part détenue à la sortie × valeur de sortie", "MOIC/CCM = produit de sortie / investissement initial", "IRR composé = MOIC^(1 / années) − 1"],
                "key_ideas": ["Le MOIC ignore la durée; l’IRR annualise les flux et peut être très sensible au calendrier.", "Les convertibles en actions et les actions nouvelles d’une IPO modifient la participation.", "Pour une série de tours avec multiples cibles, remonter depuis la sortie : post-money du dernier tour, pre-money, puis tour précédent."],
                "example": {
                    "prompt": "Annale 2023 · XO investit 10 M$ pour des preferred convertibles en 15 M d’actions ordinaires, soit 30 % après conversion. À l’IPO, 50 M d’actions valent 10 $ chacune et les frais de souscription sont de 8 %. Calcule le produit de XO et son IRR sur cinq ans.",
                    "steps": ["Capitalisation boursière = 50 M × 10 $ = 500 M$.", "Produit net après frais = 500 × (1 − 8 %) = 460 M$.", "Produit de XO = 30 % × 460 = 138 M$; CCM = 138 / 10 = 13,8x.", "IRR composé = 13,8^(1/5) − 1 ≈ 69,0 %."],
                    "answer": "XO reçoit 138 M$ nets et réalise un CCM de 13,8x, soit un IRR d’environ 69,0 % sur cinq ans, selon les conventions simplifiées du sujet.",
                    "exam_refs": ["2023-A14", "2023-A15"],
                },
                "sources": [{"file": "Topic 3 Valuation, ownership and returns(1).pdf", "pages": "8–11"}, {"file": "VC final exam 2025 solutions.pdf", "pages": "5–6"}, {"file": "Homework Assignment 2026.xlsx", "sheets": "Meridian Systems"}],
            },
            {
                "title": "5. Appliquer la Venture Capital Method",
                "explain": "La méthode part d’une valeur de sortie estimée, de l’horizon et du rendement exigé par l’investisseur. Elle actualise la valeur de sortie avec un multiple cible ou un hurdle rate, en déduit le post-money puis l’ownership que nécessite le chèque. L’hurdle incorpore notamment les risques, l’illiquidité, la durée et les services fournis. Le taux ou multiple ne doit pas être traité comme une garantie.",
                "formulas": ["CCM requis = (1 + hurdle)^T", "Post-money = valeur de sortie / CCM requis", "Ownership requise = investissement / post-money"],
                "key_ideas": ["Le modèle simple ne pondère pas directement une valeur de sortie selon la probabilité de succès; le cours discute séparément la prime d’échec.", "En multi-tours, on peut remonter de la sortie ou ne prévoir que le prochain tour si la sortie est trop incertaine.", "Toujours préciser devise, période, hypothèse de sortie et définition du hurdle."],
                "example": {
                    "prompt": "Annale 2025 · Palooka reçoit 5 M$ aujourd’hui, prévoit une sortie de 50 M$ dans cinq ans et le VC demande 40 % de rendement annuel. Quelle ownership minimale la méthode implique-t-elle ?",
                    "steps": ["Calculer le multiple requis : (1 + 0,40)⁵ ≈ 5,378×.", "Calculer la valeur post-money : 50 / 5,378 ≈ 9,297 M$.", "Calculer l’ownership : 5 / 9,297 ≈ 53,8 %.", "Vérifier que le calcul suppose une sortie unique, sans dilution future ni préférence supplémentaire."],
                    "answer": "La méthode VC implique environ 53,8 % d’ownership dans ces hypothèses. Le résultat est une exigence de rendement modélisée, pas une valorisation objective.",
                    "exam_refs": ["2024-A10", "2025-B16"],
                },
                "sources": [{"file": "Topic 3 Valuation, ownership and returns(1).pdf", "pages": "15–22"}, {"file": "Class assignments - solutions.xlsx", "sheets": "3. NextBigThing"}],
            },
            {
                "title": "6. Comparables, DCF et incertitude",
                "explain": "Les comparables donnent une valeur relative à partir de pairs pertinents et de multiples cohérents. Les comparables d’investissement sont des tours privés; les comparables de sortie sont des entreprises déjà cédées ou cotées. Les multiples doivent être comparés avec leurs dates, stades, modèles économiques, métriques, minima, médianes et plages. Un DCF est conceptuellement fondé mais fragile pour une jeune startup si les flux sont très incertains.",
                "formulas": ["Valeur de sortie estimée = métrique de la startup × multiple comparable", "Valeur DCF = somme des flux actualisés + valeur terminale actualisée", "Valeur scénario = somme(probabilité du scénario × valeur du scénario)"],
                "key_ideas": ["La valeur terminale par croissance perpétuelle exige g < taux d’actualisation.", "Les revenus ou métriques opérationnelles peuvent être plus utiles que l’EBITDA pour une startup pré-profit.", "L’analyse de scénarios rend les hypothèses de probabilité visibles; Monte Carlo fait varier plusieurs paramètres et produit une distribution de résultats."],
                "example": {
                    "prompt": "Deux startups de logiciels ont chacune 1 M€ d’ARR. L’une a une rétention forte et une croissance plus rapide; l’autre dépend de deux clients et a une croissance faible. Comment choisir les comparables et présenter une fourchette de valeur ?",
                    "steps": ["Choisir des pairs proches par modèle, stade, taille, croissance et profil de risque.", "Privilégier les multiples compatibles avec la métrique et la maturité de chaque entreprise.", "Présenter médiane et plage plutôt qu’un seul multiple, et expliquer les ajustements.", "Tester une sensibilité aux multiples et séparer la valeur observée du jugement sur les fondamentaux."],
                    "answer": "Le multiple moyen du secteur ne suffit pas : les comparables doivent être justifiés, datés et cohérents. Une fourchette rend visibles l’hétérogénéité et l’incertitude; elle ne constitue pas une valorisation certaine.",
                    "exam_refs": [],
                },
                "sources": [{"file": "Topic 3 Valuation, ownership and returns(1).pdf", "pages": "23–32"}, {"file": "Class assignments - solutions.xlsx", "sheets": "3. NextBigThing; 3. Sky-π"}],
            },
        ],
    },
    {
        "id": "topic-4",
        "chapter": "TOPIC 4",
        "title": "Term sheets, instruments et négociation",
        "objective": "Lire les clauses qui répartissent valeur, risque, contrôle et incitations; comparer leurs effets dans plusieurs scénarios de sortie.",
        "recommended_exam": {"year": 2025, "question_id": "2025-C20"},
        "exam_question_ids": ["2023-B12", "2024-A06", "2024-B19", "2025-A02", "2025-A08", "2025-A10", "2025-A11", "2025-A12", "2025-A14", "2025-A15", "2025-C20"],
        "sections": [
            {
                "title": "1. Documents des fondateurs et documents sociaux",
                "explain": "L’accord entre fondateurs clarifie avant l’investissement la propriété, les rôles, les contributions, l’IP, la confidentialité, le vesting, les départs et la résolution des blocages. Les statuts et documents d’incorporation établissent l’entité et ses règles. Le pacte d’actionnaires encadre la relation entre détenteurs de titres et évolue généralement lors des nouveaux tours. La cap table doit rester à jour et cohérente avec les documents.",
                "key_ideas": ["Documenter la cession de propriété intellectuelle à la société.", "Définir les droits, obligations et situations de départ des fondateurs.", "Un term sheet résume les conditions proposées et sert de base aux contrats finaux; certaines clauses particulières peuvent avoir un effet contraignant, il faut lire le document exact."],
                "example": {
                    "prompt": "Deux cofondateurs apportent des contributions différentes. L’un développe le code avant la création de la société. Quels sujets régler avant la levée ?",
                    "steps": ["Mettre par écrit les rôles, responsabilités et contributions de chacun.", "Vérifier la cession de la propriété intellectuelle à la société et les engagements de confidentialité.", "Définir l’allocation des actions, le vesting, les départs et le traitement des blocages.", "Réconcilier l’accord, les statuts, le pacte d’actionnaires et la cap table."],
                    "answer": "Les documents doivent attribuer clairement les droits et obligations et rester cohérents entre eux; un code développé avant l’incorporation doit notamment être transféré à la société selon les documents applicables.",
                    "exam_refs": [],
                },
                "sources": [{"file": "Topic 4 Term sheets, deal structuring and negotiation(1).pdf", "pages": "2–7"}, {"file": "Sample - Founders Agreement.pdf"}, {"file": "Background note and sample - Notes on contents of a term sheet.pdf"}],
            },
            {
                "title": "2. Jalons, term sheet et incitations",
                "explain": "Une term sheet distribue les droits économiques, les droits de contrôle, la rémunération des personnes clés et les droits liés aux tours futurs ou à la sortie. Les jalons peuvent conditionner des tranches, l’évolution de la gouvernance ou certains termes. Ils doivent être observables et réduire une incertitude importante; un objectif mal conçu peut provoquer du court-termisme ou ralentir un pivot utile.",
                "procedure": ["Lister pour chaque clause qui reçoit un droit, quand il peut l’exercer et dans quel scénario.", "Traduire les termes en conséquences financières pour fondateurs et investisseurs.", "Tester plusieurs valeurs de sortie et hypothèses de financement.", "Évaluer aussi contrôle, réputation et capacité de travailler ensemble."],
                "example": {
                    "prompt": "Un jalon de chiffre d’affaires débloque une tranche. Comment éviter que l’équipe optimise une métrique de court terme au détriment du produit ?",
                    "steps": ["Vérifier que le chiffre mesure une adoption durable et non des ventes ponctuelles subventionnées.", "Associer des indicateurs de qualité, rétention ou livraison technique au jalon.", "Prévoir une revue documentée si une hypothèse de marché change.", "Relier l’étape suivante à la réduction de l’incertitude plutôt qu’à un seuil isolé."],
                    "answer": "Un jalon robuste combine des mesures cohérentes avec la création de valeur et une procédure de revue; il évite d’inciter à manipuler un indicateur unique.",
                    "exam_refs": ["2025-A02"],
                },
                "sources": [{"file": "Topic 4 Term sheets, deal structuring and negotiation(1).pdf", "pages": "7–9, 36–39"}, {"file": "Homework Assignment 2026.xlsx", "sheets": "Docklane Systems"}],
            },
            {
                "title": "3. Actions préférentielles et payoffs à la sortie",
                "explain": "Les actions ordinaires reçoivent le résidu selon la propriété. Une préférence de liquidation donne à l’investisseur un droit prioritaire selon son multiple, les dividendes et la seniorité définis. Avec une preferred convertible non participante, l’investisseur compare le paiement préférentiel avec la conversion en actions ordinaires. Une participating preferred récupère d’abord ses termes préférentiels puis partage le résidu; un cap limite ce double rendement et peut créer un seuil de conversion.",
                "formulas": ["Preferred terms PT = multiple de liquidation × investissement + dividende selon la convention", "Convertible non participante = max(PT, part détenue × valeur de sortie), sous réserve du cash disponible", "Participante non plafonnée = PT + part détenue × (valeur de sortie − PT), lorsque la sortie dépasse PT", "Seuil de conversion simple = PT / part détenue"],
                "procedure": ["Calculer les termes préférentiels dus et vérifier que le produit disponible suffit.", "Calculer l’option de conversion en common.", "Comparer les deux payoffs pour la convertible non participante.", "Pour la participating, appliquer d’abord la préférence, puis la participation; appliquer le cap et comparer la conversion conformément au contrat."],
                "example": {
                    "prompt": "Un VC investit 4 M€ avec préférence 1x non participante et détient 30 %. L’entreprise sort à 10 M€.",
                    "steps": ["Terme préférentiel = 1 × 4 = 4 M€.", "Conversion = 30 % × 10 = 3 M€.", "Comparer : 4 M€ est supérieur à 3 M€.", "Le VC reçoit 4 M€; les 6 M€ restants reviennent aux autres détenteurs selon leurs droits."],
                    "answer": "Le paiement est 4 M€, si la préférence est senior et qu’aucun autre droit ou passif ne change le waterfall.",
                    "exam_refs": ["2024-B19", "2025-C20"],
                },
                "sources": [{"file": "Topic 4 Term sheets, deal structuring and negotiation(1).pdf", "pages": "10–21"}, {"file": "Class assignments - solutions.xlsx", "sheets": "4. TrafalgarTech"}],
            },
            {
                "title": "4. Vesting, board et décisions réservées",
                "explain": "Le reverse vesting fait dépendre le droit définitif de conserver certaines actions du temps ou de conditions prévues. Dans l’exemple courant du cours, quatre ans avec un cliff d’un an signifie qu’un quart devient acquis après douze mois, puis le reste progressivement. La term sheet précise aussi la taille du board, ses nominations, les votes, les matières réservées, les veto et parfois leur expiration.",
                "key_ideas": ["Distinguer actions émises, actions acquises et actions susceptibles d’être rachetées au départ.", "Un cliff n’est pas un vesting mensuel dès le premier jour.", "Les droits de vote et de nomination peuvent déplacer le contrôle sans modifier l’ownership économique.", "L’information et l’observation au board complètent les droits formels."],
                "example": {
                    "prompt": "Annale 2025 · Un fondateur détient 4 millions d’actions avec un reverse vesting de quatre ans et un cliff de douze mois. Il part après un an : combien d’actions ont franchi le cliff, sous réserve des clauses applicables ?",
                    "steps": ["Le vesting total est de quatre ans.", "Après douze mois, le cliff libère un quart : 4 M × 1/4 = 1 M d’actions.", "Les trois millions restantes ne sont pas encore acquises selon cette hypothèse.", "Lire les clauses de départ, rachat et révocation pour savoir le traitement exact."],
                    "answer": "Un million d’actions est acquis après le premier cliff annuel dans le calendrier décrit; les conséquences d’un départ dépendent du contrat et des faits prévus.",
                    "exam_refs": ["2025-A14"],
                },
                "sources": [{"file": "Topic 4 Term sheets, deal structuring and negotiation(1).pdf", "pages": "22–23"}],
            },
            {
                "title": "5. Anti-dilution et droits des tours futurs",
                "explain": "Dans un down round, les clauses anti-dilution ajustent le prix de conversion de certains titres préférentiels. Le full ratchet reprend le nouveau prix d’émission et est généralement plus protecteur pour l’ancien investisseur, donc plus dilutif pour les autres. Le weighted average tient compte du prix et du volume de nouvelles actions et est généralement plus modéré. Les droits pro rata, de préemption et pay-to-play ont des effets distincts.",
                "key_ideas": ["Pro rata/préemption : possibilité de participer à un futur tour pour maintenir la part.", "Right of first refusal : priorité d’achat sur des actions mises en vente.", "Pay-to-play : le maintien de certains droits peut dépendre de la participation au nouveau tour.", "Une clause anti-dilution ne supprime pas l’émission de nouvelles actions; elle ajuste certaines conversions.", "Drag-along permet, sous conditions, d’entraîner les autres détenteurs dans une vente; tag-along protège la possibilité d’accompagner le vendeur.", "Les clauses de sortie peuvent inclure des droits d’enregistrement et de participation aux ventes; elles ne se confondent pas avec les droits de préemption d’un tour futur."],
                "example": {"prompt": "Un prix de conversion de 1,00 $ est soumis à full ratchet après une émission à 0,90 $. Six millions de dollars en preferred sont concernés.", "steps": ["Le prix ajusté devient 0,90 $ par action.", "Nombre d’actions après conversion = 6 M$ / 0,90 $ = 6,667 M."], "answer": "Le full ratchet augmente le nombre d’actions convertibles; comparer ensuite la dilution avec les autres clauses du tour.", "exam_refs": ["2025-C20"]},
                "sources": [{"file": "Topic 4 Term sheets, deal structuring and negotiation(1).pdf", "pages": "24–26"}, {"file": "VC final exam 2025 solutions.pdf", "pages": "7"}, {"file": "Case - Navigating a Down Round in Venture Capital - GoStage Ventures.pdf", "pages": "1–14"}],
            },
            {
                "title": "6. Convertibles, syndication et négociation",
                "explain": "Une note convertible permet de financer une jeune entreprise sans fixer immédiatement une valorisation. Elle porte généralement intérêt, a une échéance et se convertit lors d’un tour qualifié. Une décote réduit son prix de conversion; un valuation cap protège l’investisseur si la valorisation du tour devient élevée. Quand les deux existent, il faut appliquer la convention du contrat et retenir le prix de conversion le plus favorable à l’investisseur. En syndication, un lead conduit le processus avec des investisseurs qui peuvent partager diligence, capital, risques et savoir-faire.",
                "formulas": ["Montant converti à intérêt simple = principal × (1 + taux × durée)", "Prix avec décote = prix du nouveau tour × (1 − décote)", "Prix sous cap = valuation cap / base d’actions définie par le contrat", "Prix de conversion = minimum entre les prix applicables, selon les clauses du document"],
                "key_ideas": ["La note peut reporter une négociation de valorisation mais ne fait pas disparaître dilution ni complexité.", "Une conversion dépend des définitions du qualified financing, de l’échéance, des intérêts et de la base fully diluted.", "Une syndication peut apporter diversification, expertise et certification; une structure trop large peut créer coordination et conflits.", "Le dilemme Rich-vs-King oppose la priorité donnée à la richesse économique à celle donnée au contrôle; les fondateurs doivent comparer prix, board, veto et droits futurs selon leurs propres objectifs."],
                "example": {
                    "prompt": "Annale 2023 · Pourquoi une jeune startup pourrait-elle utiliser une note convertible plutôt que négocier immédiatement une valorisation précise ?",
                    "steps": ["La startup peut manquer de données pour défendre une valorisation fiable.", "La note apporte des fonds maintenant et reporte la fixation du prix à un tour qualifié.", "L’investisseur peut recevoir des intérêts, une décote ou un cap, selon le contrat.", "Avant de calculer, relever l’échéance, le seuil du tour, la base fully diluted et la règle si cap et décote coexistent."],
                    "answer": "La note reporte la négociation de valorisation et peut accélérer le financement, mais elle crée une conversion future et une dilution qu’il faut modéliser à partir des clauses écrites.",
                    "exam_refs": ["2023-B12", "2025-A15"],
                },
                "sources": [{"file": "Topic 4 Term sheets, deal structuring and negotiation(1).pdf", "pages": "27–39"}, {"file": "Background note - Convertible notes in early-stage financing.pdf", "pages": "1–10"}, {"file": "Background note - A rich-vs-king approach to term sheet negotiations.pdf", "pages": "2–10"}, {"file": "Class assignments - solutions.xlsx", "sheets": "4. Hadupower"}],
            },
        ],
    },
    {
        "id": "topic-5",
        "chapter": "TOPIC 5",
        "title": "Gouvernance, suivi et sorties",
        "objective": "Comprendre le rôle du board après l’investissement, détecter les écarts et comparer les chemins de liquidité.",
        "recommended_exam": {"year": 2025, "question_id": "2025-A04"},
        "exam_question_ids": ["2025-A04", "2025-A13"],
        "sections": [
            {
                "title": "1. Gouverner sans étouffer l’innovation",
                "explain": "Après l’investissement, le VC passe de l’analyse ex ante au suivi ex post. La gouvernance cherche un équilibre dynamique : garder aux fondateurs assez d’autonomie pour innover, tout en protégeant le capital, en responsabilisant l’équipe et en préparant les prochains financements. Les droits formels et la qualité de la relation influencent ensemble les décisions.",
                "key_ideas": ["Les droits de vote peuvent dépendre de toutes les actions, d’une classe ou d’une série.", "Le board approuve généralement des sujets majeurs tels que budget, stratégie, financement et succession du CEO.", "Les protective provisions peuvent demander un consentement particulier pour des opérations importantes.", "Le mentorat, la confiance, les réseaux et la réputation constituent aussi une influence informelle."],
                "example": {
                    "prompt": "Les fondateurs gardent 70 % des actions, mais le budget annuel et une nouvelle émission exigent le consentement du board où les VCs ont la majorité. Qui contrôle réellement ces décisions ?",
                    "steps": ["Distinguer la propriété économique des droits de vote et de nomination.", "Identifier les décisions réservées et le seuil de consentement.", "Vérifier la composition et les règles de quorum du board.", "Conclure séparément sur l’ownership, le contrôle opérationnel et les décisions exceptionnelles."],
                    "answer": "Les fondateurs détiennent la majorité économique, mais le contrôle des décisions citées dépend des droits du board et des matières réservées.",
                    "exam_refs": [],
                },
                "sources": [{"file": "Topic 5 Governance, monitoring and exit strategies(1).pdf", "pages": "2–6"}],
            },
            {
                "title": "2. Suivre la performance et décider d’agir",
                "explain": "Un suivi utile compare les résultats au budget, actualise les prévisions et identifie assez tôt les difficultés. Il couvre le cash, le burn et le runway; les jalons produit et commerciaux; les recrutements; ainsi que les risques juridiques ou clients. Le board doit convenir d’actions, de responsables et d’échéances. Quand la startup grandit, les fondateurs peuvent avoir besoin de compléter leurs compétences par des dirigeants expérimentés.",
                "procedure": ["Comparer le réel aux hypothèses et expliquer les écarts.", "Traduire l’écart en impact sur cash, jalons, équipe et prochain tour.", "Choisir une action avec responsable, date et mesure de résultat.", "Réévaluer le plan si le marché ou les hypothèses ont changé."],
                "example": {
                    "prompt": "Le chiffre d’affaires est 20 % sous le budget et le burn dépasse de 10 % le plan. Quelles sont les trois premières étapes de la revue ?",
                    "steps": ["Décomposer l’écart de revenu par volume, prix, délai et rétention.", "Vérifier le cash disponible, le burn réel et le runway mis à jour.", "Choisir une action mesurable, un responsable et une date de revue; réviser le jalon ou le plan si nécessaire."],
                    "answer": "La revue part des causes vérifiables, évalue l’effet sur la trésorerie et se termine par une action suivie. Elle ne consiste pas à constater un écart sans décision.",
                    "exam_refs": [],
                },
                "sources": [{"file": "Topic 5 Governance, monitoring and exit strategies(1).pdf", "pages": "7–8"}],
            },
            {
                "title": "3. Lire le contexte institutionnel avec prudence",
                "explain": "Le cours compare des systèmes juridiques et des styles de gouvernance, notamment l’usage de protections contractuelles, la place des relations et l’exécution des droits. Ces contrastes sont des repères de comparaison, pas une règle absolue sur chaque pays ou chaque contrat. Dans un dossier réel, il faut examiner la loi applicable, les statuts, le pacte et la manière dont les droits sont exécutés.",
                "key_ideas": ["Un droit écrit ne vaut que si sa portée et son exécution sont comprises.", "Les contrats transfrontaliers doivent préciser le droit applicable et les mécanismes de résolution des conflits.", "La relation, la réputation et les réseaux peuvent compléter les droits juridiques sans les remplacer."],
                "example": {
                    "prompt": "Annale 2025 · Pourquoi certains investisseurs choisissent-ils une domiciliation de common law pour un fonds transfrontalier ?",
                    "steps": ["Lire la réponse au niveau du système et des pratiques contractuelles décrites dans le cours.", "Relier le choix à la prévisibilité et à l’exécution des protections contractuelles recherchées.", "Ne pas en déduire qu’un pays ou contrat de common law est automatiquement supérieur.", "Vérifier dans le cas concret la loi applicable, les documents et les voies d’exécution."],
                    "answer": "Le sujet évalue les motifs liés au cadre contractuel et à l’exécution, tout en laissant à distinguer comparaison générale et conseil juridique sur un dossier réel.",
                    "exam_refs": ["2025-A04", "2025-A13"],
                },
                "sources": [{"file": "Topic 5 Governance, monitoring and exit strategies(1).pdf", "pages": "9"}, {"file": "VC final exam 2025 solutions.pdf", "pages": "2–3"}],
            },
            {
                "title": "4. Choisir et préparer une sortie",
                "explain": "Une sortie réalise la valeur pour le VC, apporte de la liquidité aux fondateurs et peut réinvestir du capital dans l’écosystème. Le bon moment dépend de la maturité de la société, de la fenêtre de marché et de la durée de vie du fonds. Les voies comprennent l’IPO, la vente stratégique, la vente secondaire, le rachat par les fondateurs ou managers, et certains mécanismes de rachat prévus par les titres.",
                "key_ideas": ["IPO : marché et valorisation potentielle, mais coûts, contraintes réglementaires, calendrier et ventes souvent progressives.", "Vente stratégique : peut bénéficier de synergies et donner une liquidité rapide, avec le risque de perdre l’indépendance.", "Secondaire : liquidité partielle ou transfert vers un autre investisseur, parfois avant une sortie complète.", "Buyback ou redemption : dépend de la capacité à générer du cash et des conditions contractuelles.", "Drag-along, tag-along, registration et piggyback organisent certains droits de sortie."],
                "example": {
                    "prompt": "Une société rentable intéresse un acquéreur stratégique, mais ses fondateurs veulent rester indépendants et le fonds approche de la fin de sa durée. Compare une vente et une IPO.",
                    "steps": ["Pour la vente, évaluer synergies, prix, certitude d’exécution et perte d’indépendance.", "Pour l’IPO, évaluer fenêtre de marché, coûts, obligations et liquidité graduelle après lock-up.", "Comparer le calendrier de réalisation au fonds, aux besoins de la société et aux autres actionnaires.", "Prévoir les droits d’entraînement, d’accompagnement et d’enregistrement pertinents dans les documents."],
                    "answer": "Aucune voie ne domine toujours : la décision compare valeur nette, probabilité de réalisation, temps, contrôle et besoins de liquidité des parties.",
                    "exam_refs": [],
                },
                "sources": [{"file": "Topic 5 Governance, monitoring and exit strategies(1).pdf", "pages": "10–14"}],
            },
        ],
    },
)


EXAM_SCOPE: dict[str, tuple[str | None, str]] = {
    # 2023: the source paper also contains PE/M&A items. "related" items remain
    # visible in the archive but do not count as proof of core VC mastery.
    "2023-A01": ("TOPIC 1", "related"), "2023-A03": ("TOPIC 1", "core"),
    "2023-A04": ("TOPIC 3", "core"), "2023-A05": ("TOPIC 3", "core"),
    "2023-A07": ("TOPIC 2", "related"), "2023-A10": ("TOPIC 3", "related"),
    "2023-A11": ("TOPIC 2", "related"), "2023-A13": ("TOPIC 2", "related"),
    "2023-A14": ("TOPIC 3", "related"), "2023-A15": ("TOPIC 3", "related"),
    "2023-B11": ("TOPIC 1", "related"), "2023-B12": ("TOPIC 4", "core"),
    "2023-C16": ("TOPIC 3", "core"),
    # PE/M&A questions are explicitly inventoried too, so the app never treats
    # a missing mapping as proof that an exercise was absent from the bank.
    "2023-A02": (None, "outside_vc_scope"), "2023-A06": (None, "outside_vc_scope"),
    "2023-A08": (None, "outside_vc_scope"), "2023-A09": (None, "outside_vc_scope"),
    "2023-A12": (None, "outside_vc_scope"), "2023-B13": (None, "outside_vc_scope"),
    "2023-B14": (None, "outside_vc_scope"), "2023-B15": (None, "outside_vc_scope"),
    "2023-C17": (None, "outside_vc_scope"),
    # 2024 exam, verified against the scan with page 1 omitted.
    "2024-A01": ("TOPIC 1", "related"), "2024-A02": ("TOPIC 1", "related"),
    "2024-A03": ("TOPIC 1", "related"), "2024-A04": ("TOPIC 2", "related"),
    "2024-A06": ("TOPIC 4", "core"), "2024-A07": ("TOPIC 1", "core"),
    "2024-A08": ("TOPIC 3", "core"), "2024-A09": ("TOPIC 3", "core"),
    "2024-A10": ("TOPIC 3", "core"), "2024-B18": ("TOPIC 3", "core"),
    "2024-B19": ("TOPIC 4", "core"), "2024-B20": ("TOPIC 1", "core"),
    "2024-C23": ("TOPIC 3", "core"),
    "2024-A05": (None, "outside_vc_scope"), "2024-A11": (None, "outside_vc_scope"),
    "2024-A12": (None, "outside_vc_scope"), "2024-A13": (None, "outside_vc_scope"),
    "2024-A14": (None, "outside_vc_scope"), "2024-A15": (None, "outside_vc_scope"),
    "2024-A16": (None, "outside_vc_scope"), "2024-A17": (None, "outside_vc_scope"),
    "2024-B21": (None, "outside_vc_scope"), "2024-B22": (None, "outside_vc_scope"),
    "2024-C24": (None, "outside_vc_scope"),
    # 2025 is the VC-only exam bank.
    "2025-A01": ("TOPIC 1", "core"), "2025-A02": ("TOPIC 4", "core"),
    "2025-A03": ("TOPIC 1", "core"), "2025-A04": ("TOPIC 5", "core"),
    "2025-A05": ("TOPIC 3", "core"), "2025-A06": ("TOPIC 3", "core"),
    "2025-A07": ("TOPIC 3", "core"), "2025-A08": ("TOPIC 4", "core"),
    "2025-A09": ("TOPIC 3", "core"), "2025-A10": ("TOPIC 4", "core"),
    "2025-A11": ("TOPIC 4", "core"), "2025-A12": ("TOPIC 4", "core"),
    "2025-A13": ("TOPIC 5", "core"), "2025-A14": ("TOPIC 4", "core"),
    "2025-A15": ("TOPIC 4", "core"), "2025-B16": ("TOPIC 3", "core"),
    "2025-B17": ("TOPIC 3", "core"), "2025-B18": ("TOPIC 3", "core"),
    "2025-B19": ("TOPIC 3", "core"), "2025-C20": ("TOPIC 4", "core"),
    "2025-C21": ("TOPIC 3", "core"),
}


def lesson_payloads(progress: dict[str, dict[str, Any]] | None = None) -> list[dict[str, Any]]:
    statuses = progress or {}
    lessons = deepcopy(VC_LESSONS)
    for lesson in lessons:
        lesson["progress"] = statuses.get(lesson["id"], {"status": "new", "practice_count": 0})
    return list(lessons)


def classify_exam_question(question_id: str) -> dict[str, str | None]:
    chapter, scope = EXAM_SCOPE.get(question_id, (None, "unclassified"))
    return {"course_chapter": chapter, "course_scope": scope}


class LessonProgressStore:
    """Local learner choices only; it stores no lesson text or course documents."""

    def __init__(self, db_path: str | Path):
        path = Path(db_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = RLock()
        self._conn = sqlite3.connect(str(path), check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute(
            """CREATE TABLE IF NOT EXISTS lesson_progress (
                lesson_id TEXT PRIMARY KEY,
                status TEXT NOT NULL DEFAULT 'new' CHECK(status IN ('new','understood','review')),
                practice_count INTEGER NOT NULL DEFAULT 0,
                updated_at TEXT NOT NULL
            )"""
        )
        self._conn.commit()

    def close(self) -> None:
        with self._lock:
            self._conn.close()

    def all(self) -> dict[str, dict[str, Any]]:
        with self._lock:
            rows = self._conn.execute("SELECT * FROM lesson_progress").fetchall()
            return {row["lesson_id"]: {"status": row["status"], "practice_count": int(row["practice_count"]), "updated_at": row["updated_at"]} for row in rows}

    def decide(self, lesson_id: str, action: str) -> dict[str, Any]:
        if lesson_id not in {lesson["id"] for lesson in VC_LESSONS}:
            raise KeyError("Leçon VC introuvable.")
        if action not in {"understood", "practice", "review"}:
            raise ValueError("Action de leçon inconnue.")
        now = datetime.now(timezone.utc).isoformat(timespec="seconds")
        with self._lock:
            current = self._conn.execute("SELECT * FROM lesson_progress WHERE lesson_id=?", (lesson_id,)).fetchone()
            status = current["status"] if current else "new"
            count = int(current["practice_count"]) if current else 0
            if action == "understood":
                status = "understood"
            elif action == "review":
                status = "review"
            else:
                count += 1
            self._conn.execute(
                """INSERT INTO lesson_progress(lesson_id,status,practice_count,updated_at) VALUES(?,?,?,?)
                   ON CONFLICT(lesson_id) DO UPDATE SET status=excluded.status,
                   practice_count=excluded.practice_count, updated_at=excluded.updated_at""",
                (lesson_id, status, count, now),
            )
            self._conn.commit()
            return {"lesson_id": lesson_id, "status": status, "practice_count": count, "updated_at": now}


__all__ = ["EXAM_SCOPE", "LessonProgressStore", "VC_LESSONS", "classify_exam_question", "lesson_payloads"]
