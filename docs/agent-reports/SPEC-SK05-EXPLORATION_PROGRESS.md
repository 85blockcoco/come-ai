# SPEC-SK05 — Progression serveur réelle de l'exploration

Date : 21 octobre 2026
Branche : `agent/spec-sk05-exploration-progress` (poussée aussi sur `worker/cvboost-26-1792604928`)
Base : `a054c97` (`main` au moment de la création du worktree)
Statut : **TERMINÉE — endpoints réels, phases réelles, annulation coopérative, tests verts**

---

## 1. Ce qui est livré

La barre de progression de l'explorateur de stages était une **estimation locale**
(`Math.log2(elapsed)` dans `career_static/career.js`). Elle pouvait annoncer 92 % alors
qu'aucune source n'avait encore répondu. Cette mission la remplace par une **progression
côté serveur**, fondée sur des étapes réellement terminées.

### API d'exploration

```text
POST   /api/career/stage-search/explorations              → 202 + état initial
GET    /api/career/stage-search/explorations/{run_id}       → état réel du run
POST   /api/career/stage-search/explorations/{run_id}/cancel → demande d'arrêt
GET    /api/career/stage-search/explorations                → runs récents (reprise)
```

État renvoyé (contrat public, `career/exploration_run.py::ExplorationRun.to_public_dict`) :

```json
{
  "run_id": "explore_run_…", "status": "running", "phase": "qualifying",
  "sources_total": 21, "sources_completed": 8, "sources_succeeded": 7, "sources_failed": 1,
  "offers_read": 340, "offers_qualified": 57, "cancel_requested": false,
  "phases": [{"phase": "preparing", "status": "completed", "started_at": "…", "finished_at": "…"}],
  "phase_order": ["preparing", "consulting", "normalizing", "qualifying",
                  "deduplicating", "ranking", "persisting", "completed"]
}
```

Les compteurs demandés par la mission (`sources_total`, `sources_completed`,
`sources_succeeded`, `sources_failed`, `offers_read`, `offers_qualified`, `phase`,
`cancel_requested`) sont présents avec ces noms exacts ; le reste est un supplément utile
(`offers_normalized`, `offers_deduplicated`, `offers_ranked`, `offers_persisted`,
`phases`, `outcomes`, `elapsed_seconds`, `error`, `message`).

### Phases réelles

Les huit phases sont exécutées dans l'ordre par `career/exploration_service.py` :

| Phase | Travail réellement exécuté |
|---|---|
| `preparing` | Lecture du brief enregistré, plan des sources vérifiées du registre (`sources_total`). |
| `consulting` | Lecture des flux publics, **2 sources simultaines maximum**. |
| `normalizing` | Canonicalisation des annonces lues (titre, entreprise, URL canonique, champs bornés). |
| `qualifying` | Re-qualification locale : `classify_internship`, `qualify_offer`, `score_brief_match`, `criteria_admit`. |
| `deduplicating` | Une seule fiche par URL officielle canonique (la mieux classée est conservée). |
| `ranking` | Tri déterministe `ranking_key` + plafond `EXPLORATION_MAX_RESULTS`. |
| `persisting` | Import local des offres + publication du snapshot d'exploration. |
| `completed` | Fin réelle du run. |

Chaque phase n'est annoncée qu'**après** son travail, et chaque compteur est incrémenté
par une étape terminée. Aucun compteur n'est extrapolé : `offers_read` compte les annonces
réellement lues dans les flux, pas une estimation de volume.

---

## 2. Critères non négociables — preuve

| Critère | Où c'est garanti | Test |
|---|---|---|
| Aucune progression fictive | Les compteurs ne bougent que sur travail fini ; la progression n'est plus calculée côté client | `test_a_run_walks_through_the_real_phases_and_counts_real_work`, `test_progress_copy_says_the_steps_come_from_the_server` |
| Phases séquentielles réelles | `EXPLORATION_PHASES` + `ExplorationRun.begin_phase/end_phase` | `test_a_run_walks_through_the_real_phases_and_counts_real_work` |
| Maximum 2 sources simultanées | `ThreadPoolExecutor(max_workers=2)` sur des lots de 2 | `test_at_most_two_sources_are_consulted_at_the_same_time` (mesure `max_concurrent == 2`) |
| Annulation coopérative entre deux sources | `cancel_requested` persisté, testé entre deux lots | `test_cancellation_stops_between_two_sources_and_keeps_the_previous_results` |
| Reprise après rechargement | État dans `career_settings`, relu par `run_id` | `test_the_state_of_a_run_survives_a_reload`, `test_http_endpoints_start_read_and_cancel_a_run` |
| Recherche interrompue conserve les résultats précédents | Un run annulé n'écrit pas de snapshot : le published précédent reste published | `test_cancellation_stops_between_two_sources_and_keeps_the_previous_results` |
| Erreurs partielles isolées | Une source en échec n'interrompt pas le run, n'efface aucune offre | `test_a_failing_source_is_isolated_and_the_other_offers_are_kept` |
| Aucun processus orphelin | Threads `daemon` suivis, `shutdown()` à l'arrêt de l'application (`router.on_shutdown`) | `test_no_exploration_thread_survives_the_shutdown` |
| Un seul run à la fois | Verrou de recherche partagé avec l'explorateur historique | `test_a_second_run_is_refused_while_one_is_running` |
| Progression affichée = progression réelle | Le client n'invente plus de pourcentage ; il affiche l'état du serveur | `test_the_frontend_polls_the_real_server_state` |

---

## 3. Fichiers

Créés :

```text
career/exploration_run.py            # modèle de run, phases, persistance
career/exploration_service.py        # orchestration des phases, annulation, cache
career_static/js/exploration-progress.js  # client de polling (état serveur)
tests/test_exploration_progress.py   # 11 tests dédiés
docs/agent-reports/SPEC-SK05-EXPLORATION_PROGRESS.md
```

Modifiés :

```text
career/router.py                     # 4 routes d'exploration + arrêt du service
career_static/index.html             # chargement du module, libellé « progression réelle », bouton d'arrêt
career_static/career.js              # le bouton « Explorer les stages » pilote désormais le run réel
tests/test_career_search_ux.py       # les deux garde-fous de la progression estimée sont remplacés
```

`career/service.py` **n'est pas modifié** : le nouveau pipeline lit le registre, les
connecteurs, le cache local et la table `career_settings` à travers un seul adaptateur
(`CareerExplorationBackend`), ce qui évite tout conflit avec les missions SK-01→SK-04 qui
touchent le service.

`career_static/career.js` est un **fichier partagé** : la modification y est minimale et
ciblée (bloc de progression + gestionnaire du bouton « Explorer les stages »). Si
`scripts/audit_integration.py` est utilisé pour l'intégration, il faut ajouter
`--allow-shared-path career_static/career.js`.

---

## 4. Interface

`career_static/js/exploration-progress.js` interroge le serveur et n'affiche que ce qu'il a
réellement terminé :

```text
Consultation des sources (en cours) — 8/21 sources terminées · 7 réussies · 1 en erreur ·
340 annonces lues · 57 offres qualifiées
```

- le pourcentage est `phases_completed / phases réelles` (jamais une estimation) ;
- l'identifiant du run est memorized (`localStorage`) : après un rechargement, la page
  retrouve le run et reprend le polling ;
- un bouton « Arrêter la recherche » demande l'arrêt coopératif entre deux sources ;
- le message « Progression estimée » a disparu de l'interface **et** du code.

---

## 5. Validation réellement exécutée

```text
.venv/bin/python -m pytest -q tests/test_exploration_progress.py   → 11 passed
.venv/bin/python -m pytest -q tests/test_career_search_ux.py        → 6 passed
.venv/bin/python -m pytest -q                                      → 1384 passed, 1 skipped
.venv/bin/python -m ruff check .                                   → All checks passed!
git diff --check                                                   → propre
```

(`pytest` et `ruff` sont exécutés avec le `.venv` du dépôt principal : le worktree n'a pas
son propre environnement virtuel.)

---

## 6. Limites assumées et dette

1. **Deux chemins d'exploration coexistent.** L'endpoint historique
   `POST /api/career/stage-search/explore` reste synchrone et inchangé ; les nouveaux
   endpoints ajoutent le run phasé. Les deux écrivent le même snapshot, donc l'interface
   historique continue de fonctionner. Une refonte unique serait une mission dédiée.
2. **Logique dupliquée.** Le nouveau pipeline rejoue les règles pures déjà présentes dans
   `career/exploration.py`, `career/stage_search.py` et `career/offer_qualification.py`
   (il les réutilise, il ne les redit pas), mais l'enchaînement orchestration est écrit à
   nouveau. Extraire un cœur commun est la suite logique.
3. **Accès interne au service.** `CareerExplorationBackend` lit quelques attributs privés de
   `CareerService` (registre, connecteurs, cache, table `career_settings`). C'est le prix
   de ne pas modifier `career/service.py` en parallèle des autres missions. Une méthode
   publique dédiée serait préférable à terme.
4. **Un run à la fois.** Une exploration bloque les autres explorations (verrou partagé avec
   l'explorateur historique) : c'est volontaire, pour ne pas multiplier les requêtes vers
   les/job boards publics.
5. **Arrêt non instantané.** L'arrêt est coopératif : il intervient entre deux sources. Une
   source déjà lue va jusqu'au bout, conformément au critère « annulation entre deux
   sources ».

---

## 7. Intégration proposée

```bash
git push origin agent/spec-sk05-exploration-progress
python scripts/audit_integration.py \
  --branch agent/spec-sk05-exploration-progress \
  --base a054c97 \
  --allow-path career/exploration_run.py \
  --allow-path career/exploration_service.py \
  --allow-path career/router.py \
  --allow-path career_static/js/ \
  --allow-path career_static/index.html \
  --allow-path career_static/career.js \
  --allow-path tests/test_exploration_progress.py \
  --allow-path tests/test_career_search_ux.py \
  --allow-path docs/agent-reports/SPEC-SK05-EXPLORATION_PROGRESS.md \
  --allow-shared-path career_static/career.js
```

Audit réellement exécuté sur la branche : **VERDICT : MERGE AUTORISÉ**
(base, périmètre, fichiers partagés, motifs interdits, worktree jetable, `pytest`, `ruff`,
`git diff --check`).
