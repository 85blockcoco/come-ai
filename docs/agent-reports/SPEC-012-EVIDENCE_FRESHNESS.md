# SPEC-012 — Fraîcheur des preuves

**Mission** : CVBOOST-47 — module transverse qui date, surveille, alerte et dégrade les preuves du profil candidat (certifications, compétences, langues, expériences, outils, projets, formations).
**Branche** : `worker/cvboost-47-1792684170` (worktree dédié)
**Base** : `main` — `f5b22f2` (`merge(career): ATS diagnostics and targeted CV variants pipeline`)
**Date** : 2026-10-22
**Nature** : 100 % local, déterministe, hors ligne. Aucun appel réseau, aucun modèle, aucune donnée envoyée à un service externe.

---

## 1. Ce que le module apporte

Une preuve du profil vieillit : une certification expire, un outil change de version, une compétence s'efface. Sans surveillance, un CV continue d'afficher une certification périmée comme si elle était valide.

Le module règle cinq problèmes :

1. **Dater** chaque preuve — expiration et fenêtre d'avertissement, calculées depuis la dernière vérification ;
2. **Surveiller** — plan de vérification adapté au type de preuve et à son échéance ;
3. **Alerter** — trois niveaux (`info` / `warning` / `critical`), proportionnés à l'urgence réelle ;
4. **Dégrader** — une preuve expirée est automatiquement abaissée (`covered` → `warning`) ou archivée, selon son importance ;
5. **Mesurer** — tableau de bord, échéances à venir, répartition par type, tendances.

### Règle structurante

> **Le statut n'est jamais une donnée stockée, c'est une date.**

`fresh`, `warning`, `expired` et `archived` sont recalculés à chaque lecture à partir de `expires_at`, `warning_at` et de l'archivage explicite. Une preuve qui a franchi sa date d'expiration est expirée, quelle que soit la valeur écrite la veille. Aucun horodatage illisible n'est jamais remplacé par une date plausible : une date inconnue reste inconnue.

### Deux vocabulaires distincts

Confondre les deux serait mentir sur l'état du dossier :

| Vocabulaire | Question | Valeurs |
|---|---|---|
| `status` (fraîcheur) | Quelle est la vérité sur cette preuve ? | `fresh`, `warning`, `expired`, `archived` |
| `coverage_status` (couverture) | Cette preuve peut-elle encore être proposée dans une candidature ? | `covered`, `warning`, `archived`, `to_reverify` |

Une preuve optionnelle archivée automatiquement après expiration reste **`expired`** côté fraîcheur : seule sa couverture a changé. Le tableau de bord remonte les deux répartitions.

---

## 2. Fichiers

| Fichier | Statut | Rôle |
|---|---|---|
| `career/evidence_freshness.py` | créé | Cœur métier pur : policies, calcul des dates, statuts, alertes, actions automatiques, planification. Aucune horloge implicite, aucun réseau, aucun fichier. |
| `career/evidence_freshness_store.py` | créé | Persistance locale : fichier JSON privé (`0600`) dans `career_data/evidence_freshness/`, écritures atomiques, historique borné, snapshots, plan de vérification. |
| `career/evidence_freshness_audit.py` | créé | Rapports : compteurs, parts, répartition par type, échéances 7/30/90 j, tendances 30/90/365 j, garde d'export. |
| `career/router.py` | modifié | 14 endpoints `/api/career/evidence-freshness/*`. |
| `career/service.py` | modifié | Intégration métier : façade `CareerService`, export de confidentialité, effacement des données. |
| `career_static/js/evidence-freshness.js` | créé | Tableau de bord : état global, échéances, alertes, par type, tendances, preuves suivies, actions groupées, ajout d'une preuve. |
| `career_static/index.html` | modifié | Onglet « Fraîcheur » + section `view-freshness` + chargement du script. |
| `career_static/career.js` | modifié | Enregistrement de la vue, chargement des données, arrêt/reprise du rafraîchissement automatique. |
| `career_static/career.css` | modifié | Styles du tableau de bord (cartes d'état, lignes, tableaux, badge d'export bloqué). |
| `tests/test_evidence_freshness.py` | créé | 59 tests : contrat, règles, alertes, actions, surveillance, persistance, rapports, service, API HTTP, interface. |

---

## 3. Contrat implémenté

### 3.1 Politiques de fraîcheur

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

**Type inconnu** : `policy_for("mystery")` renvoie une policy sans durée ni fenêtre — la preuve n'expire jamais et n'alerte jamais. L'inconnu reste inconnu.

**Priorité des règles** : policy par défaut → override global par type → override individuel sur la preuve.

**Garde-fous de saisie** : une fenêtre d'avertissement plus large que la durée de validité est refusée ; une policy sans durée de validity n'a pas de fenêtre d'avertissement ; une durée négative ou supérieure à 20 000 jours est refusée.

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

@dataclass(frozen=True, slots=True)
class SourceCheck:
    check_id: str
    checked_at: str
    source_url: str | None
    method: Literal["http", "api", "manual", "ocr", "api_partner"]
    result: Literal["unchanged", "updated", "removed", "error"]
    details: dict
```

La preuve stockée conserve en plus son libellé, son importance (`mandatory`), sa source, ses notes, sa couverture, son override de policy, son historique de vérifications et son historique d'actions automatiques. Ces champs sont *hors* du modèle `EvidenceFreshness`, qui reste exactement celui du contrat.

### 3.3 Calcul des dates

* Ancre = `last_verified_at`, sinon `created_at`.
* `expires_at = ancre + max_age_days` ; override manuel prioritaire.
* `warning_at = expires_at − warning_days` ; override manuel prioritaire ; recalculé à partir d'une expiration manuelle.
* Une policy sans `max_age_days` (formation) → **pas d'expiration, pas d'alerte**.

---

## 4. Surveillance, alertes et actions automatiques

### 4.1 Planification

| Fréquence | Cible | Intervalle |
|---|---|---|
| Quotidienne | toute preuve dans sa fenêtre d'avertissement, ou expirant sous 30 jours | 1 j |
| Hebdomadaire | certifications, langues (sous 90 jours) | 7 j |
| Mensuelle | compétences techniques, outils | 30 j |
| Trimestrielle | expériences, projets, formations, compétences comportementales | 90 j |

Une preuve qui n'a jamais été vérifiée est **toujours** due. Le plan est consultable via `GET /api/career/evidence-freshness/schedule`.

### 4.2 Niveaux d'alerte

| Niveau | Déclencheur | Action |
|---|---|---|
| `info` | la preuve entre dans sa fenêtre d'avertissement | notification UI |
| `warning` | la preuve expire dans moins de 7 jours | notification UI + badge |
| `critical` | la preuve est expirée | dégradation automatique + notification + garde d'export |

Une preuve expirée ne lève **qu'une** alerte `critical` : elle ne remonte pas en plus un `info` pour une fenêtre d'avertissement qu'elle a déjà quittée.

### 4.3 Actions automatiques

| Événement | Action appliquée |
|---|---|
| Preuve expirée et **obligatoire** | `covered` → `warning` (elle reste visible et exige une mise à jour) |
| Preuve expirée et **optionnelle** | `covered` → `archived` (elle cesse d'être proposée) |
| Source externe changée (`updated`) | `coverage_status` → `to_reverify`, alerte `warning` |
| Source externe retirée (`removed`) | expiration immédiate à l'instant de la vérification, alerte `critical` |
| Vérification sans changement (`unchanged`) | nouvelle ancre `last_verified_at`, retour à `covered` si la preuve était à revérifier |
| Vérification en erreur (`error`) | **rien** n'est modifié sur la preuve ; seule une alerte `info` sur l'échec de la vérification est levée |

Le cycle de rafraîchissement est **idempotent** : une preuve déjà dégradée n'est pas dégradée deux fois, une alerte ouverte n'est pas dupliquée, et l'historique d'actions ne conserve que les changements d'état (pas une ligne par passage de la surveillance).

### 4.4 Garde d'export

`export_gate` liste les alertes `critical` non acquittées. Tant qu'elles existent, l'interface affiche un bandeau « Export en attente » : un CV qui revendiquerait une certification expirée est signalé plutôt qu'il n'est produit silencieusement. La garde est exposée par l'API (`export_gate` dans `/status` et `/report`) ; le branchement dur sur la génération de dossier est laissé au module `document_export`, hors périmètre de cette mission.

---

## 5. API

Base : `/api/career/evidence-freshness`

| Méthode | Route | Rôle |
|---|---|---|
| `GET` | `/status` | tableau de bord global (compteurs, parts, par type, échéances, alertes, garde d'export, policies, vérifications dues) |
| `GET` | `/evidence` | liste des preuves suivies avec leur fraîcheur |
| `POST` | `/evidence` | ajoute une preuve (201) |
| `GET` | `/evidence/{evidence_id}` | détail : preuve, fraîcheur, alertes, policy effective |
| `PATCH` | `/evidence/{evidence_id}` | override dates / policy / importance / archivage / couverture |
| `DELETE` | `/evidence/{evidence_id}` | cesse de suivre la preuve (et retire ses alertes) |
| `GET` | `/policy` | policies en vigueur, overrides et policies par défaut |
| `POST` | `/policy` | définit la policy d'un type de preuve |
| `POST` | `/check/{evidence_id}` | enregistre une vérification externe (méthode, résultat, source) |
| `GET` | `/alerts` | alertes actives + alertes acquittées |
| `POST` | `/acknowledge/{alert_id}` | acquitte une alerte |
| `GET` | `/schedule` | plan de vérification : dues, fréquences, intervalles |
| `GET` | `/report` | rapport complet : résumé, policies, tendances 30/90/365 j, historique |
| `POST` | `/monitor` | lance la surveillance planifiée (évalue, dégrade, alerte, enregistre un point d'historique) |

Les erreurs métier (`UserFacingError`) sont renvoyées en **400** avec un message lisible ; les erreurs de validation de requête en **422**, sans jamais faire fuiter la charge utile.

---

## 6. Persistance et confidentialité

* Un seul fichier : `career_data/evidence_freshness/evidence_freshness.json`, dans le répertoire privé Career (hors du `data/` général du workspace, donc invisible pour l'agent d'analyse de documents).
* Répertoire en `0700`, fichier en `0600`.
* **Écriture atomique** : fichier temporaire puis `os.replace` — une interruption n laisse jamais un état à moitié écrit.
* Un fichier illisible ou corrompu ne fait pas planter l'application : l'état repart vide plutôt que d'inventer des données.
* **Historique borné** : 400 snapshots maximum, 50 vérifications maximum par preuve, 50 actions automatiques maximum par preuve.
* **Export de confidentialité** : `GET /api/career/privacy-export` inclut désormais `evidence_freshness` (policies, preuves, alertes, snapshots) — la personne peut récupérer ce que le module retient sur elle.
* **Effacement des données** : `DELETE /api/career/data` efface aussi l'état de fraîcheur. Une suppression explicite efface tout, y compris l'historique.

---

## 7. Interface

Nouvel onglet **« Fraîcheur »** dans l'espace Career :

* **Vue globale** — cartes `%` à jour / à vérifier / expirées / archivées ;
* **Échéances** — compteurs 7 / 30 / 90 jours et liste des expirations à venir, triée par urgence ;
* **Alertes** — triées par criticité, avec acquittement en un clic ;
* **Par type** — tableau de répartition (fraîcheur × type de preuve) ;
* **Tendances** — courbe de fraîcheur issue des snapshots réellement enregistrés (aucun point interpolated) ;
* **Preuves suivies** — ligne par ligne : statut, échéance, couverture, vérification manuelle, réactivation ;
* **Actions groupées** — réactiver, étendre le délai, archiver, sur une sélection ;
* **Ajout d'une preuve** — formulaire complet (type, intitulé, source, dernière vérification, importance, note) ;
* **Politiques** — lecture des règles en vigueur par type.

**Temps réel** : rafraîchissement automatique toutes les 60 s tant que l'onglet est ouvert, arrêt dès qu'on le quitte, plus un bouton « Actualiser » et un bouton « Lancer la surveillance ». Un bandeau « Export en attente » s'affiche tant qu'une alerte critique est ouverte.

---

## 8. Tests

`tests/test_evidence_freshness.py` — **59 tests**, fixtures synthétiques, aucune horloge système pour les décisions testées (le « maintenant » est toujours injecté), aucun appel réseau.

| Famille | Couverture |
|---|---|
| Policies | valeurs exactes du contrat, normalisation, fenêtre impossible refusée, override par type |
| Évaluation | fresh → warning → expired, type sans expiration, expiration manuelle, archivage, date illisible |
| Alertes | les trois niveaux, une seule alerte critique par preuve, aucune alerte sur une preuve saine |
| Actions | downgrade obligatoire / archivage optionnel, vérité préservée, idempotence, cycle de rafraîchissement, mode sans écriture |
| Vérifications | source inchangée / modifiée / retirée / en erreur, méthode inconnue refusée |
| Surveillance | fréquence par type, warning zone quotidienne, échéance de vérification |
| Persistance | aller-retour, fichier privé `0600`, pas de doublon d'alerte, acquittement, suppression, fichier corrompu, reset |
| Rapports | compteurs, parts, échéances, répartition, garde d'export, tendances, sérialisation |
| Service | création / mise à jour / suppression, type inconnu refusé, date illisible refusée, sweep, idempotence, policy, vérification manuelle, source retirée, statut, export de confidentialité, effacement |
| API HTTP | les 14 endpoints, message d'erreur lisible, acquittement |
| Interface | onglet et section présents, script chargé, surfaces attendues du module, fenêtres de la timeline |

---

## 9. Validation exécutée

```
$ .venv/bin/python -m ruff check .
All checks passed!

$ .venv/bin/python -m pytest -q tests/test_evidence_freshness.py
59 passed

$ .venv/bin/python -m pytest -q
1483 passed, 1 skipped

$ git diff --check
(clean)
```

Vérification manuelle supplémentaire sur l'application réelle (`create_app`) : les 14 endpoints répondent, `GET /career` et `GET /career-static/js/evidence-freshness.js` répondent `200`, une preuve expirée produit bien une alerte `critical` et bloque l'export.

---

## 10. Limites et suites

1. **Intégration Centre de preuves (SK-08) et Traçabilité (SPEC-011)** — ces deux modules n'existent pas encore dans cette base. Le raccord est **préparé et non simulé** : chaque preuve porte `evidence_center_ref` et `traceability_ref`, et l'API les expose. Quand SK-08 et SPEC-011 arriveront, ils n'auront qu'à poser ces références ; aucun contrat n'est inventé d'ici là.
2. **Garde d'export** — exposée par l'API et affichée dans l'interface, mais pas encore branchée en dur sur la génération du dossier de candidature (`document_export`), qui relève d'un autre module.
3. **Vérification externe automatique** — le module enregistre et interprète les vérifications (`http`, `api`, `manual`, `ocr`, `api_partner`) mais ne déclenche **lui-même** aucun appel réseau : une source externe est consultée par un connecteur existant ou par la personne. Le module ne fait jamais de requête à la place du réseau local.
4. **Email / push** — les niveaux d'alerte sont conçus pour être branchés plus tard sur les canaux de notification ; rien n'est envoyé aujourd'hui.
5. **Étape du planning** — le plan de vérification est consultable et l'endpoint `/monitor` est idempotent, mais l'exécution périodique dépend du driver de mission existant, pas d'un ordonnanceur interne.

---

## 11. Note de coordination

Une implémentation antérieure de cette mission existe sur la branche distante `agent/spec-012-evidence-freshness` (poussée par un run antérieur, `f1fb213`). Elle est complète sur le contrat mais **n'intègre pas** la couche `CareerService` : le stockage y est instancié dans le routeur, ce qui exclut l'export de confidentialité et l'effacement des données, deux garde-fous que ce projet considère comme non négociables. Cette branche-ci passe par `CareerService` et couvre ces deux points ; c'est la principale différence structurante à l'intégration.
