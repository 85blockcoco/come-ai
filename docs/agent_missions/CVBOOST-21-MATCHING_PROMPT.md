# MISSION AGENT — Mission 21 : Matching CV ↔ Offre (Actions concrètes)

> **Contexte** : L'utilisateur veut des conseils CV **ultra-ciblés** pour une offre précise. Le module doit prendre un CV analysé (Mission 01) + une offre (Mission 02) et produire des **actions concrètes** par exigence.
> Base : `main` (1469 tests verts). **Dépendances : Mission 01 (structure CV), Mission 02 (exigences offres)** — **satisfaites**.

---

## Périmètre autorisé

| Fichier | Rôle |
|---|---|
| `career/cv_quality/matching.py` | **Nouveau** — `match_cv_to_offer(cv_result, offer) -> MatchResult` |
| `career/cv_quality/models.py` | Étendre avec `MatchResult`, `MatchAction`, `MatchEvidence` |
| `career/cv_quality/__init__.py` | Exporter `match_cv_to_offer` |
| `tests/test_cv_matching_actions.py` | **Nouveau** — tests unitaires (≥ 20 cas) |
| `docs/agent-reports/CVBOOST-21-MATCHING.md` | Rapport obligatoire |

**Interdit** : `career/service.py`, `career/router.py`, `career_static/*`, `requirements*.txt`, migrations, `SCHEMA_VERSION`.

---

## Contraintes produit (non négociables)

1. **Fonction pure** : `match_cv_to_offer(cv_result: CVAnalysisResult, offer: dict) -> MatchResult` — déterministe, sans réseau, sans LLM.
2. **Entrée** : `CVAnalysisResult` (Mission 01) + `offer` dict (avec `requirements` extraits par Mission 02).
3. **Sortie `MatchResult`** — actions concrètes par exigence :

```python
# career/cv_quality/models.py — AJOUT
from dataclasses import dataclass
from typing import Literal, Optional

@dataclass
class MatchAction:
    code: Literal["HIGHLIGHT", "REPHRASE", "DO_NOT_ADD", "QUANTIFY", "CONFIRM_LANGUAGE"]
    requirement_text: str                    # Extrait EXACT de l'exigence offre
    cv_evidence_text: str | None             # Extrait EXACT du CV (sous-chaîne exacte)
    cv_evidence_offset: int | None           # Position dans le CV source
    cv_evidence_field: str | None            # "skills", "experience", "education", "languages", "projects"
    reason: str                              # Pourquoi cette action (phrase claire)
    confidence: float                        # 0.0-1.0

@dataclass
class MatchResult:
    overall_score: float                      # 0.0-1.0 (match global)
    matched_requirements: int                 # Nombre d'exigences avec evidence
    total_requirements: int                   # Total exigences offre
    actions: list[MatchAction]                # Une action PAR exigence
    missing_critical: list[str]               # Exigences obligatoires sans evidence
    warnings: list[str]                       # ["Alternance détectée", "Niveau M2 requis vs M1 CV", ...]
```

---

## Contraintes produit (non négociables)

1. **Fonction pure** — déterministe, sans réseau, sans LLM.
2. **Zéro invention** : `cv_evidence_text` doit être une **sous-chaîne EXACTE** du CV source (provenance exacte via `cv_result.provenance`).
4. **Une action PAR exigence** — chaque exigence de l'offre génère exactement une `MatchAction`.
5. **Codes d'action** (exhaustifs) :
   - `HIGHLIGHT` — le fait existe, le rendre plus visible (mots-clés, position)
   - `REPHRASE` — le fait existe, reformuler avec vocabulaire de l'offre
   - `DO_NOT_ADD` — **aucune evidence** dans le CV → "Ne pas ajouter sans preuve"
   - `QUANTIFY` — le fait existe mais sans chiffre → "Ajouter un chiffre prouvable"
   - `CONFIRM_LANGUAGE` — langue déclarée mais non prouvée → "À confirmer"
5. **Règle DO_NOT_ADD stricte** : si `cv_evidence_text is None` → `code = "DO_NOT_ADD"` et `reason` contient "Aucune preuve dans le CV, ne pas ajouter sans preuve".
6. **Provenance obligatoire** : chaque `HIGHLIGHT`/`REPHRASE`/`QUANTIFY` doit avoir `cv_evidence_text` non-None + `cv_evidence_offset` + `cv_evidence_field`.
7. **Warnings obligatoires** :
   - Alternance détectée dans l'offre → warning
   - Niveau d'études requis > CV → warning
   - Langue requise non prouvée → warning
   - Exigence obligatoire sans evidence → `missing_critical`
7. **Confiance** : 0.0-1.0 basée sur similarité textuelle + provenance.

---

## Algorithme (logique déterministe)

```python
def match_cv_to_offer(cv_result: CVAnalysisResult, offer: dict) -> MatchResult:
    requirements = offer.get("requirements", [])  # liste d'exigences extraites (Mission 02)
    actions = []
    missing_critical = []
    warnings = []
    
    for req in requirements:
        req_text = req.get("text", "")
        req_category = req.get("category", "skill")  # skill, language, education, experience, contract
        req_mandatory = req.get("mandatory", True)
        
        # 1. Chercher evidence exacte dans CV
        evidence = find_evidence_in_cv(cv_result, req_text)
        
        if evidence:
            # Evidence trouvée → déterminer action
            if needs_quantification(req_text, evidence):
                code = "QUANTIFY"
                reason = "Le fait existe mais sans chiffre. Ajouter un chiffre prouvable (ex: 'géré équipe de 10' au lieu de 'géré équipe')."
            elif needs_rephrase(req_text, evidence):
                code = "REPHRASE"
                reason = f"Reformuler avec le vocabulaire de l'offre : '{req_text}' au lieu de '{evidence.text[:50]}...'."
            else:
                code = "HIGHLIGHT"
                reason = "Le fait existe. Le rendre plus visible (mots-clés, en haut de section, en gras)."
            
            actions.append(MatchAction(
                code=code,
                requirement_text=req_text,
                cv_evidence_text=evidence.text,
                cv_evidence_offset=evidence.offset,
                cv_evidence_field=evidence.field,
                reason=reason,
                confidence=evidence.confidence
            ))
        else:
            # Aucune evidence → DO_NOT_ADD
            actions.append(MatchAction(
                code="DO_NOT_ADD",
                requirement_text=req_text,
                cv_evidence_text=None,
                cv_evidence_offset=None,
                cv_evidence_field=None,
                reason="Aucune preuve dans le CV, ne pas ajouter sans preuve.",
                confidence=1.0
            ))
            if req_mandatory:
                missing_critical.append(req_text)
    
    # Warnings transverses
    if offer.get("contract_type") == "alternance":
        warnings.append("Alternance détectée — vérifie que ton brief exclut l'alternance.")
    if offer.get("education_level") and cv_result.education_max_level < offer.get("education_level"):
        warnings.append(f"Niveau d'études requis ({offer['education_level']}) > CV ({cv_result.education_max_level}).")
    
    # Score global
    matched = sum(1 for a in actions if a.code != "DO_NOT_ADD")
    overall_score = matched / len(requirements) if requirements else 0.0
    
    return MatchResult(
        overall_score=overall_score,
        matched_requirements=matched,
        total_requirements=len(requirements),
        actions=actions,
        missing_critical=missing_critical,
        warnings=warnings
    )
```

---

## Fonction `find_evidence_in_cv` (déterministe)

```python
def find_evidence_in_cv(cv_result: CVAnalysisResult, requirement: str) -> Evidence | None:
    # 1. Normaliser requirement (mots-clés, synonymes)
    keywords = extract_keywords(requirement)
    
    # 2. Chercher dans sections CV (skills, experience, education, languages, projects)
    for section in cv_result.sections:
        for kw in keywords:
            if kw.lower() in section.content_preview.lower():
                # Trouver offset exact dans le texte source
                offset = cv_result.provenance.full_text.lower().find(kw.lower())
                if offset >= 0:
                    return Evidence(
                        text=cv_result.provenance.full_text[offset:offset+100],
                        offset=offset,
                        field=section.title.lower(),
                        confidence=0.9
                    )
    
    # 3. Chercher dans experiences (descriptions)
    for exp in cv_result.experiences:
        for kw in keywords:
            if kw.lower() in exp.description.lower():
                offset = cv_result.provenance.full_text.lower().find(exp.description[:50].lower())
                if offset >= 0:
                    return Evidence(
                        text=exp.description[:150],
                        offset=offset,
                        field="experience",
                        confidence=0.8
                    )
    
    return None
```

---

## Tests obligatoires (≥ 20)

| Test | Description |
|---|---|
| `test_highlight_exact_match` | Exigence "Python" + CV a "Python" → HIGHLIGHT, evidence exacte |
| `test_rephrase_synonym` | Exigence "Gestion de projet" + CV "Management de projet" → REPHRASE |
| `test_quantify_missing_number` | Exigence "Géré équipe 10+" + CV "Géré équipe" → QUANTIFY |
| `test_do_not_add_absent` | Exigence "AWS" absent du CV → DO_NOT_ADD, reason "Aucune preuve..." |
| `test_missing_critical` | Exigence mandatory sans evidence → dans `missing_critical` |
| `test_warning_alternance` | Offre alternance → warning "Alternance détectée" |
| `test_warning_education_gap` | Offre M2 requis + CV M1 → warning niveau études |
| `test_multiple_requirements` | 5 exigences → 5 actions, score = matched/5 |
| `test_evidence_provenance_exact` | Evidence text = sous-chaîne exacte CV, offset correct |
| `test_confidence_scoring` | Match exact = 0.9+, match approximatif = 0.6-0.8 |
| `test_no_invention` | Jamais de cv_evidence_text inventé (sous-chaîne CV) |
| `test_confidence_do_not_add` | DO_NOT_ADD → confidence = 1.0 |
| `test_critical_vs_optional` | Optional missing → pas dans missing_critical |
| `test_language_warning` | Anglais requis, CV sans preuve anglais → warning langue |

---

## Commandes de validation

```bash
./checklist_codex.sh
.venv/bin/python -m pytest -q tests/test_cv_matching_actions.py
.venv/bin/python -m pytest -q
git diff --check
```

---

## Critères de validation (relecteur)

- [ ] `match_cv_to_offer()` pure, déterministe, sans réseau
- [ ] Une action PAR exigence (code, evidence exacte ou DO_NOT_ADD)
- [ ] Evidence = sous-chaîne EXACTE du CV + offset + field
- [ ] DO_NOT_ADD pour toute exigence sans evidence (reason standard)
- [ ] Warnings : alternance, niveau études, langue
- [ ] Score global = matched/total
- [ ] Ruff clean, 1469+ tests passent, `git diff --check` propre
- [ ] Rapport `CVBOOST-21-MATCHING.md` avec exemples matching

---

## Squelette minimal (copier-coller)

```python
# career/cv_quality/models.py — AJOUT
from dataclasses import dataclass
from typing import Literal, Optional

@dataclass
class MatchAction:
    code: Literal["HIGHLIGHT", "REPHRASE", "DO_NOT_ADD", "QUANTIFY", "CONFIRM_LANGUAGE"]
    requirement_text: str
    cv_evidence_text: str | None
    cv_evidence_offset: int | None
    cv_evidence_field: str | None
    reason: str
    confidence: float

@dataclass
class MatchResult:
    overall_score: float
    matched_requirements: int
    total_requirements: int
    actions: list[MatchAction]
    missing_critical: list[str]
    warnings: list[str]

# career/cv_quality/matching.py
def match_cv_to_offer(cv_result: CVAnalysisResult, offer: dict) -> MatchResult:
    # Implémentation déterministe (voir algo ci-dessus)
    ...
```

---

**Tu as tout. Lance-toi.** Branche `agent/cvboost-21-matching`, worktree dédié, code, tests, rapport, push. Je relis et j'intègre. **Mission CŒUR DE VALEUR — conseils CV ultra-ciblés par offre.**