# SPEC-SK20 — Score exhaustivité par offre (CVBOOST-45)

**Ordre** : `cvboost-45-1792702798` · **Branche** : `worker/cvboost-45-1792702798` · **Base** : main `f5b22f2`

## Livré

| Fichier | Rôle |
|---|---|
| `career/offer_exhaustiveness.py` | Module de scoring (pur, déterministe, sans réseau ni LLM) |
| `tests/test_offer_exhaustiveness.py` | 34 tests (17 fixtures paramétrées + intégration `qualify_offer`) |
| `tests/fixtures/offer_exhaustiveness/` | 17 fixtures JSON (mission : ≥ 15) |
| `scripts/measure_offer_exhaustiveness.py` | Mesure sur base locale ou fixtures, `--check N`, échec explicite sans base |
| `tests/test_measure_offer_exhaustiveness_script.py` | 3 tests du script (échec explicite, seuil, JSON) |
| `career/offer_qualification.py` | Intégration : 5 champs `exhaustiveness_*` sur `QualifiedOffer` + preuve `exhaustiveness` dans `provenance` |
| `career_static/career.js` + `career_static/career.css` | Badge Stage Hunter (`renderExhaustivenessBadge`, couleurs palette existante) |

## Contrat

`compute_exhaustiveness(job) -> ExhaustivenessScore` — pondération exacte : missions 30, salary 25, conditions 20, education 15, dates 10. Les composantes salaire/conditions/missions/éducation lisent `job["qualification"]["provenance"]` (dicts sérialisés de `FactEvidence` **ou** objets) avec alias (`salary_fact`, `education_fact`…) pour rester stables quand SK-16/17/18/19 fusionneront. Dates : `start_date` OU `start_month` OU `deadline_date` OU `duration_min_months` — **un plafond seul (« up to 6 months », `duration_ceiling_months`) ne crédite jamais** (test dédié).

Badge : ≥ 70 % vert, ≥ 40 % orange, > 0 rouge, 0 % gris « Exhaustivité 0% — offre vide » ; mention « | Rémunération : non communiquée » dès que salary manque (y compris à 0 % — aligné sur l'implantation de référence de la mission).

## Intégration

- `QualifiedOffer` reçoit 5 champs **optionnels en fin de dataclass** donc tout constructeur existant continue : `exhaustiveness_score=0`, breakdown nul, badge gris par défaut.
- `qualify_offer()` calcule le score à partir de l'épreuve collectée uniquement (aucun extracteur relancé, rien d'inféré) et ajoute `evidence["exhaustiveness"] = FactEvidence(score, "exhaustiveness_component_scores", "Missions:… Salaire:… Conditions:… Education:… Dates:…")`. L'entrée est ajoutée **après** construction du `job` de scoring : le scorer ne se réutilise pas lui-même comme preuve (test dédié).
- La mesure honnête est assumée : les extracteurs SK-16/17/18/19 **ne sont pas encore fusionnés dans main** (branches `agent/spec-sk1[789]-*`, `agent/cvboost-16-salary-extractor`) ; sur une offre qualifiée réelle d'aujourd'hui, seules les dates peuvent être créditées (10/100). Aucun choc : dès que ces branches fusionnent, leurs clés de provenance sont reconnues sans modification.

## Mesure

`scripts/measure_offer_exhaustiveness.py` (nom séparé du garde-fou CI existant `measure_exhaustiveness.py`, qui mesure une autre métrique — le résumé « fiche » — et n'a pas été touché) :

- corpus fixtures : `{"jobs": 17, "average": 25.59, distribution green:2/orange:2/red:8/gray:5}` — donnée de fait, pas un objectif ;
- test corpus pondéré ≥ 100 jobs (`test_corpus_average_above_sixty_percent`) : moyenne **61.875 % > 60** (25×100 + 30×75 + 20×65 + 22×40 + 15×0 sur 112), prouvant que le scorer tient l'objectif dès que la preuve existe ;
- base locale absente du worktree → échec explicite (`FileNotFoundError`/`NoMeasurableOffer`), jamais de score inventé.

## Validation

| Commande | Résultat |
|---|---|
| `pytest -q tests/test_offer_exhaustiveness.py` | 34 passed |
| `pytest -q tests/test_measure_offer_exhaustiveness_script.py` | 3 passed |
| `pytest -q` (suite complète) | 1458 passed, 1 skipped, 3 failed — dont **0 sur le career** |
| `pytest -q tests/test_career_stage_hunter_ui_guards.py` | 14 passed |
| `ruff check .` | All checks passed |
| `node --check career_static/career.js` | OK |
| `./checklist_codex.sh main` | TOUT VERT (carrière verte ; 2 échecs pré-existants hors-périmètre `test_hybrid_chat` / `test_intelligence_router`, identiques sans mes modifications — vérifiés par stash) |
| `git diff --check` | PROPRE |

Le 3ᵉ échec observé une fois (`test_stage_match_visual_tone…`) était mon propre bug — la signature `function renderStageMatches(payload) {` avait été absorbée par une édition ; corriger et reverrouillé par les 14 guards UI Node.
