# NAGe VC Study Studio — 4 novembre 2026

## Livraison

Branche `codex/vc-learning-studio-20261104`, base `5a20753`. Le travail est développé dans un worktree isolé puis installé par fichiers vérifiés dans le dépôt qui lance l'application du bureau. Aucun merge dans main.

L'écran Révision est reconstruit autour d'un cours lisible, avec quatre étapes : Learn, Recall, Practise, Mock exam. Les cinq chapitres des supports EDHEC remplacent la grande grille de 21 catégories techniques. Navigation par leçon, recherche dans le texte pédagogique, mode Focus, impression, liste à revoir et reprise de la dernière leçon.

- 28 leçons en anglais, 56 questions de contrôle avec correction après réponse.
- 170 pages des cinq supports principaux associées chacune à une leçon (sans trous ni doublons dans le mapping).
- 29 fichiers originaux disponibles localement : 26 PDF, 1 494 pages PDF au total ; trois classeurs, 14 feuilles.
- Pages PDF rendues dans l'application, avec transcription et navigation ; tableaux Excel en lecture seule, valeurs enregistrées ou formules, sans recalcul.
- Lecture, dernier contrôle et liste à revoir persistés séparément de la répétition espacée. Un clic de lecture ne crée pas de maîtrise fictive.
- La portée par défaut des nouvelles sessions de cartes suit les thèmes du cours ; les cartes de contexte restent optionnelles. Une session active est toujours conservée.
- Annales : énoncés complets, choix QCM, sous-questions numériques et écrites des cas, brouillon local et correction détaillée par item. Les réponses écrites restent à comparer au corrigé ; le score automatique n'est pas une note finale du sujet.
- Examen blanc : brouillon restauré après rechargement et minuterie conservée. Tuteur optionnel ; aucun modèle nécessaire pour lire, travailler ou corriger les contrôles.

## Exactitude et protection des données

Sept exercices générés ont été corrigés. Les versions précédentes sont conservées dans leur JSON : réponses numériques scalaires, données nécessaires explicites, bonne catégorie de notion. Régressions importantes : weighted average = 1,666667 et non 1,4 ; full ratchet = 5 000 actions et non 4 000. Les hypothèses manquantes de participation et de préférence sont explicitées.

Cinq propositions VC19 restent conservées avec statut draft et motif. Elles ne peuvent plus entrer dans le correcteur numérique tant que les réponses multiples/qualitatives et leur provenance ne sont pas validées. La validation active refuse désormais une réponse non numérique ou une dernière étape contradictoire. La banque active comporte 39 calculs.

Les exemples de leçons sont des adaptations pédagogiques, identifiés comme tels. La formule weighted-average supplémentaire est signalée comme convention de marché ; les clés QCM déduites restent distinctes des solutions officielles travaillées. La correspondance des 170 pages est une preuve d'accès et de mapping ; ce n'est pas une certification de mémorisation exhaustive. Les 1 324 autres pages PDF sont dans la bibliothèque, pas réécrites en autant de leçons.

Aucun document source ou contenu de progression personnel ajouté au dépôt. Les 29 empreintes des originaux sont identiques avant/après validation. Les tests d'écriture utilisent un espace synthétique sous /tmp. Le viewer n'accepte que les sources du dossier autorisé, exclut les liens symboliques externes et conserve les protections CSP existantes.

## Preuves exécutées

Commande ciblée, sans suite globale :

```sh
.venv/bin/python -m pytest -q tests/test_vc_course.py tests/test_vc_content.py tests/test_vc_drills.py tests/test_vc_revisions_ui.py tests/test_vc_cases.py tests/test_vc_cases_routes.py tests/test_vc_pastpapers.py tests/test_vc_api.py tests/test_vc_storage.py tests/test_vc_exams.py tests/test_v5_web.py
```

Résultat dans le worktree : **126 passed en 16,65 s**. Ruff sur les fichiers Python modifiés, `node --check` sur les deux scripts Révision et `git diff --check` : verts.

Les anciens tests de compteur 20 thèmes/170 cartes et banque de 20 questions étaient obsolètes après l'ajout antérieur de VC21 et des six questions VC06. Ils sont alignés sur les contenus actuels et vérifient toujours qu'un examen demandé de 20 questions vaut exactement 100 points. Le test de l'ancienne grille de niveaux est remplacé par une validation du mapping de toutes les pages du cours et de la confidentialité des corrigés de contrôle.

Recette Chromium réelle sur serveur isolé, store synthétique, tuteur simulé :

- desktop 1 440 px et mobile 390 px ; aucune erreur JavaScript, aucun débordement horizontal dans les quatre étapes ;
- lecture d'une source originale rendue à 1 600 px, notamment Topic 4 p.16 ;
- contrôle corrigé, lecture et liste à revoir restaurés après rechargement et redémarrage du serveur ;
- panne réseau d'un contrôle simulée, bouton réactivé et nouvelle tentative réussie ;
- flashcard révélée et notée, calcul accepté avec étapes, cas rempli avec retour par critères ;
- sept feuilles du classeur de solutions affichées intégralement, formules visibles ;
- annale 2025 : 21 questions et 17 sous-questions de cas accessibles ; toutes les réponses numériques/QCM de la clé obtiennent 100 % de la partie automatique ;
- sujets 2023/2024 et passage sujet→solution en un clic ;
- brouillon d'examen restauré, reprise et soumission du mock réussies.

Les scores de recette sont des données synthétiques : ils ne représentent pas le niveau de Côme.

## Ajustement final demandé : QCM

Pastilles A/B/C de 22 px (lettres 10 px) sur écran large, 20 px sur mobile ; texte des réponses 15 px (14 px sur mobile), interligne 1,65–1,7. Toute la ligne est cliquable, le focus clavier est visible, et la sélection reste accessible aux lecteurs d'écran. Même présentation pour les contrôles de leçon et les annales. Les listes de choix de l'examen utilisent aussi des marqueurs plus petits.

Après cette modification : 16 tests ciblés de cours/UI rejoués, verts ; recette Chromium confirmant la sélection de la ligne, les tailles calculées et l'absence de débordement à 390 px. La fenêtre Chrome de l'application du bureau a été observée avec le nouveau lecteur et ses 28 leçons. Le lanceur fixe désormais son dossier de travail sur le dépôt avant de démarrer Python.
