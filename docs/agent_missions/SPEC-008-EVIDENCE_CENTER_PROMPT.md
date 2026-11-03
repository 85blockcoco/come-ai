# MISSION SPEC KIT — SPEC-008 : Evidence Center Unifié

> **Priorité : P0** — Module central, worktree dédié. Repose sur SK-03 (Requirements Fit) et SK-10 (Profil candidat).

---

## Contexte

La provenance existe à plusieurs endroits (SK-01, SK-02, SK-03, SK-10, SK-11) mais n'est pas unifiée. Il faut un **centre de preuves unique** : compétences prouvées/non prouvées, pièces jointes, usage dans CV/lettre, fusion doublons, métriques, expiration.

---

## Objectif

Créer un **module EvidenceCenter** unifié, source de vérité pour toutes les preuves du profil candidat.

---

## Nouveaux modules à créer

```
career/evidence.py              # Modèle EvidenceItem, EvidenceCenter
career/evidence_store.py        # Persistance, indexation, requêtes
career/router.py                # CRUD preuves, usage, fusion, export
career_static/js/evidence-center.js # UI centre de preuves
tests/test_evidence.py
docs/agent-reports/SPEC-008-EVIDENCE_CENTER.md
```

---

## Contrat attendu

### EvidenceItem

```python
@dataclass
class EvidenceItem:
    id: str                           # "evidence_123"
    claim: str                        # "Analyse financière et valorisation"
    source_document: str              # "stage_transaction_services.pdf"
    source_location: str              # "page 2, lignes 14-17"
    quote: str                        # "Participation à l'analyse financière..."
    evidence_type: Literal[
        "experience", "education", "skill", "language", "project", "certification"
    ]
    confidence: Literal["direct", "inferred", "declared"]
    approved: bool                    # Validé par utilisateur
    created_at: str
    updated_at: str
    tags: list[str]
```

### EvidenceCenter (singleton par utilisateur)

```python
class EvidenceCenter:
    def add_evidence(self, item: EvidenceItem) -> str
    def get_evidence(self, evidence_id: str) -> EvidenceItem | None
    def search_evidence(self, query: str, type: str | None = None) -> list[EvidenceItem]
    def get_evidence_for_claim(self, claim: str) -> list[EvidenceItem]
    def mark_approved(self, evidence_id: str, approved: bool) -> None
    def attach_document(self, evidence_id: str, doc_path: str) -> None
    def merge_evidence(self, ids: list[str], keep_id: str) -> None
    def get_usage_stats(self) -> EvidenceUsageStats
```

### Usage Stats

```python
@dataclass
class EvidenceUsageStats:
    total_evidence: int
    approved: int
    used_in_cv: int
    used_in_letters: int
    expired: int
    by_type: dict[str, int]
    by_confidence: dict[str, int]
```

### Endpoints API

```
GET    /evidence                          # Liste avec filtres
POST   /evidence                          # Créer
GET    /evidence/{id}                     # Détail
PATCH  /evidence/{id}                     # Modifier (approved, tags, etc.)
DELETE /evidence/{id}                     # Supprimer
POST   /evidence/{id}/attach              # Pièce jointe
POST   /evidence/merge                    # Fusionner {ids: [...], keep_id: ...}
GET    /evidence/stats                    # Stats globales
GET    /evidence/export                   # Export portable (JSON + docs)
```

---

## UI attendue (career_static/js/evidence-center.js)

- **Grille** : toutes les preuves, filtres (type, confiance, approuvé, utilisé)
- **Détail** : claim, quote, source, document, usage (CV/lettres), actions
- **Actions** : ✅ Approuver | 📎 Attacher | 🔗 Fusionner | 🗑️ Supprimer | 🚫 Bloquer usage
- **Stats** : cartes "Compétences prouvées", "Non prouvées", "Expirées", "Utilisées"

---

## Commandes de validation

```bash
./checklist_codex.sh
.venv/bin/python -m pytest -q tests/test_evidence.py
.venv/bin/python -m pytest -q
git diff --check
```

---

## Critères de réussite

- [ ] `EvidenceCenter` singleton, CRUD complet, recherche, fusion
- [ ] Pièces jointes attachables, usage CV/lettres tracé
- [ ] Fusion doublons (garder 1 ID, merger provenance)
- [ ] Stats globales + par type/confiance
- [ ] Export portable (JSON + docs)
- [ ] Ruff clean, suite complète verte, `git diff --check` propre
- [ ] Rapport `docs/agent-reports/SPEC-008-EVIDENCE_CENTER.md`

---

**Tu as tout. Lance-toi.** Branche `agent/spec-008-evidence-center`, worktree dédié, code, tests, rapport, push. Je relis et j'intègre.