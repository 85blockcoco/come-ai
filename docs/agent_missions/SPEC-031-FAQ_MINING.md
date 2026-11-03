# MISSION SPEC-031 — Minage FAQ sectorielle des offres

> **Priorité : P2** — Lot nocturne 2 (post-SPEC-024). Worktree dédié, push sur branche `agent/spec-031-sector-faq`.

## Contexte
App Career / CVBoost : le dossier (SK-01..SK-11, SPEC-004..024) fournit la pipeline offre→CV→lettre→suivi.
Les offres scindées en base contiennent des formulations répétitives (attentes, outils, contraintes de stage).

## Mission
Extracteur qui regroupe les attentes par secteur/famille de poste et produit une FAQ sectorielle : questions probables + éléments de réponse issus des preuves du profil.

## Modules (nouveaux, sans conflit avec les autres specs)
```
career/faq_mining.py             # mine_sector_faq(), cluster_intents(), expected_questions()
tests/test_faq_mining.py
tests/fixtures/faq_offers_synthetic.json
```

## Contrats Python (must-have)
```python
@dataclass
class SectorFaq:
    sector: str
    top_terms: list[tuple[str, int]]      # (terme, fréquence)
    likely_questions: list[str]
    profile_answers: dict[str, list[str]] # q -> éléments de réponse du profil
```

## Règles
- Données : **fixtures synthétiques uniquement** (`tests/fixtures/*synthetic*.json`). Aucune donnée réelle.
- Tests : `.venv/bin/python -m pytest` → suite complète verte + `ruff check .` propre.
- Jamais de clé/secrets en dur ; tout via `os.environ`.
- API : routes REST via le pattern `create_app()` de `career/router.py`, sans casser `schema_version=7`.
- Clustering déterministe (aucun appel réseau) ; fréquences vérifiées par test sur fixture.

## Livrables
1. Code modules + tests (cas limites + au moins 1 test adversarial).
2. Endpoints REST servis via `create_app()` (smoke test obligatoire).
3. Rapport `docs/agent-reports/SPEC-031-faq_mining.md` (livré, décisions, limites).
4. Push UNIQUEMENT sur la branche `agent/spec-031-sector-faq` (jamais main).
