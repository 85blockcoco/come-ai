# MISSION SPEC KIT — SPEC-016 : Automatisation Contrôlée

> **Priorité : P1** — Module transverse, orchestration d'automatismes avec garde-fous, validation humaine, audit. Worktree dédié.

---

## Contexte

L'automatisation existe déjà par fragments : extraction CV (SK-01), matching (SK-21), kit candidature (SK-11), déduplication (SK-06/SK-06), monitoring (SPEC-006). Mais ces automatismes sont isolés, sans coordination, sans validation humaine centralisée, sans audit unifié. Il faut une **couche d'orchestration contrôlée** qui coordonne, valide, audite et permet l'intervention humaine aux points critiques.

---

## Objectif

Créer une **couche d'orchestration contrôlée** qui :
1. Orchestre les automatismes existants (pipelines, workflows, tâches planifiées)
2. Impose des points de validation humaine aux points critiques
3. Garantit l'audit trail complet (qui, quoi, quand, pourquoi, décision)
4. Fournit des garde-fous : seuils, timeouts, rollback, circuit breakers
5. Offre un tableau de bord unique de supervision

---

## Nouveaux modules à créer

```
career/controlled_automation.py       # Core: orchestrateur, politiques, garde-fous
career/automation_policy.py           # Politiques: seuils, timeouts, validation points
career/automation_audit.py            # Audit trail, conformité, dérive
career/automation_dashboard.py        # Dashboard supervision temps réel
career/router.py                      # Endpoints orchestration, validation, audit
career_static/js/automation-dashboard.js # UI supervision, validation, audit
tests/test_controlled_automation.py
docs/agent-reports/SPEC-016-CONTROLLED_AUTOMATION.md
```

---

## Contrat attendu

### AutomationPolicy (politique d'automatisation)

```python
@dataclass
class AutomationPolicy:
    policy_id: str
    name: str
    domain: Literal["extraction", "matching", "dedup", "enrichment", "export", "monitoring", "all"]
    version: int
    status: Literal["draft", "active", "paused", "deprecated"]
    
    # Déclencheurs
    triggers: list[Trigger]             # schedule, event, manual, webhook
    
    # Étapes du pipeline
    steps: list[PipelineStep]
    
    # Garde-fous
    guardrails: Guardrails
    
    # Validation humaine
    human_checkpoints: list[HumanCheckpoint]
    
    # Audit
    audit_level: Literal["minimal", "standard", "full"]
    retention_days: int
```

### PipelineStep (étape de pipeline)

```python
@dataclass
class PipelineStep:
    step_id: str
    name: str
    type: Literal["extraction", "enrichment", "validation", "transformation", "export", "notification", "human_review"]
    handler: str                        # Fonction/module à appeler
    input_schema: dict                  # Schéma entrée (JSON Schema)
    output_schema: dict                 # Schéma sortie
    timeout_seconds: int
    retry_policy: RetryPolicy
    dependencies: list[str]             # step_ids dont dépend cette étape
    condition: str | None               # Expression CEL pour exécution conditionnelle
    on_failure: Literal["stop", "continue", "retry", "fallback", "alert"]
    fallback_step_id: str | None
```

### Guardrails (garde-fous)

```python
@dataclass
class Guardrails:
    max_execution_time_seconds: int
    max_retries: int
    max_concurrent_executions: int
    max_data_volume_mb: int
    forbidden_operations: list[str]     # Ex: "send_email", "delete_data", "external_api_call"
    data_classification_required: bool  # Exige classification données avant exécution
    pii_handling: Literal["strip", "mask", "encrypt", "block"]
    circuit_breaker: CircuitBreakerConfig
    rate_limits: dict[str, int]         # Par endpoint/API
    cost_limit_usd: float | None        # Limite coûts cloud/LLM
```

### HumanCheckpoint (point de validation humaine)

```python
@dataclass
class HumanCheckpoint:
    checkpoint_id: str
    step_id: str                        # Étape concernée
    trigger: Literal["always", "on_failure", "on_warning", "on_threshold", "manual"]
    threshold_config: dict | None       # Ex: {"error_rate": 0.05, "data_volume_mb": 100}
    required_approvers: int
    approver_roles: list[str]           # ["reviewer", "domain_expert", "legal", "security"]
    timeout_hours: int
    escalation: EscalationConfig
    required_fields: list[str]          # Champs obligatoires pour validation
    veto_power: bool                    # Un rejet suffit à bloquer
```

---

## Orchestrateur central

### AutomationOrchestrator

```python
class AutomationOrchestrator:
    def submit_workflow(self, policy_id: str, input_data: dict, context: dict) -> WorkflowExecution
    def get_execution(self, execution_id: str) -> WorkflowExecution
    def pause_execution(self, execution_id: str, reason: str)
    def resume_execution(self, execution_id: str)
    def cancel_execution(self, execution_id: str, reason: str)
    def approve_checkpoint(self, execution_id: str, checkpoint_id: str, approver: str, decision: Literal["approve", "reject", "request_changes"], comment: str)
    def get_dashboard_data(self) -> DashboardData
```

### WorkflowExecution (exécution en cours)

```python
@dataclass
class WorkflowExecution:
    execution_id: str
    policy_id: str
    status: Literal["pending", "running", "paused", "waiting_human", "completed", "failed", "cancelled", "rolled_back"]
    current_step: str | None
    started_at: str
    updated_at: str
    completed_at: str | None
    input_data: dict
    context: dict
    step_results: dict[str, StepResult]
    human_decisions: list[HumanDecision]
    audit_trail: list[AuditEvent]
    metrics: ExecutionMetrics
```

---

## Points de validation humaine (Human-in-the-Loop)

| Point de contrôle | Déclencheur | Approbateurs | Délai | Veto |
|-------------------|-------------|--------------|-------|------|
| **Envoi candidature** | Toujours | User | 24h | Oui |
| **Envoi email recruteur** | Toujours | User | 4h | Oui |
| **Suppression données** | Toujours | User + Legal | 1h | Oui |
| **Modification règle Constitution** | Seuil critique | Domain Expert + Security | 24h | Oui |
| **Déploiement production** | Deploy | Lead + Security | 1h | Oui |
| **Seuil erreur dépassé** | > 5% erreurs | Domain Expert | 2h | Non |
| **Volume données > seuil** | > 100MB | Data Owner | 4h | Oui |
| **Coût cloud > seuil** | > $50/jour | FinOps + Lead | 4h | Non |

### Décision humaine

```python
@dataclass
class HumanDecision:
    decision_id: str
    execution_id: str
    checkpoint_id: str
    decider: str
    decision: Literal["approve", "reject", "request_changes", "defer"]
    comment: str
    decided_at: str
    metadata: dict
```

---

## Garde-fous techniques (Circuit Breakers, Rate Limits, etc.)

| Garde-fou | Configuration par défaut | Action |
|-----------|--------------------------|--------|
| **Circuit Breaker** | 5 échecs en 1min → open 5min | Stop exécution, alerte |
| **Rate Limit API** | 100 req/min par endpoint | Queue + retry exponentiel |
| **Timeout Global** | 2h par workflow | Cancel + alert |
| **Timeout Étape** | 30min par étape | Retry ou fallback |
| **Volume Données** | 100MB par exécution | Pause + validation humaine |
| **Coût Cloud** | $10/jour par policy | Pause + approbation FinOps |
| **Erreurs Consécutives** | 3 échecs → pause | Alert + pause |
| **Dérive Données** | Schema validation fail | Stop + alerte |

---

## Audit Trail complet

### AuditEvent (immuable)

```python
@dataclass
class AuditEvent:
    event_id: str
    timestamp: str
    execution_id: str | None
    event_type: Literal[
        "workflow_started", "step_started", "step_completed", "step_failed",
        "human_checkpoint_created", "human_decision_made", "guardrail_triggered",
        "circuit_breaker_opened", "circuit_breaker_closed", "rollback_initiated",
        "policy_changed", "policy_activated", "policy_deactivated"
    ]
    actor: Literal["system", "user", "scheduler", "webhook"]
    actor_id: str
    details: dict
    severity: Literal["info", "warning", "error", "critical"]
    correlation_id: str  # Pour tracer workflows liés
```

---

## Dashboard de supervision (temps réel)

### Vue d'ensemble

| Métrique | Temps réel | Historique |
|----------|------------|------------|
| **Workflows actifs** | ✅ | 24h/7j/30j |
| **Taux succès/échec** | ✅ | Courbes |
| **Temps moyen exécution** | ✅ | Percentiles |
| **Points d'attente humaine** | ✅ | File d'attente |
| **Garde-fous déclenchés** | ✅ | Compteurs |
| **Circuit breakers** | État temps réel | Historique |
| **Coûts** | Temps réel | Quotidien/mensuel |

### Vues détaillées

| Vue | Contenu |
|-----|---------|
| **Live Executions** | Liste temps réel, filtres, actions (pause, cancel, view) |
| **Human Queue** | Points d'attente, assignés, temps écoulé, actions |
| **Guardrails** | État circuit breakers, rate limits, alertes |
| **Audit Trail** | Recherche, filtres, export, corrélation |
| **Policies** | État, métriques, versions, actions |

---

## API attendue

```
POST   /automation/workflows                # Soumettre workflow
GET    /automation/workflows/{id}           # Détails exécution
POST   /automation/workflows/{id}/pause     # Pause
POST   /automation/workflows/{id}/resume    # Reprendre
POST   /automation/workflows/{id}/cancel    # Annuler
POST   /automation/checkpoints/{id}/decide  # Décision humaine
GET    /automation/dashboard                # Données dashboard
GET    /automation/audit                    # Audit trail (filtres, export)
GET    /automation/policies                 # Politiques
POST   /automation/policies                 # Créer politique
PATCH  /automation/policies/{id}            # Modifier politique
POST   /automation/policies/{id}/activate   # Activer
POST   /automation/policies/{id}/pause      # Pause politique
GET    /automation/metrics                  # Métriques agrégées
```

---

## UI attendue (career_static/js/automation-dashboard.js)

- **Live Board** : Exécutions en temps réel, cartes par workflow
- **Human Queue** : File d'attente validation, assignation, SLA
- **Guardrails Panel** : Circuit breakers, rate limits, alertes temps réel
- **Audit Explorer** : Recherche full-text, filtres, timeline, export
- **Policy Manager** : CRUD politiques, versioning, activation, tests
- **Metrics Dashboard** : Graphiques temps réel, alertes, tendances

---

## Commandes de validation

```bash
./checklist_codex.sh
.venv/bin/python -m pytest -q tests/test_controlled_automation.py
.venv/bin/python -m pytest -q
git diff --check
```

---

## Critères de réussite

- [ ] Orchestrateur ThreadPool/async gérant 10+ workflows parallèles
- [ ] Politiques configurables : triggers, étapes, garde-fous, checkpoints
- [ ] Garde-fous : circuit breakers, rate limits, timeouts, coûts
- [ ] Points de validation humaine : configuration flexible, SLA, escalade
- [ ] Audit trail immuable, complet, interrogeable, exportable
- [ ] Dashboard temps réel : live executions, human queue, guardrails, metrics
- [ ] Rollback workflow + compensation transactions
- [ ] Intégration SK-01→SK-21, SPEC-001→015 (tous automatismes)
- [ ] Ruff clean, suite complète verte, `git diff --check` propre
- [ ] Rapport `docs/agent-reports/SPEC-016-CONTROLLED_AUTOMATION.md`

---

**Tu as tout. Lance-toi.** Branche `agent/spec-016-controlled-automation`, worktree dédié, code, tests, rapport, push. Je relis et j'intègre.