# HANDOFF — Agent Mémoire

**Destinataire** : Agent Mémoire (Codex / autre)
**Émetteur** : Audit nocturne
**Branche cible** : `feature/nemotron-memory` (worktree `-memory`)
**Base** : `1b570dd` — **périmée**, rebase obligatoire sur `main` (`ed8a6b9`)

---

## 1. Ce qui est cassé (P0)

`come_ai_web.py` **ne s'importe pas** :

```bash
cd ~/AI-Excel-Agent-memory
.venv/bin/python -m py_compile come_ai_web.py
# IndentationError: expected an indented block after class definition on line 211 (line 214)
```

Cause : `class MemoryProjectRequest(BaseModel):` vide (lignes 211–214).

**Doublon d'endpoints** : deux blocs complets `/api/v5/profile/*` (lignes ~749–980 puis ~1110–1240). Le second appelle `_require_profile_adapter()` **non défini** → `POST /api/v5/profile/import` = **HTTP 500**.

**Champs orphelins** : `name:`/`description:` (les champs originaux de HEAD) se retrouvent lignes 259–260, sous `ProfileBulkAccept`. `class ProfileMemoryCreate` définie **deux fois**.

---

## 2. Conflit de source de vérité

Deux moteurs coexistent :

| | Nemotron (worktree `-memory`) | Personal Context Engine (branche) |
|---|---|---|
| Schéma | `personal_memories` dans `personal_memory.py` | `personal_profile/` (propre, versionné) |
| Tests | aucun test HTTP | 190 tests |
| Revue/approbation | endpoints (doublonnés) | flux complet (import → revue → contexte) |
| Contrat | aucun | `come-personal-profile-pack/1` |
| `CONTRACT_INTEGRATION.md` | — | dit « non raccordé » |

**Décision attendue** : choisir **une** source, migrer/archiver l'autre sans perte.

---

## 3. Tâches

1. **Corriger l'import** (PROMPT 1) : corps unique pour `MemoryProjectRequest`, supprimer le second bloc d'endpoints, nettoyer orphelins/duplicatas.
2. **Rebaser** sur `main` (`git rebase main` ou `git merge main` selon stratégie).
3. **Trancher A vs B** (PROMPT 2) : produire note + plan de migration.
4. **Raccorder au chat** (PROMPT 3) : injection bornée des souvenirs `accepte`, exclusion `tres_elevee` du cloud.
5. **UI « Mon profil »** (PROMPT 4) : onglet V5, actions confirmées, export.

---

## 4. Preuves d'acceptation (checklist Codex)

```bash
# 1. Import OK
cd ~/AI-Excel-Agent-memory
.venv/bin/python -m py_compile come_ai_web.py personal_memory.py
.venv/bin/python -c "from come_ai_web import create_app; print('OK')"

# 2. Pas de routes dupliquées, import != 500
.venv/bin/python - <<'PY'
import tempfile, pathlib
from fastapi.testclient import TestClient
from come_ai_web import create_app
tmp = pathlib.Path(tempfile.mkdtemp())
app = create_app(tmp)
seen = {}
for r in app.routes:
    if getattr(r, "path", "").startswith("/api/v5/profile"):
        seen.setdefault(r.path, []).append(sorted(getattr(r, "methods", []) or []))
print("DUP", {k:v for k,v in seen.items() if len(v)>1})
c = TestClient(app, raise_server_exceptions=False)
print("IMPORT", c.post("/api/v5/profile/import", json={"schema":"come-personal-profile-pack/1","entries":[]}).status_code)
PY

# 3. Tests HTTP profil
.venv/bin/python -m pytest -q tests/ -k "profile or personal"
```

---

## 5. Interdits

- Pas de lecture des souvenirs réels.
- Pas de secrets dans le contexte modèle.
- Pas de modification de `main` sans acceptation.
- Pas de `git reset --hard` / force-push.

---

## 6. Fichiers concernés

- `come_ai_web.py` (endpoints, `MemoryProjectRequest`)
- `personal_memory.py` (table `personal_memories` + CRUD)
- `hybrid_chat.py` (injection mémoire future)
- `v5_static/` (onglet futur)
- `tests/` (nouveaux tests d'intégration)

---

## 7. Contacts

- Agent Career : intégration catalogue / « Explorer »
- Agent Study Coach : adaptateur mémoire → StudyCoach
- Agent Codex : validation finale + checklist