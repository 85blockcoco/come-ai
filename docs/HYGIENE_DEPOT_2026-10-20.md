# Hygiène du dépôt — opération du 2026-10-20

État avant → après :

| Objet | Avant | Après |
|---|---|---|
| Branches locales | 247 | 10 |
| Worktrees git | 255 | 1 (dépôt principal uniquement) |
| `BASE_SHA_VALIDÉ/` à la racine | 3,2 Mo, non suivi, divergent | supprimé (archivé) |
| Fichiers non suivis racine | 15 entrées (HANDOFF, checklist, reports) | 0 (commits `a3f4a91` + ce dépôt) |

## Filets de sécurité (tout est récupérable)

- **Bundle complet** de toutes les références, créé avant toute suppression :
  `/private/var/folders/jd/ymcfd0zs7kzc6f90p1x6gh5c0000gp/T/opencode/come-ai-archive/come-ai-all-refs-2026-10-20.bundle`
- **Snapshot `BASE_SHA_VALIDÉ`** : `…/come-ai-archive/BASE_SHA_VALIDE_2026-10-20.tar.gz`
- **Diffs et fichiers non-suivis des 72 worktrees sales** : `…/come-ai-archive/worktrees/<nom>/`
  (tracked.diff + untracked.tar.gz, 2,3 Mo au total)

## Branches conservées (travail potentiellement non absorbé, à statuer)

- `main`, `audit/total-v3-2026-10-14` (branche de travail courante)
- `feature/career-stage-hunter`, `feature/study-coach-v1` (versions possiblement divergentes, cf. CODEX_READY §3)
- `feature/come-ai-v6`, `feature/excel-advanced-v6` (V6 non intégrée)
- `feature/v3-gmx-readonly`
- `codex/operation-integration`, `codex/operation-onboarding`, `codex/career-operation-candidate`

## Branches supprimées (justification)

1. **28 fusionnées dans `main`** — aucun contenu unique.
2. **Branches au contenu prouvé absorbé** (`git cherry main <branche>` → 0 commit `+` avec patch-id identique) — 32 supprimées ce critère + les 7 déclarées éteintes par `HANDOFF_AGENT_CODEX.md §4`.
3. **~205 missions agents scratch** (agent/c50-*, c50v2-*, c60-*, mission-*, opencode/*…) : livrables intégrés dans `main` via les branches d'intégration ; récupérables via le bundle si besoin.

## Recommandations restantes

- Créer un remote Git privé (GitHub/GitLab) : la totale absence de remote a rendu toute la discipline dépendante de scripts locaux.
- Ne plus créer de worktree dans `/tmp` : préférer des branches courtes intégrées vite.
- `.local-ai/` (2,5 Go) et `.devkit/` (178 Mo dont 24 copies de codebase dans `integration/`) : à auditer manuellement par le propriétaire (données privées, non détruit par cette opération).
