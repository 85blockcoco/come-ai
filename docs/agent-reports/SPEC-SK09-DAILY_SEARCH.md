# SPEC-SK09 — Recherche quotidienne et offres nouvelles

Mission : `CVBOOST-30` — SK-09
Branche : `agent/spec-sk09-daily-search`
Base : `f5b22f2` (`main` au moment du démarrage)
Worktree : `/Users/comedelavenne/AI-Excel-Agent-worker-cvboost-30-1792623069`
Statut : **livrée** — 27 tests dédiés, suite complète verte, ruff propre

---

## 1. Ce qui est livré

| Fichier | Rôle |
|---|---|
| `career/daily_digest.py` | Module pur : projection déterministe, cache, TTL, état, détection de changement |
| `career/service.py` | Trois méthodes de service (`daily_digest`, `refresh_daily_digest`, `record_daily_digest_visit`), le réglage du TTL, la limite de deux sources simultanées |
| `career/router.py` | `GET /api/career/daily`, `GET /career/daily`, `POST /api/career/daily/refresh`, `POST /api/career/daily/visit`, `PUT /api/career/daily/settings` |
| `career_static/js/daily-digest.js` | Panneau « Recherche du jour » (script classique, autonome, sans dépendance à `career.js`) |
| `career_static/index.html` | Le panneau dans l’onglet Tableau de bord + la balise `<script>` |
| `career_static/career.css` | Six règles additives (`.daily-digest-*`), y compris les variantes responsives |
| `tests/test_daily_digest.py` | 27 tests synthétiques (projection, cache, reprise, concurrence, HTTP) |
| `docs/career/daily-digest-launchd.md` | Modèle launchd **documenté, jamais installé** |
| `docs/career/com.comeai.career.daily-digest.plist.example` | Le fichier plist d’exemple (jamais copié automatiquement) |

**Aucune modification de schéma.** `SCHEMA_VERSION` reste à 8. L’état du digest
(« fil d’eau », traces d’offres, charge utile en cache) vit dans la table
existante `career_settings`, comme le snapshot de l’explorateur
(`stage_explorer_last_result`). Aucune donnée existante n’est réécrite.

---

## 2. Le contrat de données

La charge utile reprend exactement les huit clés demandées, plus quelques
clés de service clairement nommées :

```json
{
  "new_offers":     [{"offer_id", "title", "employer", "location", "published_date", "match_score", "source_trust"}],
  "updated_offers": [{"offer_id", "title", "employer", "changed_fields", "updated_at"}],
  "expiring_soon":  [{"offer_id", "title", "employer", "deadline_date", "days_left"}],
  "unavailable":    [{"offer_id", "title", "employer", "reason", "detected_at"}],
  "top_matches":    [{"offer_id", "title", "employer", "fit_score", "missing_critical_count", "qualification_status"}],
  "broken_sources": [{"source", "error", "last_failure", "retry_at"}],
  "last_refresh":   "ISO8601 | null",
  "cache_expires_at": "ISO8601",

  "generated_at": "ISO8601", "last_visit": "ISO8601 | null",
  "partial": false, "counts": {...}, "notes": [...], "disclaimer": "...",
  "cache_status": "fresh | expired | missing", "requires_refresh": true|false,
  "refreshed": true|false, "ttl_seconds": 900
}
```

Deux précisions honnêtes :

- `published_date` vaut `null` quand la source n’a jamais publié de date.
  Aucune date n’est devinée à partir du titre ou de la description.
- `source_trust` est une chaîne (`verified` / `unverified` / `unknown`) :
  `verified` exige à la fois une URL officielle et une vérification source
  encore à jour (snapshot courant ou board suivi). Une offre importée à la
  main reste `unverified` — elle ne devient pas vérifiée en le prétendant.

---

## 3. Les sept catégories, règles exactes

| Catégorie | Règle | Ce qui est **exclu** |
|---|---|---|
| `new_offers` | publication (`posted_date`) ou, à défaut, première importation (`created_at`) **postérieure à la dernière visite** | offres déjà vues, rejetées ou archivées, offres hors critères géographiques |
| `updated_offers` | champs réellement différents entre deux versions de la même offre | offres déjà classées « nouvelles » (une offre nouvelle n’est pas aussi une mise à jour) |
| `expiring_soon` | `deadline_date` connue, dans les 14 prochains jours | offres sans date limite connue |
| `unavailable` | source `closed` **ou** date limite dépassée | une offre simplement absente d’un flux n’est jamais déclarée close |
| `top_matches` | classement local contre les critères enregistrés | offres `non_conforming` (pays exclu, poste senior, contrat permanent…) |
| `broken_sources` | `last_error_code` renseigné + issue « error » de l’explorateur | sources en panne qui ont réussi depuis |
| `last_refresh` | horodatage de la dernière actualisation manuelle | — |

`missing_critical_count` compte les faits critiques manquants parmi
`publication`, `début`, `durée` et `pays` : sans eux, impossible de décider
si l’offre vaut une candidature. `counts.uncertain_offers` donne le volume
total des offres qui restent à vérifier — c’est la réponse à « ce qui reste
incertain ».

---

## 4. Contraintes de la mission → preuve

| Contrainte | Mise en œuvre | Test |
|---|---|---|
| **Cache avec expiration (TTL configurable)** | durée par défaut 900 s, réglable par `CareerService(daily_digest_ttl_seconds=…)`, par `PUT /api/career/daily/settings` et par la clé `career_settings["daily_digest_ttl_seconds"]` | `test_a_cached_digest_is_served_until_its_lifetime_expires`, `test_an_expired_cache_is_rebuilt_from_the_local_facts_and_asks_for_a_refresh`, `test_the_cache_lifetime_is_configurable_from_the_local_settings` |
| **Rafraîchissement manuel d’abord** | `GET /api/career/daily` ne fait **aucune** requête : socket bloqué pendant tout le test | `test_reading_the_digest_never_queries_a_source` |
| **Max 2 sources simultanées** | `discover_opportunities(max_parallel=…)` borné par `MAX_PARALLEL_SOURCES = 2` ; l’explorateur public reste séquentiel | `test_a_refresh_reads_at_most_two_sources_at_the_same_time` (le connecteur synthétique mesure la concurrence réelle : 2, jamais plus) |
| **Reprise après interruption** | l’état passe `running` **avant** la première requête ; un état resté `running` est relu comme `partial` et signalé | `test_an_interrupted_refresh_is_reported_as_partial_and_can_resume` |
| **Pas de remplissage artificiel** | une catégorie vide reste `[]` ; `published_date` vaut `null` quand la date est inconnue | `test_an_empty_digest_stays_empty_instead_of_being_filled` |
| **Offres rejetées ou vues séparées** | `status ∈ {rejected, archived}` → comptées à part ; le fil d’eau de visite les sort des « nouvelles » | `test_digest_separates_the_offers_the_person_already_rejected`, `test_digest_never_repeats_an_offer_the_person_already_saw` |
| **Paris et France exclus** | la qualification reprend les critères **enregistrés** (`excluded_countries`, `excluded_cities`, `require_known_location`), jamais une règle cachée | `test_digest_excludes_france_and_paris_with_the_saved_criteria` |
| **launchd documenté, pas auto-installé** | documentation + plist d’exemple ; aucun `plist` installable, aucun appel à `launchctl` dans le code | `test_the_launchd_model_is_documented_but_never_installed` |
| **Ruff propre, suite verte, `git diff --check`** | voir §6 | — |

---

## 5. Points de conception à relire

### 5.1 Le fil d’eau « dernière visite »

« Nouvelles offres depuis la dernière visite » a besoin d’un repère. Le
digest en garde deux :

- `last_visit` — la dernière fois où la synthèse a été **affichée**. Le
  panneau l’enregistre (`POST /api/career/daily/visit`) **après** l’avoir
  rendu, jamais pendant. Le `GET` reste donc une lecture pure.
- `last_refresh` — la dernière actualisation manuelle des sources.

Le premier écran sans aucune visite affiche tout ce qui est enregistré
(limité à 40 offres, triées par date de publication décroissante) : c’est
honnête — tout est nouveau pour quelqu’un qui n’a jamais regardé.

### 5.2 Les champs réellement modifiés

Il n’existe aucun journal de modifications par champ dans la base. Plutôt
que d’inventer un « changement », le digest **compare deux empreintes** de
l’offre (11 champs structurés + une empreinte du texte de l’annonce) et
nomme les champs différents. L’empreinte est bornée à 300 offres
(`MAX_TRACKED_OFFERS`), les plus récentes d’abord.

### 5.3 Ce qui a été touché dans `career/service.py`

Le chemin de découverte a été **extrait** sans changement de comportement :
`_refresh_discovery_source()` porte désormais le corps de la boucle, et
`discover_opportunities()` l’appelle séquentiellement (comportement par
défaut, identique) ou via un `ThreadPoolExecutor` borné à deux quand
`max_parallel > 1`. L’ordre des résultats est préservé. Aucun autre fichier
existant n’a été réécrit.

### 5.4 Pourquoi il n’y a pas de « seen » dans la base

Ajouter une table `daily_digest_seen` aurait obligé un bump de
`SCHEMA_VERSION` (8 → 9), ce que le dépôt interdit explicitement
(`HANDOFF_CODEX_MISSION_2026-10-20.md`). Le fil d’eau de visite dans
`career_settings` rend la table inutile : une offre antérieure à la
dernière visite n’est plus « nouvelle », qu’elle ait été vue ou non.

---

## 6. Validation

```
pytest -q tests/test_daily_digest.py   →  27 passed
pytest -q                                →  1451 passed, 1 skipped
ruff check .                             →  All checks passed!
git diff --check                         →  propre
scripts/audit_integration.py            →  VERDICT : MERGE AUTORISÉ
```

Le test `skipped` est préexistant (`tests/test_offer_summary_exhaustiveness.py` :
script ou base absents) et n’a rien à voir avec cette mission.

Aucun socket n’est ouvert par les tests : le fixture `deny_network` bloque
`create_connection`, `getaddrinfo` et les primitives de socket pendant toute
la session.

---

## 7. Limites connues

- **L’actualisation lit deux chemins de sources** : les boards Greenhouse
  configurés par la personne (en parallèle, 2 maximum) et le registre public
  de l’explorateur (séquentiel, budget 60 s). Une actualisation peut donc
  prendre jusqu’à une minute. C’est le prix d’une lecture réelle ; le cache
  évite de la répéter.
- **Une source qui répond sans annonce valide n’est pas « en panne »** :
  elle est seulement vide. Seuls les codes d’erreur explicites alimentent
  `broken_sources`.
- **`retry_at` est un délai de 30 minutes** après le dernier échec. Ce n’est
  pas une promesse de la source : c’est la date à laquelle l’actualisation
  manuelle suivante aura le plus de chances de réussir.
- **Le panneau est dans l’onglet Tableau de bord.** Aucune nouvelle
  navigation n’a été créée pour ne pas casser les tests d’onglets existants.

---

## 8. Intégration

Fichiers partagés touchés : `career/service.py` (autorisation explicite
requise par l’outil d’audit) et `career/router.py` (nouvelles routes).
`career_static/career.js` n’est **pas** modifié : le nouveau script est
autonome et n’ajoute aucun `window.prompt`.

Commande d’audit d’intégration :

```bash
.venv/bin/python scripts/audit_integration.py \
  --branch agent/spec-sk09-daily-search \
  --base main \
  --allow-path career/daily_digest.py \
  --allow-path career/router.py \
  --allow-path career/service.py \
  --allow-path career_static/js/daily-digest.js \
  --allow-path career_static/index.html \
  --allow-path career_static/career.css \
  --allow-path tests/test_daily_digest.py \
  --allow-path docs/agent-reports/SPEC-SK09-DAILY_SEARCH.md \
  --allow-path docs/career/ \
  --allow-shared-path career/service.py
```

La mission reste fusionnable en parallèle de SK-05 à SK-08 : aucune de ces
branches n’est touchée, et le digest ne dépend d’aucune de leurs API.
