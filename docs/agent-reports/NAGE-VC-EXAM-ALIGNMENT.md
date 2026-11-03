# Audit du sujet VC 2025 — alignement question par question

Date : 2026-11-03

Branche candidate : `codex/vc-mastery-20261103`
SHA audité : `9ae3927bd5eceb39a82218df27783a3fe141e92d`

## Portée et méthode

Audit du document local `VC final exam 2025 solutions.pdf` (8 pages), comparé aux cinq supports Topic 1–5, à `Sessions 5-6 Venture Capital.pdf` lorsqu’utile et aux classeurs d’exercices du cours. Les réponses des QCM ont été vérifiées visuellement sur les pages 2–3. Les réponses chiffrées ont été rapprochées du corrigé extrait; la page 7, qui contient le tableau de term sheets et les payoffs, a aussi été inspectée visuellement. Les pages de cours indiquées ci-dessous sont les pages PDF.

Ce sujet est un repère historique : il décrit un examen de 90 minutes et 60 points, mais ne prouve pas que l’épreuve à venir aura la même forme. Il ne justifie aucune promesse de note.

Une nouvelle extraction isolée du dossier de cours, sans ouvrir ni modifier la base locale d’apprentissage, a trouvé **29 fichiers (26 PDF, 3 XLSX)**. Le parseur courant a accepté 28 fichiers : **1 013 pages/feuilles et 997 unités indexées**. Un PDF de 56 MiB dépasse la limite courante de 50 MiB; il n’a donc pas été inclus. Un examen PEVC 2024 numérisé compte 14 pages, mais son texte extrait est vide. Sa couverture contient un identifiant étudiant : elle n’a pas été recopiée, OCRisée ni ajoutée au dépôt. Un PDF de rapport supplémentaire contient aussi une page sans texte extractible. Le précédent rapport annonçant 29/29 fichiers, 1 501 pages/feuilles et 1 499 unités textuelles n’est pas reproductible avec cette extraction; sa base locale n’a pas été consultée.

## Barème observé

| Partie | Éléments | Points | Ce que permet de vérifier le corrigé |
|---|---|---:|---|
| A — QCM | Q1–Q15, 1 point chacun | 15 | Une réponse attendue par question; lettres correctes en gras dans le corrigé. |
| B — Calculs | Q16: 3; Q17: 3; Q18: 4; Q19: 5 | 15 | Résultats finaux et certaines étapes de calcul. Aucun barème détaillé de points partiels par étape n’est fourni. |
| C — Cas | Q20: 15; Q21: 15 | 30 | Tableaux et conclusions attendues. Les points de chaque sous-partie et une grille analytique de crédit partiel ne sont pas indiqués. |
| **Total** |  | **60** | L’épreuve est à dominante calcul/cas : 45/60 points ne sont pas des QCM. |

La matrice ci-dessous décrit l’état de couverture audité au SHA `9ae3927`; le lot 2 est présenté séparément après elle.

## Matrice des 21 questions

| Q / points | Notion et résultat du corrigé | Référence au cours | État de couverture dans NAGe à ce SHA |
|---|---|---|---|
| Q1 / 1 | Financement par étapes : incitations et jalons, information sur le fondateur, option d’arrêter; réponse D. | Topic 1, p. 6; Topic 5, p. 2. | **Partiel** — une question existe sur les jalons et l’option d’arrêter, sans vérifier séparément les trois mécanismes. |
| Q2 / 1 | Jalons mal conçus : effort détourné vers des objectifs mesurables à court terme au détriment de la valeur durable; réponse C. | Topic 1, p. 6 pour le financement par jalons; Topic 5, p. 2 pour l’alignement autour de la valeur et le risque de métriques court terme. | **Absent** — aucune question existante sur cet arbitrage. |
| Q3 / 1 | Seed pour construire/valider le produit; Series A pour développer l’échelle; réponse C. | Topic 1, p. 25; p. 6 donne aussi les phases. | **Présent** — une question couvre explicitement cette distinction. |
| Q4 / 1 | Common law : précédents judiciaires et exécution des droits contractuels; réponse C. | Topic 5, p. 9 (comparaison common law / civil law). | **Absent** — pas de quiz sur le choix de juridiction ou l’exécution contractuelle. |
| Q5 / 1 | Fully diluted : traiter les options comme exercées dans le calcul; réponse B. | Topic 3, p. 5–6. | **Partiel** — une question calcule un pool post-money, mais ne teste pas la définition fully diluted. |
| Q6 / 1 | Entrées du VCM : investissement, délai avant sortie, valeur de sortie, hurdle rate; réponse A. | Topic 3, p. 16–19. | **Présent, à compléter** — une question calcule un cas VCM chiffré, mais ne vérifie pas l’identification de chaque entrée. |
| Q7 / 1 | Avec un apport positif, la pre-money est inférieure à la post-money; réponse B. | Topic 3, p. 2. | **Partiel** — une question déduit la post-money d’un montant investi et d’un pourcentage, mais ne teste pas directement cette relation. |
| Q8 / 1 | Comparer valorisation et protections ensemble, car elles répartissent risque et rendement; réponse B. | Topic 4, p. 36. | **Absent** — pas de question de comparaison économique des clauses. |
| Q9 / 1 | Dans le VCM simple, la préférence de liquidation n’est pas une entrée directe du calcul d’ownership; réponse D. | Topic 3, p. 16–18 pour le VCM; Topic 4, p. 11 et 14–15 pour l’effet des préférences sur les produits. | **Absent** — aucune question ne distingue le VCM simple du payoff contractuel réel. |
| Q10 / 1 | Anti-dilution : ajuster la conversion lors d’un down round; réponse A dans le sujet. | Topic 4, p. 6 et 24. | **Présent** — la banque explique l’ajustement de conversion. Le libellé du sujet simplifie l’effet en disant « empêcher » la dilution; le cours explique plutôt un repricing qui peut réduire la dilution. |
| Q11 / 1 | Reverse vesting : les fondateurs acquièrent progressivement le droit de conserver leurs actions; réponse B. | Topic 4, p. 6 et 22. | **Absent** — pas de question sur le mécanisme ou le calendrier. |
| Q12 / 1 | Pay-to-play : conserver certains droits en participant pro rata aux tours suivants; réponse A. | Topic 4, p. 24. | **Absent** — aucun test sur la condition de participation. |
| Q13 / 1 | Contrats VC américains plus juridiques; Europe continentale davantage fondée sur la confiance et le financement par étapes; réponse C. | Topic 5, p. 9. | **Absent** — pas de comparaison géographique. |
| Q14 / 1 | Dans le cas avec licenciement pour faute, la clause de déchéance donne 0 action conservée; réponse B. | Topic 4, p. 22. | **Absent** — nuance importante : le 25 % acquis au cliff ordinaire ne neutralise pas la perte prévue en cas de faute. |
| Q15 / 1 | Cap et discount apportent deux protections de prix de conversion; réponse C dans le corrigé. | Topic 4, p. 27–29, notamment la formule de prix minimal p. 29. | **Partiel** — la banque présente les deux méthodes, mais l’exercice doit s’aligner précisément sur la formule et expliquer quel prix s’applique selon le tour. |
| Q16 / 3 | Investir 5 M$, sortie 50 M$ en 5 ans, hurdle 40 % : CCM `1,4^5 = 5,378`; post-money `50/5,378 = 9,297 M$`; ownership ≈54 %. | Topic 3, p. 10 et 16–18. | **Présent** — la banque a un calcul quasi identique. Pas encore de saisie de calcul libre ni de crédit partiel. |
| Q17 / 3 | 5 M actions fondateurs, 2 M$ investis à 8 M$ post, pool 20 % : fondateurs 55 %, pool 20 %, VC 25 %; 9,091 M actions au total. | Topic 3, p. 2 et 5–6. | **Présent, partiel** — les pourcentages sont pratiqués; les étapes de dilution et le tableau fully diluted ne sont pas évalués comme réponse libre. |
| Q18 / 4 | Conversion de 1 M préférentielles en 2 M ordinaires; après 3 M d’actions IPO, ownership `2/18 = 11,1 %`; sortie 50 M$ sur 5 M$ investis en 8 ans : IRR ≈33 %. | Topic 3, p. 3–5 et 10; Topic 4, p. 11 pour la conversion préférentielle. | **Présent** — deux questions couvrent ownership après IPO et IRR; pas de correction à étapes ni de points partiels. |
| Q19 / 5 | Calcul multi-tours à rebours : C post-money 2 000 M$; B post-money `1 800/4 = 450 M$`; A post-money `400/5 = 80 M$`; Seed post-money `55/8 = 6,875 M$`; fondateurs 47 % à la sortie. | Topic 3, p. 17 (algorithme multi-tours), p. 18–19 (hypothèses et hurdle). | **Absent** — aucune question sur les valorisations successives ni sur la dilution composée. |
| Q20 / 15 | Comparer deux term sheets, calculer les payoffs, puis la conversion full-ratchet. Alpha : 1x convertible non-participante, 44,4 % VC, pool 25 %, weighted average, 2 sièges fondateurs. Mega : 1x participating jusqu’au cap 2,5x, 50 % VC, pool 15 %, full ratchet, 2 sièges investisseurs. Payoffs Alpha aux sorties 5/10/28/35 M$ : 4/4,44/12,43/15,54 M$; Mega : 5/8/15/17,5 M$. Full ratchet à 0,90 $ : 6,67 M actions converties. | Topic 3, p. 5–6 pour la cap table; Topic 4, p. 6, 11, 14–15, 22–24 et 36. | **Absent** — aucun cas combinant capitalisation, arbitrage de clauses, payoffs par scénario et conversion anti-dilution. |
| Q21 / 15 | Deux offres et deux scénarios de financement : à 75 % de probabilité pour le scénario 1, XY donne 56,25 % d’ownership espérée et 5,625 M$ de richesse attendue, contre 53,33 % et 5,333 M$ pour VW; choisir XY selon ces hypothèses. | Topic 3, p. 2–3 et 17 pour valorisation, ownership et dilution; classeur `Class assignments - solutions.xlsx`, onglet `3. Aliboy` (financements étagés/scénarios) et `4. TrafalgarTech` (payoffs espérés selon probabilités). | **Partiel** — une question reprend une comparaison de richesse espérée d’un ancien corrigé, mais pas les calculs de tours successifs de Q21. |

## Lecture produit à partir du code

- Avant le lot 2, `career/quiz.py` contenait 15 questions de départ réparties 2/2/7/2/2 sur Topic 1–5, sans identifiant d’objectif d’examen.
- `career/exam.py` crée un examen à choix multiples depuis la banque de quiz, calcule `bonnes réponses / total` et produit des corrections avec explications/citations. Il n’accepte pas de réponse libre, n’attribue pas de points partiels et ne représente pas le barème 15/15/30 de 2025.
- L’interface envoie actuellement six questions pour 30 minutes (`desktop_static/app.js`). Le sujet de référence faisait 90 minutes pour 60 points. Cette différence doit être visible pour l’étudiant afin qu’un petit quiz ne soit pas présenté comme une simulation fidèle.

## Lot 2 — couverture de quiz alignée au sujet passé

Implémenté sur la branche candidate; les validations ont été rejouées après le dernier changement de code. Le SHA de publication sera ajouté après le commit/push :

- La banque passe à **34 questions** réparties Topic 1–5 : 4/2/15/9/4.
- **27 identifiants d’objectifs** relient les notions du sujet 2025 et les sous-étapes d’exercices aux questions d’entraînement. Chaque question taguée garde une explication et une recherche de citation locale.
- L’API de quiz renvoie ces références. Le tableau de bord donne une couverture séparée « notions du sujet 2025 vues en quiz »; l’interface précise que cela ne signifie ni maîtrise ni simulation des cas libres.
- La maîtrise compte désormais les questions distinctes de la banque actuelle auxquelles l’étudiant a répondu, avec le seuil de justesse de 80 %. Répéter une seule réponse ne suffit pas à valider un chapitre. Les questions encore jamais vues passent avant les répétitions.
- La base SQLite existante migre la colonne des tags avec valeur vide par défaut; un test vérifie que les lignes précédentes sont conservées.
- Un index temporaire du corpus autorisé a servi **34/34 questions avec une citation contenant source et page**. Cette mesure prouve la disponibilité d’une citation, pas encore la pertinence de chaque extrait ni l’exhaustivité des pages non indexées.
- Tests ciblés rejoués : **17 passed en 2,85 s** (`tests/test_nage_learning.py`, `tests/test_nage_learning_ui.py`); Ruff ciblé : `All checks passed`; `node --check desktop_static/app.js` et `git diff --check` : réussite.

## Prochaines missions, dans l’ordre

1. **Réponses libres et barème pédagogique** : mettre en pratique Q16–Q19 par étapes, avec unités/formules et validation des calculs intermédiaires. Ne parler de points partiels que pour une grille clairement identifiée comme pédagogique, car le corrigé officiel ne donne pas de barème détaillé.
2. **Cas de la partie C** : transformer Q20 et Q21 en cas guidés avec scénarios séparés, tableau de payoffs et comparaison justifiée. Garder distincte la grille officielle de la grille d’entraînement NAGe.
3. **Audit des unités non extraites** : déterminer si le rapport de 56 MiB contient des notions utiles, définir une prise en charge bornée sans retirer la limite de taille, et examiner les pages scannées sans traiter l’identifiant de couverture comme contenu pédagogique. Tester les OCR sur une copie temporaire locale, jamais dans le dépôt.
4. **Recette d’apprentissage réelle** : vérifier citations pertinentes, points faibles, ordre des étapes, minuterie, correction et persistance après redémarrage sur un profil de test vierge; puis vérifier l’instance lancée par l’icône du bureau.

## Limites établies

- L’exhaustivité pédagogique de toutes les pages, tableaux, formules et images du corpus n’est pas prouvée. Le rapport de 56 MiB et les 14 pages scannées restent hors de l’index texte de cette extraction.
- Le corrigé ne fournit pas de grille explicite de points par étape pour Q16–Q21. Une correction détaillée peut être construite à partir des étapes visibles, mais le crédit partiel doit être étiqueté « barème pédagogique NAGe » tant qu’un barème officiel n’est pas disponible.
- Le sujet 2025 n’est pas une garantie du sujet futur; il sert de base d’entraînement empirique, pas de promesse de couverture de tout ce qui peut tomber.
- Aucun fichier de cours, classeur original, base de progression locale ou correction n’a été modifié. Aucun contenu personnel n’est ajouté au dépôt.

## Vérifications de cette livraison

- `/Users/comedelavenne/AI-Excel-Agent/.venv/bin/python -m pytest -q tests/test_nage_learning.py tests/test_nage_learning_ui.py` : **14 passed en 3,64 s**, exécuté depuis ce worktree sur le SHA audité.
- `/Users/comedelavenne/AI-Excel-Agent/.venv/bin/ruff check career/quiz.py career/exam.py tests/test_nage_learning.py tests/test_nage_learning_ui.py` : **All checks passed**.
- `git diff --check` : réussite. Les dossiers locaux non suivis `career_data` et `learning_data/` sont restés intacts et hors de l’index Git.
