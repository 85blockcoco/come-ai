# CVBOOST-13 — Ranking géographique (Boost étranger, Pénalité France)

**Branche** : `agent/cvboost-13-geo-ranking` (worktree dédié)
**Base** : `main` (`3a0d1ee`, « merge: integrate reviewed Spec Kit Career cycles »)
**Date** : 2026-10-21
**Auteur** : Agent Mission 13 (CVBOOST)
**Dépendance** : Mission 11 (filtre pays connecteurs) — intégration séquencée 11 → 13

---

## 1. Le contrat géographique livré

| Règle | Valeur | Comportement |
|-------|--------|--------------|
| Pays exclu (France par défaut) | **-50** points | Appliqué une seule fois, jamais cumulé |
| Pays ciblé (`preferred_countries`) | **+20** points | Appliqué une seule fois, même si le pays figure dans une longue liste |
| Pays ni exclu ni ciblé | **0** | Neutre, le motif reste affiché |
| Pays non écrit par la source | **0** | « Pays inconnu » — aucune déduction |
| Score total | **borné 0-100** | `max(0, min(100, base + geo))` |

**Pas de géo-inférence** : le pays n'est jamais déduit d'une ville. « Francfort » reste un
pays inconnu (`Pays inconnu`, 0 point) tant que la source n'écrit pas le pays ; une offre
publiée à Francfort avec `country="Germany"` reçoit le bonus DE et **jamais** la pénalité FR.
Une ville ne prouve jamais un pays.

**Signal de classement, pas filtre** : les points géographiques ne changent jamais
`target_status`. L'admissibilité reste décidée par les seules exclusions que la personne a
choisies. Une offre française reste donc consultable, elle ne peut simplement plus être en tête.

---

## 2. Fichiers touchés (périmètre autorisé respecté)

| Fichier | Modification |
|---------|--------------|
| `career/models.py` | Table fermée des pays (`_COUNTRY_ALIASES`), `canonical_country_code()`, `country_wordings()`, `COUNTRY_LABELS`, `DEFAULT_PREFERRED_COUNTRIES`, `DEFAULT_GEO_EXCLUDED_COUNTRIES`, `GEO_PREFERRED_BOOST`, `GEO_EXCLUDED_PENALTY` |
| `career/offer_qualification.py` | `geo_score_for()`, `geo_score` / `geo_reason` dans `QualifiedOffer`, exclusion dure qui reconnaît « FR » = « France » |
| `career/stage_search.py` | Brief : `preferred_countries` + `geo_excluded_countries`, score total, vocabulaire pays |
| `career/discovery.py` | Le classement de la découverte utilise le score total + un rang géographique |
| `career/router.py` | **Écart assumé** — voir §2.1 : `StageSearchPayload` (+2 champs optionnels) |
| `tests/test_geo_ranking.py` | **Nouveau** — 27 tests synthétiques, hors réseau |
| `docs/agent-reports/CVBOOST-13-GEO_RANKING.md` | **Nouveau** — ce rapport |

**Non touchés** (interdits) : `career/service.py`, `career_static/*`, `requirements*.txt`,
migrations, `SCHEMA_VERSION`.

### 2.1 Écart assumé : `career/router.py`

La mission demande d'« étendre `StageSearchPayload` avec `preferred_countries`,
`excluded_countries` » et situe cette classe dans `career/models.py`. **Dans ce code,
`StageSearchPayload` est un modèle pydantic de `career/router.py`** (`career/models.py` ne
contient que des fonctions et des constantes). Sans modifier ce modèle, la liste des pays
ciblés serait **impossible à régler depuis l'API du brief** : le corps HTTP est filtré par
le modèle et un champ inconnu est ignoré — la contrainte produit « configurable via brief »
serait donc violée.

Le changement est **additif et minimal** (deux champs optionnels, `default=None`, aucun
comportement existant modifié) :

```python
preferred_countries: list[str] | None = Field(default=None, max_length=40)
geo_excluded_countries: list[str] | None = Field(default=None, max_length=40)
```

`None` signifie « non configuré » (les valeurs par défaut du produit s'appliquent), une
liste vide signifie « désactivé ». Si le relecteur préfère ne pas toucher au routeur, ce
hunk peut être retiré seul : la fonctionnalité reste complète (valeurs par défaut
européennes, exclusion dure existante, pénalité liée à `excluded_countries`), seule
l'API perd l'accès à `preferred_countries`.

### 2.2 Tests préexistants adaptés (3)

Trois tests de `tests/test_career_stage_hunter.py` mesuraient la **pertinence** d'une offre
française dans un brief sans critère géographique. La règle géographique s'appliquant par
défaut, leur score de classement passe de 100 à 50 : leur brief autorise désormais
explicitement la France (`"excluded_countries": []`), ce qui restaure exactement leur
intention d'origine (mesurer la pertinence, pas la géographie). Aucune assertion n'a été
affaiblie : les trois tests gardent leurs attentes initiales.

```diff
-    service.update_stage_search({"domains": ["M&A"]})
+    service.update_stage_search({"domains": ["M&A"], "excluded_countries": []})
```

La nouvelle règle est couverte par `tests/test_geo_ranking.py` (27 tests dédiés).


---

## 3. Configuration par le brief

```python
DEFAULT_PREFERRED_COUNTRIES = ("DE", "GB", "CH", "NL", "LU", "BE", "IE", "AT", "SE", "NO",
                               "DK", "FI", "ES", "IT", "PT", "PL", "CZ", "HU", "RO", "BG",
                               "HR", "SI", "SK", "EE", "LV", "LT", "MT", "CY")
DEFAULT_GEO_EXCLUDED_COUNTRIES = ("FR",)
```

| Clé du brief | Défaut | Rôle |
|--------------|--------|------|
| `preferred_countries` | 28 pays européens (ci-dessus) | Pays **récompensés** (+20) |
| `geo_excluded_countries` | `["FR"]` | Pays **pénalisés** (-50) |
| `excluded_countries` | `[]` | Exclusion **dure** (inchangée) |

Règles de résolution, appliquées dans `validate_brief()` :

1. `geo_excluded_countries` présent → il gagne, **même vide** (la pénalité est alors éteinte) ;
2. sinon, si `excluded_countries` est présent → la liste d'exclusions sert aussi de liste de
   pénalisation ;
3. sinon → défaut `["FR"]`.

Une liste **explicitement vide** désactive donc la pénalité : les exclusions restent
éditables, ce n'est pas une règle cachée. La liste géographique explicite, elle, remplace
entièrement la liste d'exclusions (elle ne s'y ajoute pas).

Le vocabulaire exposé à l'interface (`vocabulary()`, aka `stage_search_vocabulary`) contient
`preferred_countries`, `geo_excluded_countries`, `countries` (code + libellé),
`geo_preferred_boost` et `geo_excluded_penalty`.

---

## 4. Le score total atteint tous les classements

Point d'attention de cette mission : le score de pertinence (`score_brief_match`) était lu
tel quel par **trois** classements — la découverte (`career/discovery.py`), la liste des
offres enregistrées (`career/service.py`, `list_stage_matches`) et l'explorateur
(`career/exploration.py`, `ranking_key`). Appliquer la pénalité dans un seul de ces chemins
aurait laissé la France en tête de la liste affichée à la personne.

Le signal est donc appliqué **une seule fois**, au point commun :

```python
base_score = round(100 * weighted_points / weighted_maximum) if weighted_maximum else None
geo_score, geo_reason = geo_score_for(job.get("country"),
                                       preferred_countries=brief.get("preferred_countries"),
                                       excluded_countries=_geo_excluded_countries(brief))
score = None if base_score is None else max(0, min(100, base_score + geo_score))
```

`score_brief_match()` renvoie désormais :

| Clé | Signification |
|-----|---------------|
| `score` | **score total** utilisé par tous les classements (pertinence + géographie, borné 0-100) |
| `base_score` | pertinence seule, sans le signal géographique |
| `total_score` | alias de `score` (lisibilité) |
| `geo_score` | -50, 0 ou +20 |
| `geo_reason` | « Pays exclu (FR) », « Pays ciblé (DE) », « Pays neutre (US) », « Pays inconnu » |

La découverte (`career/discovery.py`) ajoute en plus un rang géographique explicite : une
offre pénalisée passe **derrière toutes les autres**, même devant une offre non conforme.

---

## 5. Classement avant / après (exemples synthétiques)

Brief : `{"domains": ["Corporate Finance"]}` — les six offres ont exactement la même
pertinence (base 100).

| Offre | avant | geo | après | motif |
|-------|------:|----:|------:|-------|
| Paris, France | 100 | **-50** | **50** | Pays exclu (FR) |
| Berlin, Germany | 100 | **+20** | **100** | Pays ciblé (DE) |
| Amsterdam, Netherlands | 100 | **+20** | **100** | Pays ciblé (NL) |
| Luxembourg, Luxembourg | 100 | **+20** | **100** | Pays ciblé (LU) |
| New York, United States | 100 | 0 | 100 | Pays neutre (US) |
| Francfort (pays non indiqué) | 100 | 0 | 100 | Pays inconnu |

Classement final :

```
100  Berlin, Germany
100  Amsterdam, Netherlands
100  Luxembourg, Luxembourg
100  New York, United States
100  Francfort (pays non indiqué)   <- ville seule : jamais déduite
 50  Paris, France                  <- même avec une pertinence parfaite
```

Avant la mission, les six offres étaient à égalité (100) et l'ordre final dépendait
uniquement de l'identité de la source. Après, l'offre française passe en dernière position
et les pays cibles remontent.

---

## 6. Transparence

* `qualify_offer()` renvoie `geo_score` et `geo_reason` (et `country`), visibles dans
  `to_dict()` ; le motif est aussi ajouté aux `reasons` de la qualification.
* `score_brief_match()` renvoie `geo_score` / `geo_reason` et l'insère en tête des raisons
  (« Pays exclu (FR) : -50 points au classement. »).
* Le code pays retenu et le libellé sont ceux que la **source** a écrits ; le tableau de
  correspondance ne remplace jamais la formulation d'origine.

---

## 7. Tests

`tests/test_geo_ranking.py` — **27 tests**, tous synthétiques et hors réseau :

| Test | Ce qu'il garantit |
|------|-------------------|
| `test_france_penalty_50` | geo_score = -50, total réduit de 50 |
| `test_preferred_country_boost_20` | pays ciblé → +20 |
| `test_multiple_preferred_is_not_cumulative` | un pays ciblé ne rapporte ses points qu'une fois |
| `test_neutral_country` | pays ni ciblé ni exclu → 0 |
| `test_country_unknown_neutral` | sans pays écrit → 0, « Pays inconnu » |
| `test_frankfurt_is_not_france` | une ville ne prouve jamais un pays |
| `test_no_geographic_inference_from_the_city` | idem, sur le score de classement |
| `test_preferred_override_default` | sans liste explicite → défaut européen |
| `test_excluded_override_default` | liste vide → pénalité éteinte |
| `test_explicit_geo_exclusion_list_wins` | la liste géographique remplace l'autre |
| `test_brief_defaults_penalize_france_and_reward_europe` | les défauts sont exposés |
| `test_vocabulary_exposes_the_country_lists` | le formulaire peut afficher les pays |
| `test_geo_reason_is_visible_in_the_qualification` | score + motif dans la qualification |
| `test_score_is_bounded_between_0_and_100` | le total reste dans 0-100 |
| `test_geo_signal_never_changes_admissibility` | classement ≠ filtre |
| `test_geo_score_for_is_pure_and_explicit` | fonction pure, exclusion prioritaire |
| `test_france_never_leads_the_ranking` | la France n'est jamais en tête |
| `test_ranking_integration_uses_the_total_score` | la découverte suit le score total |
| `test_preferred_country_climbs_over_a_neutral_one` | un pays ciblé remonte |
| `test_internship_selection_reports_the_geographic_signal` | la qualification porte le signal |
| `test_a_country_code_and_its_name_exclude_the_same_offer` | « FR » = « France » |
| `test_a_country_outside_the_table_is_still_penalised_verbatim` | exclusion écrite telle quelle |
| `test_the_saved_offer_list_never_leads_with_a_penalised_country` | **la liste de l'application** respecte la règle |
| `test_the_geographic_points_are_part_of_the_score_every_ranking_uses` | `score` = total |
| `test_vocabulary_exposes_the_country_labels` | libellés de pays |
| `test_the_brief_api_accepts_the_country_lists` | l'API accepte les deux listes |
| `test_the_brief_api_keeps_the_local_defaults_when_nothing_is_set` | les défauts du produit tiennent |

---

## 8. Validation

```bash
.venv/bin/python -m pytest -q tests/test_geo_ranking.py   # 27 passed
.venv/bin/python -m pytest -q                              # 1394 passed, 1 skipped
.venv/bin/python -m ruff check .                           # All checks passed!
git diff --check                                            # propre
```

Aucune régression : la suite complète passe (1367 tests avant la mission, 1394 après — les
27 nouveaux). Aucun appel réseau, aucune donnée réelle, aucune migration, `SCHEMA_VERSION`
inchangé.

---

## 9. Limites assumées

* **Le signal ne remplace pas l'exclusion dure.** Une offre France reste visible et
  consultable ; elle est simplement jamais en tête. Le filtre « zéro France » reste le
  travail de la Mission 11 (côté connecteur) et des exclusions que la personne coche.
* **La pénalité France suit la configuration.** Si la personne remplace la liste des pays
  exclus par une liste qui ne contient pas la France, la pénalité France ne s'applique plus :
  les exclusions restent éditables, ce n'est pas une règle cachée.
* **Aucun fuseau, aucune carte, aucun fuseau horaire** : seuls le pays écrit par la source
  et les listes du brief entrent dans le calcul.
* **Le score total reste un score de priorité**, pas une probabilité de recrutement
  (l'avertissement existant du module est inchangé).

---

## 10. Notes d'intégration

* La mission doit être intégrée **après la Mission 11** (ordre séquentiel 11 → 13) ; les
  deux ne modifient pas les mêmes fichiers.
* `career/service.py` n'a pas été modifié : la lecture du brief passe par
  `default_brief()` / `validate_brief()`, qui fournissent déjà `preferred_countries` et
  `geo_excluded_countries`. Le service continue donc d'utiliser `excluded_countries` pour
  l'exclusion dure et reçoit le signal géographique par le score total.
* Aucun changement d'API publique : les nouvelles clés du brief sont additionnelles, les
  nouvelles clés de `score_brief_match()` aussi. Les deux champs du payload HTTP sont
  optionnels (`None` = non configuré).
