# SPEC-013 — Dépendances et Impact

## Livrable

Module transverse local-first : graphe de dépendances orienté, analyse d'impact pondérée, scénarios what-if, détection de cycles, centralité/fragilité, plans d'exécution, persistance versionnée et routes HTTP sous `/dependencies` et `/api/career/dependencies`. UI interactive dans la page Career (`career_static/js/dependencies.js`, `dependencies.css`).

## Fichiers créés/modifiés

- `career/dependencies.py` — core graphe, algorithmes (propagation, cycles Tarjan, betweenness, PageRank, articulation, plans)
- `career/dependencies_store.py` — persistance JSON atomique, versioning, snapshots, rollback, historique
- `career/impact_analysis.py` — application pure, simulation multi-changements, façade `ImpactEngine`
- `career/router.py` — endpoints graphe/impact/scénarios/plan/validation/snapshot/historique/rollback
- `career_static/js/dependencies.js`, `career_static/dependencies.css`, modifications `index.html`/`career.js`
- `tests/test_dependencies.py` — 61 tests synthétiques

## Validation

- `pytest -q tests/test_dependencies.py` → 61 passed
- `./checklist_codex.sh` → TOUT VERT (suite principale 1483 passed, 2 échecs env-dépendants préexistants)
- `ruff check .` → All checks passed
- `git diff --check` → clean

## Notes

- Aucun appel réseau ; déterministe.
- Les niveaux d'impact sont prudents (risques à vérifier, pas des certitudes).
- Intégration auto depuis `_career_dependency_payload` (SK-02, SK-10, SK-21, SK-11, SK-08).