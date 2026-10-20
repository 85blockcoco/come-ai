# REVUE DE SÉCURITÉ — Mémoire Personnelle (pour Agent Mémoire + Codex)

**Périmètre** : code, contrats, schémas, API. **Jamais** les souvenirs réels.

---

## 1. Sources de vérité concurrentes

| Moteur | Schéma | API | État |
|---|---|---|---|
| Nemotron (worktree `-memory`) | `personal_memories` dans `personal_memory.py` | endpoints doublonnés dans `come_ai_web.py` | **cassé** (BUG-01→04) |
| Personal Context Engine | `personal_profile/` (SQLite dédiée) | façade `personal_profile.service` | **prêt** (190 tests, contrat versionné) |

**Risque** : deux bases, deux API, aucune gouvernance. Décision P0 attendue.

---

## 2. Schéma `personal_memories` (Nemotron)

```sql
CREATE TABLE personal_memories (
    id TEXT PRIMARY KEY,
    category TEXT NOT NULL,              -- A_faits .. V_valeurs
    domain TEXT NOT NULL,                -- DEV .. GENERAL
    statement TEXT NOT NULL,
    evidence_type TEXT NOT NULL,
    evidence TEXT,
    source_kind TEXT NOT NULL,
    source_reference TEXT,
    observed_at TEXT NOT NULL,
    confidence TEXT NOT NULL,            -- elevee / moyenne / basse / inconnue
    temporal_scope TEXT NOT NULL,        -- durable / temporaire / revise_periodique
    sensitivity TEXT NOT NULL,           -- normale / elevee / tres_elevee
    personalization_use TEXT NOT NULL,
    contradictions TEXT NOT NULL DEFAULT '[]',
    status TEXT NOT NULL,                -- candidat / accepte / rejete / a_revoir / suspendu / obsolete
    review_due TEXT,
    retention_decision TEXT,
    justification TEXT,
    original_statement TEXT,
    source_id TEXT REFERENCES sources(id) ON DELETE SET NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
```

**Observations** :
- `sensitivity` 3 niveaux → exploitable pour filtrage cloud.
- `status` = workflow revue (candidat → accepte/rejete/a_revoir/suspendu).
- `source_id` FK vers `sources` (documents) — traçabilité possible.
- **Pas de chiffrement** au repos (fichier 0600 seulement).

---

## 3. Flux d'approbation (Nemotron)

`candidat` → (humain) → `accepte` | `rejete` | `a_revoir` | `suspendu`
- `accept_personal_memory`, `reject_personal_memory`, `suspend_personal_memory`, `revise_personal_memory` existent.
- `bulk_accept_personal_memories` existe.
- **Manquant** : journal d'audit (qui a fait quoi, quand, pourquoi).

---

## 4. API exposée (actuelle, doublonnée)

| Endpoint | Méthode | Note |
|---|---|---|
| `/api/v5/profile/overview` | GET | comptes par statut |
| `/api/v5/profile/entries` | GET | liste filtrée |
| `/api/v5/profile/entries/{id}` | GET | détail |
| `/api/v5/profile/entries/{id}/history` | GET | **second bloc seulement** |
| `/api/v5/profile/entries` | POST | création (candidat) |
| `/api/v5/profile/entries/{id}` | PATCH | mise à jour partielle |
| `/api/v5/profile/entries/{id}/accept` | POST | accepter |
| `/api/v5/profile/entries/{id}/reject` | POST | rejeter |
| `/api/v5/profile/entries/{id}/suspend` | POST | suspendre |
| `/api/v5/profile/entries/{id}/revise` | POST | réviser |
| `/api/v5/profile/entries/{id}` | DELETE | supprimer |
| `/api/v5/profile/bulk-accept` | POST | lot |
| `/api/v5/profile/suspended` | GET | liste suspendus |
| `/api/v5/profile/export` | POST | export |
| `/api/v5/profile/import` | POST | **500** (helper absent) |
| `/api/v5/profile/settings` | GET | **premier bloc seulement** |

**Risque** : doublon = maintenance impossible, surface d'attaque accrue.

---

## 5. Intégration chat / Career / Study Coach

- **Chat** : **aucun appel** à `list_personal_memories()` → souvenirs **jamais utilisés**.
- **Career** : profil Career séparé (`career_data/`) — pas de partage.
- **Study Coach** : non raccordé — utiliserait documents, pas souvenirs profil.

**Risque** : données sensibles stockées sans usage, promesse non tenue.

---

## 6. Consentement / suppression

- Création = consentement implicite (POST utilisateur).
- Suppression : `DELETE /entries/{id}` + `bulk` possible.
- `reset_personal_data` (Career) ne couvre **pas** cette table.
- **Manquant** : RGPD « droit à l'oubli » explicite, export complet, purge.

---

## 7. Journalisation

- `personal_memory.py` : pas de log des `statement` / `evidence`.
- `come_ai_web.py` : logs génériques `error_id` seulement.
- **Manquant** : journal d'audit immuable (création, accept, reject, export, delete).

---

## 8. Transmission cloud

- **Gardes** : `tres_elevee` doit être exclu de tout envoi cloud (non implémenté).
- Modèle cloud reçoit **texte inerte** (pas de function calling) — bon point.
- DevKit : expurgation secrets/chemins avant envoi — bon point.

---

## 9. Fichiers temporaires / SQLite

- `PersonalMemoryStore` : `sqlite3.connect(..., timeout=5.0, isolation_level=None)` — WAL par défaut.
- Permissions `0600` posées à la création.
- **Gardes symlink** : `_assert_paths` refuse les liens symboliques.
- **Concurrence** : un `Lock` par instance + `timeout=5.0` — acceptable pour 1 processus.

---

## 10. Imports non fiables

- `personal_memory.py` : imports stdlib seulement (`sqlite3`, `json`, `html.parser`, etc.).
- `come_ai_web.py` : `pydantic`, `fastapi`, `starlette` — versions fixées dans `requirements-v3.txt`.
- **Pas d'import dynamique** de code utilisateur.

---

## 11. Commandes exécutées par agents

- **Aucune** : ni DevKit, ni Chat, ni Career n'exécutent de commande shell avec entrées utilisateur.
- DevKit : `sandbox-exec` (macOS) pour tests, pas pour prod.

---

## 12. Téléchargements / dépendances

- Modèles : **aucun téléchargement auto** (Ollama géré manuellement).
- Catalogue modèles : rafraîchissement explicite, TTL 24 h, pas de binaire.
- `pip` : requirements fixés, `pip check` dans DevKit.

---

## 13. Rollback / conflits Git

- DevKit : sauvegardes atomiques + rollback testé.
- Git : worktrees isolés, pas de `reset --hard` sur `main`.
- **Manquant** : procédure documentée de rollback mémoire (si migration de schéma échoue).

---

## 14. Recommandations (pour Agent Mémoire + Codex)

1. **Choisir un seul moteur** (Nemotron nettoyé vs `personal_profile/`).
2. **Chiffrement au repos** pour `sensitivity = tres_elevee` (optionnel mais recommandé).
3. **Journal d'audit** : table `personal_memory_audit` (id, action, user, before, after, timestamp).
4. **Filtrage cloud** : dans `hybrid_chat._local_context`, exclure `tres_elevee` du contexte envoyé.
5. **RGPD** : endpoint `/api/v5/profile/export` complet + `/api/v5/profile/purge`.
6. **Tests** : un test par endpoint + test d'injection chat + test d'exclusion sensibilité.
7. **Procédure rollback** : documenter `ALTER TABLE` / migration + `git revert` associé.

---

## 15. Preuves demandées à la livraison

- `pytest` vert + `py_compile` OK.
- `grep list_personal_memories hybrid_chat.py` → présent + test.
- `TestClient` : exclusion `tres_elevee` prouvée.
- Journal d'audit écrit à chaque action.
- Empreinte DevKit à jour.