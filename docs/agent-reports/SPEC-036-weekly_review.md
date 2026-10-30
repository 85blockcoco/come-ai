# SPEC-036 — Bilan hebdo & objectifs

**Mission** : CVBOOST-71 · **Branche** : `agent/spec-036-weekly-review` · **Statut** : done

## Livrés

| Fichier | Rôle |
|---|---|
| `career/weekly_review.py` | `WeeklySummary`, `Objective`, `weekly_summary()`, `objective_check()`, `recommend_next()` |
| `career/service.py` | `CareerService.weekly_review()` (+ alias `weekly_summary`) |
| `career/router.py` | `GET/POST /api/career/weekly-review` (+ alias) |
| `tests/test_weekly_review.py` | tests (cas limites + adversarial + smoke) |
| `tests/fixtures/weekly_synthetic.json` | fixture synthétique |

## Contrats respectés

- `WeeklySummary(iso_week, applications_sent, responses, interview_rate, objective_met, top_actions)` avec `top_actions` ≤ 3.
- `Objective(metric, target)` avec metric ∈ {applications, responses, interviews}.
- Objectif absent → `objective_met=None` et actions basées sur les données seules.
- Données synthétiques uniquement ; aucune clé secrète en dur.

## Limites

- Agrégation locale déterministe ; pas d'envoi automatique.
- Taux d'entretien = entretiens / candidatures envoyées.
PY