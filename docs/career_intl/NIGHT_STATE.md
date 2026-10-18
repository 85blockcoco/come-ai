# Career International — état de nuit

- Début (UTC) : 2026-10-18T01:52:17Z
- Limite étendue par l'utilisateur : 13 heures après le début, soit 2026-10-18T14:52:17Z.
- Base : `main` = `5ef814eb16f3357264624abdf0b8fd746315b7b1`
- Worktree initial : `/Users/comedelavenne/AI-Excel-Agent-night`
- Branche active : `codex/w2-offer-qualification`
- HEAD initial : `5ef814eb16f3357264624abdf0b8fd746315b7b1`
- Worktrees constatés avant création : 175 ; après création : 176.
- Tags `night-*` : aucun au démarrage.
- États/rapports `docs/career_intl/NIGHT_STATE.md`, `REPORT_W2.md`, `REPORT_W3.md`, `MORNING_REVIEW.md` recherchés dans les worktrees existants : aucun trouvé.

## Baseline vérifiée

- `pytest -q` : **749 passed in 47.28s**, aucun skip affiché.
- `python -m evals suite` : 60 cas, 49 supported, 11 future, 0 application_verified.
- `python -m evals run --target come-ai --strict --no-persist` : 9 cas connus, 8 exécutés et réussis, 1 non pris en charge (`REAL-009`, `local_model_generation`), 0 échec, 0 appel API déclaré par la cible (non mesuré par le runner), 0.117 s, pic 78.2 MiB.
- Tous les appels Python/tests de cette session utilisent les variables de secrets retirées, `HOME=/tmp/codex_home` et `PYTHONDONTWRITEBYTECODE=1`.

## Tranches

| Tranche | Statut | Branche / tag | Résumé |
|---|---|---|---|
| W2 | TERMINÉE (isolée, non intégrée) | `codex/w2-offer-qualification` / tag `night-W2-done` | Qualification conservatrice branchée à la découverte ; suite complète et évaluation HTTP synthétique vérifiées. |
| W3 | TERMINÉE (isolée, non intégrée) | `codex/w3-source-connectors` | Connecteurs ATS publics Lever/Ashby/SmartRecruiters; source registry encore inchangé, aucun employeur ajouté. Voir `REPORT_W3.md`. |
| W4 | À FAIRE | `codex/w4-daily-freshness` | Fraîcheur, cache et propositions du jour. |
| W9-lite | À FAIRE | `codex/w9-lite-router-resilience` | Cooldowns et Retry-After. |
| W6 | À FAIRE | `codex/w6-explainable-fit` | Adéquation vérifiable et explicable. |
| W7 | À FAIRE | `codex/w7-application-dossier` | Dossier contrôlé, sans envoi. |
| W8 | À FAIRE | `codex/w8-application-followup` | Suivi persistant et relances suggérées. |
| W5-lite | À FAIRE | `codex/w5-lite-profile-provenance` | Provenance et approbation du profil. |
| W10 | À FAIRE | `codex/w10-end-to-end-rehearsal` | Parcours HTTP synthétique de bout en bout. |

## Décisions prudentes

1. Aucun état de nuit existant ni tag n'a été trouvé dans les 175 worktrees visibles ; commencer W2 depuis le SHA actuel de `main`, qui correspond au SHA attendu. L'alternative de reprendre une tranche antérieure a été écartée faute de point de reprise vérifiable.
2. L'utilisateur a ensuite autorisé des recherches réseau réelles. Cette autorisation est limitée à la lecture de sources publiques et à la documentation officielle ; aucune candidature, authentification, écriture distante, API payante ou transmission de données personnelles. Les tests de code restent synthétiques et ne prouvent pas la fraîcheur ou la qualité de vraies offres.
3. Aucun fichier personnel, base applicative, secret ou document réel ne sera ouvert. Les scénarios d'intégration utiliseront des fixtures synthétiques.
4. Toute source/connecteur sans documentation officielle consultée sera explicitement `doc_verified=False` ; aucun identifiant de board/employeur ne sera inventé.
5. Les modifications aux fichiers partagés existants resteront des accroches de 15 lignes maximum ; toute logique ira dans des modules nouveaux.
6. Le nouvel ordre de priorité donné par l'utilisateur place les garde-fous de confidentialité avant la couverture des sources et le profil. W2 est achevée dans son worktree isolé et reste non fusionnée ; avant tout lot W3/W4, revoir le lot T1 de confidentialité en lecture seule et déterminer le plus petit chemin d'intégration sûr.

## Blocages

- Aucun au prologue.
- Les tests de qualification ne remplacent pas la validation de couverture/fraîcheur sur les sources de production ; les résultats synthétiques et la recherche documentaire restent séparés.

## Journal

- Prologue : worktree créé depuis `main`; baseline complète mesurée et consignée ci-dessus.
- Autorisation actualisée : recherches publiques en lecture seule permises ; limite de mission étendue à 13 h depuis le début. Pas d'appel aux fournisseurs Gemini/OpenRouter et pas de données personnelles dans les tests.
- W2 : tests adversariaux d'abord (30 cas de base, puis cas HTTP et plages de dates), implémentation conservatrice, suite complète verte à 785 tests et évaluation `come-ai` stricte à 11/11 cas exécutés réussis, 1 non pris en charge. Détails et limites dans `REPORT_W2.md`.
- Le point de reprise après W2 était l'audit ciblé, en lecture seule, de `codex/t1-privacy-guards`; le lot T1 est maintenant dans le candidat isolé décrit au journal.
- W3 : adaptateurs séparés ajoutés au map par défaut, désactivés pour les consultations; fixtures, cas HTTP application_verified, smoke réseau uniquement sur les boards-exemples de documentation. Aucun identifiant réel d'employeur n'a été ajouté au registre. Détails dans `REPORT_W3.md`.
