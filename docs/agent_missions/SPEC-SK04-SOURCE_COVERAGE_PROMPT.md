# MISSION SPEC KIT — SK-04 : Couverture et santé des sources

> **Priorité : P1** — Module indépendant, worktree dédié, peut tourner en parallèle SK-01/SK-02/SK-03

---

## Contexte

Afficher des statistiques exactes sur la couverture réelle de Career Explorer. Séparation stricte métriques synthétiques vs réelles.

---

## Nouveau module à créer

```
career/source_coverage.py
tests/test_source_coverage.py
```

---

## Mesures obligatoires

| Métrique | Description |
|----------|-------------|
| `sources_planned` | Sources prévues |
| `sources_queried` | Sources consultées |
| `sources_succeeded` | Sources réussies |
| `sources_cached` | Sources servies depuis cache |
| `sources_failed` | Sources en erreur |
| `unique_employers` | Employeurs uniques |
| `raw_offers` | Annonces brutes lues |
| `valid_offers` | Annonces valides (après qualification) |
| `offers_pre_dedup` | Annonces avant déduplication |
| `offers_post_dedup` | Annonces après déduplication |
| `offers_verified_url` | Annonces avec URL officielle vérifiée (SK-01) |
| `offers_with_location` | Annonces avec localisation connue |
| `offers_with_published_date` | Annonces avec date publication |
| `offers_with_start_date` | Annonces avec date début |
| `offers_with_duration` | Annonces avec durée |
| `offers_with_requirements` | Annonces avec prérequis |
| `compliant` | Annonces conformes |
| `to_verify` | Annonces à vérifier |
| `non_compliant` | Annonces non conformes |

---

## Contrainte absolue : séparation metrics.synthetic vs metrics.live

```json
{
  "metrics": {
    "synthetic": { "sources_planned": 8, "raw_offers": 600, ... },
    "live": { "sources_planned": 8, "raw_offers": 820, ... }
  }
}
```

**Les 60 offres synthétiques ne doivent JAMAIS augmenter un compteur présenté comme mesure de la recherche réelle.**

---

## Critères de cohérence

- Tous les nombres sont **recalculables** à partir des données brutes
- Les **sommes doivent être cohérentes** (ex: succeeded + failed + cached = queried)
- **Aucun double comptage** après déduplication
- **HTTP 200 ≠ source de qualité** — une source qui répond mais renvoie 0 offres valides est comptée dans `queried` mais pas `succeeded`

---

## Commandes de validation

```bash
./checklist_codex.sh
.venv/bin/python -m pytest -q tests/test_source_coverage.py
.venv/bin/python -m pytest -q
git diff --check
```

---

## Critères de réussite

- [ ] `source_coverage.compute_metrics(run_id: str) -> CoverageMetrics` pure, déterministe
- [ ] Séparation stricte `metrics.synthetic` / `metrics.live`
- [ ] 19+ métriques couvertes
- [ ] Sommes cohérentes, pas de double comptage
- [ ] Fixtures synthétiques + données live séparées
- [ ] Ruff clean, suite complète verte, `git diff --check` propre
- [ ] Rapport `docs/agent-reports/SPEC-SK04-SOURCE_COVERAGE.md`

---

## Squelette minimal

```python
# career/source_coverage.py
from __future__ import annotations
from dataclasses import dataclass
from typing import Literal

@dataclass
class CoverageMetrics:
    sources_planned: int
    sources_queried: int
    sources_succeeded: int
    sources_cached: int
    sources_failed: int
    unique_employers: int
    raw_offers: int
    valid_offers: int
    offers_pre_dedup: int
    offers_post_dedup: int
    offers_verified_url: int
    offers_with_location: int
    offers_with_published_date: int
    offers_with_start_date: int
    offers_with_duration: int
    offers_with_requirements: int
    compliant: int
    to_verify: int
    non_compliant: int

@dataclass
class CoverageReport:
    metrics: dict[Literal["synthetic", "live"], CoverageMetrics]
    computed_at: str

def compute_metrics(run_id: str) -> CoverageReport:
    # 1. Charger données du run (run_id lie exploration → offres brutes → qualifiées → dédupliquées)
    # 2. Séparer offres synthétiques vs live (champ source: "synthetic" vs "live")
    # 3. Calculer chaque métrique pour chaque catégorie
    # 4. Vérifier cohérence sommes
    # 5. Retourner CoverageReport
    ...
```

---

**Tu as tout. Lance-toi.** Branche `agent/spec-sk04-source-coverage`, worktree dédié, code, tests, rapport, push. Je relis et j'intègre.