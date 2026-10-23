# SPEC-005 — Cockpit quotidien (« Aujourd'hui »)

**Mission** : CVBOOST-35 — SPEC-005 — Daily Application Command Center
**Branche** : `worker/cvboost-35-1792646438` (worktree dédié `/Users/comedelavenne/AI-Excel-Agent-worker-cvboost-35-1792646438`)
**Base** : `f5b22f2` (merge ATS diagnostics + targeted CV variants)
**Date** : 2026-10-22
**Auteur** : Agent Worker SPEC-005

---

## 1. Objectif et périmètre

Le pipeline Career existe déjà (offres → matching → kit → candidature → suivi). Il manquait un
**cockpit quotidien** qui répond à une seule question : *« qu'est-ce qui compte aujourd'hui ? »*.

Cette mission ajoute un module **indépendant**, **local** et **sans modèle IA** :

* une projection pure et déterministe `compute_daily(user_id) -> DailyDigest` ;
* un cache local avec TTL (4 h par défaut, configurable) et invalidation manuelle ;
* deux routes de lecture (`/api/career/daily`, `/api/career/daily/ics`) et une route de refresh ;
* un export calendrier `.ics` inert ;
* un onglet « Aujourd'hui » dans l'interface Career.

**Hors périmètre (volontairement)** : aucun envoi d'e-mail, aucun message, aucune candidature
envoyée, aucune lecture réseau, aucun appel de board, aucune migration de schéma, aucune
nouvelle dépendance.

---

## 2. Fichiers livrés

| Fichier | Nature | Rôle |
|---------|--------|------|
| `career/daily_digest.py` | nouveau | Projection **pure** : urgences, opportunités, progression, entretiens + constructeur ICS |
| `career/daily_digest_store.py` | nouveau | Cache local : TTL, persistance atomique, invalidation, fichier corrompu toléré |
| `career/service.py` | modifié | 4 méthodes de service + 3 lectures SQL bornées + capacité `daily_digest` |
| `career/router.py` | modifié | `GET /api/career/daily`, `POST /api/career/daily/refresh`, `GET /api/career/daily/ics` + alias `/career/daily`, `/career/daily/ics` |
| `career/calendar_export.py` | modifié | Deux helpers publics (`escape_ical_text`, `fold_ical_line`) partagés, **aucun changement de comportement** |
| `career_static/js/daily-digest.js` | nouveau | Rendu de l'onglet « Aujourd'hui » (cartes, métriques, refresh) |
| `career_static/index.html` | modifié | Onglet + section `view-daily` + script |
| `career_static/career.js` | modifié | Enregistrement de la vue `daily` + pont `loadDailyDigest()` |
| `career_static/career.css` | modifié | Styles `.daily-*` (réutilisation des tokens existants) |
| `tests/test_daily_digest.py` | nouveau | 31 tests (projection pure, cache, service, HTTP, garde-fous UI + exécution réelle du JS dans Node) |
| `docs/agent-reports/SPEC-005-DAILY_COMMAND_CENTER.md` | nouveau | Ce rapport |

---

## 3. Architecture

```
career_static/js/daily-digest.js
        │  GET /api/career/daily          POST /api/career/daily/refresh
        ▼                                         ▼
career/router.py  ──►  career/service.py  ──►  career/daily_digest.py   (PUR : 0 E/S)
                              │                       ▲
                              │                       │ entrées : offres, candidatures,
                              │                       │ événements, brouillons, candidats
                              ▼                       │
                    career/daily_digest_store.py  ────┘
                    (cache TTL, career_data/daily_digest_cache.json)
```

### 3.1 Module pur — `career/daily_digest.py`

```python
compute_daily(
    user_id: str = DEFAULT_USER_ID,
    *,
    today: date | None = None,
    now: datetime | None = None,
    jobs: Sequence[Mapping[str, Any]] = (),
    applications: Sequence[Mapping[str, Any]] = (),
    drafts: Sequence[Mapping[str, Any]] = (),
    opportunity_candidates: Sequence[Mapping[str, Any]] = (),
    ttl_seconds: int = DEFAULT_TTL_SECONDS,
    excluded_countries: Sequence[str] = DEFAULT_EXCLUDED_COUNTRIES,
    excluded_cities: Sequence[str] = DEFAULT_EXCLUDED_CITIES,
) -> DailyDigest
```

* **Aucun E/S, aucun réseau, aucun modèle** : le module ne fait que transformer des mappings.
* **Déterministe** : la date du jour et l'instant sont des paramètres injectables ; à entrant
  identique et date identique, la sortie est identique (test `test_compute_daily_is_deterministic_and_pure`).
* **Bornage** : 500 enregistrements locaux inspectés au maximum, 12 urgences, 8 opportunités,
  12 entretiens.
* **Sortie** : `DailyDigest` (dataclass) avec `to_dict()` qui renvoie exactement le contrat JSON.

### 3.2 Cache local — `career/daily_digest_store.py`

| Garantie | Mise en œuvre |
|----------|---------------|
| TTL 4 h par défaut | `DEFAULT_TTL_SECONDS = 14400`, surchargeable par variable d'environnement `CAREER_DAILY_DIGEST_TTL_SECONDS` (bornée 60 s → 7 j) |
| Persistance locale | `career_data/daily_digest_cache.json`, écrit de façon **atomique** (fichier temporaire + `os.replace`), permissions `0600` |
| Entrée expirée | jamais servie, supprimée au passage |
| Fichier corrompu / illisible | traité comme un cache vide : le cockpit reste disponible |
| Invalidation | `invalidate(user_id)` utilisé par le bouton « Actualiser » |
| Écriture impossible | ignorée silencieusement : le cache est un confort, jamais un point de rupture |

### 3.3 Service local — `career/service.py`

| Méthode | Rôle |
|---------|------|
| `get_daily_digest(force_refresh=False)` | Renvoie le cockpit (cache si valide, sinon recalcul + écriture du cache) |
| `refresh_daily_digest()` | Invalide le cache puis recalcule (bouton « Actualiser ») |
| `_daily_digest_applications()` | Candidatures + événements, **une** requête jointe bornée à 200 lignes |
| `_daily_digest_drafts()` | Brouillons de dossiers préparés (progression) |
| `_daily_digest_opportunity_candidates()` | Offres éligibles (matching + qualification existants) avec score et couverture |
| `export_daily_calendar()` | Écrit le `.ics` privé dans `career_data/exports/` et journalise l'export |

Les scores et les couvertures **ne sont pas réinventés** : ils viennent du moteur local existant
(`score_job`, `qualify_offer`, `prepare_application`). Le cockpit ne fait que les ordonner.

---

## 4. Contrat de données

### 4.1 `GET /api/career/daily` (et alias `GET /career/daily`)

Exemple réel (données synthétiques) :

```json
{
  "user_id": "local",
  "date": "2026-10-21",
  "urgent": [
    {
      "type": "expiring_offer",
      "offer_id": "123",
      "title": "M&A Analyst",
      "employer": "Goldman Sachs",
      "location": "Londres, Royaume-Uni",
      "deadline_date": "2026-10-23",
      "days_left": 2,
      "match_score": 86,
      "action_label": "Candidater avant clôture",
      "action_url": "/api/career/jobs/123/prep",
      "is_email": false
    },
    {
      "type": "followup_due",
      "application_id": "456",
      "offer_title": "J.P. Morgan — IBD Summer",
      "employer": "J.P. Morgan",
      "sent_date": "2026-10-14",
      "sent_date_source": "stage_updated_event",
      "days_since_sent": 7,
      "suggested_followup_date": "2026-10-24",
      "status": "upcoming",
      "action_label": "Relancer",
      "action_url": "/api/career/applications/456",
      "is_email": false
    }
  ],
  "opportunities": [
    {
      "offer_id": "789",
      "title": "Equity Research",
      "employer": "Morgan Stanley",
      "location": "Londres, Royaume-Uni",
      "match_score": 92,
      "mandatory_coverage": "8/9",
      "source_trust": "verified",
      "published_days_ago": 1,
      "action_label": "Préparer ce dossier",
      "action_url": "/api/career/jobs/789/prep"
    }
  ],
  "interviews": [
    {
      "type": "interview_due",
      "application_id": "457",
      "offer_title": "Sales & Trading",
      "employer": "BNP Paribas",
      "interview_date": "2026-10-19",
      "days_left": -2,
      "action_label": "Préparer l’entretien",
      "action_url": "/api/career/applications/457",
      "is_email": false
    }
  ],
  "progression": {
    "prepared_this_week": 3,
    "sent_this_week": 1,
    "responses_this_week": 0,
    "interviews_this_week": 1,
    "rejections_this_week": 0,
    "conversion_rate": 0.25,
    "conversion_known": true,
    "window_days": 7,
    "formula": "Progression = actions déclarées localement sur les 7 derniers jours. …"
  },
  "last_refresh": "2026-10-21T08:00:00Z",
  "cache_expires_at": "2026-10-21T12:00:00Z",
  "ttl_seconds": 14400,
  "exclusions": { "countries": ["France"], "cities": ["Paris"] },
  "notes": ["Aucune offre enregistrée : importe une offre pour obtenir des échéances."],
  "disclaimer": "Cockpit calculé localement … aucun e-mail, message, formulaire ou candidature n'est envoyé …",
  "cached": false
}
```

### 4.2 Écarts assumés par rapport au contrat de la mission

| Contrat demandé | Implémentation | Pourquoi |
|-----------------|----------------|----------|
| `action_url: "/career/offers/123/prep"` | `/api/career/jobs/123/prep` | Le contrat est un exemple de forme. Les URL locales réelles de Career sont `/api/career/jobs/{id}/prep` (préparation d'un dossier) et `/api/career/applications/{id}` (suivi + radar de relance). Pointer vers des routes inexistantes aurait cassé les liens de l'interface. |
| `action_url: "/career/applications/456/followup"` | `/api/career/applications/456` | Il n'existe pas de route « followup » dans Career : la relance est un **brouillon local** affiché dans le radar de l'onglet Candidatures. |
| `urgent` : 2 types | 4 types (`expiring_offer`, `followup_due`, `receipt_unknown`, `interview_due`) | La réception non confirmée et l'entretien déclaré sont des urgences réelles du tracker local ; les deux sont des **extensions**, pas des contradictions. |
| `followup_due` sans seuil | apparition à **J+7**, `status` `due` à J+10 | Le radar existant reste à 10 jours (délai de respiration). Le cockpit montre la relance **3 jours plus tôt** pour préparer le brouillon ; `suggested_followup_date` reste la date raisonnable du radar (J+10). Les deux vues ne se contredisent donc pas. |
| `interviews` absent du contrat | clé `interviews` ajoutée | L'export ICS doit contenir les « entretiens planifiés » : ils ont donc besoin d'une source explicite dans le JSON. |

### 4.3 Règles métier appliquées

| Règle | Valeur | Test |
|-------|--------|------|
| Échéance « proche » | ≤ 7 jours (`EXPIRING_OFFER_WINDOW_DAYS`) | `test_expiring_offer_is_urgent_with_an_action` |
| Échéance dépassée / inconnue | jamais affichée comme urgente, jamais de date inventée | `test_offer_outside_the_urgent_window_is_not_urgent`, `test_unknown_deadline_is_an_unknown_not_an_invented_date` |
| Offre close, archivée ou déjà suivie | plus d'urgence | `test_closed_and_already_tracked_offers_are_not_urgent` |
| Relance | visible à J+7, `due` à J+10, `suggested_followup_date` = J+10 | `test_followup_due_after_the_respiration_delay`, `test_followup_is_shown_three_days_before_the_reasonable_date` |
| Candidature **non envoyée** | jamais de relance | `test_unsent_application_never_becomes_a_followup` |
| Réception non confirmée | priorité sur la relance (« Vérifie la réception ») | `test_unknown_receipt_is_flagged_before_any_followup` |
| Entretien déclaré | liste dédiée `interviews` | `test_declared_interview_is_listed_separately` |
| Opportunités | offres ouvertes, non suivies, score décroissant | `test_opportunity_exposes_score_coverage_and_trust` |
| **Paris / France exclus par défaut** | `excluded_countries = ("France",)`, `excluded_cities = ("Paris",)` — appliqué aux **opportunités** | `test_paris_and_france_are_excluded_from_opportunities_by_default` |
| Exclusion sur une échéance déjà suivie | **jamais** appliquée : une vraie date limite ne disparaît pas | `test_urgent_deadline_is_never_hidden_by_the_location_filter` |
| Couverture inconnue | `"inconnue"` (jamais `0/0` trompeur) | `test_unknown_coverage_stays_unknown` |
| Progression | 7 derniers jours, sur actions **déclarées** | `test_progression_counts_only_declared_local_actions` |
| Taux de conversion | `envoyées / préparés`, `conversion_known = false` si aucun dossier préparé | `test_conversion_rate_is_unknown_without_prepared_dossiers` |

Les exclusions suivent le brief de recherche de la personne **si elle l'a configuré** ; sinon les
exclusions par défaut (France / Paris) s'appliquent.

---

## 5. Export calendrier — `GET /api/career/daily/ics`

Fichier `.ics` **inert**, écrit dans `career_data/exports/` (permissions `0600`), renvoyé en
`text/calendar; charset=utf-8` avec `Cache-Control: no-store`.

| Événement | `DTSTART` | `DTEND` | Récurrence |
|------------|-----------|---------|-----------|
| Échéance d'offre | jour du digest | **date limite** | — |
| Relance suggérée | `suggested_followup_date` | + 1 jour | `RRULE:FREQ=WEEKLY;INTERVAL=1;COUNT=4` |
| Entretien déclaré | `interview_date` | + 1 jour | — |

* **UID déterministes** : `come-ai-career-daily-<sha256(type:clé)[:32]>@local` → réimporter le
  fichier **met à jour** les mêmes événements au lieu d'en créer de nouveaux.
* **Déterministe sans horodatage caché** : `DTSTAMP` vaut minuit du jour du digest ; deux exports
  du même digest sont **identiques octet pour octet**.
* **Texte inerte** : échappement RFC 5545 (`\`, `;`, `,`, retours ligne) + repli des lignes à
  75 octets UTF-8 ; un titre d'offre contenant un saut de ligne ne peut pas créer une fausse
  propriété iCalendar (test `test_ics_export_escapes_untrusted_text`).
* L'export ne crée aucun accès réseau : il ne s'agit pas d'une synchronisation calendrier.

---

## 6. Interface — onglet « Aujourd'hui »

* Nouvel onglet **« Aujourd'hui »**, premier de la barre de navigation, actif par défaut
  (`career_static/index.html`).
* Section `view-daily` : 6 métriques de progression, carte « À faire aujourd'hui », carte
  « Offres qui te correspondent », notes de contexte, bandeau d'honnêteté (cache + disclaimer).
* Bouton **« Actualiser »** → `POST /api/career/daily/refresh` (invalidation du cache puis
  recalcul), avec état « Actualisation… » pendant l'appel.
* Lien **« Exporter la journée (.ics) »** → `GET /api/career/daily/ics`.
* Rendu 100 % `textContent` (aucun `innerHTML`), chargé sans dépendance à l'ordre des scripts
  (`window.careerDailyDigest`), noms globaux préfixés pour ne jamais entrer en collision avec
  `career.js` / `cv_plan.js`.

---

## 7. Validation

```bash
.venv/bin/python -m pytest -q tests/test_daily_digest.py   # 31 passed
.venv/bin/python -m pytest -q                              # 1455 passed, 1 skipped
.venv/bin/python -m ruff check .                           # All checks passed!
git diff --check                                            # propre
node --check career_static/js/daily-digest.js              # OK
node --check career_static/career.js                       # OK
```

Le test ignoré (`tests/test_offer_summary_exhaustiveness.py`) est antérieur à cette mission : il
exige un script ou une base absents de la machine.

Le rendu du cockpit est **exécuté pour de vrai** dans Node (stubs DOM + API) :
`test_daily_digest_renders_cards_without_innerhtml` vérifie les cartes rendues, les états vides,
la route de refresh (`POST`) et l'affichage des erreurs réseau.

`checklist_codex.sh` : la section `main` (pytest complet) et la section `lint` (ruff) sont vertes ;
les sections `memory` / `study-coach` concernent d'autres worktrees, absents de cette mission.

---

## 8. Intégration et rollback

* **Aucune migration** : pas de nouvelle table, pas de changement de schéma SQLite.
* **Aucune dépendance** : bibliothèque standard uniquement.
* **Aucune donnée personnelle** : le cache ne contient que la projection déjà affichée ; il vit
  dans `career_data/` (jamais dans `data/`), donc invisible pour l'agent d'analyse de documents.
* **Rollback** : supprimer `career/daily_digest.py`, `career/daily_digest_store.py`,
  `career_static/js/daily-digest.js`, `tests/test_daily_digest.py` et les blocs ajoutés dans
  `service.py`, `router.py`, `calendar_export.py`, `career.js`, `index.html`, `career.css`.
  Le fichier `career_data/daily_digest_cache.json` peut être supprimé sans conséquence.

## 9. Points de vigilance pour la relecture

1. **Seuil de relance J+7 vs J+10** : le cockpit prépare la relance 3 jours avant la date
   raisonnable du radar. Si la relecture préfère une seule politique, aligner
   `FOLLOWUP_PREVIEW_DAYS` sur `FOLLOWUP_DELAY_DAYS` (une seule constante à changer).
2. **Type `action_url`** : ce sont les routes locales réelles (`/api/career/...`), pas les
   chemins d'exemple du contrat.
3. **Couverture `mandatory_coverage`** : reprise de la couverture documentaire existante
   (`supported / requirements_total`) ; « inconnue » quand aucune exigence n'est détectable.
4. **Onglet par défaut** : « Aujourd'hui » est devenu l'onglet d'ouverture du module Career
   (le tableau de bord reste accessible en un clic).
