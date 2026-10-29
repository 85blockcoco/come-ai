# COORDINATION — OpenCode ⟷ Codex

Objectif commun : livrer l’application de candidatures (interface desktop) sans
se marcher dessus. Deux écrivains, deux périmètres.

## Périmètres (ne pas écraser le travail de l’autre)

| Zone | Propriétaire | Fichiers |
|---|---|---|
| Backend career, perf, dédup, sprint | **Codex** | `career/**`, `tests/**` liés à career |
| Interface desktop, icône, bundle macOS | **OpenCode** | `desktop_static/**`, `desktop/**`, routes `/app` et `/api/app/*` de `come_ai_web.py` |
| Orchestrateur de missions | **OpenCode** | `orchestrator.py`, `mission_driver.py`, `night_supervisor.py`, `missions_registry.json` |
| Registre des missions | **OpenCode** (seul écrivain) | `missions_registry.json` |

Règle : un fichier n’a qu’un propriétaire. Si Codex doit toucher
`come_ai_web.py`, il le fait **hors** des blocs `/app` et `/api/app/missions`.

## Protocole

1. **Avant de commencer** : `git fetch origin && git log --oneline -5 origin/main`.
2. **Commits petits**, message préfixé : `career:`, `perf:`, `ui:`, `fleet:`.
3. **Pousser sa branche** dès qu’un lot passe ses tests :
   `git push -u origin <branche>`. Une branche non poussée n’existe pas.
4. **Preuve obligatoire** avant de dire « fini » : branche sur origin + tests
   ciblés rejoués (jamais la suite complète pendant que la flotte tourne).
5. **Pas de merge sur `main`** sans go explicite de Côme.
6. **Jamais de données personnelles** dans le dépôt, aucune soumission
   automatique d’une candidature.

## État au 26/10 15:00

- `codex/v3-stable-consolidation` : 6 commits (perf dédup médiane 319,9 → 185,5 ms),
  poussée sur origin par OpenCode pour préserver le travail.
- `main` : `69fc924` + missions (56/73 livrées, preuve = branche + tests).
- Interface desktop : `/app` (bundle `NAGE.app` sur le Bureau).
- Flotte : 4 workers, modèles **gratuits uniquement** (quota opencode-go préservé).

## Ce qu’OpenCode attend de Codex

- Pousser `codex/v3-stable-consolidation` (fait), puis ouvrir une PR ou signaler
  les commits prêts à intégrer.
- Priorité backend : images des missions 39 → 51, 66 → 68 → 72 (dépendances).
- Ne pas lancer la suite complète : `pytest -q tests/test_<zone>.py` suffit.

## Transfert du 29/10 16:15 — 12 missions passées à Codex

Ordre de reprise, dépendances et règles : voir `messages/handoff_codex_missions.md`.

- 7 missions échouées au retry max (39, 66, 70, 71, 73, 74, 77) → **Codex**,
  flotte suspendue sur ces lots (charge machine trop élevée).
- 5 missions en attente de dépendance (51, 68, 72, 79, 80) → se débloquent
  automatiquement quand la mission amont est `done`.
- Codex signale chaque livraison dans `messages/codex_mission_<n>.md` ;
  OpenCode vérifie (branche sur origin + tests ciblés) puis marque `done`
  dans `missions_registry.json` — seul écrivain du registre.
