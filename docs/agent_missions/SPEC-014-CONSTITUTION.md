# MISSION SPEC KIT — SPEC-014 : Constitution Exécutable

> **Priorité : P0** — Module transverse, transforme les règles métier en code exécutable et vérifiable. Worktree dédié.

---

## Contexte

Les règles métier (politiques de fraîcheur, seuils de matching, règles de déduplication, politiques de confidentialité) sont aujourd'hui dispersées : dans le code, dans la documentation, dans la tête des développeurs. Il faut une **Constitution Exécutable** : un ensemble de règles formelles, versionnées, testables et exécutables qui servent de source de vérité unique.

---

## Objectif

Créer une **Constitution Exécutable** qui :
1. Centralise toutes les règles métier sous forme formelle (DSL, code, contrats)
2. Rend les règles exécutables (validation auto, tests de conformité)
3. Versionne les règles (historique, rollback, audit)
4. Permet la validation auto à chaque PR/CI
5. Sert de documentation vivante et source de vérité

---

## Nouveaux modules à créer

```
career/constitution.py              # Core: DSL, moteur règles, validation
career/constitution_store.py        # Persistance, versioning, signatures
career/constitution_audit.py        # Conformité, dérive, rapport
career/router.py                    # Endpoints CRUD, validation, audit
career_static/js/constitution.js    # UI éditeur règles, visualisation, tests
tests/test_constitution.py
docs/agent-reports/SPEC-014-CONSTITUTION.md
```

---

## Contrat attendu

### Rule (règle atomique)

```python
@dataclass
class Rule:
    rule_id: str                          # "freshness.certification.max_age"
    name: str                             # "Durée max certification"
    domain: str                           # "freshness" / "matching" / "dedup" / "privacy" / "export"
    version: int
    status: Literal["draft", "active", "deprecated", "archived"]
    description: str                      # Description humaine
    rationale: str                        # Pourquoi cette règle existe
    expression: str                       # Expression DSL (ex: "max_age_days <= 365")
    dsl_type: Literal["cel", "rego", "python", "sql", "json_logic"]
    parameters: dict                      # Paramètres configurables
    scope: list[str]                      # Entités concernées ("evidence", "requirement", "offer")
    tags: list[str]                       # Tags de classification
    created_at: str
    updated_at: str
    created_by: str
    approved_by: str | None
    approved_at: str | None
```

### RuleSet (ensemble cohérent)

```python
@dataclass
class RuleSet:
    ruleset_id: str
    name: str
    version: int
    rules: list[str]                      # rule_ids
    description: str
    effective_from: str
    effective_until: str | None
    supersedes: str | None                # ruleset_id remplacé
```

### ValidationResult

```python
@dataclass
class ValidationResult:
    entity_id: str
    entity_type: str
    rule_id: str
    passed: bool
    details: dict                         # Contexte, valeurs, message
    severity: Literal["info", "warning", "error", "critical"]
    remediation: str | None               # Action corrective suggérée
```

---

## DSL d'expression (CEL - Common Expression Language)

```cel
// Exemples d'expressions CEL
freshness.certification.max_age_days <= 365
matching.score_threshold >= 0.7
dedup.jaro_winkler_threshold >= 0.92
privacy.pii_fields.all(field, field.encrypted == true)
export.docx.max_size_mb <= 10
matching.critical_requirements.all(req, req.covered == true)
```

### Moteur d'évaluation

```python
class ConstitutionEngine:
    def evaluate(self, rule: Rule, context: dict) -> ValidationResult
    def evaluate_all(self, ruleset: RuleSet, entity: dict) -> list[ValidationResult]
    def check_conformance(self, entity: dict, ruleset_id: str) -> ConformanceReport
    def get_violations(self, entity: dict, severity_min: str = "warning") -> list[Violation]
```

---

## Versioning et gouvernance

| Action | Processus |
|--------|-----------|
| **Création** | Draft → Review → Approve → Active |
| **Modification** | Nouveau version + migration auto si compatible |
| **Dépréciation** | Deprecated → période transition → Archived |
| **Urgence** | Hotfix → Active immédiat + review post-hoc |
| **Rollback** | Rollback vers version précédente (instantané) |

### Workflow de validation

```
Draft → Peer Review (1+ approvers) → Security Review (si privacy/security) → Approve → Active
                    ↓
              Auto-tests générés + CI validation
```

---

## Validation automatique (CI/CD)

### Hooks pré-commit / CI

```yaml
# .github/workflows/constitution.yml
jobs:
  validate-constitution:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - name: Validate Constitution
        run: |
          python -m career.constitution validate --all
          python -m career.constitution test --generate-tests
      - name: Check Conformance
        run: |
          python -m career.constitution check --all-entities
```

### Rapports de conformité

```python
@dataclass
class ConformanceReport:
    entity_id: str
    entity_type: str
    ruleset_version: int
    total_rules: int
    passed: int
    warnings: int
    errors: int
    critical: int
    compliance_score: float  # 0.0-1.0
    violations: list[Violation]
    trends: dict[str, float]  # score history
```

---

## Dérive et audit

| Métrique | Seuil alerte |
|----------|--------------|
| **Dérive règles** | > 5% règles modifiées sans review |
| **Couverture tests** | < 90% règles sans test |
| **Violations critiques** | > 0 en production |
| **Drift temps** | Règle non revue depuis > 1 an |

---

## API attendue

```
POST   /constitution/rules                  # Créer règle (draft)
GET    /constitution/rules                  # Liste + filtres
GET    /constitution/rules/{id}             # Détail + historique
PATCH  /constitution/rules/{id}             # Modifier (nouvelle version)
POST   /constitution/rules/{id}/approve     # Approuver → active
POST   /constitution/rules/{id}/deprecate   # Déprécier
POST   /constitution/rulesets               # Créer RuleSet
POST   /constitution/validate               # Valider entité contre ruleset
GET    /constitution/report/{entity_id}     # Rapport conformité entité
GET    /constitution/audit                  # Rapport global conformité
POST   /constitution/test/generate          # Générer tests depuis règles
GET    /constitution/drift                  # Rapport dérive
POST   /constitution/rollback/{ruleset_id}  # Rollback version
```

---

## UI attendue (career_static/js/constitution.js)

- **Éditeur règles** : DSL avec autocomplete, validation temps réel, preview résultat
- **Visualisation graphe** : Règles → Entités → Tests
- **Tableau de bord conformité** : Score global, tendances, top violations
- **Éditeur DSL** : Autocomplete CEL, validation syntaxe, preview résultat
- **Historique** : Timeline versions, diff visuel, rollback 1-clic
- **Audit trail** : Qui a changé quoi, quand, pourquoi

---

## Commandes de validation

```bash
./checklist_codex.sh
.venv/bin/python -m pytest -q tests/test_constitution.py
.venv/bin/python -m pytest -q
git diff --check
```

---

## Critères de réussite

- [ ] DSL CEL supporté + moteur évaluation rapide (<1ms/règle)
- [ ] CRUD règles + versioning + workflow approbation
- [ ] Validation auto entités (offres, profils, preuves, offres, matchings)
- [ ] Tests auto-générés depuis règles (property-based testing)
- [ ] CI intégré : validation PR, rapport conformité, blocage si critique
- [ ] Audit trail complet + détection dérive + alertes
- [ ] Rollback instantané + migration auto compatible
- [ ] UI : éditeur DSL, visualisation graphe, dashboard conformité
- [ ] Intégration SK-01→SK-21, SPEC-011→013 (toutes règles centralisées)
- [ ] Ruff clean, suite complète verte, `git diff --check` propre
- [ ] Rapport `docs/agent-reports/SPEC-014-CONSTITUTION.md`

---

**Tu as tout. Lance-toi.** Branche `agent/spec-014-constitution`, worktree dédié, code, tests, rapport, push. Je relis et j'intègre.