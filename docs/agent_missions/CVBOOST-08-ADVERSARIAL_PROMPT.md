# MISSION AGENT — Mission 08 : Banc adversarial matching CV/offre (100+ cas)

> **Contexte** : Le matching CV/offre doit être robuste aux faux positifs. Il faut un banc de 100+ couples synthétiques CV/offre couvrant les cas limites critiques.
> Base : `main` (tag `v3-cvboost-sources-2026-10-20`), 1469 tests verts.
> Dépendances : **Mission 01** (structure CV), **Mission 02** (exigences offres) — **satisfaites**.

---

## Périmètre autorisé

| Fichier | Rôle |
|---|---|
| `career/cv_quality/matching.py` | **Nouveau** — `match_cv_to_offer(cv_result, offer) -> MatchResult` |
| `career/cv_quality/models.py` | Étendre avec `MatchResult`, `MatchAction`, `MatchEvidence` |
| `career/cv_quality/__init__.py` | Exporter `match_cv_to_offer` |
| `tests/test_cv_matching_adversarial.py` | **Nouveau** — 100+ cas de test adversariaux |
| `docs/agent-reports/CVBOOST-08-ADVERSARIAL.md` | Rapport obligatoire |

**Interdit** : `career/service.py`, `career/router.py`, `career_static/*`, `requirements*.txt`, migrations, `SCHEMA_VERSION`.

---

## Contraintes produit (non négociables)

1. **Fonction pure** : `match_cv_to_offer(cv_result, offer) -> MatchResult` — déterministe, sans réseau, sans LLM.
2. **100+ couples adversariaux** couvrant (minimum) :
   - **Excel vs Analyse financière** — "Excel avancé" ≠ "Analyse financière" (faux positif fréquent)
   - **Java vs JavaScript** — confusion fréquente sur "Java"
   - **Langue déclarée vs programme enseigné** — "Anglais courant" vs "Programme en anglais"
   - **Stage vs CDI** — offres "Stage 6 mois" vs "CDI" ne doivent pas matcher
   - **Alternance exclue** — offres "Alternance" doivent être rejetées si brief exclut
   - **M1 vs M2 vs Bachelor** — niveau d'études précis requis
   - **Mot nié** — "pas de gestion d'équipe" dans offre → CV avec "gestion d'équipe" = match mais attention
   - **Compétence seulement dans l'offre** — exigence absente du CV → action "Ne pas ajouter sans preuve"
   - **Acronymes** — "M&A" = "Fusion-Acquisition", "PE" = "Private Equity"
   - **Homonymes** — "Audit" (financier) vs "Audit" (informatique)
   - **Profil multilingue** — CV FR/EN, offre EN → match si compétences transposables
3. **Sortie `MatchResult`** structurée :
   ```python
   @dataclass
   class MatchAction:
       code: Literal["HIGHLIGHT", "REPHRASE", "DO_NOT_ADD", "QUANTIFY", "CONFIRM_LANGUAGE"]
       requirement_text: str           # Extrait exact de l'offre
       cv_evidence_text: str | None    # Extrait exact du CV (ou None)
       cv_evidence_offset: int | None  # Position dans le CV
       reason: str                     # Pourquoi cette action
       confidence: float               # 0.0-1.0
   
   @dataclass
   class MatchResult:
       overall_score: float            # 0.0-1.0
       matched_requirements: int
       total_requirements: int
       actions: list[MatchAction]
       missing_critical: list[str]     # Exigences obligatoires non couvertes
       warnings: list[str]             # Avertissements (ex: "Alternance détectée")
   ```
4. **Zéro invention** : chaque `cv_evidence_text` doit être un sous-chaîne EXACTE du CV (provenance exacte).
5. **Règle "DO_NOT_ADD"** : si aucune evidence CV pour une exigence → action `DO_NOT_ADD` avec raison "Aucune preuve dans le CV, ne pas ajouter sans preuve".

---

## 100+ cas de test (structure)

Chaque cas = `dict` avec :
```python
{
    "id": "ADV-001",
    "name": "Excel vs Analyse financière",
    "cv_text": "...",
    "offer_requirements": ["Excel avancé", "Modélisation financière"],
    "expected_actions": [
        {"code": "HIGHLIGHT", "requirement": "Excel avancé", "cv_evidence": "Excel avancé"},
        {"code": "REPHRASE", "requirement": "Analyse financière", "cv_evidence": "Modélisation financière"},
    ],
    "expected_score_range": (0.6, 0.8),
    "expected_warnings": []
}
```

### Catégories minimales (10 cas par catégorie = 100+)

| Catégorie | Exemples |
|---|---|
| **Compétences techniques proches** | Excel/Analyse, Java/JS, Python/R, SQL/NoSQL, AWS/Azure/GCP |
| **Langues** | "Courant" vs "Lu/Écrit/Parlé", "Programme en anglais" vs "Anglais courant" |
| **Types de contrat** | Stage vs CDD vs CDI vs Alternance vs VIE vs Freelance |
| **Niveaux d'études** | Bac+3 vs Bac+5, M1 vs M2, Bachelor vs Master, PhD |
| **Négation** | "Pas de gestion", "Sans déplacement", "Pas de télétravail" |
| **Compétence absente** | Exigence 100% absente du CV → DO_NOT_ADD |
| **Acronymes/synonymes** | M&A/Fusion-Acquisition, PE/Private Equity, IB/Investment Banking |
| **Homonymes sectoriels** | Audit financier vs Audit IT, Risk management vs Risk IT |
| **Multilingue** | CV FR/EN, offre EN/FR, compétences transposables |
| **Quantification** | "Géré équipe 10p" vs "Expérience management" → QUANTIFY |

---

## Commandes de validation

```bash
./checklist_codex.sh
.venv/bin/python -m pytest -q tests/test_cv_matching_adversarial.py
.venv/bin/python -m pytest -q
git diff --check
```

---

## Critères de validation (relecteur)

- [ ] `match_cv_to_offer()` pure, déterministe, sans réseau
- [ ] 100+ cas de test passent (précision/rappel sur vérité connue)
- [ ] Faux positifs historiques éliminés (Excel≠Analyse, Java≠JS, Stage≠CDI, etc.)
- [ ] Règle DO_NOT_ADD respectée (aucune invention)
- [ ] Preuve exacte (sous-chaîne CV) pour chaque action HIGHLIGHT/REPHRASE/QUANTIFY
- [ ] Warnings pour alternance, négations, langues
- [ ] Ruff clean, 1469+ tests passent, `git diff --check` propre
- [ ] Rapport `CVBOOST-08-ADVERSARIAL.md` avec matrice de confusion, cas limites

---

## Squelette minimal (copier-coller)

```python
# career/cv_quality/models.py — AJOUT
from dataclasses import dataclass
from typing import Literal

@dataclass
class MatchAction:
    code: Literal["HIGHLIGHT", "REPHRASE", "DO_NOT_ADD", "QUANTIFY", "CONFIRM_LANGUAGE"]
    requirement_text: str
    cv_evidence_text: str | None
    cv_evidence_offset: int | None
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
from __future__ import annotations
from career.cv_quality.models import CVAnalysisResult, MatchResult, MatchAction

def match_cv_to_offer(cv_result: CVAnalysisResult, offer: dict) -> MatchResult:
    # 1. Extraire exigences de l'offre (réutiliser offer_qualification.extract_requirements)
    # 2. Pour chaque exigence:
    #    - Chercher evidence exacte dans cv_result (sections, experiences, skills)
    #    - Si trouvée: HIGHLIGHT / REPHRASE / QUANTIFY
    #    - Si non trouvée: DO_NOT_ADD (reason: "Aucune preuve dans le CV")
    #    - Détecter: langue, négation, alternance, niveau études, quantification
    # 3. Calculer score global, warnings, missing_critical
    # 4. Retourner MatchResult
    ...
```

---

**Tu as tout. Lance-toi.** Branche `agent/cvboost-08-adversarial`, worktree dédié, code, tests (100+ cas), rapport, push. Je relis et j'intègre. **Mission critique pour la fiabilité du matching.**