# Prompt Codex — Intégration main (NAGe N100)

## Objectif
Pousser dans `main` la consolidation de :
- Travail OpenCode : `origin/agent/n100-carrier-20261101` (HEAD `25dff64`) — backend `career/`, modules N100, CLI `nage.py`.
- Travail courant (J04 PWA) : `origin/agent/n100-G05-bundle-export` (HEAD `c33ca07`) — `desktop_static/manifest.json`, `desktop_static/sw.js`, edit `desktop_static/index.html`, registre `missions_next100.json` (J04 → done).

## État
- `main` (worktree `/Users/comedelavenne/AI-Excel-Agent-main-live`) a divergé ; merge direct échoue (conflits add/add et content).
- Branche consolidée candidate historique : `codex/n100-consolidated-20261101` @ `a9f8226`.

## Tâche pour Codex
1. Dans le worktree main-live, créer une branche d'intégration `codex/main-integration-20261103`.
2. Merger d'abord `origin/agent/n100-carrier-20261101` (backend + CLI), résoudre les conflits en privilégiant le côté carrier pour `career/`, `nage.py`, tests.
3. Merger ensuite `origin/agent/n100-G05-bundle-export` (J04 PWA) ; pour `desktop_static/**` et `missions_next100.json`, privilégier le côté G05 (ajouts manifest/sw + statut J04 done).
4. Pour les fichiers en conflit add/add (tests/fixtures, docs/agent-reports), choisir la version la plus récente / unionner manuellement.
5. Lancer tests ciblés : `tests/test_nage_cli.py` (8), recette J10 (42), ruff. Vérifier `git diff --check`.
6. Pousser la branche d'intégration sur origin, puis fast-forward `main` (ou PR si protection).
7. Ne pas toucher `/Users/comedelavenne/NAGE-release`.

## Règles
- Ne pas écraser de travail non commité.
- SHA, tests et conflits résolus à transmettre à OpenCode.
- Modèles coût nul uniquement si IA impliquée.
