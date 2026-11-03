# MISSION SPEC-037 — Briefing J-1 veille d'entretien

> **Priorité : P1** — Lot nocturne 2 (post-SPEC-024). Worktree dédié, push sur branche `agent/spec-037-j1-briefing`.

## Contexte
App Career / CVBoost : le dossier (SK-01..SK-11, SPEC-004..024) fournit la pipeline offre→CV→lettre→suivi.
La veille d'un entretien, tout doit être réuni en un seul document actionable.

## Mission
Générateur de briefing J-1 : fiche entreprise (sources), questions probables (SPEC-031), worksheets STAR remplies (SPEC-027), checklist administratives (SPEC-028) si stage à l'étranger, éléments à relire du CV — un seul JSON/export lien.

## Modules (nouveaux, sans conflit avec les autres specs)
```
career/j1_briefing.py            # build_j1_briefing(), BriefingDoc
tests/test_j1_briefing.py
tests/fixtures/j1_synthetic.json
```

## Contrats Python (must-have)
```python
@dataclass
class BriefingDoc:
    application_id: str
    company_facts: list[str]       # avec sources
    top_questions: list[str]       # depuis SPEC-031
    star_ready: list[str]          # worksheets complètes (>= 0.8 completeness)
    admin_blockers: list[str]      # de SPEC-028 si applicable
    cv_section_reread: list[str]
```

## Règles
- Données : **fixtures synthétiques uniquement** (`tests/fixtures/*synthetic*.json`). Aucune donnée réelle.
- Tests : `.venv/bin/python -m pytest` → suite complète verte + `ruff check .` propre.
- Jamais de clé/secrets en dur ; tout via `os.environ`.
- API : routes REST via le pattern `create_app()` de `career/router.py`, sans casser `schema_version=7`.
- Briefing incomplet (worksheets vides) → document livré avec sections 'À COMPLÉTER' explicites, jamais masquées.

## Livrables
1. Code modules + tests (cas limites + au moins 1 test adversarial).
2. Endpoints REST servis via `create_app()` (smoke test obligatoire).
3. Rapport `docs/agent-reports/SPEC-037-j1_briefing.md` (livré, décisions, limites).
4. Push UNIQUEMENT sur la branche `agent/spec-037-j1-briefing` (jamais main).
