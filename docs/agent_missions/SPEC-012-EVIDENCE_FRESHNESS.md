# MISSION SPEC KIT — SPEC-012 : Fraîcheur des Preuves

> **Priorité : P0** — Module transverse, garantit que les preuves utilisées sont à jour. Worktree dédié.

---

## Contexte

Les preuves du profil candidat (SK-10) et les exigences des offres (SK-02) peuvent devenir obsolètes : changement de poste, nouvelles compétences, expiration de certifications, évolution des technologies. Il faut un **système de fraîcheur** qui surveille, alerte et gère l'expiration des preuves.

---

## Objectif

Créer un **module de fraîcheur des preuves** qui :
1. Attribue une date d'expiration ou de révision à chaque EvidenceItem
2. Surveille les changements externes (nouvelles versions, expiration certifications)
3. Alerte proactivement quand une preuve devient obsolète
4. Dégrade automatiquement le statut des preuves expirées
5. Fournit un dashboard de fraîcheur

---

## Nouveaux modules à créer

```
career/evidence_freshness.py        # Core: politiques, surveillance, alertes
career/evidence_freshness_store.py  # Persistance, planification, historique
career/evidence_freshness_audit.py  # Rapports fraîcheur, tendances
career/router.py                    # Endpoints CRUD, monitoring, alertes
career_static/js/evidence-freshness.js # UI dashboard, alertes, actions
tests/test_evidence_freshness.py
docs/agent-reports/SPEC-012-EVIDENCE_FRESHNESS.md
```

---

## Contrat attendu

### Policy de fraîcheur par type de preuve

```python
FRESHNESS_POLICIES = {
    "certification": {"max_age_days": 365, "warning_days": 30, "auto_expire": True},
    "skill_technical": {"max_age_days": 730, "warning_days": 90, "auto_expire": False},
    "skill_soft": {"max_age_days": 1095, "warning_days": 180, "auto_expire": False},
    "experience": {"max_age_days": 1825, "warning_days": 365, "auto_expire": False},
    "education": {"max_age_days": None, "warning_days": None, "auto_expire": False},
    "language": {"max_age_days": 730, "warning_days": 90, "auto_expire": True},
    "tool": {"max_age_days": 730, "warning_days": 90, "auto_expire": False},
    "project": {"max_age_days": 1095, "warning_days": 180, "auto_expire": False},
}
```

### EvidenceFreshness (étendu EvidenceItem)

```python
@dataclass
class EvidenceFreshness:
    evidence_id: str
    evidence_type: str
    created_at: str
    last_verified_at: str | None
    expires_at: str | None
    warning_at: str | None
    status: Literal["fresh", "warning", "expired", "archived"]
    source_checks: list[SourceCheck]
    auto_actions: list[str]  # actions déclenchées (downgrade, alert, archive)
```

### SourceCheck (vérification externe)

```python
@dataclass
class SourceCheck:
    check_id: str
    checked_at: str
    source_url: str | None
    method: Literal["http", "api", "manual", "ocr", "api_partner"]
    result: Literal["unchanged", "updated", "removed", "error"]
    details: dict
```

---

## Surveillance et alertes

### Vérifications planifiées

| Fréquence | Cible |
|-----------|-------|
| Quotidienne | Preuves en warning (expiration < 30j) |
| Hebdomadaire | Certifications, langues (expiration < 90j) |
| Mensuelle | Compétences techniques, outils |
| Trimestrielle | Expériences, projets, diplômes |

### Alertes

| Niveau | Déclencheur | Action |
|--------|-------------|--------|
| **Info** | Preuve entre dans warning zone | Notification UI, email optionnel |
| **Warning** | Preuve expire dans < 7j | Notification UI + email, badge UI |
| **Critical** | Preuve expirée | Downgrade auto (covered → warning), notification push, blocage export si critique |

---

## Actions automatiques

| Événement | Action |
|-----------|--------|
| Preuve expire | `covered` → `warning` (si mandatory) / `archived` (si optional) |
| Source externe changée | Marquer `to_reverify`, créer SourceCheck |
| Certification révoquée | `expired` immédiat, alerte critical |
| Preuve réactivée | Reset timer, new `last_verified_at` |

---

## API attendue

```
GET    /evidence-freshness/status              # Dashboard global
GET    /evidence-freshness/evidence/{id}       # Détail fraîcheur
POST   /evidence-freshness/policy              # Définir policy par type
PATCH  /evidence-freshness/evidence/{id}       # Override dates, policy
POST   /evidence-freshness/check/{id}          # Déclencher vérification manuelle
GET    /evidence-freshness/alerts              # Alertes actives
POST   /evidence-freshness/acknowledge/{alert_id} # Acquitter alerte
GET    /evidence-freshness/report              # Rapport fraîcheur global
```

---

## Dashboard UI attendu

- **Vue globale** : % fresh / warning / expired / archived
- **Timeline** : Expirations à venir (7j, 30j, 90j)
- **Alertes** : Liste triée par criticité, actions rapides
- **Par type** : Répartition par evidence_type
- **Tendances** : Courbes fraîcheur sur 30/90/365j
- **Actions batch** : Réactiver, archiver, étendre délai

---

## Commandes de validation

```bash
./checklist_codex.sh
.venv/bin/python -m pytest -q tests/test_evidence_freshness.py
.venv/bin/python -m pytest -q
git diff --check
```

---

## Critères de réussite

- [ ] Policies configurables par evidence_type
- [ ] Surveillance planifiée + vérification manuelle
- [ ] Alertes 3 niveaux (info/warning/critical) + auto-actions
- [ ] Downgrade auto des preuves expirées (configurable)
- [ ] Dashboard temps réel + alertes temps réel
- [ ] Historique vérifications + tendances
- [ ] Intégration EvidenceCenter (SK-08) + Traceability (SPEC-011)
- [ ] Ruff clean, suite complète verte, `git diff --check` propre
- [ ] Rapport `docs/agent-reports/SPEC-012-EVIDENCE_FRESHNESS.md`

---

**Tu as tout. Lance-toi.** Branche `agent/spec-012-evidence-freshness`, worktree dédié, code, tests, rapport, push. Je relis et j'intègre.