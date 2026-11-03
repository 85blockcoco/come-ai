# MISSION AGENT — Mission 04 : Contrôle ATS local PDF/DOCX

> **Contexte** : l'utilisateur exporte son CV/lettre en PDF ou DOCX — l'app doit **analyser le fichier généré** pour détecter les risques ATS (Applicant Tracking System) **sans jamais appeler de service distant**.
> Base : `main` (tag `v3-cvboost-sources-2026-10-20`), 1269 tests verts.
> Dépendances : **Mission 01** (structure CV) fournie en amont — le module `cv_quality.parser` et `cv_quality.models` existent.

---

## Périmètre autorisé

| Fichier | Rôle |
|---|---|
| `career/cv_quality/ats.py` | **nouveau** — `run_ats_check(document: DocumentInput) -> ATSCheckResult` |
| `career/cv_quality/parser.py` | **existant (Mission 01)** — extraction texte + structure (réutiliser) |
| `career/cv_quality/models.py` | **existant** — étendre avec `ATSCheckResult`, `ATSFinding`, `ATSRiskLevel` |
| `career/cv_quality/__init__.py` | exporter `run_ats_check` |
| `tests/test_cv_quality_ats.py` | **tests unitaires** (fixtures PDF/DOCX synthétiques) |
| `docs/agent-reports/CVBOOST-04-ATS.md` | rapport obligatoire |

**Interdit** : `career/service.py`, `career/router.py`, `career_static/*`, `requirements*.txt`, migrations, `SCHEMA_VERSION`.

---

## Contraintes produit (non négociables)

1. **100 % local** : aucun appel réseau, aucun LLM, aucune clé. `pypdf`, `python-docx`, `pdfplumber` (si ajouté à requirements — **pas pour cette mission**, utilise l'existant).
2. **Vocabulaire prudent** : le système parle de **risque ATS**, **jamais** de "rejet certain". Aucun binaire "pass/fail".
3. **Détections obligatoires** (chaque = un `ATSFinding` avec `risk_level: Literal["LOW","MEDIUM","HIGH"]`, `message`, `page`, `bbox` approximative, `evidence_excerpt`) :
   - **Ordre de lecture problématique** : flux de texte non linéaire (colonnes, encadrés, en-têtes/pieds de page lus au milieu) — heuristique : sauts de `y` non monotones > 2 fois par page.
   - **Texte dans images** : page PDF avec texte extractible < 50 % de la surface OU présence d'`/XObject` image sans `/Text` adjacent → `HIGH`.
   - **Tableaux imbriqués** : détection de structures tabulaires (grilles alignées, `pdfplumber` tables) → `MEDIUM` (peut casser l'extraction).
   - **Colonnes multiples** : détection de > 1 colonne de texte par page (largeur < 60 % page) → `MEDIUM`.
   - **En-têtes/pieds de page** : texte répété en haut/bas de ≥ 2 pages consécutives (même `y`, même contenu) → `LOW` (pollution extraction).
   - **Caractères décoratifs / ligatures** : glyphes non-ASCII non mappés (ﬁ, ﬂ, •, ◆, ►, etc.) → `LOW`.
   - **Liens peu lisibles** : URL complète visible dans le texte au lieu d'ancre → `LOW`.
   - **Sections introuvables** : mots-clés de section attendus (Expérience, Formation, Compétences...) **absents** du texte extrait → `HIGH` (structure invisible pour ATS).
   - **Fichiers chiffrés / malformés** : PDF protégé par mot de passe, DOCX corrompu → `HIGH` + `error: "PARSE_ERROR"`.
4. **Score global** : `ats_risk_score` 0–100 (pondéré par `risk_level` : LOW=5, MEDIUM=20, HIGH=50, somme plafonnée à 100). **Interprétation fournie** : "Faible risque", "Risque modéré — relecture conseillée", "Risque élevé — restructuration recommandée".
5. **Entrée** : `DocumentInput` (réutilise Mission 01) + optionnel `expected_sections: list[str]` (sections attendues par l'utilisateur).
6. **Sortie** : `ATSCheckResult(findings: list[ATSFinding], risk_score: int, risk_label: Literal["LOW","MEDIUM","HIGH"], pages_analyzed: int, parse_errors: list[str])`.
7. **Tests** : fixtures **synthétiques** — PDF 1 colonne propre, PDF 2 colonnes, PDF avec tableau, PDF image-only, PDF chiffré, DOCX propre, DOCX avec colonnes, DOCX tableau imbriqué. 12+ cas.
8. **Performance** : ≤ 3 s par fichier ≤ 5 pages sur Mac Intel.

---

## Commandes de validation

```bash
./checklist_codex.sh
/Users/comedelavenne/AI-Excel-Agent/.venv/bin/python -m pytest -q tests/test_cv_quality_ats.py
/Users/comedelavenne/AI-Excel-Agent/.venv/bin/python -m pytest -q
git diff --check
```

---

## Critères de validation (relecteur)

- [ ] `run_ats_check()` pure, déterministe, sans réseau.
- [ ] 9 détecteurs + score pondéré + label.
- [ ] Chaque `ATSFinding` a `risk_level`, `page`, `evidence_excerpt` vérifiable.
- [ ] Gestion erreurs parse (chiffré, corrompu) → finding `HIGH` + `error`.
- [ ] Tests synthétiques ≥ 12 (chaque détecteur + combinés).
- [ ] Suite globale ≥ 1269 tests.
- [ ] Rapport avec exemples de détection sur PDF/DOCX synthétiques.
- [ ] Branche `agent/cvboost-04-ats` prête.

---

## Squelette minimal

```python
# career/cv_quality/models.py (extension)
from __future__ import annotations
from dataclasses import dataclass
from typing import Literal

@dataclass
class ATSFinding:
    code: str
    risk_level: Literal["LOW", "MEDIUM", "HIGH"]
    message: str
    page: int
    bbox: tuple[float, float, float, float] | None  # (x0, y0, x1, y1) en points PDF
    evidence_excerpt: str

@dataclass
class ATSCheckResult:
    findings: list[ATSFinding]
    risk_score: int  # 0-100
    risk_label: Literal["LOW", "MEDIUM", "HIGH"]
    pages_analyzed: int
    parse_errors: list[str]

# career/cv_quality/ats.py
from __future__ import annotations
from career.cv_quality.models import DocumentInput, ATSFinding, ATSCheckResult
from career.cv_quality.parser import extract_text_and_structure

def run_ats_check(document: DocumentInput, *, expected_sections: list[str] | None = None) -> ATSCheckResult:
    # 1. extract_text_and_structure(document) -> pages: list[Page] (texte, blocs, images, tables)
    # 2. pour chaque page, lancer les 9 détecteurs
    # 3. agréger findings, calculer risk_score, risk_label
    # 4. retourner ATSCheckResult
    ...
```

---

**Tu as tout. Lance-toi.** Branche `agent/cvboost-04-ats`, worktree dédié, code, tests, rapport, push. Je relis et j'intègre **après Mission 01** (dépendance parser/models).