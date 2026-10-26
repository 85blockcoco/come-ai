# SPEC-044 — Postuler en un clic : dossier prêt par offre

**Mission** : CVBOOST-81 · **Branche** : `agent/spec-044-apply-kit-ready` · **Statut** : done

## Livrés

| Fichier | Rôle |
|---|---|
| `career/apply_kit.py` | `ApplyKit` dataclass + `build_apply_kit()` |
| `career/service.py` | `CareerService.build_apply_kit()` |
| `career/router.py` | `POST /api/career/apply-kit/{job_id}` |
| `tests/test_apply_kit.py` | 5 tests (complet, incomplet, inconnu, smoke, dataclass) |

## Contrats respectés

- `ApplyKit(job_id, readiness, block_reasons, variant, letter, answers, checklist, deep_link, export_urls)`
- `build_apply_kit(job_id, profile) -> ApplyKit`
- Aucune soumission automatique ; export_urls pointent vers les exports existants.

## Notes

- Variante CV via `classify_variant`, lettre via `build_local_application_draft` (mémoire).
- Readiness < 100 + `block_reasons` si profil incomplet / éligibilité non vérifiée / exigences non étayées.
- Endpoint crée réutilise un kit existant (idempotent) pour fournir des `export_urls`.