# MISSION SPEC KIT — SPEC-004 : Evidence-backed CV Review Workspace

> **Priorité : P0** — Continue directement SK-03/SK-10/SK-11. Module indépendant, worktree dédié.

---

## Contexte

Le générateur de CV ciblé existe (SK-11). Il faut maintenant un **éditeur de révision** : l'utilisateur voit chaque différence entre CV source et CV ciblé, la preuve derrière chaque affirmation, et valide/refuse/modifie avant export.

---

## Objectif

Créer un **workspace de révision** où chaque adaptation du CV est :

1. **Visible** : diff phrase par phrase (source → proposé)
2. **Justifiée** : preuve exacte (quote + offsets) ou placeholder
3. **Contrôlée** : Accepter / Modifier / Refuser / Revenir au source
4. **Traçable** : historique des décisions, statut par bloc

---

## Nouveaux modules à créer

```
career/cv_review.py           # Core: diff, statuts, validation
career/cv_review_store.py     # Persistance workspace + historique
career/router.py              # Endpoints GET/POST /cv-review/{application_id}
career_static/js/cv-review.js # UI revue ligne par ligne
tests/test_cv_review.py
tests/fixtures/cv_review/
docs/agent-reports/SPEC-004-CV_REVIEW_WORKSPACE.md
```

---

## Contrat attendu

### Workspace de révision (par candidature)

```python
@dataclass
class ReviewBlock:
    block_id: str
    section: Literal["experiences", "skills", "education", "projects", "languages"]
    source_text: str
    proposed_text: str
    status: Literal["pending", "accepted", "rejected", "modified", "verified"]
    evidence: list[EvidenceRef] | None  # refs vers EvidenceCenter
    placeholder_reason: str | None
    user_text: str | None               # si modified
    decided_at: str | None
    decided_by: str                     # "user"
```

### Statuts obligatoires

| Statut | Signification |
|--------|---------------|
| `pending` | En attente de décision |
| `verified` | Preuve directe → accepté auto |
| `accepted` | Validé par utilisateur |
| `rejected` | Refusé → revient au source |
| `modified` | Modifié manuellement par utilisateur |

### Règle de blocage export

```python
def can_export(workspace: ReviewWorkspace) -> tuple[bool, list[str]]:
    # BLOQUÉ si : blocs critiques (experiences, skills) en pending SANS preuve
    # BLOQUÉ si : placeholders critiques non confirmés
    # OK si : tous blocs critiques sont verified/accepted/modified
    ...
```

### Endpoints API

```
GET  /cv-review/{application_id}           # Workspace complet
POST /cv-review/{application_id}/decide    # {block_id, status, user_text?}
GET  /cv-review/{application_id}/export    # DOCX seulement si can_export=True
GET  /cv-review/{application_id}/history   # Historique décisions
```

---

## UI attendue (career_static/js/cv-review.js)

- **Vue split** : source à gauche, proposé à droite, diff coloré
- **Boutons par bloc** : ✅ Accepter | ✏️ Modifier | ❌ Refuser | ↩️ Source
- **Badge preuve** : 🟢 Vérifié | 🟡 À vérifier | 🔴 Placeholder
- **Barre progression** : X/Y blocs critiques validés
- **Export DOCX** : désactivé si `can_export=False`, tooltip explicatif

---

## Commandes de validation

```bash
./checklist_codex.sh
.venv/bin/python -m pytest -q tests/test_cv_review.py
.venv/bin/python -m pytest -q
git diff --check
```

---

## Critères de réussite

- [ ] `cv_review.build_workspace(application_id) -> ReviewWorkspace` pure
- [ ] Diff phrase par phrase (difflib.SequenceMatcher ou équivalent)
- [ ] Statuts persistés, historique immuable
- [ ] Export DOCX bloqué si placeholders critiques non validés
- [ ] Tests : workspace créé, décisions persistées, export bloqué/autorisé
- [ ] Ruff clean, suite complète verte, `git diff --check` propre
- [ ] Rapport `docs/agent-reports/SPEC-004-CV_REVIEW_WORKSPACE.md`

---

**Tu as tout. Lance-toi.** Branche `agent/spec-004-cv-review-workspace`, worktree dédié, code, tests, rapport, push. Je relis et j'intègre.