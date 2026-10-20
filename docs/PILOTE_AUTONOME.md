# PILOTE AUTONOME — comment les missions se font toutes seules

Date : 2026-10-20 · Propriétaire : l'agent superviseur (OpenCode).
But : faire avancer le produit **sans intervention de l'utilisateur**, avec un
maximum d'exécution en arrière-plan, en respectant les règles de l'atelier
(`docs/ATELIER_AGENTS.md`) et les règles utilisateur (`docs/REGLES_UTILISATEUR_CAREER.md`).

## Les 5 rôles

| Rôle | Qui | Ce qu'il fait |
|---|---|---|
| **Décideur** | l'agent superviseur (moi) | choisit et formule la mission suivante, selon les priorités produit |
| **Exécuteur** | OpenCode headless (`opencode run --auto`, worktree dédié) **ou** Codex (worktree dédié) | écrit le code + tests, jamais de merge |
| **Critique locale** | Ollama local (`qwen3.5:2b`, runtime `.local-ai`, réseau isolé) | micro-contrôles adversariaux : fixtures, classification, recoupements — **jamais de code de production** |
| **Arbitre** | CI GitHub (`lint` + `tests` sur `main`) | vert/rouge,bloque toute fusion fautive |
| **Relecteur** | l'agent superviseur | vérifie le diff, les interdits, la recette, puis fusion |

## Cycle d'une mission

1. **File de missions** : `docs/agent_missions/MISSIONS_FILE.md` — chaque mission
   y est écrite en prompt directement collable (contexte, périmètre de fichiers,
   interdits, tests adversariaux, livrables).
2. **Exécution en arrière-plan** :
   ```bash
   git worktree add /Users/comedelavenne/AI-Excel-Agent-auto -b auto/<mission> main
   cd /Users/comedelavenne/AI-Excel-Agent-auto
   opencode run --auto --session auto-<mission> "$(cat mission.md)"
   ```
   ou, si la mission est lourde : Codex sur sa branche (worktree dédié).
   Jamais deux exécuteurs sur la même branche ; jamais d'écriture sur `main`.
3. **Critique locale** (si utile) : le modèle Ollama isole du réseau est interrogé
   sur des points bornés (ex. « ce classement peut-il fusionner deux offres
   différentes ? », « ce résumé contient-il une information inventée ? »). Les
   réponses nourrissent le rapport, ne remplacent jamais les tests.
4. **Arbitrage CI** : push de la branche → `lint` + `tests`. Rouge = la branche
   repart à l'exécuteur avec le log.
5. **Relecture + fusion** : checklist `docs/ATELIER_AGENTS.md` ; fusion
   `--no-ff` dans `main` après CI verte ; tag de jalon pour un lot majeur.

## Garde-fous (inchangés)

- `SCHEMA_VERSION` (7) non modifié · pas de `window.prompt` · pas d'envoi
  automatique de candidature · pas de secret · pas de données personnelles
  réelles dans les fixtures · `career_data/` jamais migré à la main.
- Les lots en cours des agents (branches `cvboost-*`) ne sont jamais modifiés
  par le pilote : il travaille sur **ses propres branches** ou **après** leur
  intégration.

## File de missions (ordre de priorité actuel)

1. `docs/agent_missions/VAGUE_2_OFFRES_2026-10-20.md` — « beaucoup plus
   d'offres, un max bien analysées » : exhaustivité du résumé (R2), scoring
   sensible aux préférences + exclusion France (R1), cadre de connecteurs
   bornés, mesure automatique d'exhaustivité.
2. Chaque mission y est un prompt complet et autonome (SHA de base, branche,
   périmètre, tests adversariaux, livrables, rapport obligatoire).

## Traçabilité

- Chaque mission exécutée laisse : branche + commit SHA + rapport dans
  `docs/agent-reports/` + entrée dans ce fichier (date, verdict, limites).
- Le rapport **AUTO-001** (exhaustivité des résumés d'offres) est la première
  mission exécutée par le pilote : il mesure le gap avant d'y remédier.
