# MISSION SPEC-021 — Course & Education Reformulator (cours, formations, certifications)

> **Priorité : P1** — Complète le SPEC-020 pour la partie académique. Worktree dédié.

## Contexte
Pour un stage, les cours / formations / certifications doivent être **re-priorisés et reformulés**
pour montrer leur lien avec le stage (ex: cours "Bases de données" → "conception schéma SQL
applicable au pipeline de données du stage"). Comme pour les expériences : multi-IA + anti-invention.

## Sources d'entrée
- Profil SK-10 : formations, cours suivis, certifications avec preuves.
- SPEC-018 : compétences stack de l'entreprise (lien cours ↔ outils).
- SPEC-019 : mots-clés pondérés (évidences cours à remonter en haut).

## Modules
```
career/course_reformulate.py    # pipeline académique (cours, mixins, certifs)
career/course_ranker.py         # réordonner sections éducation pour l'offre
career/course_router.py
career_static/js/course-reformulator.js
tests/test_course_reformulator.py
docs/agent-reports/SPEC-021-COURSE_REFORMULATOR.md
```

## Contrats
```python
@dataclass
class ReformulatedCourse:
    course_id: str
    original_title: str
    adapted_title: str                # reformulé, sans mentir sur intitulé réel
    link_to_stage: str                # pourquoi c'est utile pour ce stage
    evidence_refs: list[str]
    rank_delta: int                    # mouvement dans la section éducation
    jury_score: float

@dataclass
class EducationPlan:
    courses: list[ReformulatedCourse]
    reordered_list: list[str]          # ids dans l'ordre CV adapté
    certifications_boosted: list[str]  # à mettre en avant (STILL dans preuves)
```

## Règles
- Le intitulé **original du cours** reste visible (ex: tooltip "cours réel: X").
- Jamais affirmer avoir suivi un cours qui n'existe pas dans le profil.
- Certifications expirées SPEC-012 → pas boostées sans mention d'expiration.
- Arena: 2-3 reformulations, jury décide le best-of-consensus (fiche des diffs).

## API
```
POST /reformulate/education/{offer_id}     # → EducationPlan
POST /reformulate/education/apply          # applique l'ordre + adaptés, diff générée
```

## Validation
```bash
./checklist_codex.sh
.venv/bin/python -m pytest -q tests/test_course_reformulator.py
.venv/bin/python -m pytest -q
git diff --check
```

## Critères de réussite
- [ ] Chaque cours compte un lien explicite au stage, traçable aux preuves
- [ ] Réordonnancement éducation simulable, réémission diff CV
- [ ] Adversarial: cours non suivis rejetés, certifs expirées pas boostées
- [ ] Ruff clean, suite verte, git diff --check + rapport SPEC-021

**Tu as tout. Lance-toi.** Branche `agent/spec-021-course-reformulator`, worktree dédié, code, tests, rapport, push.
