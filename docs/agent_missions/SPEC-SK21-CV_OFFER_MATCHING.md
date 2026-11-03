# MISSION SPEC KIT — SK-21 : Matching CV ↔ Offre + Conseils ultra-ciblés

> **Priorité : P1 — CŒUR DE VALEUR** — Après SK-16 à SK-20. Module indépendant, worktree dédié.

---

## Contexte

Aujourd'hui : Mission 01 (cv_quality) analyse le CV, Mission 02 (offer_requirements) existe mais **pas branchées ensemble**. Résultat : conseils CV génériques, pas "pour CETTE offre".

**Objectif** : `match_cv_to_offer(cv_result, offer) → liste actions concrètes` avec evidence verbatim CV + evidence verbatim offre.

---

## Modules à créer

```
career/cv_quality/matching.py
career/cv_quality/action_generator.py
career/cv_quality/impact_scorer.py
tests/test_cv_offer_matching.py
tests/fixtures/cv_offer_matching/
```

---

## Architecture

```
CV (profil local)          OFFRE (qualifiée)
     │                          │
     ▼                          ▼
extract_requirements()    extract_requirements()  ← SK-16/17/18/19
     │                          │
     └──────────┬───────────────┘
                ▼
        match_cv_to_offer()
                │
                ▼
        ┌───────┴───────┐
        ▼               ▼
action_generator   impact_scorer
        │               │
        └───────┬───────┘
                ▼
        TOP 5 actions prioritaires
```

---

## Contracts attendus

### 1. Match Result

```python
@dataclass
class RequirementMatch:
    requirement_text: str           # Exigence offre (verbatim)
    requirement_source: str         # "description_original", "requirements", etc.
    cv_field: str                   # "skills", "experience", "education", "languages"
    cv_evidence: str                # Extrait CV verbatim (ex: "Python 3.10, 3 ans")
    cv_evidence_source: str         # "skills", "experience:2022-2024", etc.
    match_type: Literal["exact", "partial", "missing", "transferable"]
    confidence: Literal["high", "medium", "low"]
    matched_keywords: list[str]     # ["python", "financial modeling"]
    missing_keywords: list[str]     # ["vba", "bloomberg"] si partial/missing
```

### 2. Action CV

```python
@dataclass
class CVAction:
    action_id: str                  # "act-1", "act-2"...
    priority: Literal["critical", "high", "medium", "low"]
    action_type: Literal[
        "add_skill",           # Ajouter compétence manquante (SI preuve)
        "rephrase_skill",      # Reformuler compétence existante
        "move_up_skill",       # Remonter compétence dans section
        "add_experience_bullet", # Ajouter bullet point expérience
        "rephrase_experience", # Reformuler expérience
        "add_education",       # Ajouter formation
        "add_language",        # Ajouter langue
        "quantify_achievement", # Quantifier un résultat
    ]
    section: Literal["Compétences", "Expériences", "Formation", "Langues", "Informations complémentaires"]
    offer_reference: str            # "Exigence : 'Maîtrise Python 3.8+'"
    cv_reference: str               # "Profil local · Compétences : 'Python 3.10'"
    requirement_quote: str          # Extrait exact offre
    cv_evidence_quote: str          # Extrait exact CV (ou "" si missing)
    suggested_change: str           # "Dans Compétences, ajoute 'Python 3.10' car l'offre exige 'Python 3.8+'"
    why: str                        # "Preuve locale correspond à exigence offre"
    impact_score: float             # 0-100 (voir impact_scorer)
    fact_safe: bool                 # True = ne demande pas d'inventer
    evidence_quality: Literal["documented", "needs_quantification", "missing"]
```

### 3. Match Summary

```python
@dataclass
class CVOfferMatch:
    job_id: str
    job_title: str
    company: str
    total_requirements: int
    matched_count: int
    partial_count: int
    missing_count: int
    coverage_percent: int           # matched / total * 100
    top_actions: list[CVAction]     # TOP 5 par impact_score
    all_matches: list[RequirementMatch]
    disclaimer: str
```

---

## Algorithme `match_cv_to_offer()`

```python
def match_cv_to_offer(
    cv_profile: dict[str, Any],      # profile local (skills, experience, education, languages, eligibility)
    intake_answers: dict[str, Any],  # réponses guided intake (strengths, missions)
    job: dict[str, Any],             # offre qualifiée (avec requirements extraits)
) -> CVOfferMatch:
    
    # 1. Extraire exigences offre (réutilise application_prep.extract_requirements)
    requirements = extract_requirements(job)
    
    # 2. Construire profil CV de travail (inclut intake)
    working_cv = build_working_cv(cv_profile, intake_answers)
    
    # 3. Pour CHAQUE exigence → matcher
    matches = []
    for req in requirements:
        tokens = _tokens(req["text"])  # tokens non-génériques
        evidence = _find_evidence(working_cv, tokens)  # réutilise application_prep._find_evidence
        
        if evidence:
            field, excerpt, hits = evidence
            match_type = "exact" if len(hits) >= 2 else "partial"
            confidence = "high" if match_type == "exact" else "medium"
            matches.append(RequirementMatch(
                requirement_text=req["text"],
                requirement_source=req["source"],
                cv_field=field,
                cv_evidence=excerpt,
                cv_evidence_source=field,
                match_type=match_type,
                confidence=confidence,
                matched_on=hits,
                missing_keywords=[t for t in tokens if t not in hits],
            ))
        else:
            matches.append(RequirementMatch(
                requirement_text=req["text"],
                requirement_source=req["source"],
                cv_field="",
                cv_evidence="",
                cv_evidence_source="",
                match_type="missing",
                confidence="low",
                matched_on=[],
                missing_keywords=tokens[:6],
            ))
    
    # 4. Générer actions pour CHAQUE match
    actions = generate_actions(matches, working_cv)
    
    # 5. Scorer impact
    scored_actions = score_impact(actions, matches, job)
    
    # 6. Top 5
    top_5 = sorted(scored_actions, key=lambda a: a.impact_score, reverse=True)[:5]
    
    return CVOfferMatch(...)
```

---

## Générateur d'actions (`action_generator.py`)

```python
def generate_actions(matches: list[RequirementMatch], cv: dict[str, Any]) -> list[CVAction]:
    actions = []
    for i, match in enumerate(matches):
        if match.match_type in ("exact", "partial"):
            # Compétence existe → mettre en avant / reformuler
            if match.cv_field in ("skills", "languages"):
                actions.append(CVAction(
                    action_id=f"supported-{i}",
                    priority="high" if i < 3 else "medium",
                    action_type="move_up",
                    action_label="Mettre en avant",
                    section=_CV_SECTION_LABELS[match.cv_field],
                    offer_reference=f"Exigence : « {match.requirement_text[:80]} »",
                    cv_reference=f"Profil local · {_CV_SECTION_LABELS[match.cv_field]}",
                    requirement_quote=match.requirement_text,
                    cv_evidence_quote=match.cv_evidence,
                    suggested_change=f"Dans « {_CV_SECTION_LABELS[match.cv_field]} », rends plus visible : « {match.cv_evidence} ». Adapte l'ordre à la langue de l'offre.",
                    why=f"Preuve locale correspond à l'exigence : « {match.requirement_text} »",
                    fact_safe=True,
                    evidence_quality="needs_quantification" if match.cv_field == "experience" and not re.search(r"\d", match.cv_evidence) else "documented",
                ))
            elif match.cv_field == "experience":
                actions.append(CVAction(
                    action_id=f"supported-{i}",
                    priority="high" if i < 3 else "medium",
                    action_type="rephrase",
                    action_label="Reformuler fidèlement",
                    section="Expériences",
                    ...
                ))
        else:  # missing
            # Compétence manquante → NE PAS AJOUTER sans preuve
            actions.append(CVAction(
                action_id=f"missing-{i}",
                priority="high" if i < 3 else "medium",
                action_type="verify_before_adding",
                action_label="Ne pas ajouter sans preuve",
                section="À déterminer",
                offer_reference=f"Exigence non étayée : « {match.requirement_text[:80]} »",
                cv_reference="Aucune preuve trouvée dans le profil local",
                requirement_quote=match.requirement_text,
                cv_evidence_quote="",
                suggested_change="Ne l'ajoute pas au CV maintenant. Si tu possèdes réellement cet acquis, renseigne d'abord une preuve précise et vérifiable dans ton profil (contexte, action, résultat).",
                why=f"Aucune preuve correspondante pour : « {match.requirement_text} »",
                fact_safe=True,
                evidence_quality="missing",
            ))
    return actions
```

---

## Impact Scorer (`impact_scorer.py`)

```python
def score_impact(actions: list[CVAction], matches: list[RequirementMatch], job: dict[str, Any]) -> list[CVAction]:
    # Récupérer qualification offre pour savoir exigences obligatoires
    qual = job.get("qualification", {})
    mandatory_requirements = set()
    for req in qual.get("requirements", []):
        if req.get("mandatory", True):  # par défaut mandatory
            mandatory_requirements.add(req["text"])
    
    for action in actions:
        # Trouver match correspondant
        match = next((m for m in matches if m.requirement_text == action.requirement_quote), None)
        
        base_score = 0
        if action.action_type == "verify_before_adding":
            # Exigence manquante
            is_mandatory = action.requirement_quote in mandatory_requirements
            base_score = 80 if is_mandatory else 40
        elif action.action_type in ("move_up", "rephrase"):
            # Compétence existante
            confidence = match.confidence if match else "low"
            base_score = {"high": 70, "medium": 50, "low": 30}.get(confidence, 30)
            # Bonus si exigence mandatory
            if action.requirement_quote in mandatory_requirements:
                base_score += 15
        
        # Pénalité si evidence_quality = needs_quantification
        if action.evidence_quality == "needs_quantification":
            base_score -= 10
        
        action.impact_score = max(0, min(100, base_score))
    
    return actions
```

---

## Export "Plan d'action pour cette offre" (PDF/Markdown)

```python
def export_action_plan(match: CVOfferMatch, format: Literal["markdown", "pdf"]) -> str:
    if format == "markdown":
        lines = [
            f"# Plan d'action pour : {match.job_title} chez {match.company}",
            f"**Couverture CV/Offre : {match.coverage_percent}%** ({match.matched_count}/{match.total_requirements} exigences étayées)",
            "",
            "## Top 5 actions prioritaires",
        ]
        for i, action in enumerate(match.top_actions, 1):
            lines.extend([
                f"### {i}. {action.action_label} — {action.section}",
                f"**Priorité :** {action.priority.upper()} | **Impact :** {action.impact_score:.0f}/100",
                f"**Exigence offre :** {action.requirement_quote}",
                f"**Preuve CV :** {action.cv_evidence_quote or 'AUCUNE'}",
                f"**Action :** {action.suggested_change}",
                f"**Pourquoi :** {action.why}",
                f"**Sécurité factuelle :** {'✅' if action.fact_safe else '⚠️'} {action.evidence_quality}",
                "",
            ])
        return "\n".join(lines)
```

---

## Validation

### Fixtures synthétiques (minimum 10 scénarios complets)

| Scénario | CV | Offre | Actions attendues (top 3) |
|----------|-----|-------|---------------------------|
| Match parfait | Python, Excel, M&A, Anglais | Python, Excel, M&A, Anglais | 0 missing, 4 move_up |
| Gap critique | Python, Excel | Python, **VBA**, Bloomberg, M&A | 1. add_skill VBA (critical) 2. add_skill Bloomberg (high) 3. move_up Python |
| Gap partiel | "Modélisation financière" | "Financial modeling (LBO, DCF)" | 1. rephrase_experience "LBO/DCF" (high) 2. move_up "Modélisation" |
| Compétence transférable | "Analyse données Python" | "Data analysis SQL" | 1. rephrase_skill "Python → SQL" (medium) 2. verify_before_adding SQL |
| Langue manquante | Français | Anglais requis | 1. add_language Anglais (critical si mandatory) |
| Niveau études | Master 1 | Bac+5 requis | 1. add_education Master 2 (high) |
| Quantification manquante | "Géré portefeuille" | "Géré portefeuille 50M€" | 1. quantify_achievement "50M€" (high) |

### Pièges obligatoires

| Piège | Règle |
|-------|-------|
| Compétence manquante | **JAMAIS** action "add_skill" sans `fact_safe=True` + `evidence_quality="missing"` |
| Action suggère d'inventer | `fact_safe=False` → REJETÉ |
| Priorité sans impact_score | Interdit |
| Top 5 sans justification `why` | Interdit |

---

## Commandes de validation

```bash
./checklist_codex.sh
.venv/bin/python -m pytest -q tests/test_cv_offer_matching.py
.venv/bin/python -m pytest -q
git diff --check
```

---

## Critères de réussite

- [ ] `match_cv_to_offer(cv, intake, job) -> CVOfferMatch`
- [ ] `generate_actions(matches, cv) -> list[CVAction]`
- [ ] `score_impact(actions, matches, job) -> list[CVAction]` avec impact_score
- [ ] TOP 5 actions retournées
- [ ] `export_action_plan(match, "markdown") -> str` (PDF via document_export)
- [ ] 10+ scénarios complets fixtures
- [ ] **Zéro** action `add_skill` sans `fact_safe=True`
- [ ] Intégré dans `service.py` → endpoint "Générer mon plan pour cette offre"
- [ ] Ruff clean, suite complète verte, `git diff --check` propre
- [ ] Rapport `docs/agent-reports/SPEC-SK21-CV_OFFER_MATCHING.md`

---

## Squelette minimal

```python
# career/cv_quality/matching.py
from __future__ import annotations
from dataclasses import dataclass
from typing import Literal
from career.application_prep import extract_requirements, _find_evidence, _tokens

@dataclass
class RequirementMatch:
    requirement_text: str
    requirement_source: str
    cv_field: str
    cv_evidence: str
    cv_evidence_source: str
    match_type: Literal["exact", "partial", "missing", "transferable"]
    confidence: Literal["high", "medium", "low"]
    matched_keywords: list[str]
    missing_keywords: list[str]

@dataclass
class CVAction:
    action_id: str
    priority: Literal["critical", "high", "medium", "low"]
    action_type: Literal["add_skill", "rephrase_skill", "move_up_skill", "add_experience_bullet", "rephrase_experience", "add_education", "add_language", "quantify_achievement", "verify_before_adding"]
    section: str
    offer_reference: str
    cv_reference: str
    requirement_quote: str
    cv_evidence_quote: str
    suggested_change: str
    why: str
    impact_score: float
    fact_safe: bool
    evidence_quality: Literal["documented", "needs_quantification", "missing"]

@dataclass
class CVOfferMatch:
    job_id: str
    job_title: str
    company: str
    total_requirements: int
    matched_count: int
    partial_count: int
    missing_count: int
    coverage_percent: int
    top_actions: list[CVAction]
    all_matches: list[RequirementMatch]
    disclaimer: str

def match_cv_to_offer(cv_profile: dict[str, Any], intake_answers: dict[str, Any], job: dict[str, Any]) -> CVOfferMatch:
    ...

# career/cv_quality/action_generator.py
def generate_actions(matches: list[RequirementMatch], cv: dict[str, Any]) -> list[CVAction]:
    ...

# career/cv_quality/impact_scorer.py
def score_impact(actions: list[CVAction], matches: list[RequirementMatch], job: dict[str, Any]) -> list[CVAction]:
    ...
```

---

**Tu as tout. Lance-toi.** Branche `agent/spec-sk21-cv-offer-matching`, worktree dédié, 3 modules, tests (10 scénarios complets), rapport, push. Je relis et j'intègre. **Mission à plus forte valeur utilisateur finale.**