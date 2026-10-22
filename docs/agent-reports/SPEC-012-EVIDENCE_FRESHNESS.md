# SPEC-012 — Fraîcheur des preuves (CVBOOST-47)

**Mission** : module transverse de fraîcheur des preuves du profil candidat — expiration, révision, surveillance planifiée, alertes proactives et dégradation automatique des preuves obsolètes. 100 % local, déterministe, hors ligne.

**Branche** : `worker/cvboost-47-1792667223`
**Base** : `main` (`f5b22f2`)
**Livrables** : 3 modules Python, 12 endpoints HTTP, 1 tableau de bord, 52 tests, ce rapport.

---

## 1. Pourquoi ce module

Les preuves d'un profil (certifications, compétences, langues, expériences) vieillissent : une certification expire, une compétence se périme, un outil change de version. Un module de fraîcheur permet de :

1. **dater** chaque preuve (expiration + fenêtre d'avertissement) ;
2. **surveiller** les preuves selon une fréquence adaptée au type et à l'échéance ;
3. **alerter** avant que la preuve ne devienne inutilisable ;
4. **dégrader** automatiquement une preuve expirée (couverture `covered` → `warning`, ou archivage) ;
5. **mesurer** la fraîcheur globale et son évolution.

Règle structurante : **le statut n'est jamais une donnée stockée, c'est une date**. `fresh`, `warning`, `expired` et `archived` sont recalculés à chaque lecture à partir de `expires_at`, `warning_at` et de l'indicateur d'archivage. Une preuve qui a franchi sa date d'expiration est expirée, quelle que soit la valeur écrite auparavant.

---

## 2. Fichiers

| Fichier | Rôle |
|---------|------|
| `career/evidence_freshness.py` | Cœur métier pur : policies, dates, statuts, alertes, actions automatiques, plan de surveillance. Aucune horloge implicite, aucun réseau, aucun fichier. |
| `career/evidence_freshness_store.py` | Persistance locale : un fichier JSON privé (`0600`) dans `career_data/evidence_freshness/`, écritures atomiques, historique borné, snapshots quotidiens, refresh et planification. |
| `career/evidence_freshness_audit.py` | Rapports : compteurs, parts, répartition par type, timeline 7/30/90 jours, tendances 30/90/365 jours, historique de vérification, rendu Markdown. |
| `career/router.py` | 12 endpoints `/api/career/evidence-freshness/*` (CRUD, policy, monitoring, alertes, rapport). |
| `career_static/js/evidence-freshness.js` | Tableau de bord : vue globale, timeline, alertes, par type, tendances, plan de contrôle, registre, formulaire d'ajout, panneau de policy, actions rapides et actions batch. |
| `career_static/index.html` | Onglet « Fraîcheur des preuves » + section `view-evidence-freshness` + chargement du script. |
| `tests/test_evidence_freshness.py` | 52 tests (contrat, actions automatiques, alertes, surveillance, persistance, rapports, API HTTP, interface, pureté). |

---

## 3. Contrat

### 3.1 Politiques par type de preuve

Les huit policies sont exactement celles du contrat SPEC-012 :

```python
FRESHNESS_POLICIES = {
    "certification":   {"max_age_days": 365,  "warning_days": 30,  "auto_expire": True},
    "skill_technical": {"max_age_days": 730,  "warning_days": 90,  "auto_expire": False},
    "skill_soft":      {"max_age_days": 1095, "warning_days": 180, "auto_expire": False},
    "experience":      {"max_age_days": 1825, "warning_days": 365, "auto_expire": False},
    "education":       {"max_age_days": None,  "warning_days": None, "auto_expire": False},
    "language":        {"max_age_days": 730,  "warning_days": 90,  "auto_expire": True},
    "tool":            {"max_age_days": 730,  "warning_days": 90,  "auto_expire": False},
    "project":         {"max_age_days": 1095, "warning_days": 180, "auto_expire": False},
}
```

* `max_age_days` — durée de validité depuis la dernière vérification ;
* `warning_days` — durée de la fenêtre d'avertissement avant l'expiration ;
* `auto_expire` — le module a-t-il le droit de dégrader seul une preuve expirée.

**Type inconnu** : l'inconnu reste inconnu. `policy_for("mystery")` renvoie une policy sans durée ni fenêtre : la preuve n'expire jamais et n'alerte jamais. Une policy est modifiable par type (override global) et par preuve (override local), avec priorité : base → override global → override local.

### 3.2 Structures de données

```python
@dataclass(frozen=True, slots=True)
class EvidenceFreshness:
    evidence_id: str
    evidence_type: str
    created_at: str
    last_verified_at: str | None
    expires_at: str | None
    warning_at: str | None
    status: Literal["fresh", "warning", "expired", "archived"]
    source_checks: list[SourceCheck]
    auto_actions: list[str]
    # extensions optionnelles (toutes avec une valeur par défaut)
    title: str = ""
    mandatory: bool = False
    source_url: str = ""
    coverage_status: str = "unknown"     # covered | warning | archived | unknown
    needs_reverification: bool = False
    archived: bool = False
    dates_pinned: bool = False
    policy_override: dict = {}
    notes: str = ""

@dataclass(frozen=True, slots=True)
class SourceCheck:
    check_id: str
    checked_at: str
    source_url: str | None
    method: Literal["http", "api", "manual", "ocr", "api_partner"]
    result: Literal["unchanged", "updated", "removed", "error"]
    details: dict

@dataclass(frozen=True, slots=True)
class FreshnessAlert:
    alert_id: str
    evidence_id: str
    evidence_type: str
    level: Literal["info", "warning", "critical"]
    kind: str
    title: str
    message: str
    created_at: str
    expires_at: str | None = None
    acknowledged: bool = False
    acknowledged_at: str | None = None

@dataclass(frozen=True, slots=True)
class ScheduledCheck:
    evidence_id: str
    evidence_type: str
    title: str
    cadence: str          # daily | weekly | monthly | quarterly
    due_at: str
    days_until_due: int
    overdue: bool
    priority: str         # high | normal
    reason: str
    source_url: str = ""
```

Les neuf premiers champs de `EvidenceFreshness` sont ceux du contrat SPEC-012 ; les champs suivants sont des extensions optionnelles, toutes dotées d'une valeur par défaut.

### 3.3 Identifiants déterministes

* `alert_<sha256(evidence_id|kind|expires_at)[:16]>` — une preuve expirée, renouvelée puis re-expirée produit deux alertes distinctes ; la même situation produit toujours la même alerte.
* `chk_<sha256(evidence_id|checked_at|method|result)[:16]>` — idem pour les vérifications.

Aucun identifiant ne dépend d'une horloge, d'un aléa ou du réseau.

---

## 4. Surveillance

| Cadence | Cible | Règle implémentée |
|---------|-------|--------------------|
| Quotidienne | Preuves en zone d'avertissement | reste ≤ 30 jours avant l'échéance |
| Hebdomadaire | Certifications, langues | reste ≤ 90 jours avant l'échéance |
| Mensuelle | Compétences techniques, outils, langues, certifications | cadence de base du type |
| Trimestrielle | Expériences, projets, diplômes | cadence de base du type |

`resolve_cadence(preuve, now)` applique ces règles dans l'ordre : quotidien si l'échéance est dans moins de 30 jours, hebdomadaire pour une certification ou une langue qui expire dans moins de 90 jours, sinon la cadence de base du type (mensuelle ou trimestrielle).

`plan_check` calcule la prochaine vérification à partir de la dernière vérification enregistrée (ou de la date de création), signale les retards (`overdue`) et les preuves à échéance proche (`priority: high`).

---

## 5. Alertes et actions automatiques

### 5.1 Niveaux d'alerte

| Niveau | Déclencheur | Identifiant d'alerte |
|--------|-------------|----------------------|
| `info` | la preuve entre dans sa fenêtre d'avertissement | `entered_warning_zone` |
| `warning` | la preuve expire dans moins de 7 jours | `expiring_soon` |
| `critical` | la preuve est expirée (ou révoquée) | `expired` |

L'alerte critique est levée sur la **date**, pas sur le statut : une preuve optionnelle archivée automatiquement pour expiration reste signalée critique. Les alertes sont **matérialisées** dans le store (idempotentes) : un refresh répété ne duplique rien, et une alerte acquittée ne ressuscite pas au refresh suivant.

### 5.2 Actions automatiques

| Événement | Action | Code enregistré |
|-----------|--------|------------------|
| Preuve expirée, obligatoire | couverture `covered` → `warning`, export bloqué | `downgrade_to_warning` |
| Preuve expirée, optionnelle | archivage (`archived`, couverture `archived`) | `archive_expired` |
| Preuve expirée, policy sans `auto_expire` | rien n'est dégradé, l'expiration est signalée | `expired_no_auto_action` |
| Source externe modifiée | preuve marquée `to_reverify` | `to_reverify` |
| Source disparue / certification révoquée | expiration immédiate (`expires_at = now`) | `revoked` |
| Preuve vérifiée sans changement | le compteur repart de la vérification | `verified` |
| Preuve réactivée | nouveau `last_verified_at`, nouvelles dates | `reactivated` |
| Échéance prolongée | dates décalées, dates épinglées | `extended_expiry` |

`blocks_export(preuve)` renvoie vrai pour une preuve **obligatoire** expirée : c'est le point de raccord avec le registre de traçabilité (SPEC-011) et avec le pipeline d'export de CV.

---

## 6. API HTTP

Préfixe : `/api/career/evidence-freshness` (convention du dépôt : toutes les routes Career sont sous `/api/career`).

| Méthode | Route | Rôle |
|---------|-------|------|
| `GET` | `/status` | Tableau de bord global : rapport, preuves, alertes actives, plan de surveillance, policies |
| `GET` | `/evidence` | Liste des preuves (filtres `status`, `evidence_type`) |
| `POST` | `/evidence` | Enregistre une preuve (201) |
| `GET` | `/evidence/{id}` | Détail d'une preuve + ses alertes |
| `PATCH` | `/evidence/{id}` | Override des dates, du titre, du flag obligatoire, archivage, réactivation, prolongation, policy locale |
| `DELETE` | `/evidence/{id}` | Supprime la preuve et ses alertes |
| `GET` | `/policy` | Policies de tous les types |
| `POST` | `/policy` | Override (ou reset) de la policy d'un type |
| `POST` | `/check/{id}` | Vérification manuelle (ou `http`, `api`, `ocr`, `api_partner`) |
| `GET` | `/alerts` | Alertes actives (ou toutes avec `active_only=false`) |
| `POST` | `/acknowledge/{alert_id}` | Acquitte une alerte |
| `GET` | `/schedule` | Plan de surveillance |
| `GET` | `/report` | Audit complet : rapport, tendances, historique de vérification, version Markdown |

Erreurs : `400` avec un message français (`UserFacingError`) pour une date illisible, une méthode de vérification inconnue ou une policy incohérente ; `404` (`Preuve introuvable.`) pour un identifiant inconnu.

Exemple :

```bash
curl -s http://127.0.0.1:8000/api/career/evidence-freshness/status | jq '.report.totals'
```

---

## 7. Tableau de bord

`career_static/js/evidence-freshness.js` (922 lignes, JavaScript natif, sans framework ni build) ajoute un onglet « Fraîcheur des preuves » :

* **vue globale** — compteurs fresh / warning / expired / archived et parts ;
* **timeline** — expirations à 7, 30 et 90 jours ;
* **alertes** — triées par criticité, acquittement en un clic ;
* **par type** — répartition fresh / warning / expired / archived ;
* **tendances** — courbes 30 / 90 / 365 jours reconstruites depuis les relevés quotidiens + phrase de synthèse (« Fraîcheur : 62 % → 71 % sur 30 j ») ;
* **plan de contrôle** — cadence, échéance, retard ;
* **registre** — les preuves avec actions rapides (Vérifier, Réactiver, Archiver, Prolonger de 30 jours, Supprimer) ;
* **formulaire** d'ajout et **panneau de policy** par type.

Le tableau de bord est « temps réel » : il se recharge à l'ouverture de l'onglet, après chaque action et toutes les 60 secondes quand la vue est visible et que l'onglet du navigateur est actif (aucun appel n'est fait dans le dos de l'utilisateur, aucun appel hors de cette vue).

Le fichier est autonome : il ne modifie pas `career.js`, n'utilise que des appels same-origin, n'injecte jamais de donnée utilisateur en `innerHTML` et n'envoie rien à un tiers.

---

## 8. Persistance et confidentialité

* un seul fichier : `career_data/evidence_freshness/evidence_freshness.json` ;
* dossier en `0700`, fichier en `0600` (aucun autre utilisateur ne peut le lire) ;
* écriture **atomique** : fichier temporaire dans le même dossier, `fsync`, puis `os.replace` — une écriture interrompue ne peut pas tronquer l'état ;
* schéma versionné : un fichier écrit par une version plus récente est refusé, jamais réinterprété ;
* historique borné à 500 événements (le plus récent en fin de liste) ;
* aucun secret, aucune donnée personnelle réelle dans les fixtures de test.

---

## 9. Intégration SK-08 / SPEC-011

Le registre de traçabilité (SPEC-011, branche `agent/spec-012-evidence-freshness` voisine) et l'Evidence Center (SK-08) **ne sont pas présents sur cette branche de base** : ce sont des missions parallèles, non mergées. L'intégration n'est donc pas un import direct mais un **contrat de données stable**, documenté et testé :

| Consommateur | Ce que le module expose |
|--------------|---------------------------|
| Registre de traçabilité (SPEC-011) | `coverage_status` (`unknown` / `covered` / `warning` / `archived`) — vocabulaire identique à celui de la couverture d'une exigence ; `blocks_export` pour la preuve obligatoire expirée ; `needs_reverification` pour la preuve à revérifier. |
| Evidence Center (SK-08) | `needs_reverification` (état « to_reverify » du contrat), `source_checks` (historique des vérifications), `auto_actions` (ce que le module a fait tout seul). |
| Profil candidat (SK-10) | `evidence_type` couvre `certification`, `skill_technical`, `skill_soft`, `experience`, `education`, `language`, `tool`, `project` — les faits SK-10 (skill, experience, education, language, project, certification) s'y rangent directement. |

Quand les modules traceability / evidence_center landed, le raccord se fera par ce vocabulaire, sans migration du fichier local : `coverage_status` est déjà le champ que le registre consomme.

---

## 10. Tests

```bash
.venv/bin/python -m pytest -q tests/test_evidence_freshness.py   # 52 passed
.venv/bin/python -m pytest -q                                    # suite complète : 1521 passed, 1 skipped
.venv/bin/python -m ruff check .                                 # All checks passed
git diff --check                                                # propre
```

Couverture (52 tests) :

* **contrat** — les 8 policies sont figées par un test d'égalité stricte ; type inconnu qui n'expire jamais ; hiérarchie des overrides ; validation des valeurs de policy ; calcul des dates ; transitions `fresh → warning → expired` aux boundaries exactes ; dates épinglées qui résistent à un changement de policy ;
* **actions automatiques** — downgrade d'une preuve obligatoire, archivage d'une preuve optionnelle, expiration sans `auto_expire` (constatée mais rien n'est dégradé), révocation immédiate, source modifiée → `to_reverify`, vérification sans changement → compteur relancé, réactivation, prolongation ;
* **alertes** — les 3 niveaux, identifiants déterministes, pas de doublon au refresh, acquittement stable ;
* **surveillance** — cadence quotidienne / hebdomadaire / mensuelle / trimestrielle, plan trié par urgence ;
* **persistance** — round-trip, permissions `0600`/`0700`, refus d'un schéma plus récent, historique borné, recalcul des dates non épinglées après changement de policy, suppression en cascade des alertes, snapshots alimentant les tendances, écriture atomique sans fichier temporaire résiduel ;
* **rapports** — compteurs, parts, buckets de timeline, tendances 30/365 j, historique de vérification, rendu Markdown ;
* **API HTTP** — cycle complet d'une preuve, override des dates, policy locale, policy par type, vérification manuelle, révocation par une source disparue, rejet d'une méthode inconnue, rejet d'un type hors contrat, filtres de liste, alerte critique acquittable, rapport, 404 sur identifiant inconnu, 400 sur date illisible ;
* **interface et pureté** — le script existe et est branché dans `index.html` ; le cœur du module ne contient ni `datetime.now`, ni `time.time`, ni accès réseau ; le round-trip de sérialisation conserve tous les champs du contrat.

---

## 11. Limites assumées

* La vérification externe est **déclarative** : le module enregistre et applique le résultat d'un contrôle (`http`, `api`, `manual`, `ocr`, `api_partner`), il n'appelle aucun fournisseur lui-même — la mission impose un module local.
* Les tendances ne sont aussi fines que les relevés quotidiens : une application installée aujourd'hui n'a pas d'historique, l'absence de relevé n'est jamais présentée comme une preuve de fraîcheur.
* Le « blocage d'export » est exposé comme un fait (`blocks_export`) ; brancher ce fait sur le pipeline d'export de CV relève de la mission d'export, pas de celle-ci.
* Les preuves ne sont pas encore synchronisées automatiquement avec le profil candidat (SK-10) : l'import automatique est laissé à l'intégration des deux modules.
