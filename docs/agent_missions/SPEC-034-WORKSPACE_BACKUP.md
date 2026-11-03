# MISSION SPEC-034 — Sauvegarde / restauration workspace

> **Priorité : P1** — Lot nocturne 2 (post-SPEC-024). Worktree dédié, push sur branche `agent/spec-034-workspace-backup`.

## Contexte
App Career / CVBoost : le dossier (SK-01..SK-11, SPEC-004..024) fournit la pipeline offre→CV→lettre→suivi.
Le workspace utilisateur (candidatures, dossiers, preuves) doit être exportable/restaurable sans perte.

## Mission
Backup ZIP versionné (manifest + checksums) et restore avec validation de schéma + diff avant écrasement ; jamais d'écrasement sans confirmation explicite de l'appelant.

## Modules (nouveaux, sans conflit avec les autres specs)
```
career/workspace_backup.py       # create_backup(), restore_backup(), diff_state()
tests/test_workspace_backup.py
tests/fixtures/backup_synthetic.json
```

## Contrats Python (must-have)
```python
@dataclass
class BackupManifest:
    created_at: str
    schema_version: int            # actuel = 7
    files: list[str]
    checksums: dict[str, str]

@dataclass
class RestorePlan:
    to_overwrite: list[str]
    to_add: list[str]
    conflicts: list[str]           # jamais résolus silencieusement
```

## Règles
- Données : **fixtures synthétiques uniquement** (`tests/fixtures/*synthetic*.json`). Aucune donnée réelle.
- Tests : `.venv/bin/python -m pytest` → suite complète verte + `ruff check .` propre.
- Jamais de clé/secrets en dur ; tout via `os.environ`.
- API : routes REST via le pattern `create_app()` de `career/router.py`, sans casser `schema_version=7`.
- Restore refuse en cas de schema_version différent du workspace local sauf flag explicite upgrade=True.

## Livrables
1. Code modules + tests (cas limites + au moins 1 test adversarial).
2. Endpoints REST servis via `create_app()` (smoke test obligatoire).
3. Rapport `docs/agent-reports/SPEC-034-workspace_backup.md` (livré, décisions, limites).
4. Push UNIQUEMENT sur la branche `agent/spec-034-workspace-backup` (jamais main).
