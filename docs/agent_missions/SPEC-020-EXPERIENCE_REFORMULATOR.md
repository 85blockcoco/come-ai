# MISSION SPEC-020 — Experience Reformulator (reformule chaque expérience pour le stage)

> **Priorité : P0** — Cœur de l'adaptation CV. Worktree dédié.

## Contexte
Une même expérience professionnel(le) doit être reformulée différemment selon le stage visé.
Objectif : pour chaque expérience du profil (SK-10), générer N variantes de bullet points,
**slectionnées par la arena multi-IA (SPEC-017)**, alignées sur les mots-clés (SPEC-019),
**sans jamais inventer** au-delà des preuves approuvées.

## Modules
```
career/exp_reformulate.py     # orchestrateur (async future arbre)
career/exp_constraints.py     # garde-fous anti-invention, max à 2 lignes, verbes d'action
career/exp_scorer.py          # score ATS (SPEC-04) + coverage mots-clés + jury
career/exp_router.py          # endpoints + diff/para line CV Review (SPEC-004)
career_static/js/exp-reformulator.js  # comparateur variantes endpoints + apply
tests/test_exp_reformulator.py
docs/agent-reports/SPEC-020-EXPERIENCE_REFORMULATOR.md
```

## Contrats
```python
@dataclass
class ReformulatedBullet:
    original_block_id: str
    text_fr: str
    variant_actions: list[str]          # "ajout résultat chiffré", "verbe d'action selon l'offre"
    keyword_hits: list[str]
    evidence_refs: list[str]            # exclusifs preuves SK-10
    ats_score: float
    jury_score: float
    provider: str
    version: int

@dataclass
class RecommendVerdict:
    bullets: list[ReformulatedBullet]
    recommended_combo: list[str]        # quels choisir et під cur_file alignment
    diff_vs_current: str                # affichable dans CV Review
```

## Règles anti-invention (hard)
- Un bullet reformulé mentionne SEULEMENT des faits présents dans les preuves SF-10.
- Interdits: inventer pourcentage, durée, product (certains cas mis à la mains ×57).
- Verbe d'action autorisés (list whitelisted, prière de préférer "Dirigé" à "Géré" si mem.)
- Si une demande exige un skill absent du profil → **gap signalé** plutôt qu'inventé.

## API
```
POST /reformulate/experience                  # offer_id + block_id → list bullets
POST /reformulate/section                     # toutes expériences d'une section
POST /reformulate/{bullet_id}/apply           # applique et produit diff CV Review
POST /reformulate/{bullet_id}/reject          # feedback mémoire (SPEC-023)
GET  /reformulate/{offer_id}/score            # ATS avant/après, coverage, gaps
```

## Validation
```bash
./checklist_codex.sh
.venv/bin/python -m pytest -q tests/test_exp_reformulator.py
.venv/bin/python -m pytest -q
git diff --check
```

## Critères de réussite
- [ ] ≥3 variantes multi-IA par expérience, choix début par scoring + jury
- [ ] Zéro invention (suite adversarial 150+ cas: entités non factuelles rejetées)
- [ ] Diff intégré dans CV Review Workspace (SPEC-004), accept/reject tracés
- [ ] ATS score avant/après visible pour chaque variante
- [ ] Ruff clean, suite verte, git diff --check + rapport SPEC-020

**Tu as tout. Lance-toi.** Branche `agent/spec-020-experience-reformulator`, worktree dédié, code, tests, rapport, push.
