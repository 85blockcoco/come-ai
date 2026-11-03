# SPEC-023 — Mémoire personnelle & style

> Mission CVBOOST-58 · branche `worker/cvboost-58-1792698451` · priorité P1

## Objectif

Construire une mémoire personnelle locale qui apprend des choix de reformulation
(verbe d'action, tonicité, longueur, glossaire, décisions passées) et les
réinjecte comme contraintes explicites dans les futures générations
(SPEC-017/020/021/022), avec réversibilité totale et export/import.

## Livrables

| Fichier | Rôle |
| --- | --- |
| `career/memory_types.py` | `StylePreference`, `PastChoice`, `Glossary` (dataclasses JSON-friendly, aucune I/O) |
| `career/personal_memory.py` | `StyleMemoryStore` : journal d'événements append-only, replay, apprentissage, purge, undo, export/import, `inject_constraints` fail-closed |
| `career/memory_report.py` | `build_report` (JSON) + `render_markdown` (dashboard/export lisible) |
| `career/memory_router.py` | API FastAPI locale montée par `come_ai_web` |
| `career_static/js/memory-panel.js` | Panneau « Réglages » : confiance, source, undo, glossaire, export/import |
| `career_static/career.css` | Styles du panneau |
| `career_static/index.html` | Chargement du script |
| `come_ai_web.py` | Instanciation du store (`career_data/style_memory`), `app.state.style_memory`, montage du routeur |
| `tests/test_career_personal_memory.py` | 13 tests offline (store, corruption, API, UI statique) |

## Format de stockage (version fermée)

Un seul fichier JSON privé (`0600`, dossier `0700`) :
`career_data/style_memory/style_memory.json`

```json
{
  "schema": "come-ai.career.style-memory",
  "version": 1,
  "updated_at": "2026-10-22T20:00:00Z",
  "integrity": "<sha256 des événements canoniques>",
  "events": [
    {"id": "…", "type": "choice_recorded", "at": "…", "choice_id": "…", "context": "bullet_reformulate:offer_123", "chosen": {…}, "rejected": [ … ], "evidence_refs": ["offer_123"]},
    {"id": "…", "type": "preference_observed", "at": "…", "key": "js-action-verb", "value": "conçu", "source": "user_pick", "choice_id": "…"},
    {"id": "…", "type": "choice_undone", "at": "…", "choice_id": "…"},
    {"id": "…", "type": "preference_purged", "at": "…", "key": "tone", "reason": "Retrait volontaire"}
  ]
}
```

* **Append-only** : aucune écriture ne supprime un événement ; l'état est
  reconstructible par replay.
* **Version fermée** : `schema` et `version` sont vérifiés ; une version
  inconnue est refusée sans modifier le fichier.
* **Intégrité** : un digest SHA-256 détecte une troncature ou une corruption.
* **Purge tracée** : `preference_purged` porte une raison explicite — aucune
  perte silencieuse.
* **Écriture atomique** : fichier temporaire, `fsync`, `os.replace`, permissions
  privées.

## Apprentissage et réversibilité

| Occurrences identiques | Confiance | Effet |
| --- | --- | --- |
| 1 (`auto_infer`) | 0.35 | proposée, non appliquée |
| 2 (`auto_infer`) | 0.60 | proposée, non appliquée |
| ≥ 3 | ≥ 0.80 | **appliquée automatiquement** |
| 1 (`user_pick` / `manual`) | 0.50 / 0.95 | explicite, appliquée |

* Un choix (`POST /memory/back`) est le hook post-choix : il enregistre
  `chosen` / `rejected` / `evidence_refs`, puis infère les préférences de style.
* Les identifiants (`variant_id`, `job_id`, `score`, `label`…) ne deviennent
  jamais des préférences.
* `undo` ajoute `choice_undone` : les observations liées sont ignorées au
  replay, la confiance redescend et l'historique reste consultable.
* Une préférence `manual`/`user_pick` prime sur une inférence automatique
  (priorité `manual > user_pick > auto_infer`).

## Injection (fail-closed)

`inject_constraints(store)` et `GET /memory/constraints` renvoient le top-5 :

```json
{"constraints": [{"key": "js-action-verb", "value": "conçu", "confidence": 0.8, "auto_applied": true, "constraint": "js-action-verb = conçu"}],
 "degraded": false, "generation_allowed": true}
```

Si le fichier est corrompu : `constraints: []`, `degraded: true`,
**`generation_allowed: false`** — l'appelant ne doit pas produire une variante
non contrainte. L'arena (SPEC-017/020/021/022, non encore fusionnée) consomme
cet endpoint sans jamais lire le fichier directement.

## API

| Méthode | Route | Effet |
| --- | --- | --- |
| `GET` | `/memory/prefs` | préférences + confiance + top-5 + stats |
| `POST` | `/memory/prefs` | réglage manuel (`source` = `manual` par défaut) |
| `DELETE` | `/memory/prefs/{key}?reason=…` | purge tracée |
| `GET` | `/memory/back` | historique des choix (undo 1 clic côté UI) |
| `POST` | `/memory/back` | hook post-choix |
| `POST` | `/memory/back/{choice_id}/undo` | annulation réversible |
| `GET` | `/memory/constraints` | injection top-5, fail-closed |
| `GET` | `/memory/report[?format=markdown]` | dashboard / résumé lisible |
| `POST` | `/memory/export` | export JSON (`Content-Disposition: attachment`) |
| `POST` | `/memory/import` | import JSON idempotent (fusion par `id`) |

Erreurs : `400` pour une entrée invalide, `409` pour une mémoire corrompue ou
une version non prise en charge, `404` pour une préférence ou un choix
introuvable. Aucun chemin disque n'est renvoyé au client.

## Validation

```bash
./checklist_codex.sh                  # → TOUT VERT
pytest -q tests/test_career_personal_memory.py   # 13 passed
pytest -q                             # 1437 passed, 1 skipped
ruff check .                          # All checks passed
git diff --check                      # propre
```

## Écarts assumés

* Le fichier de tests demandé (`tests/test_personal_memory.py`) appartient déjà
  à la mémoire de chat V5 sur `main`. Les tests SPEC-023 sont donc dans
  `tests/test_career_personal_memory.py` pour ne pas écraser une suite
  existante.
* Aucune arena de reformulation n'existe encore dans la base (`main` =
  `f5b22f2`) : l'intégration se limite au contrat d'injection
  (`/memory/constraints`, `inject_constraints`) que l'arena branchera.
* Le panneau est monté dans l'onglet existant « Réglages » plutôt qu'un nouvel
  onglet, afin de ne pas modifier `career_static/career.js` (fichier partagé
  soumis à l'audit d'intégration).

## Critères de réussite

- [x] 3 choix identiques → `confidence ≥ 0.8`, `auto_applied = true`, visible
      dans les contraintes injectées et le panneau.
- [x] Panneau UI avec confiance, source, glossaire et undo.
- [x] Export/import JSON round-trip sans perte et idempotent.
- [x] Mémoire corrompue → `generation_allowed = false`, fichier préservé, API
      `409`, aucun reset silencieux.
- [x] Ruff clean, suite complète verte, `git diff --check` propre.
