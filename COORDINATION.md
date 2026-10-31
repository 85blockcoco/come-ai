# Coordination de la candidate Côme AI

Contrat repris du dépôt partagé, puis actualisé par la réponse explicite de Côme du 26 octobre 2026: « Codex prend l’UI dans sa candidate ».

- Codex: backend `career/**`, performance, `desktop_static/**`, routes `/app` et `/app-static` de la candidate, tests et intégration finale.
- Le checkout partagé `/Users/comedelavenne/AI-Excel-Agent` est préservé. Les développements OpenCode déjà committés sont intégrés sélectivement.
- Aucun changement par Codex dans l’orchestrateur de flotte, `mission_driver.py`, `night_supervisor.py`, `model_health.py` ou `missions_registry.json`.
- La coordination et les preuves sont publiées dans `messages/codex_note.md` et sur `codex/v3-stable-consolidation`. Aucun nouvel agent OpenCode Go n’est lancé.
- Tests ciblés uniquement pendant cette opération; données synthétiques et fournisseurs simulés.
- Aucune candidature automatique. Aucun merge dans `main` sans validation explicite de Côme.

## Cycle Spec Kit du 31 octobre 2026

- Codex réserve temporairement `devkit/**`, `desktop_static/**` et leurs tests pour intégrer le panneau « Construire mon NAGE ».
- Branche de livraison : `codex/nage-consolidation-20261030`; le checkout partagé OpenCode reste préservé.
- Côme a demandé un backlog de 100 missions et quatre workers OpenCode en parallèle. Un prompt de coordination lui a été fourni; le coordinateur OpenCode attribue les fichiers et les worktrees avant exécution.
- Les fichiers réservés à Codex et `/Users/comedelavenne/NAGE-release` restent exclus des missions OpenCode jusqu’au handoff de livraison.
- Une mission préparée, une tâche en file, une branche livrée et un parcours validé sont des états différents.
- Une revue ponctuelle OpenCode en lecture seule a été lancée sur `opencode/mimo-v2.6-flash-free`, puis interrompue à 180 secondes sans verdict; aucun pool supplémentaire n’a été lancé par Codex.
