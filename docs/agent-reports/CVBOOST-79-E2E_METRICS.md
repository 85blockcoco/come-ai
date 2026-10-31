# CVBOOST-79 — Instrumentation + évaluation E2E (SPEC-044)

**Mission** : CVBOOST-79 · **Branche** : `agent/spec-044-e2e-metrics` · **Statut** : done

## Livrés

| Fichier | Rôle |
|---|---|
| `career/metrics.py` | `MetricsStore` (SQLite local), `StepTimer` (pause/reprise), `new_run_id`, exports CSV/JSON |
| `career/eval_e2e.py` | `load_offers`, `evaluate_offer`, `aggregate`, `render_report`, `run_evaluation`, `OfferResult`, `AggregateReport` |
| `tests/test_eval_e2e.py` | 12+ tests (timing, pause/reprise, offres, agrégation, rapport, confiance) |
| `evals/real_offers/` | Dossier local pour les 10 offres réelles (ignoré par git) |

## Contrats respectés

- Chronométrage par étape (import CV, génération dossier, lettre, audit, correction utilisateur).
- Stockage SQLite local, export CSV/JSON, aucun observateur tiers.
- Pause/reprise exclut le temps d'attente utilisateur.
- Lecture d'offres locales (JSON/texte), fichiers cachés ignorés.
- Rapport agrégé avec confiance explicite (n=10 → tendances indicatives, pas de conclusion forte).
- Aucune donnée personnelle réelle dans le dépôt ; offres réelles exclues de git.

## Notes

- `run_evaluation()` produit un dashboard textuel (`e2e_report.md`) et une fiche MD par offre.
- Confiance : `n=0` aucune donnée ; `n<10` échantillon faible ; `n>=10` tendances indicatives.
