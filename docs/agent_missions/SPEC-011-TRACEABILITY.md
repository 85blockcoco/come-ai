# MISSION SPEC KIT — SPEC-011 : Registre de Traçabilité des Exigences

> **Priorité : P0** — Module transverse, fondation pour l'audit et la conformité. Worktree dédié.

---

## Contexte

Actuellement, les exigences extraites des offres (SK-02) et les preuves du profil (SK-10) existent mais ne sont pas liées dans un registre unique traçable. Il faut un **registre centralisé** qui relie chaque exigence à sa preuve, son statut, son historique et son impact.

---

## Objectif

Créer un **Registre de Traçabilité** centralisé qui :
1. Enregistre chaque exigence (source, texte, catégorie, criticité)
2. Lie chaque exigence à sa preuve (SK-10) ou signale son absence
3. Traque les changements (création, modification, suppression, résolution)
4. Fournit des rapports d'audit et de couverture
5. Sert de base pour l'audit, la conformité et l'amélioration continue

---

## Nouveaux modules à créer

```
career/traceability.py              # Core: registre, modèles, API
career/traceability_store.py        # Persistance, indexation, requêtes
career/traceability_audit.py        # Rapports d'audit, couverture, gaps
career/router.py                    # Endpoints CRUD, audit, export
career_static/js/traceability.js    # UI registre, filtres, historique
tests/test_traceability.py
docs/agent-reports/SPEC-011-TRACEABILITY.md
```

---

## Contrat attendu

### RequirementTrace (entité centrale)

```python
@dataclass
class RequirementTrace:
    trace_id: str                           # UUID unique
    requirement_id: str                     # ID depuis SK-02 (ex: "req_123")
    requirement_text: str                   # Texte exact de l'exigence
    source: str                             # "offer_123" / "cv_456" / "manual"
    category: Literal["skill", "experience", "education", "language", "tool", "certification", "soft_skill", "other"]
    criticality: Literal["mandatory", "preferred", "nice_to_have", "contextual"]
    evidence_id: str | None                 # ID EvidenceItem (SK-10) si lié
    evidence_quote: str | None              # Citation exacte de la preuve
    status: Literal["uncovered", "covered", "partial", "contradicted", "waived"]
    created_at: str                         # ISO 8601
    updated_at: str                         # ISO 8601
    history: list[TraceEvent]               # Historique des changements
    tags: list[str]                         # Tags métier (ex: "finance", "m&a", "python")
```

### TraceEvent (historique)

```python
@dataclass
class TraceEvent:
    event_id: str
    timestamp: str                          # ISO 8601
    event_type: Literal["created", "linked", "unlinked", "status_changed", "category_changed", "criticality_changed", "waived", "reopened"]
    old_value: str | None
    new_value: str | None
    actor: Literal["system", "user", "worker"]
    comment: str | None
```

---

## API attendue

```
POST   /traceability/requirements           # Créer une traçabilité
GET    /traceability/requirements           # Liste avec filtres (status, category, criticality, offer_id, cv_id)
GET    /traceability/requirements/{trace_id} # Détail complet + historique
PATCH  /traceability/requirements/{trace_id} # Modifier status, evidence, tags, comment
POST   /traceability/requirements/{trace_id}/link-evidence   # Lier EvidenceItem
POST   /traceability/requirements/{trace_id}/unlink-evidence # Délier EvidenceItem
POST   /traceability/requirements/{trace_id}/waive           # Marquer waived avec justification
GET    /traceability/audit/coverage         # Rapport couverture par offre/CV
GET    /traceability/audit/gaps             # Exigences non couvertes
GET    /traceability/audit/history          # Historique global filtré
GET    /traceability/export                 # Export JSON/CSV complet
```

---

## Règles métier

1. **Création auto** : À l'extraction d'une offre (SK-02), créer les RequirementTrace
2. **Liaison auto** : Au matching (SK-21), lier auto si EvidenceItem match exact
3. **Validation manuelle** : User peut confirmer/rejeter les liaisons auto
4. **Immuabilité** : Historique immuable, seule la mise à jour de status/tags/comment autorisée
5. **Cohérence** : Une exigence "covered" doit avoir evidence_id + evidence_quote
6. **Audit trail** : Toute modification tracée avec actor, timestamp, comment

---

## Rapports d'audit attendus

| Rapport | Contenu |
|---------|---------|
| **Couverture par offre** | % exigences covered/partial/uncovered par offre |
| **Couverture par CV** | % exigences du profil couvertes par preuves |
| **Gaps critiques** | Exigences mandatory non couvertes |
| **Historique changements** | Timeline des statuts par exigence |
| **Exigences waived** | Liste avec justifications |
| **Évolution dans le temps** | Courbes de couverture dans le temps |

---

## Commandes de validation

```bash
./checklist_codex.sh
.venv/bin/python -m pytest -q tests/test_traceability.py
.venv/bin/python -m pytest -q
git diff --check
```

---

## Critères de réussite

- [ ] Registre RequirementTrace CRUD complet + historique immuable
- [ ] Liaison auto SK-02 → SK-10 au matching + validation manuelle
- [ ] Rapports d'audit : couverture, gaps, waived, historique
- [ ] Export complet (JSON/CSV) + import
- [ ] UI : filtres, tri, historique par exigence, actions batch
- [ ] Intégration SK-02 (création auto), SK-10 (liaison), SK-21 (matching)
- [ ] Ruff clean, suite complète verte, `git diff --check` propre
- [ ] Rapport `docs/agent-reports/SPEC-011-TRACEABILITY.md`

---

**Tu as tout. Lance-toi.** Branche `agent/spec-011-traceability`, worktree dédié, code, tests, rapport, push. Je relis et j'intègre.