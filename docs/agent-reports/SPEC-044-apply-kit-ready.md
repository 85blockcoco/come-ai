# SPEC-044 — Postuler en un clic : dossier prêt par offre

**Mission** : CVBOOST-81 · **Branche** : `agent/spec-044-apply-kit-ready` · **Statut** : done

## Livrés

| Fichier | Rôle |
|---|---|
| `career/apply_kit.py` | `ApplyKit` dataclass + `build_apply_kit()` |
| `career/service.py` | `CareerService.build_apply_kit()` |
| `career/router.py` | `POST /api/career/apply-kit/{job_id}` |
| `tests/test_apply_kit.py` | 10 tests (complet, incomplet, inconnu, checklist, deadline, exports, variante, smoke) |

## Contrats respectés

- `ApplyKit(job_id, readiness, block_reasons, variant, letter, answers, checklist, deep_link, export_urls)`
- `build_apply_kit(job_id, profile) -> ApplyKit`
- Aucune soumission automatique : la checklist se termine par une action humaine
  explicite (`submit`, `done=False`) ; le kit n'expose aucun champ de soumission.
- `export_urls` pointent vers les exports PDF/DOCX existants, créés par
  `CareerService.create_application_kit()` (idempotent par offre/langue/variante).

## Comportement

- **Variante CV** : `classify_variant` sur les faits de l'offre et du profil, avec
  override explicite (`markets`, `corporate_finance`, `m_a`).
- **Lettre** : `build_local_application_draft` en mémoire, sans appel réseau.
- **Réponses** : faits de profil + réponses d'intake + textes de kit locaux.
- **Checklist** : profil, éligibilité, variante, lettre, pièces à joindre
  (CV/lettre PDF), lien officiel, date limite (marquée `urgent` si ≤ 14 jours),
  dates du stage, preuves manquantes, puis dépôt manuel.
- **Readiness** : 100 seulement si profil complet, éligibilité vérifiée, exigences
  étayées, variante + lettre disponibles et lien de candidature présent.
  Sinon `readiness < 100` + `block_reasons` explicites.
- **Deep link** : URL de formulaire explicite (`apply_url`, `application_url`,
  `form_url`, `ats_url`) sinon `official_url`.
- **Performance** : ~0,15 s par appel sur une offre déjà préparée (mesure locale
  synthétique, bien sous la limite de 3 s).

## Vérifications

```text
pytest -q tests/test_apply_kit.py       → 10 passed
ruff check career/apply_kit.py career/service.py career/router.py tests/test_apply_kit.py → All checks passed
git diff --check                        → clean
```
