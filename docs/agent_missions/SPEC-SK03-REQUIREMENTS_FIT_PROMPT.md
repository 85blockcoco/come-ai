# MISSION SPEC KIT — SK-03 : Adéquation prérequis ↔ profil approuvé

> **Priorité : P0** — Module indépendant, worktree dédié, peut tourner en parallèle SK-01/SK-02/SK-04

---

## Contexte

L'analyseur `career.offer_requirements.analyze_offer()` existe déjà et est le **contrat canonique** pour les exigences. Il faut le réutiliser et comparer ses exigences aux faits approuvés du profil candidat.

---

## Interdiction importante

❌ **NE PAS créer un nouvel extracteur de prérequis.** L'analyseur `offer_requirements` est déjà le contrat canonique.

---

## Nouveau module à créer

```
career/requirements_fit.py
tests/test_requirements_fit.py
tests/fixtures/requirements_fit/
```

---

## Verdicts par exigence

| Verdict | Sémantique |
|---------|------------|
| `supported` | Preuve exacte dans profil approuvé |
| `unsupported` | Aucune preuve, exigence non couverte |
| `contradicted` | Profil contredit l'exigence (ex: "pas de gestion" vs "gestion d'équipe") |
| `to_verify` | Info absente du profil = à vérifier, **PAS** incompatible |
| `not_applicable` | Exigence non pertinente pour ce profil |

---

## Modalités à conserver (depuis offer_requirements)

- `mandatory` — obligatoire
- `preferred` — préférée
- `contextual` — contextuelle
- `unknown` — inconnue

---

## Catégories minimales à couvrir

1. Niveau d'études
2. Expérience
3. Compétences techniques
4. Outils
5. Langues
6. Mobilité
7. Autorisation de travail
8. Disponibilité
9. Date de diplomation

---

## Règles essentielles

1. **Absent ≠ Incompatible** — Information absente du profil → `to_verify`
2. **"Master preferred" ne rejette jamais** automatiquement Bachelor ou M1
3. **"Master 2 required"** traité séparément de la compatibilité générale
4. **OCR non approuvé ≠ Preuve** — Seuls faits approuvés comptent
5. **Citations croisées** — Chaque correspondance cite exigence offre + fait profil
6. **Isolation** — Aucune donnée profil ajoutée au snapshot public de l'offre

---

## Contrat attendu

```python
# career/requirements_fit.py
from __future__ import annotations
from dataclasses import dataclass
from typing import Literal

@dataclass
class RequirementFit:
    requirement_id: str           # ID depuis offer_requirements
    requirement_text: str         # Texte exact exigence
    modality: Literal["mandatory", "preferred", "contextual", "unknown"]
    category: str                 # études, expérience, tech, outils, langues, mobilité, auth_travail, dispo, diplomation
    verdict: Literal["supported", "unsupported", "contradicted", "to_verify", "not_applicable"]
    profile_evidence: str | None  # Extrait exact profil approuvé (ou None)
    evidence_offset: int | None   # Position dans profil
    reason: str                   # Explication lisible
    confidence: float             # 0.0-1.0

@dataclass
class FitResult:
    fits: list[RequirementFit]
    supported_count: int
    unsupported_count: int
    to_verify_count: int
    contradicted_count: int
    overall_score: float          # 0.0-1.0
    missing_critical: list[str]   # Exigences mandatory non supported
```

---

## Commandes de validation

```bash
./checklist_codex.sh
.venv/bin/python -m pytest -q tests/test_requirements_fit.py
.venv/bin/python -m pytest -q
git diff --check
```

---

## Critères de réussite

- [ ] `requirements_fit.analyze_fit(offer_requirements, approved_profile) -> FitResult` pure, déterministe
- [ ] Réutilise `offer_requirements.analyze_offer()` — **pas de nouvel extracteur**
- [ ] 5 verdicts, 4 modalités, 9 catégories minimales
- [ ] Règle "absent = to_verify" respectée
- [ ] "Master preferred" n'exclut pas Bachelor/M1
- [ ] OCR non approuvé ignoré
- [ ] Citations croisées exigence↔fait pour chaque `supported`
- [ ] Fixtures synthétiques: 30+ cas couvrant toutes catégories/verdicts
- [ ] Ruff clean, suite complète verte, `git diff --check` propre
- [ ] Rapport `docs/agent-reports/SPEC-SK03-REQUIREMENTS_FIT.md`

---

## Squelette minimal

```python
# career/requirements_fit.py
from __future__ import annotations
from career.offer_requirements import analyze_offer, OfferRequirement
from career.candidate_profile import ApprovedProfile  # existant ou à définir

def analyze_fit(offer: dict, approved_profile: ApprovedProfile) -> FitResult:
    # 1. Extraire exigences canoniques
    requirements = analyze_offer(offer)
    # 2. Pour chaque exigence:
    #    - Chercher evidence exacte dans approved_profile (sections, experiences, skills, education, languages, etc.)
    #    - Si trouvée: supported + citation exacte
    #    - Si contredite (négation dans offre vs présence profil): contradicted
    #    - Si absente: to_verify (PAS unsupported)
    #    - Appliquer règles: Master preferred, OCR, etc.
    # 3. Agréger comptages, score global, missing_critical
    # 4. Retourner FitResult
    ...
```

---

**Tu as tout. Lance-toi.** Branche `agent/spec-sk03-requirements-fit`, worktree dédié, code, tests (30+ cas), rapport, push. Je relis et j'intègre.