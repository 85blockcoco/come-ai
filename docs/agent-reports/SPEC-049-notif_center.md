# SPEC-049 — Centre de notifications et relances dues

- **Mission** : CVBOOST-86
- **Branche** : `agent/spec-049-notif_center`
- **Périmètre** : interface bureau `/app` (`desktop_static/`)
- **Date** : 2026-10-26
- **Statut** : livré

## Livrable

Un centre de notifications local, accessible depuis la cloche de la barre
supérieure de `/app` :

- badge du nombre de notifications **non lues** ;
- panneau accessible (`role="dialog"`, `aria-expanded`, focus, `Échap`) ;
- filtres **Tout / Relances / Échéances / Dossiers** ;
- lignes classées par gravité puis par date, avec une action explicite ;
- mémoire locale **lu / masqué** (`localStorage`, clé
  `nage.notifications.v1`), conservée après rechargement ;
- aucune requête réseau supplémentaire : tout est projeté depuis les données
  déjà chargées par le cockpit (`apply-tracker` + `application-pipeline`).

## Notifications produites

| Type | Source locale | Gravité | Action proposée |
|---|---|---|---|
| Relance due aujourd’hui | `apply-tracker` (`status="due"`) | `due` | copier le brouillon de relance |
| Relance en retard | `apply-tracker` (`overdue=true`) | `critical` | copier le brouillon de relance |
| Échéance à ≤ 3 jours | `application-pipeline` (`deadline_status="urgent"`) | `urgent` | ouvrir l’offre officielle |
| Échéance dépassée | `application-pipeline` (`deadline_status="passed"`) | `critical` | ouvrir l’offre / le dossier |
| Réception à vérifier | `application-pipeline` (`next_action_code="confirm_receipt"`) | `info` | ouvrir le dossier |
| Entretien à préparer | `application-pipeline` (`next_action_code="prepare_interview"`) | `info` | ouvrir le dossier |

Règles de vérité :

- une candidature déjà envoyée (`submitted`, `submitted_confirmed`,
  `response_received`, `interview`, `offer_received`, `rejected`, `refused`,
  `withdrawn`, `receipt_unknown`) ne produit **pas** d’alerte d’échéance ;
- les relances seulement « à venir » restent dans la vue Suivi et ne
  déclenchent pas de notification ;
- l’identifiant d’une relance ou d’une échéance inclut sa date : si la date
  change (relance faite, échéance repoussée), la notification réapparaît ;
- les états lu/masqué sont limités à 300 identifiants, purement locaux au
  navigateur, et ne sont jamais envoyés au serveur.

## Fichiers modifiés

| Fichier | Rôle |
|---|---|
| `desktop_static/index.html` | cloche, badge, panneau, filtres, zone `aria-live` |
| `desktop_static/app.css` | styles NAGE du panneau, badges, états de gravité, responsive |
| `desktop_static/app.js` | projection locale, filtres, actions, mémoire lu/masqué, routage `tracking` |
| `come_ai_web.py` | correction lint préexistante (imports séparés dans `/api/app/missions`) |
| `tests/test_desktop_notification_center.py` | contrat statique `/app` + absence d’appel réseau dédié |
| `scripts/notif_center_cdp_check.py` | scénario CDP reproductible (Chrome headless) |
| `docs/agent-reports/SPEC-049-notif_center.md` | ce rapport |

## Vérifications

### Tests Python

```text
.venv/bin/python -m pytest -q tests/test_desktop_notification_center.py
→ 2 passed

.venv/bin/python -m pytest -q tests/test_desktop_notification_center.py \
    tests/test_career_action_center.py tests/test_send_confirmation.py \
    tests/test_career_explorer_web.py
→ 42 passed

.venv/bin/python -m ruff check come_ai_web.py \
    tests/test_desktop_notification_center.py scripts/notif_center_cdp_check.py
→ All checks passed!

node --check desktop_static/app.js
→ OK
```

### Scénario CDP — Chrome headless

Commande :

```bash
.venv/bin/python scripts/notif_center_cdp_check.py
```

Le script démarre l’application réelle sur un répertoire temporaire, mocke
uniquement les réponses `/api/*` avec des données synthétiques, puis pilote
Chrome headless via CDP (Playwright). Il vérifie l’interface servie par la
route `/app`, pas une copie statique.

```text
PASS badge non lues 3
PASS panneau fermé au départ
PASS ouverture accessible
PASS trois notifications 3
PASS filtre relances 1
PASS relance copiée annoncée
PASS tout lu masque le badge
PASS lecture persistée après reload
PASS masquage immédiat 2
PASS masquage persisté après reload 2
PASS Échap ferme le panneau
PASS aucune requête externe

12/12 checks
```

Le scénario couvre : compteur non lu, ouverture/fermeture accessible,
filtrage, action « copier la relance » (annonce `aria-live`), « tout lu »,
persistance après `reload`, masquage persistant, fermeture par `Échap`, et
absence totale de requête hors `127.0.0.1`.

## Garanties

- **Aucune soumission automatique** : aucune notification n’envoie de
  relance, ne dépose de candidature et n’appelle un service externe.
- **Aucune donnée réelle** : les tests utilisent des réponses synthétiques et
  un répertoire temporaire.
- **Aucune nouvelle source réseau** : le centre lit `state.tracker` et
  `state.pipeline`, déjà chargés par l’application.
- **Aucun secret** : aucune clé, aucun identifiant, aucun fournisseur.

## Limites assumées

- lu/masqué est propre au navigateur et au profil local (pas de
  synchronisation multi-appareils) ;
- le centre n’est pas un service de notifications système (pas de push macOS,
  pas d’e-mail) ;
- une notification masquée ne revient que si sa date ou son identifiant change.
