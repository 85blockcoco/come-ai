# MISSION SPEC-028 — Checklist documents administratifs stage

> **Priorité : P2** — Lot nocturne 2 (post-SPEC-024). Worktree dédié, push sur branche `agent/spec-028-stage-admin-docs`.

## Contexte
App Career / CVBoost : le dossier (SK-01..SK-11, SPEC-004..024) fournit la pipeline offre→CV→lettre→suivi.
Stage à l'étranger = papier (convention tripartite, visa, assurance) ; rien n'existe dans l'app.

## Mission
Moteur de checklist administrative par pays, statut par pièce (missing/in_progress/ok/not_applicable), preuves exigées, récap exportable.

## Modules (nouveaux, sans conflit avec les autres specs)
```
career/stage_admin_docs.py       # AdminChecklist, REQUIREMENTS_BY_COUNTRY, completeness()
tests/test_stage_admin_docs.py
tests/fixtures/admin_docs_synthetic.json
```

## Contrats Python (must-have)
```python
@dataclass
class AdminItem:
    key: str                       # convention, insurance, work_permit...
    label_fr: str
    required: bool
    status: Literal["missing","in_progress","ok","not_applicable"]
    proof_refs: list[str]

@dataclass
class AdminChecklist:
    country: str
    items: list[AdminItem]
    blocking_missing: list[str]
```

## Règles
- Données : **fixtures synthétiques uniquement** (`tests/fixtures/*synthetic*.json`). Aucune donnée réelle.
- Tests : `.venv/bin/python -m pytest` → suite complète verte + `ruff check .` propre.
- Jamais de clé/secrets en dur ; tout via `os.environ`.
- API : routes REST via le pattern `create_app()` de `career/router.py`, sans casser `schema_version=7`.
- REQUIREMENTS_BY_COUNTRY : FR + 4 pays déjà couverts par les connecteurs internationaux.

## Livrables
1. Code modules + tests (cas limites + au moins 1 test adversarial).
2. Endpoints REST servis via `create_app()` (smoke test obligatoire).
3. Rapport `docs/agent-reports/SPEC-028-stage_admin_docs.md` (livré, décisions, limites).
4. Push UNIQUEMENT sur la branche `agent/spec-028-stage-admin-docs` (jamais main).
