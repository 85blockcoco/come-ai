# NAGe — parcours d’apprentissage Venture Capital

Date : 2026-11-03

Branche candidate : `codex/vc-mastery-20261103`

Référence locale avant ce lot : `de9fcc3325ce34a7231aac8bae352a19503d78c9`

## Résultat

Le parcours de révision VC propose désormais quatre étapes visibles : **réviser → apprendre avec les sources → s’exercer → examen blanc**. L’en-tête permet de choisir le style général `NAGe original` ou `Étude sobre`, mémorisé localement, indépendamment du thème clair/sombre. Une barre de progression globale et une progression par étape rendent les activités effectuées visibles; la maîtrise académique reste calculée séparément à partir des quiz.

Le corpus local actuellement indexé contient 29/29 fichiers (26 PDF et 3 classeurs), soit 1 501 pages/feuilles détectées et 1 499 unités contenant du texte. Deux unités vides expliquent l’écart. L’indexation est locale; aucune donnée de cours n’est ajoutée à Git ni envoyée à un modèle externe.

## Changements livrés

- Sérialisation des accès concurrents SQLite dans l’index, les cartes SRS, les quiz et les examens; identifiant de référence conservé dans les erreurs locales génériques.
- Génération de cartes avec extrait de réponse complet et citation; les évaluations Again/Hard/Good/Easy sont prises en charge et une carte déjà révisée garde son historique.
- Le progrès d’un chapitre tient compte de la justesse **et** du nombre de questions prévues tentées. Un bon résultat isolé ne déclare donc pas tout un chapitre maîtrisé.
- Tuteur borné au chapitre sélectionné et recherche de termes français avec variantes anglaises. Vérification navigateur d’une explication de la relation pre-money/post-money citant le cours.
- Plan réparti sur les cinq chapitres jusqu’à la date de fin; chapitres les plus faibles en priorité. L’examen reste verrouillé si les critères de maîtrise ne sont pas satisfaits.
- Tableau de bord de révision, exports PDF de fiches et de plan, résumé d’examens persisté.
- Interface apprentissage réordonnée autour du parcours, des sources, du quiz et du plan; style sobre vert, lisible et responsive, sans retirer le thème NAGe d’origine.

## Vérifications observées

- Tests ciblés rejoués pour cette livraison avec `/Users/comedelavenne/AI-Excel-Agent/.venv/bin/python -m pytest -q tests/test_nage_learning.py tests/test_nage_learning_ui.py` : **14 passed en 3,37 s**. Aucun test complet du dépôt n’a été lancé.
- Le test concurrence le tableau de bord et le plan sur des lectures parallèles; le test du tuteur vérifie la formule post-money découpée sur plusieurs lignes et sa citation; le plan vérifie la couverture des chapitres et le verrou d’examen.
- Ruff sur les modules Career et tests modifiés : `All checks passed!`.
- `git diff --check` et `node --check desktop_static/app.js` : réussite.
- Navigateur de test isolé : `http://127.0.0.1:18765/app#learning`. Le parcours, le sélecteur `Étude sobre`, la barre de progression, les cartes (génération, révélation et notation), le quiz avec correction, la recherche du cours, la réponse sourcée du tuteur et le verrou de l’examen ont été parcourus. L’état de progression affiché provient de cette base de test locale et ne constitue pas un résultat d’examen.
- Vérifications HTTP du 2026-11-03 : `GET /api/career/plan` → 200 JSON, 5 sessions jusqu’au vendredi; `GET /api/career/plan/pdf` → 200 `application/pdf` (2 326 octets); `GET /api/career/summary/TOPIC%203/pdf` → 200 `application/pdf` (3 832 octets); `GET /api/career/learning/dashboard` et `GET /api/career/coverage` → 200 JSON.

## Limites à connaître

- Une couverture d’indexation de 100 % des unités textuelles ne prouve pas une couverture pédagogique de chaque notion. Les 15 questions de départ (réparties sur cinq chapitres) ne constituent pas encore une banque exhaustive alignée page par page sur tous les supports et le sujet passé.
- Les documents scannés ou formules présentes uniquement sous forme d’image nécessitent une vérification OCR/visuelle dédiée. Les deux unités sans texte sont signalées par le comptage mais ne sont pas interprétées.
- Le simulateur actuel est un entraînement chronométré de six questions à choix multiples, pas une reproduction complète de l’épreuve avec cas longs et calculs libres. Aucun score d’examen n’est revendiqué; le verrou est actif dans l’état de test observé.
- La vérification navigateur porte sur le serveur de candidate local. Elle ne valide ni le lancement par l’icône de bureau ni un déploiement dans `main`.
- Les données SRS et les réponses locales du navigateur restent propres à leur base locale. Les progrès du bac de test doivent être distingués de la progression durable de l’utilisateur.

## Publication

Cette livraison est destinée à la branche candidate uniquement. `main` et `/Users/comedelavenne/NAGE-release` ne sont pas modifiés. Le SHA du commit et la vérification distante seront ajoutés au rapport après le commit et le push.
