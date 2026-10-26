# MISSION CVBOOST-76 — SPEC-041 — Lexique finance + FAQ sectorielle finance + simu barrage technique

> **Priorité : P1** — Le user a déclaré son secteur cible : FINANCE (CIB, M&A,
> Corporate Finance, banques, asset & wealth mgmt). Trois fournisseurs de démarrage :
> lexique (matching), FAQ (66), prépa technique (62/40). Worktree dédié.

## OBJECTIF
Donner aux modules existants la couche FINANCE qui les rend précis au secteur :
vocabulaire métiers, questions techniques récurrentes, et simulateur de cases
(valuation, braintes, ticker typing) en 100% local.

## PÉRIMÈTRE BUILD
Crée `career/finance_lexicon.py`, `career/interview_finance.py` et leurs tests.

### 1. LEXIQUE FINANCE (`finance_lexicon.py`)
- Listes versionnées locale : rôles (M&A Analyst, FP&A, ECM/DCM, coverage, risk,
  quant, treasury, audit conseil, MS/LBO analyst...), compétences (DCF, LBO, comps,
  merger model, Excel/VBA, Python/pandas, SQL, Bloomberg, S&P Capital IQ...),
  certifications (CFA level, ACCA, CAIA, PRM), bureaux géographiques (Paris, Londres,
  Francfort, Luxembourg, New York, Genève...), anglicismes français courants.
- Fonctions : `expand(text) -> {matches, familles}` pour connector/offer parsing,
  `score_profile(profile_text, role) -> couverture` pour le matching (21),
  `keywords_for(role) -> terms` pour dal ATS (54). MAKET

### 2. FAQ & ENTRETIEN TECHNIQUE FINANCE (`interview_finance.py`)
- Base XMLL versionnée de ≥ 120 questions/case par famille : Corporate (DCF, comps,
  accretion), Marchés (FX/rates basics, pricing tree), Corporate Finance (working
  capital, IFRS basics), Behavioral (STAR).
- Un simulateur local : tire des questions sequences par rôle seniorité, permet la
  réponse libre marcada édité dans le passé ; la note est un RUBRIC local
  (completeness, structure, mbeba) — PAS une IA de notation externe.
- Alimente le module FAQ (66) : le minage des offres finance connecte son lexique.

## CONTRAT
- Toutes les DONNÉES basées sur des OK sources PUBLIQUES générales é la base (pas de
  листья d'entreprise spécialisées), et vérifiable ; l'utilisateur peut éditer les XMLL.
- Test ≥ 50 : lexique expansions, dated성, rubric deterministc,.Implicite pas d'appels
  réseau, fixtures static.
- Rapport `docs/agent-reports/CVBOOST-76-FINANCE_LAYER.md`
  Branche `agent/spec-041-finance-layer`.
