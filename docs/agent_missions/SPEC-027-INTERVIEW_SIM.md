# MISSION SPEC-027 — Simulateur d'entretien STAR

> **Priorité : P1** — Lot nocturne 2 (post-SPEC-024). Worktree dédié, push sur branche `agent/spec-027-interview-sim`.

## Contexte
App Career / CVBoost : le dossier (SK-01..SK-11, SPEC-004..024) fournit la pipeline offre→CV→lettre→suivi.
La préparation d'entretien est manuelle ; interview.py basique existe, à étendre sans le casser.

## Mission
Scheduler de questions par offre (mots-clés, secteur) + worksheets STAR guidées avec checklist de preuves et auto-évaluation chiffrée.

## Modules (nouveaux, sans conflit avec les autres specs)
```
career/interview_sim.py          # build_question_set(), StarWorksheet, self_score()
tests/test_interview_sim.py
tests/fixtures/interview_offers_synthetic.json
```

## Contrats Python (must-have)
```python
@dataclass
class InterviewQuestion:
    kind: Literal["behavior","technical","motivation","company"]
    question: str
    evidence_needed: list[str]     # vers preuves du profil

@dataclass
class StarWorksheet:
    question_id: str
    situation: str = ""
    task: str = ""
    action: str = ""
    result: str = ""
    completeness: float            # 0-1 calculé
```

## Règles
- Données : **fixtures synthétiques uniquement** (`tests/fixtures/*synthetic*.json`). Aucune donnée réelle.
- Tests : `.venv/bin/python -m pytest` → suite complète verte + `ruff check .` propre.
- Jamais de clé/secrets en dur ; tout via `os.environ`.
- API : routes REST via le pattern `create_app()` de `career/router.py`, sans casser `schema_version=7`.
- ≥ 12 questions par offre, les 4 kinds présents ; génération déterministe (seed configurable).

## Livrables
1. Code modules + tests (cas limites + au moins 1 test adversarial).
2. Endpoints REST servis via `create_app()` (smoke test obligatoire).
3. Rapport `docs/agent-reports/SPEC-027-interview_sim.md` (livré, décisions, limites).
4. Push UNIQUEMENT sur la branche `agent/spec-027-interview-sim` (jamais main).
