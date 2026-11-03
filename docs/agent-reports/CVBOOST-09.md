# CVBOOST-09 — Tableau de bord de préparation et relances

- **Date** : 2026-10-20
- **Branche** : `agent/cvboost-09` (worktree `/Users/comedelavenne/AI-Excel-Agent-cvboost-09`)
- **Base demandée** : SHA candidat fourni par l'intégrateur = `7834e45` (tip de
  `codex/career-cv-boost`, branche de référence du pack CVBOOST). C'est le candidat
  intégré confirmé avant construction.
- **Commits** : `af3d4a2` (module + service/router + tests), `a151ddf` (UI + script de fumée)
- **Aucune fusion, aucun push, aucun rebase/stash/clean/reset** — conformément au contrat commun.
- **Aucune base réelle lue**, aucun `.env`, aucun secret, aucun e-mail/candidature envoyé.

## 1. Contexte et dépendance

La dépendance annoncée (« kit de candidature intégré » = CVBOOST-05) n'existait pas encore
dans le SHA candidat fourni : la checklist n'y était pas persistée. Conformément au contrat
produit prévu par le handoff `HANDOFF_CODEX_STAGES_CV_2026-10-20.md` (chantier B), la
checklist est donc un **événement du journal existant** (`application_events.event_type =
'checklist'`, détail JSON `{"items": {clé: bool}}`), sans changement de schéma ni de
`SCHEMA_VERSION` (toujours 7). Le kit futur branche sur le même contrat ; en l'absence de
checklist, le facteur reste **inconnu nommé** et jamais zéro silencieux.

## 2. Ce qui a changé

### Module pur — `career/application_dashboard.py` (nouveau, ~540 lignes)

- `build_dashboard_payload(...)` : assemble compteurs, entrées, radar et honnêteté.
- Compteurs par état **sur toute la population**, filtres ignorés pour les compteurs.
- Filtres : état, réception, échéance (`next_7_days`/`passed`/`unset`), `à traiter`, recherche.
- Chronologie bornée (`MAX_TIMELINE_EVENTS = 15`), tri par horodatage UTC réel
  (`parse_event_timestamp` : fuseaux convertis en UTC, valeur naïve lue en UTC,
  illisible → `None`, jamais comparée à l'heure locale).
- Radar de relance : brouillons locaux uniquement, `is_email: false` partout.
  Règles constantes et affichables : `FOLLOWUP_DELAY_DAYS = 10`,
  `REVIEW_INTERVAL_DAYS = 7`, `DEADLINE_SOON_DAYS = 7`, `DEADLINE_MARGIN_DAYS = 3`.
  Exclut les candidatures closes et les offres reçues ; entretien = préparation, pas relance.
- Note de préparation 0–100 : **moyenne simple de trois facteurs** —
  couverture CV (exigences de l'offre étayées par le profil),
  vérification des faits (preuves entièrement documentées vs à chiffrer),
  checklist (5 cases locales). Les trois facteurs, les inconnues (avec raison)
  et la formule sont retournés et affichés. Score `null` si rien de connu.
- `deadline_bucket` : `unset` par défaut (jamais « ouvert » inventé), `closed`,
  `passed`, `soon`, `later` ; un horodatage invalide ne plante pas le tableau de bord.
- Honnêteté centrale : `sent_declared` ne peut venir que des états déclarés par la
  personne ; `HONESTY_NOTE` répète qu'une ligne SQLite n'est jamais un envoi.

### Service — `career/service.py` (2 méthodes, ~127 lignes)

- `application_dashboard(...)` : jointure `applications`×`jobs`, événements groupés,
  limite `MAX_DASHBOARD_APPLICATIONS = 200` + comptage réel (troncature affichée et
  non silencieuse), validations `UserFacingError` en français, réutilisation de
  `_connection()`/`_lock`, zéro migration, zéro réseau.
- `set_application_checklist(application_id, checked)` : valide les 5 clés,
  écrit un événement `checklist` (dernier événement faire foi → état rejouable
  et réversible), retourne l'état projeté. Toute clé inconnue → `UserFacingError`.

### Routes — `career/router.py`

- `GET /api/career/applications/dashboard` enregistrée **avant**
  `/applications/{application_id}` (ordre vérifié par test HTTP).
- `POST /api/career/applications/{application_id}/checklist`
  (`ApplicationChecklistPayload`, ≤ 10 clés).

### UI — `career_static/index.html`, `career.js`, `career.css`

- Bandeau « États et compteurs » cliquables (`role="list"`), filtres
  (état/réception/échéance/à traiter), lien export calendrier `.ics`.
- `#applications-radar` `aria-live="polite"` : « N jours sans réponse »,
  date suggérée, bouton **« Copier le brouillon de relance »**
  (`navigator.clipboard` + repli `execCommand`, message explicite « Envoie-le
  toi-même », aucun envoi).
- Par fiche : bloc note de préparation (`<details>` : score, 3 facteurs, inconnues,
  formule), checklist 5 cases cochables (POST local, aucun envoi), chronologie locale.
- Aucun `window.prompt` ajouté (toujours exactement 1 : la suppression).
- Tokens CSS existants uniquement.

### Script de fumée — `scripts/cvboost09_browser_smoke.py` (nouveau)

Serveur uvicorn réel sur répertoire temporaire vide, 9 vérifications HTTP,
données 100 % synthétiques.

## 3. Résultats réels

| Contrôle | Commande | Résultat |
| --- | --- | --- |
| Tests ciblés mission | `pytest tests/test_career_application_dashboard.py -q` | **22 passed** |
| Suite complète | `pytest -q` | **1167 passed** (baseline 1145 + 22) |
| Lint | `ruff check career/ tests/ scripts/` | **All checks passed** |
| `git diff --check` | — | **OK** |
| Checklist Codex | `VENV_PY=…/.venv/bin/python ./checklist_codex.sh` | main **1167 passed** ✓, DevKit **207 passed** ✓ ; étape 5 « aucun secret tracké » ✗ **pré-existante sur `7834e45`** (`secret_redaction.py`, `tests/test_secret_redaction_parity.py` trackés, inchangés — vérifié par `git ls-tree 7834e45`) |
| Parcours HTTP réel | `python scripts/cvboost09_browser_smoke.py` | **9/9** (accueil → offre synthétique → suivi → dashboard → filtre → checklist → .ics → assets JS) |
| Scan secrets (diff) | `grep -rnE "api[_-]?key|secret|token|password|sk-…"` | aucune clé dans les fichiers modifiés |

### Couverture des tests exigés (tous synthétiques, aucune base réelle)

Transitions et statut invalide · retour arrière (chronologie conservée) · doublons
(idempotence `create_application`) · fuseaux (`+02:00` vs UTC, naïve lue UTC) ·
deadline inconnue (`unset`, renvoi vers page officielle) · relance passée (15 j,
`due`, date suggérée 15 oct.) · **candidature non envoyée** (`sent_declared=false`,
`HONESTY_NOTE`, refus `submitted` sans approbation → 400 HTTP) · réception non
confirmée (`unknown` → action « vérifie », puis `confirmed`) · profil incompte →
3 facteurs inconnus, score `null`, raisons affichées · export calendrier (VEVENT
20261201 présent, absent après envoi) · filtres · troncature 200 · HTTP (ordre
des routes, 400 invalides, checklist) · gardes UI (`window.prompt` == 1,
`navigator.clipboard`, `aria-live`, aucun `mailto:`/`smtp`) + test Node de
`radarEntryText` (honneur des libellés).

## 4. Étiquetage honnête

- **Testé sur fixtures** : oui — tout le volet logique et la suite complète.
- **Testé dans un navigateur réel** : **non** (aucun moteur de navigateur
  automatisé disponible sur la machine hôte). Remplacé par : test Node des
  fonctions UI réelles (comme le fait déjà `test_career_stage_hunter_ui_guards.py`)
  **et** parcours HTTP réel 9/9 sur un serveur local.
- **Testé réseau réel** : non, hors périmètre (aucun connecteur dans cette mission).
- **Données réelles** : aucune.

## 5. Limites restantes

1. Le radar calcule `waiting_days` à partir du **dernier événement**, pas d'un
   horodatage « envoi » métier : le délai post-envoi part donc du dernier suivi
   local enregistré (documenté dans la fiche).
2. Le facteur « faits » compte les preuves **entièrement documentées** ; une
   expérience sans résultat chiffré compte comme `needs_quantification` et est
   listée « à chiffrer uniquement si vérifiable » — jamais inventée.
3. La checklist sera rejouée par le kit CVBOOST-05 via le même événement ;
   tant qu'aucun événement n'existe, le facteur reste inconnu (volontaire).
4. Limite d'affichage de 200 candidatures (troncature annoncée par
   `totals.truncated` et `truncated_note`, jamais silencieuse).

## 6. Rejeu

```bash
VENV_PY=/Users/comedelavenne/AI-Excel-Agent/.venv/bin/python
cd /Users/comedelavenne/AI-Excel-Agent-cvboost-09
$VENV_PY -m pytest tests/test_career_application_dashboard.py -q   # 22 passed
$VENV_PY -m pytest -q                                              # 1167 passed
$VENV_PY -m ruff check career/ tests/ scripts/
$VENV_PY scripts/cvboost09_browser_smoke.py                        # 9/9 vertes
```

## 7. Fichiers modifiés / créés

- **Nouveaux** : `career/application_dashboard.py`,
  `tests/test_career_application_dashboard.py`, `scripts/cvboost09_browser_smoke.py`
- **Modifiés** : `career/service.py` (+2 méthodes), `career/router.py` (+2 routes,
  +1 payload), `career_static/index.html`, `career_static/career.js`,
  `career_static/career.css`
- **Rollback** : `git revert a151ddf af3d4a2` (les deux commits sont autonomes et
  n'ont modifié ni le schéma ni les tables existantes).

## 8. Livrable pour CVBOOST-10

Le candidat CVBOOST-09 est `a151ddf` sur `agent/cvboost-09` (base `7834e45`).
Branche préservée ; aucune fusion dans `main`, aucun push (contrat commun).
