# MISSION SPEC-019 — ATS Keywords Intelligence (mots-clés pondérés par stage)

> **Priorité : P0** — Première pierre de l'adaptation CV/lettre. Worktree dédié.

## Contexte
Chaque stage a ses mots-clés : hard skills, soft skills, outils, méthodologies, langues.
Objectif : extraire et **pondérer** ces mots-clés (1) du texte de l'offre,
(2) des extraiteurs SK-17/18/19, (3) de la recherche internet SPEC-018, puis
**tester par consensus multi-IA** (SPEC-017 arena).

## Modules
```
career/keyword_extract.py      # extraction regulière + normalisation + dédup
career/keyword_scorer.py       # pondération: must-have/nice, fréquence, section
career/keyword_arena.py        # consensus multi-IA avec fixes mix spelen maelligentes
career/keyword_report.py       # rapport investsability + sortie HTML/JSON
tests/test_keywords.py (100+ style adversarial cvboost-08)
docs/agent-reports/SPEC-019-ATS_KEYWORDS.md
```

## Contrats
```python
@dataclass
class Keyword:
    term: str
    normalized: str
    category: Literal["hard_skill","soft_skill","tool","method","domain","language","certification"]
    weight: float                    # 0.0–1.0 pondération ATS
    kind: Literal["must","nice","implicit"]
    evidence_refs: list[str]         # où dans l'offre/web
    synonyms: list[str]

@dataclass
class KeywordProfile:
    offer_id: str
    keywords: list[Keyword]
    score_coverage: dict             # couverture profil actuel, par catégorie
    gaps: list[Keyword]              # dans l'offre, absent du profil → reformulables
    generated_at: str
```

## Algorithme poids
```
weight = 0.5*freq_offer + 0.2*is_in_title_or_requirements
       + 0.2*web_stack_confirm (SPEC-018) + 0.1*jury_boost (arena)
```
Seuil must/nice selon fréquence & locale titres; trois niveaux conservés.

## API
```
POST /keywords/extract/{offer_id}          # → KeywordProfile
GET  /keywords/{offer_id}/cookie           # adjusments changes des poids
PATCH/keywords/{offer_id}/weight           # ajuster poids à la main (traço)
```

## Validation
```bash
./checklist_codex.sh
.venv/bin/python -m pytest -q tests/test_keywords.py
.venv/bin/python -m pytest -q
git diff --check
```

## Critères de réussite
- [ ] Extraction tiling dente ses liste (offre texte, SK-17/18/19, web)
- [ ] 100+ tests adversarial (ne pas compter extra en keyword ce qui n'est pas offre)
- [ ] Couverture / gap report calculé vs profil SK-10 avec preuves d'offre
- [ ] Arena consensus détermine must/nice sans halluciner de skills du CV
- [ ] Ruff clean, suite verte, git diff --check + rapport SPEC-019

**Tu as tout. Lance-toi.** Branche `agent/spec-019-ats-keywords`, worktree dédié, code, tests, rapport, push.
