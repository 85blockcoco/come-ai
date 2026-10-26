# CVBOOST-76 — SPEC-041 — Couche finance (lexique, FAQ, cases techniques)

**Branche :** `agent/spec-041-finance-layer` — **Worktree :** `AI-Excel-Agent-worker-cvboost-76-1793025523699`
**Statut :** ✅ Terminé — 56 tests hors-ligne verts, ruff propre.

## Livré

### 1. `career/finance_lexicon.py` — lexique finance versionné (`LEXICON_VERSION = "1.0.0"`)

- **Vocabulaire statique éditable** (littéraux Python, aucune logique cachée) :
  - 12 rôles canoniques → familles (`m&a`, `fpa`, `ecm_dcm`, `coverage`, `risk`, `quant`, `treasury`, `audit`, `lbo_pe`, `equity_research`), avec alias FR/EN et anglicismes réels des offres (« analyste m&a », « fusions acquisitions », « m & a »…).
  - 15 compétences (DCF, LBO, comps, merger model, Excel/VBA, Python/pandas, SQL, Bloomberg, S&P Capital IQ, modélisation, IFRS, BFR, valuation, FX, taux).
  - 4 certifications (CFA niveaux, ACCA, CAIA, PRM).
  - 13 places financières (Paris, Londres, Francfort, Luxembourg, New York, Genève, Zurich, Milan, Madrid, Amsterdam, Dubaï, Singapour, Hong Kong).
  - 14 anglicismes courants des offres françaises (sell-side, data room, term sheet, due diligence…).
- **API déterministe** (normalisation accent/casse via NFKD, déduplication par concept, tri stable) :
  - `expand(text) -> {matches, familles, counts}` — détection de vocabulaire finance pour le parsing offres/connecteurs et le minage FAQ (66).
  - `score_profile(profile_text, role) -> {role, coverage, present, missing, certifications}` — couverture du socle attendu par rôle (`ROLE_REQUIREMENTS`) pour le matching (21). `LookupError` si rôle inconnu — jamais de scoring contre un poste deviné.
  - `keywords_for(role) -> terms` — mots-clés ATS dédupliqués pour la retouche de CV (54).

### 2. `career/interview_finance.py` — banque ≥ 120 questions + simulateur local (`BANK_VERSION = "1.1.0"`)

- **122 questions** réparties 30/30/30/32 sur quatre familles — corporate/valorisation (DCF, comps, accretion, LBO), marchés (FX, taux, pricing), corporate finance (BFR, IFRS, comptabilité), behavioral (STAR, fit) — chacune bilingue FR/EN, taggée `stage`/`analyst`/`associate`, avec groupes de mots-clés de référence et points de référence.
- **`draw_sequence(role, seniority, count, seed)`** : tirage reproductible (graine explicite ou dérivée stable en SHA-256 — jamais `hash()` salé), pool plafonné à la séniorité demandée, séquence ordonnée du plus facile au plus difficile. Rôle inconnu ⇒ pool élargi (jamais de guess) ; `ROLE_QUESTION_FAMILIES` relie les familles du lexique aux familles de questions.
- **`score_answer(question, answer)`** : rubric 100 % locale et déterministe — complétude (couverture des groupes de référence, 50 %), structure (marqueurs de raisonnement + longueur, 30 %), précision (termes concrets + chiffres, 20 %). Retourne aussi `missing_keywords` et un `feedback` actionnable. **Aucune IA de notation externe, aucun appel réseau.**
- **`faq_entries(topic)`** : enregistrements plats prêts à consommer par le module FAQ (66) — l'intégration se fera côté module 66 (absent du commit de base de ce worktree).

## Contrat vérifié

| Exigence | Résultat |
|---|---|
| ≥ 50 tests hors-ligne, données statiques | ✅ 56 tests (`tests/test_finance_lexicon.py` : 24, `tests/test_interview_finance.py` : 32) |
| Pas d'appels réseau | ✅ testé (aucun import requests/urllib/socket/http) |
| Rubric déterministe | ✅ tests d'identité (même entrée ⇒ même score), poids figés 0.5/0.3/0.2 |
| Sources publiques générales, éditable par l'utilisateur | ✅ vocabulaire et questions en littéraux Python commentés, versionnés |
| Ruff | ✅ All checks passed |
| `git diff --check` | ✅ CLEAN |

## Logs

```
.venv/bin/python -m pytest -q tests/test_finance_lexicon.py tests/test_interview_finance.py
→ 56 passed in 2.10s
ruff check career/finance_lexicon.py career/interview_finance.py tests/*.py
→ All checks passed
```

Suite complète volontairement non lancée (interdiction du contrat de sortie : tests ciblés uniquement).

## Pistes d'intégration (hors périmètre de cette mission)

- Module 66 (FAQ) : consommer `faq_entries()` et brancher `expand()` sur le minage des offres finance.
- Module 21 (matching) : remplacer le scoring générique par `score_profile()` quand le secteur est finance.
- Module 54 (ATS) : injecter `keywords_for(role)` dans la liste de mots-clés du CV retouché.
