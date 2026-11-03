# NAGe — couverture du cours VC et des annales

Date : 2026-11-03
Branche candidate : `codex/vc-mastery-20261103`
Base de code observée : `815fc87c4312e65b13dceb3ffd69557317cd5844` (modifications de travail non commitées)

## Parcours pédagogique présent

Le cours présente cinq chapitres et 27 sections guidées. Chaque section contient une explication, un exemple d’exercice, des étapes de résolution, une réponse et des références aux supports. Les choix de fin de chapitre sont persistés localement : se déclarer prêt, lancer l’exercice conseillé ou ajouter le chapitre à « À revoir ». « Prêt » reste une auto-évaluation et ne vaut pas preuve de maîtrise.

Les cinq supports principaux sont référencés dans les leçons sur leurs pages de contenu : Topic 1 p. 3–9 et 15–49; Topic 2 p. 2–36; Topic 3 p. 2–32; Topic 4 p. 2–39; Topic 5 p. 2–14. Le contrôle automatisé vérifie que ces pages apparaissent dans les références. Il ne prouve pas, à lui seul, que toute formule, illustration, note de bas de page ou nuance de chaque page a été transformée en question pédagogique.

Les thèmes des chapitres couvrent l’écosystème et les fonds, l’analyse d’opportunité, les valorisations et rendements, les term sheets et la négociation, puis la gouvernance, le suivi et les sorties. Les exemples incluent notamment les calculs de dilution et de rendement, la valorisation pre-money/post-money, les clauses préférentielles et anti-dilution, les notes convertibles, l’analyse de scénarios et le suivi de portefeuille.

## Inventaire des annales structurées

| Année | Questions principales | Sous-parties | Items de réponse distincts |
|---|---:|---:|---:|
| 2023 | 22 | 8 | 30 |
| 2024 | 24 | 8 | 32 |
| 2025 | 21 | 17 | 38 |
| **Total** | **67** | **33** | **100** |

Les questions hors VC des épreuves PE/VC/M&A restent dans l’archive et sont explicitement classées « hors périmètre VC »; elles ne sont pas confondues avec une notion du cours. Les questions pertinentes sont rattachées aux cinq chapitres, et les 2025 Q20/Q21 sont découpées en exercices guidés avec crédit partiel pédagogique clairement distinct du barème officiel absent.

Les deux fichiers d’examen 2023 ont des empreintes différentes et une mise en page différente. Les pages de QCM ont le même ordre et un contenu textuel très proche; le fichier intitulé « Final exam 2023 » contient des réponses et des éléments reportés sur les pages suivantes, tandis que l’autre porte la mention « Final Exam A ». Ils sont traités comme une même session/version et non comme deux années ou deux banques indépendantes. Ce rapprochement porte sur l’extraction textuelle et la structure, pas sur une expertise d’authenticité documentaire.

## Contrôle effectué sur les routes

Une validation ciblée parcourt les routes des trois sujets et compare chaque identifiant affiché avec l’objet de la banque : toutes les questions principales et toutes les sous-parties sont exposées une fois, soit 100 identifiants uniques. Elle contrôle également que ni les réponses ni les corrigés ne sont présents avant soumission. Les comptes par année et la classification des 67 questions sont vérifiés par tests.

Cette validation prouve la complétude de l’interface par rapport à la banque structurée. La banque est une adaptation d’étude condensée/paraphrasée des sujets; elle ne remplace pas la lecture intégrale du PDF ni la vérification de chaque détail de calcul contre le barème d’origine. Le sujet corrigé 2025 a déjà fait l’objet d’un rapprochement détaillé question par question. Les banques 2023 et 2024 ne disposent pas encore d’un rapport de correction aussi détaillé pour chaque réponse et chaque calcul.

## Limites encore ouvertes

- Le dossier contient 29 fichiers. Le parseur de l’application n’en a accepté que 28 dans l’inventaire précédent : le rapport *European Capital Map 2022* (58,2 Mo) dépasse la limite locale actuelle de 50 Mo.
- L’examen 2024 numérisé de 14 pages n’est pas exploitable par extraction textuelle. La banque de 2024 est fondée sur le document de solutions lisible; la copie numérisée contenant un identifiant étudiant n’a pas été OCRisée ni copiée dans le dépôt.
- Les cinq supports principaux ont des références de pages couvrantes; les articles, rapports de marché, cas et annexes complémentaires ne sont pas tous convertis en cours guidés distincts.
- Les cas de cours sont accompagnés d’étapes utiles, mais les corrigés historiques ne donnent pas toujours les critères de points partiels. Quand un crédit partiel est ajouté, il est indiqué comme pédagogique.
- L’examen blanc chronométré global n’est pas encore une reproduction complète du format historique, et aucun niveau d’application ne garantit une note.
- La vérification de l’interface précédente a été faite sur une base temporaire isolée. L’application lancée depuis l’icône du bureau n’a pas été vérifiée dans cette livraison.

## Validations de la livraison

- `/Users/comedelavenne/AI-Excel-Agent/.venv/bin/python -m pytest -q tests/test_nage_course_lessons.py tests/test_nage_learning.py tests/test_nage_learning_ui.py tests/test_vc_pastpapers.py tests/test_nage_case_practice.py` : **47 passed en 3,78 s**.
- `/Users/comedelavenne/AI-Excel-Agent/.venv/bin/ruff check career/course_lessons.py career/learning_router.py tests/test_nage_course_lessons.py tests/test_nage_learning_ui.py` : **All checks passed**.
- `node --check desktop_static/app.js`, `node --check desktop_static/sw.js` et `git diff --check` : réussite.
- Aucun test complet du dépôt n’a été lancé. Les données locales non suivies `career_data` et `learning_data/` sont restées hors de l’index Git et n’ont pas été consultées.
