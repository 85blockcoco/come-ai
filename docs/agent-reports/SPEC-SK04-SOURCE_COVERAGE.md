# SPEC-SK04 — Couverture et santé des sources

**Mission** : CVBOOST-25 — SK-04 — Couverture et santé des sources
**Branche** : `worker/cvboost-25-1792603307` (worktree dédié `/Users/comedelavenne/AI-Excel-Agent-worker-cvboost-25-1792603307`)
**Base** : `main` (SHA `a054c97`)
**Date** : 2026-10-21
**Auteur** : Agent Worker SK-04

---

## 1. Objectif

Afficher des **statistiques exactes** sur la couverture réelle de Career Explorer, avec une
séparation stricte entre ce qui est **synthétique** et ce qui est **live**.

Le module ne devine rien : une donnée absente reste absente, un compteur n'est publié que s'il
est recalculable à partir des résultats bruts des sources et des annonces du parcours.

---

## 2. Fichiers créés

```
career/source_coverage.py        # module de mesure (pur, déterministe, sans réseau ni modèle)
tests/test_source_coverage.py    # 30 tests (synthétiques + base Career locale réelle)
docs/agent-reports/SPEC-SK04-SOURCE_COVERAGE.md
messages/result.json             # rapport worker (lu par l'orchestrateur)
```

**Aucun fichier existant n'a été modifié.** Le module est volontairement autonome : il ne touche
ni au schéma SQLite, ni à `career/service.py`, ni au routeur — ce qui permet son intégration
parallèle avec SK-01 / SK-02 / SK-03 sans conflit.

---

## 3. API publique

| Symbole | Rôle |
|---------|------|
| `compute_coverage(payload)` | **Cœur pur et déterministe** : même payload ⇒ même rapport. |
| `compute_metrics(run_id, *, loader=None, base_dir=None)` | Point d'entrée de la mission : lie un parcours à un loader et renvoie le rapport. |
| `CoverageMetrics` | Les 19 mesures d'un compartiment (`synthetic` **ou** `live`). |
| `CoverageReport` | Le rapport : deux compartiments, cohérence, résumé du run, notes. |
| `CoveragePayload` | Matière première brute : résultats par source + annonces du parcours. |
| `CareerDatabaseLoader` | Lit le dernier parcours de l'explorer dans la base Career locale (`.sqlite3`). |
| `synthetic_fixture_payload()` / `synthetic_fixture_metrics()` | Le jeu de fixtures synthétique du dépôt, mesuré **à part**. |
| `is_synthetic_source(*values)` | Détection d'un marqueur synthétique explicite. |
| `CoverageRunNotFound` | Erreur explicite quand un parcours n'est pas mesurable. |

`computed_at` est **l'horodatage du parcours mesuré**, pas l'heure de la mesure : deux appels sur
le même parcours rendent exactement le même rapport.

---

## 4. Définition exacte des 19 métriques

Toutes les mesures sont recalculables à partir des données brutes du parcours.

### 4.1 Niveau source (résultats par source du parcours)

| Métrique | Définition exacte | Donnée d'origine |
|----------|-------------------|------------------|
| `sources_planned` | Nombre de sources **prévues** pour le parcours (une entrée par source du registre, y compris celles jamais consultées). | `outcomes[]` |
| `sources_queried` | Nombre de sources **effectivement consultées** (lecture réseau ou cache) : `status ∈ {success, partial, error, cached}`. | `outcomes[].status` |
| `sources_succeeded` | Sources consultées ayant livré **au moins une annonce valide** (`status ∈ {success, partial}` **et** `retained_count > 0`). | `outcomes[]` |
| `sources_cached` | Sources servies depuis le cache du parcours (`status = cached`). | `outcomes[].status` |
| `sources_failed` | Sources consultées **en erreur** (`status = error`) **ou** ayant répondu **sans aucune annonce valide**. | `outcomes[]` |

> `not_queried` et `unsupported` sont **prévues mais jamais consultées** : ni succès, ni échec.

### 4.2 Niveau annonce (annonces du parcours, après déduplication)

| Métrique | Définition exacte |
|----------|-------------------|
| `unique_employers` | Entreprises distinctes (normalisation accents/casse) parmi les annonces dédupliquées. |
| `raw_offers` | Annonces **brutes lues** : somme des `raw_count` des sources du compartiment. |
| `valid_offers` | Annonces dédupliquées portant un **verdict de qualification enregistré** (`conforming` / `to_verify` / `non_conforming`). |
| `offers_pre_dedup` | Nombre d'annonces du compartiment **avant** déduplication. |
| `offers_post_dedup` | Nombre d'annonces **après** déduplication (URL canonique ; à défaut source+id ; à défaut entreprise+titre+ville). |
| `offers_verified_url` | Annonces dont l'URL officielle est vérifiée **et** exploitable (`verification_status = verified` + URL canonique valide). |
| `offers_with_location` | Annonces dont la localisation est connue (pays **ou** ville). |
| `offers_with_published_date` | Annonces avec date de publication. |
| `offers_with_start_date` | Annonces avec date de début (ou mois de début connu). |
| `offers_with_duration` | Annonces avec durée connue (mois, min ou max). |
| `offers_with_requirements` | Annonces dont le champ prérequis est renseigné. |
| `compliant` / `to_verify` / `non_compliant` | Répartition des verdicts de qualification. |

`compliant + to_verify + non_compliant == valid_offers` par construction.

---

## 5. Séparation synthétique / live (contrainte absolue)

Le rapport expose **exactement deux compartiments** :

```json
{
  "metrics": {
    "synthetic": { "sources_planned": 1, "raw_offers": 36, "offers_post_dedup": 36, ... },
    "live":      { "sources_planned": 4, "raw_offers": 7,  "offers_post_dedup": 1,  ... }
  }
}
```

Règles d'attribution (applicées dans cet ordre) :

1. **Marqueur synthétique explicite** sur l'identité de la source (`source_id`, `provider`) ⇒
   compartiment `synthetic`. Ce signal passe **avant** tout le reste : une annonce synthétique ne
   peut jamais être comptée comme live, même si elle a été lue par une source réelle.
2. **Identifiant de source explicitement déclaré synthétique** (`CoveragePayload.synthetic_source_ids`).
3. **Source du parcours connue** (`registry_source_id` ⇒ compartiment de la source) ⇒ ce
   compartiment.
4. **Source identifiée** (`source_name` / `source_id` non vides, hors `manual`) ⇒ `live`.
5. **Ni source ni marqueur** ⇒ *non attribuée* : comptée à part (`unattributed`), elle ne gonfle
   **aucun** compteur.

Le marqueur est searché **sur l'identité de la source uniquement** (jamais sur le nom de
l'entreprise : un employeur réel peut legitimement ressembler à un marqueur).

**Preuve** (`tests/test_source_coverage.py`) :

- `test_synthetic_offers_never_inflate_the_live_counters` — un run mixte (1 source live + 1 source
  synthétique) : `live.raw_offers == 10`, `synthetic.raw_offers == 60`, aucun mélange.
- `test_a_synthetic_offer_read_from_a_live_source_stays_synthetic` — l'inverse du cas précédent.
- `test_the_bundled_synthetic_dataset_is_measured_apart` + `test_the_synthetic_dataset_never_enters_the_live_bucket`
  — les 36 fixtures synthétiques du dépôt sont mesurées, `live` reste à zéro.
- `test_offers_without_an_identifiable_source_are_reported_apart` — une offre `manual` n'est
  comptée ni en live ni en synthétique.

---

## 6. Règles de cohérence (contrôlées à chaque calcul)

| Règle | Formulation |
|-------|-------------|
| Sommes des sources | `sources_succeeded + sources_cached + sources_failed == sources_queried` |
| Plafond des sources | `sources_queried <= sources_planned` |
| Déduplication | `offers_post_dedup <= offers_pre_dedup` |
| Verdicts | `compliant + to_verify + non_compliant == valid_offers` |
| Brut vs qualifié | `raw_offers >= valid_offers` |
| Employeurs | `unique_employers <= offers_post_dedup` |
| Couverture | `live.offers_pre_dedup + synthetic.offers_pre_dedup + non attribuées == annonces du parcours` |
| Double comptage | Aucune URL canonique ne peut être comptée à la fois en live et en synthétique |

Chaque violation est renvoyée dans `report.coherence.violations` (français, lisible) et
`report.coherence.ok` passe à `false`. Un test injecte des mesures volontairement incohérentes
pour vérifier que le filet de sécurité fonctionne (`test_a_broken_measurement_is_reported`).

---

## 7. HTTP 200 ≠ source de qualité

Une source qui répond mais **ne renvoie aucune annonce valide** est comptée :

- dans `sources_queried` (elle a bien été consultée) ;
- dans `sources_failed` (elle n'a delivered **aucune** couverture) ;
- **jamais** dans `sources_succeeded`.

C'est la seule définition qui rend `succeeded + cached + failed == queried` vrai **et** qui refuse
de récompenser une source vide. Preuve : `test_a_source_that_answers_without_a_valid_offer_is_not_a_success`
et `test_a_partial_source_with_offers_is_a_success`.

---

## 8. Absence de double comptage

- Les **sources** sont dédupliquées par identité (`source_id`, sinon `provider|company`) : une
  source répétée dans le snapshot n'est comptée qu'une fois (`test_a_source_is_never_counted_twice`).
- Les **annonces** sont dédupliquées par URL canonique (paramètres de tracking retirés), puis par
  `source+id`, puis par `entreprise+titre+ville` : `offers_post_dedup <= offers_pre_dedup`
  (`test_duplicates_are_removed_after_deduplication`).
- Les mesures de fait (localisation, dates, durée, prérequis, verdicts) sont calculées sur le
  **lot dédupliqué**, jamais sur le lot brut : un doublon ne peut donc pas gonfler deux fois un
  compteur.

---

## 9. Chargement depuis la base Career locale

`CareerDatabaseLoader` lit, en lecture seule :

| Table | Usage |
|-------|-------|
| `career_settings` (`stage_explorer_last_result`) | Le snapshot du parcours : `run_id`, `outcomes[]`, `summary`, `match_refs[]`, `finished_at`. |
| `jobs` | Les annonces importées par le parcours (via `match_refs[].job_id`), avec `source_name`, `source_id`, `official_url`, `city`, `country`, `posted_date`, `start_date`, `duration_months`, `requirements`. |
| `job_qualification_snapshots` | Le verdict de qualification enregistré à l'import : `verification_status`, `target_status`, `start_month`, `duration_min/max_months`. |

`match_refs[].source_id` est l'identifiant de source du registre : il relie chaque annonce à sa
source, donc à son compartiment (synthétique ou live) sans approximation.

**Limite assumée** : l'explorer ne conserve que le **dernier** parcours (le snapshot écrase le
précédent). `compute_metrics("explore_ancien")` échoue donc explicitement avec
`CoverageRunNotFound` — message clair, aucune mesure inventée. Les parcours plus anciens ne sont
reconstituables que depuis un export JSON.

---

## 10. Tests

`tests/test_source_coverage.py` — **30 tests**, tous verts :

| Famille | Tests |
|---------|-------|
| Forme de la mesure | 19 métriques publiées, un compartiment par bucket, JSON sérialisable, déterminisme, `computed_at` = horodatage du run |
| Séparation synthétique / live | 5 tests (dont les 36 fixtures du dépôt) |
| Santé des sources | 6 tests (sommes, HTTP 200 sans offre, `partial`, `unsupported`, source comptée deux fois) |
| Annonces | 4 tests (doublons, faits, verdict absent, URL vérifiée) |
| Filet de cohérence | 2 tests |
| Points d'entrée / loader | 4 tests (loader factice, run inconnu, base absente) |
| Base Career locale | 4 tests (mesure du dernier run, run inconnu, base sans run, offre supprimée) |

```bash
.venv/bin/python -m pytest -q tests/test_source_coverage.py   → 30 passed
.venv/bin/python -m pytest -q                                  → 1403 passed, 1 skipped
.venv/bin/python -m ruff check career/source_coverage.py tests/test_source_coverage.py → All checks passed
git diff --check                                               → propre
```

Aucune régression : la suite complète passe de **1373** à **1403** tests (les 30 nouveaux), sans
aucun test supprimé ni modifié.

---

## 11. Limites connues (assumées)

1. **Un seul parcours mesurable à la fois** dans la base locale (cf. §9). Pas de migration
   SQLite ajoutée : SK-04 reste compatible avec SK-01 / SK-02 / SK-03 en parallèle.
2. `offers_pre_dedup` est calculé sur **l'ensemble d'annonces fourni au module**. Le loader
   depuis la base fournit les annonces **dédupliquées** du parcours (donc `pre == post` sauf
   doublon inter-sources). Le nombre de doublons retiré par le parcours reste lisible dans
   `report.run_summary.duplicate_count` — le module ne l'invente pas ailleurs.
3. `raw_offers` inclut les sources servies depuis le cache (annonces relues dans la fenêtre de
   cache de 10 minutes) ; le rapport le signale dans ses notes quand c'est le cas.
4. Les annonces sans verdict de qualification enregistré ne sont pas comptées dans
   `valid_offers` : elles restent visibles dans `offers_post_dedup`.
5. Les métriques ne distinguent pas, à elles seules, la **qualité** d'une offre : elles mesurent
   la **couverture** (ce qui a été lu, qualifié, dédupliqué, documenté).

---

## 12. Point d'intégration (proposé, non fait ici)

Le module est prêt à être branché sans modifier le schéma :

```python
from career.source_coverage import compute_metrics, CareerDatabaseLoader

report = compute_metrics(run_id, loader=CareerDatabaseLoader.from_base_dir(base_dir))
payload = report.to_dict()   # JSON prêt pour l'API / l'UI
```

L'UI d'exploration peut afficher `metrics["live"]` comme « couverture réelle » et
`metrics["synthetic"]` comme « jeu de démonstration », jamais mélangés. Branchement routeur
laissé à l'intégration pour éviter tout conflit avec les missions parallèles.

---

## 13. Checklist avant terminaison

- [x] `./checklist_codex.sh` → tests verts, ruff clean, aucun secret tracké
- [x] `pytest -q` → 1403 passed, 1 skipped (aucune régression)
- [x] `git diff --check` → propre
- [x] `messages/result.json` écrit dans le worktree
- [x] Branche poussée, prête pour relecture
