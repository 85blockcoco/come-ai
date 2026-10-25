# STEER CODEX 14:30 — 2 tâches bornées (recette navigateur, puis verdict final)

Règles d'engagement :
- Tu es OBSERVATEUR : tu ne modifies AUCUN code produit (sauf config de lancement si réellement bloquant), tu ne touches au repo principal ni à la flotte (messages/, missions_registry.json, drivers).
- Temps budgété : tâche A ≤ 45 min, tâche B ≤ 20 min.
- Tout résultat : tu le finis par un rapport écrit dans /Users/comedelavenne/AI-Excel-Agent-integration-v2/CODEX_RECETTE.md puis CODEX_VERDICT.md.
- Si un pas échoue : note-le AVEC la ligne d'erreur exacte et continue le parcours : on veut la carte complète des échecs, pas l'arrêt au premier.

## TÂCHE A — Recette navigateur du kit 1-clic (lot 59)
Depuis /Users/comedelavenne/AI-Excel-Agent-integration-v2 : trouve le point d'entrée du service web
(lis README/Makefile/service.py/router.py ; commande d'attente : `python3 -m uvicorn service:app --port 8747`).
Lance-le, puis dans ton navigateur (open-link-in-target-preference = external-browser) :
1. Charger la page "{{racine 8747}}/" — note: rendu complet sans erreur console
2. Import profil + CV de test (utilise les fixtures/valuations fournies, JAMAIS de données personnelles réelles)
3. Importer une offre de test (fixture synthetic_offer) et lancer la génération du kit
4. Vérifier dans le flux que l'ÉTAPE 2 d'audit qualité s'affiche (si le lot 77 n'existe pas encore: noter "absent attendu")
5. Télécharger/exporter le kit : tailles des fichiers attestées (CV, lettre, checklist)
6. Rapport: chaque étape OK/ÉCHEC + captures + erreurs console.

## TÂCHE B — Verdict final d'intégration CVBOOST-10 V2
DÉCLENCHEMENT: attends mon signal "RÉPARATIONS TERMINÉES — ÉTAT FINAL DISPONIBLE" avant cette tâche
(le fichier RESULTAT_TESTS_FINAL.md sera déposé sur origin, branche integration/cvboost-10-v2).
1. Recois ce fichier + le rapport CVBOOST-10-INTEGRATION-V2.md (rapport V2 docs/agent-reports côté main).
2. Écris CODEX_VERDICT.md avec EXACTEMENT:
   - Verdict: **MERGE AUTORISÉ** | **MERGE REFUSÉ** (rien d'autre)
   - 3 raisons chiffrées (nb tests rouge, lots en échec, montage preuve)
   - Si REFUSÉ: la plus petite liste de correctifs qui rendrait le merge possible
   - Ton de certitude calibré: ce que tu n'as PAS vérifié (ex: vraie exécution manuelle de l'app)

