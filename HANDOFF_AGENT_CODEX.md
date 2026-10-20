# HANDOFF — Agent Codex (Validation finale)

**Destinataire** : Agent Codex (intégration / validation)
**Émetteur** : Audit nocturne
**Rôle** : Garantir que chaque livraison est **intégrée, testée, sans régression** avant d'être acceptée dans `main`.

---

## 1. Référence inaltérable : `main` (`ed8a6b9`)

```bash
cd ~/AI-Excel-Agent
git log --oneline -1
# ed8a6b9 docs: record delivered Career journey and post-merge validation

.venv/bin/python -m pytest -q
# 681 passed, 2 skipped
```

**Empreinte source DevKit** : `d7098a354143d36c18e1dd044db7edf628c0647c69aea88c315a843f520c0a6a` (rapport `.devkit/diagnostics/latest.*`)

---

## 2. Checklist exécutoire (à passer pour CHAQUE PR de fusion)

| # | Vérification | Commande | Critère |
|---|---|---|---|
| 1 | `main` intact | `cd ~/AI-Excel-Agent && .venv/bin/python -m pytest -q` | 681 passed / 2 skipped |
| 2 | Worktree mémoire importable | `cd ~/AI-Excel-Agent-memory && .venv/bin/python -m py_compile come_ai_web.py personal_memory.py && .venv/bin/python -c "from come_ai_web import create_app"` | 0 erreur |
| 3 | Routes profil uniques | Voir script ci-dessous | `DUP_ROUTES {}` |
| 4 | Import profil != 500 | Voir script | `IMPORT_STATUS != 500` |
| 5 | Tests HTTP profil | `.venv/bin/python -m pytest -q tests/ -k "profile or personal"` | ≥1 test par endpoint |
| 6 | Aucun secret tracké | `git ls-files \| grep -iE '\.env$|\.db$|secret|key|token|password'` | 0 (sauf test garde) |
| 7 | Mémoire injectée dans le chat (après raccord) | `grep -n list_personal_memories hybrid_chat.py` | présence + tests intégration |
| 8 | DevKit sandbox + rollback | `.venv/bin/python -m pytest -q tests/test_devkit*.py tests/test_evolution*.py` | vert |
| 9 | Study Coach (après intégration) | `cd ~/AI-Excel-Agent-study-coach && .venv/bin/python -m pytest -q tests/test_study_coach_*.py` | 82 passed + route/UI testées |
| 10 | Empreinte source enregistrée | `ls -la .devkit/diagnostics/latest.*` | rapport présent |

**Script routes profil / import** (à copier-coller) :
```bash
cd ~/AI-Excel-Agent-memory
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
dups = {k:v for k,v in seen.items() if len(v)>1}
print("DUP_ROUTES", dups)
c = TestClient(app, raise_server_exceptions=False)
print("IMPORT_STATUS", c.post("/api/v5/profile/import", json={"schema":"come-personal-profile-pack/1","entries":[]}).status_code)
PY
```

---

## 3. Règles d'intégration (non négociables)

1. **Rebase obligatoire** : toute branche basée sur `1b570dd` (ex. `-memory`) doit être rebasée sur `main` avant PR.
2. **Pas de doublons** : un seul jeu d'endpoints par ressource.
3. **Tests d'intégration** : chaque nouvelle route a un test HTTP ; chaque raccordement a un test prouvant le flux.
4. **Zéro secret** : `.env`, `.db`, clés **jamais** dans Git.
5. **Pas de `main` modifié** sans validation complète ci-dessus.
6. **Empreinte DevKit** : le rapport `.devkit/diagnostics/latest.*` doit refléter la nouvelle base.

---

## 4. Branches à nettoyer (pointeurs vides)

Supprimer ces branches locales (contenu déjà dans `main`) :
- `feature/noveria-career-integration`
- `feature/profile-integration-v1`
- `feature/workspace-control-center`
- `integration/consolidated`
- `integration/career-explorer`
- `integration/lot1-mimo`
- `integration/step5-facts`

---

## 5. Livraisons en attente de validation Codex

| Livraison | Branche | Statut |
|---|---|---|
| Mémoire (réparée + raccordée) | `feature/nemotron-memory` ou `personal-context-engine` | ❌ bloquée par BUG-01 |
| Study Coach UI | `feature/study-coach-v1` | ⚠️ prête, non raccordée |
| Catalogue Career | `feature/career-sources-overnight` | ⚠️ prêt, non câblé |
| Step 5 cycles restants | `feature/step5-intelligence-centrale` | ⚠️ 2 commits non intégrés |

---

## 6. Interdits

- Pas de `git reset --hard`, `clean`, force-push sur `main`.
- Pas de secrets dans le contexte modèle.
- Pas de données personnelles réelles dans les fixtures.
- Pas de validation sans empreinte DevKit à jour.