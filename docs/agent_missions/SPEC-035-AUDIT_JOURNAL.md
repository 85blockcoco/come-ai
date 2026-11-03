# MISSION SPEC-035 — Journal d'audit des décisions

> **Priorité : P1** — Lot nocturne 2 (post-SPEC-024). Worktree dédié, push sur branche `agent/spec-035-audit-journal`.

## Contexte
App Career / CVBoost : le dossier (SK-01..SK-11, SPEC-004..024) fournit la pipeline offre→CV→lettre→suivi.
Traçabilité : chaque décision automatisée (score, suggestion de relance, verdict arena) doit être explicable a posteriori.

## Mission
Journal append-only des décisions (qui, quand, contexte, résultat) avec recherche/filtre et génération d'un rapport d'explication par décision.

## Modules (nouveaux, sans conflit avec les autres specs)
```
career/audit_journal.py          # AuditJournal, record(), explain()
tests/test_audit_journal.py
tests/fixtures/audit_synthetic.json
```

## Contrats Python (must-have)
```python
@dataclass
class AuditEntry:
    decision_id: str
    decision_type: str             # followup_scheduled, offer_ranked, arena_verdict...
    context: dict
    outcome: dict
    at: str

@dataclass
class AuditExplanation:
    entry: AuditEntry
    narrative: str                  # explication en français lisible
    contributing_factors: list[tuple[str, float]]
```

## Règles
- Données : **fixtures synthétiques uniquement** (`tests/fixtures/*synthetic*.json`). Aucune donnée réelle.
- Tests : `.venv/bin/python -m pytest` → suite complète verte + `ruff check .` propre.
- Jamais de clé/secrets en dur ; tout via `os.environ`.
- API : routes REST via le pattern `create_app()` de `career/router.py`, sans casser `schema_version=7`.
- Append-only : aucune API de modification/suppression ; hash-chaîné simple (prev_hash) avec détection de altération (test adversarial).

## Livrables
1. Code modules + tests (cas limites + au moins 1 test adversarial).
2. Endpoints REST servis via `create_app()` (smoke test obligatoire).
3. Rapport `docs/agent-reports/SPEC-035-audit_journal.md` (livré, décisions, limites).
4. Push UNIQUEMENT sur la branche `agent/spec-035-audit-journal` (jamais main).
