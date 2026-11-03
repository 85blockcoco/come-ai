# MISSION SPEC KIT — SPEC-010 : Interview Prep Assistant Ciblé

> **Priorité : P2** — Module indépendant, worktree dédié. Repose sur SK-03 (Requirements Fit) et SK-10 (Profil candidat).

---

## Contexte

L'outil contient déjà des briques d'entretien. Il faut les relier directement au diagnostic de l'offre pour créer un **assistant d'entretien véritablement ciblé**.

---

## Objectif

Créer un module **InterviewPrep** qui génère depuis une offre + profil : questions techniques/comportementales, écarts CV, points sensibles, questions recruteur, fiche entreprise, simulations chronométrées, mode finance spécialisé.

---

## Nouveaux modules à créer

```
career/interview_prep.py        # Core: génération questions, simulations
career/interview_store.py       # Persistance sessions, historique
career/router.py                # Endpoints GET/POST /interview-prep
career_static/js/interview-prep.js # UI simulation chronométrée
tests/test_interview_prep.py
docs/agent-reports/SPEC-010-INTERVIEW_PREP.md
```

---

## Contrat attendu

### Génération préparation (POST /interview-prep/generate)

```json
{
  "offer_id": 123,
  "profile_id": "user_profile",
  "mode": "standard" | "finance"
}
```

**Réponse** : `InterviewPrepSession`

### InterviewPrepSession

```python
@dataclass
class InterviewPrepSession:
    session_id: str
    offer_id: int
    profile_id: str
    technical_questions: list[InterviewQuestion]
    behavioral_questions: list[InterviewQuestion]
    gap_questions: list[InterviewQuestion]          # Basés sur SK-03 gaps
    sensitive_points: list[str]                     # Points sensibles du CV
    recruiter_questions: list[str]                  # Questions à poser
    company_factsheet: CompanyFactsheet
    created_at: str
```

### InterviewQuestion

```python
@dataclass
class InterviewQuestion:
    id: str
    category: Literal["technical", "behavioral", "gap", "recruiter"]
    question: str
    expected_elements: list[str]           # Points clés attendus
    related_evidence: list[str] | None     # IDs preuves profil
    related_requirement: str | None        # ID exigence offre (si gap)
    difficulty: Literal["easy", "medium", "hard"]
    time_estimate_seconds: int
```

### CompanyFactsheet

```python
@dataclass
class CompanyFactsheet:
    name: str
    sector: str
    size: str
    recent_news: list[str]
    culture_keywords: list[str]
    interview_process: list[str] | None
    sources: list[str]
```

---

## Mode Simulation (POST /interview-prep/simulate)

```json
{
  "session_id": "session_123",
  "question_id": "q_456",
  "user_answer": "Mon expérience en modélisation LBO..."
}
```

**Réponse** : `SimulationFeedback`

### SimulationFeedback

```python
@dataclass
class SimulationFeedback:
    question_id: str
    user_answer: str
    score: Literal["excellent", "good", "needs_improvement", "insufficient"]
    strengths: list[str]
    missing_elements: list[str]           # Points attendus non couverts
    unproven_claims: list[str]            # Affirmations sans preuve
    suggested_structure: str              # STAR, CAR, etc.
    retry_prompt: str                     # Pour nouvelle tentative
    pedagogical_source: str | None        # Source pédagogique citée
```

---

## Mode Finance Spécialisé

Si `mode: "finance"`, banques de questions dédiées :

| Banque | Exemples |
|--------|----------|
| **M&A** | Processus vente, due diligence, earnouts, représentations/garanties |
| **Valuation** | DCF, multiples, LBO, premiere, valeurs terminales |
| **LBO** | Structure dette, IRR, MOIC, cash sweep, refinancement |
| **Marchés** | Greeks, volatilité, produits structurés, hedging |
| **Produits dérivés** | Options, swaps, forwards, exotiques |
| **FP&A** | Budgeting, forecasting, variance analysis, drivers |
| **Contrôle de gestion** | Coûts standards, écarts, transfer pricing |
| **Probabilités** | Brainteasers, distributions, Monte Carlo |

**Règle** : Chaque correction cite sa source pédagogique (ex: "Rosenbaum & Pearl, *Investment Banking*, Ch. 3").

---

## Endpoints API

```
POST   /interview-prep/generate           # Génère session
GET    /interview-prep/{session_id}       # Récupère session
POST   /interview-prep/simulate           # Simule réponse
GET    /interview-prep/{session_id}/history # Historique simulations
POST   /interview-prep/{session_id}/export  # Export PDF/Markdown
```

---

## UI attendue (career_static/js/interview-prep.js)

- **Onglets** : Technique | Comportemental | Écart | Recruteur | Entreprise
- **Mode simulation** : Question → zone réponse → chrono → Soumettre → Feedback structuré
- **Chrono** : Temps estimé, temps réel, alerte dépassement
- **Feedback** : Score, forces, manquants, non-prouvés, structure suggérée, retry
- **Export** : PDF/Markdown pour révision avant entretien

---

## Commandes de validation

```bash
./checklist_codex.sh
.venv/bin/python -m pytest -q tests/test_interview_prep.py
.venv/bin/python -m pytest -q
git diff --check
```

---

## Critères de réussite

- [ ] `interview_prep.generate(offer_id, profile_id, mode) -> InterviewPrepSession`
- [ ] 4 catégories questions + fiche entreprise + questions recruteur
- [ ] Mode simulation : réponse → feedback structuré (score, forces, manquants, non-prouvés, structure, retry, source pédagogique)
- [ ] Mode finance : 8 banques spécialisées, sources pédagogiques citées
- [ ] Historique simulations persistant
- [ ] Export PDF/Markdown
- [ ] Ruff clean, suite complète verte, `git diff --check` propre
- [ ] Rapport `docs/agent-reports/SPEC-010-INTERVIEW_PREP.md`

---

**Tu as tout. Lance-toi.** Branche `agent/spec-010-interview-prep`, worktree dédié, code, tests, rapport, push. Je relis et j'intègre.