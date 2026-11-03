# Rapport final — NAGe VC Révisions (mission avant-examen EDHEC)

Date : 2026-11-03 · Examen : vendredi 6 novembre 2026, 16:00 (90 min) · Reste : J-3
Branche : `agent/n100-G05-bundle-export` (working tree, non commité)

Légende des états :
**[V]** vérifié par exécution · **[M]** modifié cette session · **[P]** passé (tests)
**[O]** ouvert / non fait · **[H]** nécessite validation humaine (toi)

---

## A. Architecture (ce qui existe, tel quel)

- [V] Pipeline desktop inchangé : `Lancer Côme AI V3.command` → `run_come_ai_v3.py` → FastAPI `come_ai_web.py` (127.0.0.1:8765) → page `/v5`.
- [M] Nouveau routeur `academics/vc/api.py` branché dans `come_ai_web.py` via `create_app(..., vc_store_override, vc_tutor_override)` — réutilise les moteurs déterministes existants (`content`, `drills`, `pastpapers`, `mastery`, `scheduler`), aucun rebuild.
- [M] Onglet **Révisions** construit dans la structure existante : `v5_static/index.html` (nav + vue), `v5_static/revisions.js` (comportement), `v5_static/v5.css` (styles), enregistré dans `v5.js`.
- [V] Isolation de test : les tests passent un `base_dir` → `VcStore(base_dir/"vc")` + `VCTutor(cloud=False, load_env=False)` ; l'instance de test tourne avec `NAGE_VC_HOME=/tmp/nage_vc_visual_store` pour ne jamais toucher à ta progression réelle.
- [V] Aucune clé API affichée ni journalisée : l'auth Gemini passe par l'en-tête `x-goog-api-key` ; `provider_status()` expose uniquement le mode.

## B. Fonctionnalités préservées (aucune régression)

- [P] Suite complète du repo : **3864 passed** + 1 test de perf flaky (`test_five_hundred_offers_are_deduplicated_quickly`, 244 ms > 200 ms) qui **passe seul** → non régressé, simplement sensible à la charge.
- [P] VC + web : **251 passed** (`tests/test_vc_*.py` = 221 tests / 25 fichiers + `test_v5_web` + `test_hybrid_web` + `test_academics_routes`).
- [V] Mode hors-ligne, mode examen 90 min, intégrité des données de progression, cloud désactivé par défaut (Gemini uniquement opt-in explicite) — tous préservés et testés.
- [V] Travaux de Kilo (lot annales/cram, commits `5662820`, `46db228`, `9e8fbe0`, `25dff64`) **déjà dans HEAD** : comparés, non mergeés de force. Mon diff sur `pastpapers.py` = messages d'erreur FR→EN + notice « clé MCQ dérivée », **zéro changement de logique de correction** (vérifié hunk par hunk).
- [V] Aucun `git reset/clean/force` effectué ; aucun push ; aucune réécriture d'historique.

## C. Améliorations livrées

- [M] **Tuteur Gemini** : modes explain / hint / socratic / analogy / correct / deep ; hint et socratic retiennent la réponse ; réponses porteuses de `source` (ai/offline) + citations `passages`.
- [M] **170 flashcards** (20 packs), **32 drills**, **3 annales** (2023/2024/2025) avec solutions, examen blanc 20 questions / 90 min, radar de maîtrise 20 sujets, plan de révision, tableau d'erreurs.
- [M] **Drills anti-dilution corrigés** : `VC08-D003` réécrit (prix de conversion broad-based explicite, CP2 = CP1×(A+B)/(A+C), 3 error paths) ; `VC08-D005` ajouté (broad $3.50 attendu, narrow $3.43 accepté via `alternative_conventions` avec explication). Grading vérifié dans les deux sens (4 cas sur D003 + 4 sur D005).
- [M] **Labelling honnête des annales** dans l'UI : badge orange « Derived key » pour les MCQ, vert « Official » pour les solutions travaillées, bouton renommé « Solutions & key », notice de pack affichée, badge « Pack answer key » sur le résultat de correction.
- [M] Corrections de cartes : `VC17-C008` (taille de fonds €100-€500m), `VC18-C003` (fatal flaws du cours), `VC18-C008` (risques Market/Tech/People).
- [M] Fix CSP : styles inline `style="..."` remplacés par la classe `.rev-gap-top` (sinon bloqués → vérification graphique).

## D. Gemini / tuteur

- [V] Clé via en-tête, modèle `gemini-3.1-flash-lite` (opt-in `.env` : `VC_TUTOR_CLOUD=1`, `VC_TUTOR_LOAD_ENV=1`).
- [V] Testé **en direct** dans l'UI : question « pre-money vs post-money » → réponse AI + **5 passages cités**.
- [V] Repli hors-ligne testé (`VCTutor(cloud=False)`), Mistral en HTTP 402, Ollama en bas → le mode offline reste fonctionnel.
- [V] `provider_status()` affiché dans la pastille : « Gemini online · gemini-3.1-flash-lite ».

## E. Fiabilité académique

- [V] **Mission 2 terminée** : 72 cartes des 9 topics basse confiance vérifiées contre `docs/vc_study/*.txt`, avec citations fichier:ligne dans `docs/vc_card_traceability.md` → **41 vérifiées / 17 partielles / 14 non vérifiées**.
- [M] 3 cartes corrigées (cf. section C).
- [V] **Anomalie MCQ découverte et documentée** : les 4 fichiers officiels d'annales **ne marquent aucune réponse MCQ** → la clé MCQ des packs est **déduite, pas officielle**. Signalée dans les 3 notices de pack, dans l'UI (badges) et dans le doc de traçabilité. Les solutions B/C (calculs/cas) sont bien officielles (ex. waterfall `Final exam 2023.txt:213-218`).
- [V] Formule anti-dilution CP2 = CP1×(A+B)/(A+C) : **pas dans le corpus** → explicitement labellisée « convention standard de marché » ; la convention broad/narrow est citée (rich-vs-king:288-321, 88-92 % des deals).
- [O] **14 cartes restent « non vérifiées »** (définitions standard absentes du corpus) : VC07 timeline, VC11 reserve/overage, VC15 scenario/sensitivity, VC17 SAS/ELTIF/VCT, **VC19 quasi-intégralement (venture debt — topic le moins couvert)**, VC20 conseils de stratégie. À retenir comme connaissances générales, pas comme « cours cité ».
- [H] À ta validation : la clé MCQ dérivée (utilise-la en pratique, pas comme vérité officielle) et les 14 cartes NV.

## F. Qualité des tests

- [P] **221 tests VC** (25 fichiers) — incluant `test_vc_revisions_ui.py` (7) et `test_vc_api.py` (19).
- [P] **251 tests VC+web** · **3864+1 tests repo complet**.
- [V] **27/27 vérifications graphiques Playwright** (Chromium headless, store isolé) : ouverture de l'onglet, statut J-3/examen, pastille Gemini, **tour de tuteur réel avec 5 passages**, flashcard révélée/notée, drill noté avec verdict « verified », 3 annales + vue solutions, examen 20 questions avec timer / fuite zéro / soumission, radar 20 lignes, plan, dashboard d'erreurs, **zéro erreur console**.
- [V] Assertion du nombre de drills rendue dynamique (`len(load_content().drills)`) pour ne pas casser à chaque ajout.
- [O] Le test de perf flaky (`test_job_deduplication`) n'est pas le sujet VC mais reste à assainir (seuil 200 ms).

## G. Intégration desktop

- [V] Tout est utilisable **depuis l'app NAGe → onglet Révisions** : rien à faire en CLI ni en terminal.
- [V] Vérifié dans le navigateur réel (Playwright sur le serveur de test 8799) avec captures d'écran : `/tmp/nage_revisions_shots/01..06*.png`.
- [V] Aucune style inline (CSP), aucun lien externe, aucune donnée envoyée hors-ligne sans opt-in.
- [V] Serveur de production : 8765 (inchangé) ; serveur de test 8799 (arrêté/relancé à volonté, log `/tmp/nage_vc_server.log`).

## H. Priorités restantes

1. **[H] Validation humaine (toi)** : relire les 14 cartes « non vérifié » (surtout VC19) et la clé MCQ dérivée avant l'examen — ce sont les seuls contenus non garantis par le corpus.
2. **[O] Rappe-toi la limite d'honnêteté en tête** : toute note MCQ = pratique avec clé dérivée ; toute note B/C = corrigé officiel.
3. **[O] Optionnel** : assainir le test de perf flaky (seuil 200 ms) si tu veux une suite toujours 100 % verte.
4. **[O] Non fait volontairement** : aucun commit/push (211+ fichiers modifiés restent dans le working tree — à toi de décider du versionnement avant l'examen).

### Compteurs de preuve

| Niveau | Résultat |
|---|---|
| Tests VC | 221/221 **[P]** |
| Tests VC+web | 251/251 **[P]** |
| Repo complet | 3864 passed + 1 flaky (passe seul) **[P]** |
| Vérif. graphique | 27/27 **[V]** |
| Cartes vérifiées | 41 V / 17 P / 14 NV **[V]** |
| Drills | 32 (2 anti-dilution réécrits/ajoutés) **[M]** |
| Annales | 3 packs, notices clé MCQ dérivée **[M]** |
