# NAGe — parcours d’apprentissage Venture Capital

Date : 2026-11-03

## Correction de couverture du corpus — 2026-11-03

Une réindexation isolée du dossier de cours a ensuite détecté 29 fichiers, mais le parseur courant n’en a accepté que 28 : 1 013 pages/feuilles et 997 chunks. Un PDF de 56 MiB dépasse la limite locale de 50 MiB; un examen PEVC 2024 numérisé contient 14 pages sans texte extractible. La couverture `29/29`, `1 501 pages/feuilles`, `1 499 unités textuelles` ci-dessous décrit un état local antérieur et n’est pas reproductible avec cette réindexation. La base locale de progression n’a pas été consultée.

Branche candidate : `codex/vc-mastery-20261103`

Référence locale avant ce lot : `de9fcc3325ce34a7231aac8bae352a19503d78c9`

## Résultat

Le parcours de révision VC propose désormais quatre étapes visibles : **réviser → apprendre avec les sources → s’exercer → examen blanc**. L’en-tête permet de choisir le style général `NAGe original` ou `Étude sobre`, mémorisé localement, indépendamment du thème clair/sombre. Une barre de progression globale et une progression par étape rendent les activités effectuées visibles; la maîtrise académique reste calculée séparément à partir des quiz.

Une réindexation de contrôle isolée a détecté 29 fichiers locaux (26 PDF et 3 classeurs), mais le parseur a accepté 28 fichiers, couvrant 1 013 pages/feuilles et produisant 997 chunks. Un PDF de 56 MiB dépasse la limite locale de 50 MiB; un examen PEVC 2024 de 14 pages est scanné et son texte n’est pas extractible. Sa couverture inclut un identifiant étudiant : elle n’a pas été OCRisée ni copiée dans le dépôt. La base persistante utilisée par l’application n’a pas été ouverte; son état courant n’est donc pas affirmé ici. Aucune donnée de cours n’est ajoutée à Git ni envoyée à un modèle externe.

## Changements livrés

- Sérialisation des accès concurrents SQLite dans l’index, les cartes SRS, les quiz et les examens; identifiant de référence conservé dans les erreurs locales génériques.
- Génération de cartes avec extrait de réponse complet et citation; les évaluations Again/Hard/Good/Easy sont prises en charge et une carte déjà révisée garde son historique.
- Après le lot d’alignement, le progrès du chapitre tient compte de la justesse **et** du nombre de questions distinctes couvertes dans la banque; répéter une question ne valide pas le chapitre. Le seuil de maîtrise est de 80 %.
- Tuteur borné au chapitre sélectionné et recherche de termes français avec variantes anglaises. Vérification navigateur d’une explication de la relation pre-money/post-money citant le cours.
- Plan réparti sur les cinq chapitres jusqu’à la date de fin; chapitres les plus faibles en priorité. L’examen reste verrouillé si les critères de maîtrise ne sont pas satisfaits.
- Tableau de bord de révision, exports PDF de fiches et de plan, résumé d’examens persisté.
- Interface apprentissage réordonnée autour du parcours, des sources, du quiz et du plan; style sobre vert, lisible et responsive, sans retirer le thème NAGe d’origine.

## Vérifications du commit de base `6891150`

- Tests ciblés rejoués pour cette livraison avec `/Users/comedelavenne/AI-Excel-Agent/.venv/bin/python -m pytest -q tests/test_nage_learning.py tests/test_nage_learning_ui.py` : **14 passed en 3,37 s**. Aucun test complet du dépôt n’a été lancé.
- Le test concurrence le tableau de bord et le plan sur des lectures parallèles; le test du tuteur vérifie la formule post-money découpée sur plusieurs lignes et sa citation; le plan vérifie la couverture des chapitres et le verrou d’examen.
- Ruff sur les modules Career et tests modifiés : `All checks passed!`.
- `git diff --check` et `node --check desktop_static/app.js` : réussite.
- Navigateur de test isolé : `http://127.0.0.1:18765/app#learning`. Le parcours, le sélecteur `Étude sobre`, la barre de progression, les cartes (génération, révélation et notation), le quiz avec correction, la recherche du cours, la réponse sourcée du tuteur et le verrou de l’examen ont été parcourus. L’état de progression affiché provient de cette base de test locale et ne constitue pas un résultat d’examen.
- Vérifications HTTP du 2026-11-03 : `GET /api/career/plan` → 200 JSON, 5 sessions jusqu’au vendredi; `GET /api/career/plan/pdf` → 200 `application/pdf` (2 326 octets); `GET /api/career/summary/TOPIC%203/pdf` → 200 `application/pdf` (3 832 octets); `GET /api/career/learning/dashboard` et `GET /api/career/coverage` → 200 JSON.

## Limites à connaître

- La banque a été étendue à 34 questions et 27 objectifs du sujet historique, mais cela ne prouve pas une couverture de chaque notion du cours ni de tous les examens futurs. Les pages du PDF trop volumineux et l’examen scanné restent hors de cette réindexation isolée.
- Les documents scannés ou formules présentes uniquement sous forme d’image nécessitent une vérification OCR/visuelle dédiée. Les deux unités sans texte sont signalées par le comptage mais ne sont pas interprétées.
- Le simulateur chronométré reste un entraînement de six QCM; le panneau Q16–Q19 est une pratique séparée avec saisie numérique et barème indicatif, pas une reproduction complète de l’épreuve. Aucun score d’examen réel n’est revendiqué.
- La vérification navigateur porte sur le serveur de candidate local. Elle ne valide ni le lancement par l’icône de bureau ni un déploiement dans `main`.
- Les données SRS et les réponses locales du navigateur restent propres à leur base locale. Les progrès du bac de test doivent être distingués de la progression durable de l’utilisateur.

## Publication

Cette livraison est destinée à la branche candidate uniquement. `main` et `/Users/comedelavenne/NAGE-release` ne sont pas modifiés. Commit publié : `689115099fd16f01e0c49847d3b0d7eb05de1895`; la référence distante `origin/codex/vc-mastery-20261103` a été vérifiée sur le même SHA.

## Livraison du lot 2 — couverture du sujet historique

Le lot 2 est publié dans `7dde24008049887183650e0299e0ce789294232f`; la branche distante a été vérifiée sur le même SHA. Les tests ciblés rejoués après le dernier changement : `tests/test_nage_learning.py` et `tests/test_nage_learning_ui.py`, **17 passed en 2,85 s**. Ruff ciblé, `node --check desktop_static/app.js` et `git diff --check` sont verts. Le détail des changements et les limites figure dans `NAGE-VC-EXAM-ALIGNMENT.md`.

## Livraison du lot 3 — calculs Q16–Q19

Le code et l’interface sont publiés dans `8a4c1aae5477878c8cb18db6d18a7d4d242c3633`, complétés par `25e071c` pour restaurer le dernier résultat après rechargement. Les deux SHA ont été poussés sur la branche candidate. Les validations finales de ce lot : **22 passed en 3,89 s** sur les trois suites ciblées; Ruff, `node --check desktop_static/app.js` et `git diff --check` réussis. Le parcours Q16 et la persistance après redémarrage ont été vérifiés sur des données synthétiques et un profil temporaire isolé. Le rapport d’alignement détaille le périmètre et les limites.

## Livraison du lot 4 — cas d’examen Q20/Q21

Les six sous-parties de la section C du sujet 2025 sont maintenant entraînables dans l’interface : choix comparés de term sheets, tableaux de payoff, full ratchet, offres initiales, tours de financement selon les scénarios et richesse espérée. Q20a accepte Alpha/Mega dans des menus; les autres réponses sont numériques. Le corrigé est caché avant soumission, les tentatives restent locales et la correction donne la réponse attendue avec son raisonnement.

Le crédit partiel est marqué comme indicatif : Q20a/b/c attribuent 4/8/3 points et Q21a/b/c 3/9/3, soit 15 points par question. Le corrigé ne publie pas de distribution officielle entre sous-parties.

Sur copies locales temporaires du corrigé, des supports Topic 3/4 et du classeur d’exercices, les citations réelles ont été vérifiées : corrigé p. 7 pour Q20, corrigé p. 8 pour Q21; Q20 renvoie aussi à Topic 4 p. 6/14/24, Q21a/b à Topic 3 p. 2, et Q21c à l’onglet `4. TrafalgarTech` du classeur. Le corpus temporaire comptait 4 documents, 86 pages/onglets et 86 unités sans erreur d’extraction.

Validations après ce lot : **24 passed en 3,04 s** (`tests/test_nage_case_practice.py`, `tests/test_nage_learning_ui.py`, `tests/test_nage_learning.py`); Ruff ciblé, `node --check desktop_static/app.js` et `git diff --check` réussis. Une recette navigateur synthétique antérieure a noté Q20a 4/4, Q20b 8/8, Q21a 3/3 et Q21c 3/3, et restauré la dernière tentative après redémarrage. L’amélioration finale qui affiche la feuille XLSX et la nouvelle sélection de source Q21c n’a pas été vérifiée au navigateur cette fois; le détail se trouve dans `NAGE-VC-EXAM-ALIGNMENT.md`.

La couverture de toutes les notions du cours n’est toujours pas prouvée. Un document volumineux, un examen numérisé et les pages à formules/images non interprétées restent à examiner. L’examen blanc chronométré complet demeure distinct et incomplet par rapport au format historique. La candidate n’a pas été vérifiée via l’icône du bureau. Aucun travail n’a été intégré à `main` ni à `/Users/comedelavenne/NAGE-release`.
