# MISSION SPEC-024 — Stage adapted Kit 1-clic (assemblage final CV + lettre)

> **Priorité : P0** — Coupure "1 clic" pour candidature de stage maximisée. Worktree dédié.

## Contexte
Fin de la chaîne : tout combien orchestre **SPEC-017 à 023** : à partir d'une offre,
produire en 1 clic un **dossier de stage adapté** (CV ciblé + lettre + rang des preuves)
avec dashboard des scores (ATS, couverture, jury) et les gaps qui restent.

## Pipeline (1 clic)
```
offre → web research (018) → keyword profile (019)
     → exp reformulations (020) + courses (021) [arena 017 + memory 023]
     → letter (022)
     → kit (05/32) — dossier build: CV DOCX/PDF + lettre + tracking + scorecard
```

## Modules
```
career/stage_fit_kit.py        # orchestrateur final (async pipeline, resumable)
career/stage_fit_scorer.py     # scorecard finale: ATS, couverture, gaps, jury
career/stage_fit_router.py
career_static/js/stage-fit-kit.js       # UI grande répartition "adaptation"
tests/test_stage_fit_kit.py
docs/agent-reports/SPEC-024-STAGE_FIT_KIT.md
```

## Contrats
```python
@dataclass
class StageFitScorecard:
    offer_id: str
    ats_before: float
    ats_after: float
    keyword_coverage_before: float
    keyword_coverage_after: float
    gaps_unresolved: list[str]        # demandés par l'offre, absents du profil
    jury_summary: dict[str, float]
    evidence_audit: dict              # % de phrases avec preuves

@dataclass
class StageFitKit:
    kit_id: str
    offer_id: str
    cv_variant_json: dict
    letter_draft_id: str
    docx_path: str                    # CV + lettre dans le kit 05/32
    scorecard: StageFitScorecard
    pipeline_trace: list[dict]        # chaque étape, IA utilisé, durée, coût
```

## Règles
- **Resumable** : si une étape a l'échec, reprendre à l'étape suivante sans tout recalculer.
- Scorecard reflète **avant/après** — jamais masquer le diff (traçabilité totale).
- Gaps non résolus → agenda explicit (l'utilisateur voit ce qui manque pour ce stage).
- Un kit n'est jamais auto-envoyé; export dossier + envoi manuel uniquement (SPEC-032).
- Fidèle aux règles non-régression: toute pièce repasse par le check rel稽 ATS 04.

## API
```
POST  /stagefit/kit/{offer_id}          # lance pipeline (async, retour kit_id)
GET   /stagefit/kit/{kit_id}            # état + scorecard + trace
GET   /stagefit/kit/{kit_id}/export     # dossier DOCX/PDF ready
POST  /stagefit/kit/{kit_id}/rerun      # avec nouvelles constraints (mémoire)
```

## Validation
```bash
./checklist_codex.sh
.venv/bin/python -m pytest -q tests/test_stage_fit_kit.py
.venv/bin/python -m pytest -q
git diff --check
```

## Critères de réussite
- [ ] Pipeline 1-click: offre → kit complet DOCX + scorecard, temps cible < 3 min
- [ ] Scorecard avant/après + gaps, aucune information non-tracée
- [ ] Resumable face à provider KO (reprise d'un fichier d'état)
- [ ] Intégration UI (dashboard generation + historique des kits)
- [ ] Ruff clean, suite verte, git diff --check + rapport SPEC-024

**Tu as tout. Lance-toi.** Branche `agent/spec-024-stage-fit-kit`, worktree dédié, code, tests, rapport, push.
