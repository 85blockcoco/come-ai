# Career Stage Hunter — acceptation du 13 octobre 2026

Career est intégré dans l’application principale. Aucun développement mémoire ou autre chantier n’a été fusionné dans ce lot.

## Livraison et conservation

- Source Career conservée : `feature/career-stage-hunter`, `a14676950b58d6833d396175949dffa69a44d9aa`.
- Les seuls commits métier `98a5815`, `089ea83`, `6368817`, `a146769` ont été réutilisés dans la copie d’intégration, puis corrigés. Aucun remplacement par l’arbre complet de la branche ancienne.
- Commit métier consolidé : `fe798858d51dfa4facccdad325b8b87ec62744a9`.
- Le commit de documentation antérieur de main a été conservé par merge dans la copie : `fb9dbba9fc8dce2c89407d8c91ba348fce84e40c`. Main a ensuite avancé avec `git merge --ff-only integration/career-stage-hunter`, les deux arbres étant propres.
- Les captures de preuve sont privées et exclues de Git, dans `.devkit/integration/career-stage-hunter/.devkit/`. Aucun document, clé ou base privée n’a été exporté. Checkpoint préalable : `.devkit/integration/20261013T213342Z` (14 worktrees, 41 sources/docs/lanceurs sauvegardés).

## Correctifs acceptés

1. Toutes les entrées admissibles du flux sont normalisées et évaluées selon le brief explicitement enregistré **avant** de retenir les 150 meilleures par board. Départage stable par identité source / URL / empreinte du contenu ; classement affiché stable aussi. Aucun critère ni profil n’est envoyé au board.
2. Limites conservées : réponse de 8 Mio, délai de 8 secondes, un seul retry et 8 boards au maximum. Un flux de plus de 20 000 entrées est refusé entièrement, plutôt que tronqué avant classement. La sélection supplémentaire utilise un heap de 150 candidats, pas une deuxième copie du flux normalisé.
3. Les lignes invalides ne prennent pas une place du top 150. Elles sont comptées et annoncées ; les erreurs de source préservent les données existantes.
4. L’empreinte des critères fait partie du cache. Un changement de critères, y compris pendant une recherche, ne rend pas un ancien top 150 artificiellement valide. Les offres suivies restent conservées ; une exclusion du top 150 ne prouve pas une fermeture.
5. Stage Hunter ne remplace plus une erreur ou un résultat partiel de recherche par un message de réussite.
6. Quand Greenhouse ne fournit pas un champ d’exigences distinct, la préparation cite les passages explicitement repérés dans la description et affiche un extrait borné à 4 000 caractères. Les champs optionnels vides ne deviennent pas de fausses exigences. L’extraction lexicale est annoncée comme potentiellement incomplète.
7. Le suivi n’utilise plus `prompt()` / `confirm()` pour ses notes, approbations et références de réception : champs visibles, case d’approbation initialement décochée et contrôles backend inchangés. Correction nécessaire car le navigateur intégré ne prend pas en charge `prompt()`.

## Preuves réellement exécutées

- Copie avant corrections : **136 tests réussis**, déjà acquis, sans nouvel audit global.
- Régressions ajoutées : **23 tests**, couvrant notamment une offre financière après la 150e position, ordre du flux inversé, poids explicites, critères modifiés / redémarrage / changement pendant requête, erreurs et conservation du suivi, description → préparation, messages JavaScript et consentement explicite.
- Après les corrections finales : **159 tests ciblés réussis en 22,53 s** sur la copie.
- DevKit final sur la copie : **681 réussis, 2 ignorés en 47,25 s**, empreinte `d7098a354143d36c18e1dd044db7edf628c0647c69aea88c315a843f520c0a6a`. Rapport `.devkit/integration/career-stage-hunter/.devkit/diagnostics/latest.md` ; syntaxe JS vérifiée séparément avec `/usr/local/bin/node --check career_static/career.js` car le PATH minimal du runner ne trouvait pas Node.
- Après fusion dans main : **161 tests réussis en 26,91 s**, soit 159 ciblés et les 2 tests OS ignorés sous sandbox imbriquée. Tests sur fixtures, sans clés ni cloud.
- DevKit **rejoué dans main après fusion** : **681 réussis, 2 ignorés en 44,45 s**, même empreinte source `d7098a354143d36c18e1dd044db7edf628c0647c69aea88c315a843f520c0a6a`. Python, dépendances, smoke hors IA et syntaxe JavaScript également réussis. Rapport `.devkit/diagnostics/2026-10-13T21-46-46.599913Z.md` et JSON correspondant. La différence 136 → 159 correspond aux 23 régressions ajoutées ; 161 inclut les 2 scénarios OS, pas deux nouvelles fonctions.
- Revue indépendante en lecture seule : sélection, cache, description source, messages et contrôles d’approbation / référence ; aucun blocage constaté. Les deux agents de préparation interrompus n’ont pas été comptés comme une revue finale réussie.
- Navigateur **réel** contre l’application complète et une base temporaire synthétique sur le port 8877 : ouverture Career, enregistrement M&A / Paris, ajout de board, recherche parmi 153 offres, offre financière en position 153 retenue première à 100/100 sur ces seuls critères, analyse de l’offre citant les champs réels du profil fictif, création du suivi, passage À préparer / Prête, refus de consigner Envoyée sans approbation, approbation explicite, déclaration Envoyée et référence de réception synthétique, puis rechargement avec persistance. Aucun dépôt externe.
- Source **publique réelle** : un GET anonyme du board Greenhouse Stripe par le transport de production avec TLS vérifié. **724 entrées évaluées, 150 retenues, 0 invalide, 3,27 s**. Aucun enregistrement dans les données utilisateur. Cela prouve l’accès et le traitement du flux, pas 150 stages pertinents ou une vérification de chaque annonce.
- Serveur principal sur port libre 8765 : `/v5`, `/career`, `/career-static/career.js` répondent **HTTP 200** ; la page principale Career contient Stage Hunter. Aucun serveur existant redémarré.

## Reproduire les validations

Depuis `/Users/comedelavenne/AI-Excel-Agent`, utiliser le venv existant :

```bash
env -i PATH=/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m devkit --python /Users/comedelavenne/AI-Excel-Agent/.venv/bin/python check --timeout 300
env -i PATH=/usr/bin:/bin:/usr/sbin:/sbin PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest -q -p no:cacheprovider tests/test_career_discovery_selection.py tests/test_career_stage_hunter_ui_guards.py tests/test_career_stage_hunter.py tests/test_career_agent.py tests/test_career_action_plan.py tests/test_calendar_export.py tests/test_come_ai_v3.py tests/test_hybrid_web.py tests/test_evolution_web.py tests/test_v5_web.py tests/test_devkit_real_workflow.py tests/test_evolution_real_sandbox.py
```

Les tests JavaScript exécutent les véritables fonctions avec des stubs UI/API en Node ; ils ne constituent pas seuls une preuve de navigation. La preuve navigateur est distinguée ci-dessus. Les deux scénarios OS demandent de ne pas imbriquer une sandbox macOS.

## Lancement et limites

Commande : `.venv/bin/python run_come_ai_v3.py --port 8765 --no-browser` depuis la racine. URL : `http://127.0.0.1:8765/career#career/stagehunter`. **Le serveur lancé pour cette livraison existe déjà : ne pas lancer une seconde instance sur le même port.** Guide : `GUIDE_STAGE_HUNTER_5_MINUTES.md`.

- Recherche : boards Greenhouse configurés explicitement + imports manuels. Pas de recherche universelle LinkedIn / banques / fonds, ni besoin d’une clé IA pour le parcours.
- Classement lexical explicable, pas une probabilité d’embauche ni un benchmark de modèle. Les contraintes libres, dates / niveau / langues non structurés restent à vérifier. Des emplois permanents peuvent figurer dans les boards : relire chaque offre officielle.
- La préparation validée est un dossier factuel et des suggestions CV / message, pas une garantie de CV et lettre finaux prêts à envoyer. L’Application Studio préexistant reste accessible, mais sa génération cloud n’a pas été testée dans cette mission.
- Réception confirmée = référence déclarée localement par la personne, pas accès à sa boîte mail ni validation externe de l’accusé.
- Certaines autres actions historiques (notes de shortlist, réinitialisation) utilisent encore des dialogs natifs ; elles ne sont pas nécessaires au parcours validé. Ne pas utiliser la réinitialisation pour commencer.
- Aucun appel Gemini / OpenRouter, aucune API payante, aucun envoi de candidature. Le profil et les tâches mémoire des autres agents ne sont pas fusionnés.
