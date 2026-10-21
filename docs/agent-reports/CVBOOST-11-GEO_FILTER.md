# CVBOOST-11 — Filtre pays côté connecteurs (Zéro France)

**Branche** : `agent/cvboost-11-geo-filter` (worktree dédié `AI-Excel-Agent-cvboost-11-geo-filter`)
**Base** : `main` @ `3a0d1ee` (merge: integrate reviewed Spec Kit Career cycles)
**Implémentation** : `c8bfbe4` — *feat(career): CVBOOST-11 — filtre pays côté connecteurs (zéro France)*
**Date** : 2026-10-21
**Auteur** : Worker Mission 11 (CVBOOST)
**Dépendance** : Mission 06 (connecteurs) — satisfaite

---

## 1. Pourquoi cette mission

85 % des offres viennent de Greenhouse, qui ne filtre pas par pays. La personne ne veut
**jamais** d'offre française. Tant que le filtrage est fait après coup, dans
`discovery.py`, la France continue de :

- consommer le quota et le budget de recherche de la source,
- polluer la base locale (les offres sont persistées puis éliminées),
- fausser les compteurs de santé (`raw_count` / `filtered_count`) et donc la lecture
  qu'on fait de la performance d'une source.

Cette mission pousse donc le filtre **côté connecteur** : chaque connecteur normalise
le pays qu'il publie, écarte les pays exclus **avant** de matérialiser l'offre, et
publie dans `health_check()` ce que chaque pays a coûté.

---

## 2. Architecture technique

### 2.1 Nouveau fichier : `career/countries.py`

Vocabulaire ISO 3166-1 canonique, 100 % local (aucun appel réseau) :

| Fonction | Rôle |
|----------|------|
| `canonicalize_country(value)` | Un libellé de pays → code ISO alpha-2. `"FR"`, `"fr"`, `"FRA"`, `"France"`, `"République Française"` → `FR`. Un libellé inconnu → `""`. |
| `country_from_source(country)` | Idem, en acceptant un champ qui contient une localisation complète (`"London, United Kingdom"` → `GB`). |
| `canonical_country_codes(values)` | Liste d'exclusion → codes canoniques, sans doublon, ordre conservé. |
| `DEFAULT_COUNTRIES_EXCLUDE` | `("FR",)` — le défaut produit, la France. |

**Règle de non-invention** (cohérente avec le reste du produit) : un libellé inconnu
n'invente jamais un pays. `canonicalize_country("Frankfurt")` renvoie `""` — un nom de
ville n'est pas un pays. `"Paris"` reste un pays inconnu : l'offre est conservée et
affichée *à vérifier*, elle n'est jamais écartée comme française sur une supposition.

### 2.2 Normalisation avant filtrage

Chaque connecteur applique **son propre** vocabulaire avant de décider :

| Connecteur | Source du pays | Fallback |
|------------|----------------|----------|
| Greenhouse (`career/discovery.py`) | `location.office.country_code`, puis `location.country_code` | `location.name` (prose) via `country_from_source()` |
| ATS publics (`career/connectors/public_ats.py`) | champ pays du vendor (Lever `country`, Ashby `address.postalAddress.addressCountry`, SmartRecruiters `location.country`) | localisation |
| Welcome to the Jungle, JobTeaser, Talent.com, APEC | 2ᵉ fragment de la localisation (`"Paris, France"` → `France`) | 1ᵉ fragment |

Sur Greenhouse, **le code structurel gagne sur la prose** : un tableau qui publie
`office.country_code = "FR"` avec une localisation écrite `London, United Kingdom` est
écarté, car le code est un fait publié et la localisation un texte.

### 2.3 Filtrage côté source (avant matérialisation)

L'exclusion est appliquée dans la boucle qui lit les lignes brutes, **avant** la
normalisation d'offre, donc avant toute persistance et avant que l'offre ne consomme
une place dans le top 150 :

- **Greenhouse** : `career/discovery.py` → `country_excluded_count++`, `excluded_count++`,
  `excluded_by_country[FR] += 1`, puis `continue` (l'offre n'est jamais construite).
- **ATS publics** : idem dans `PublicATSConnector.discover_internships()`.
- **4 connecteurs HTML** : idem dans `_iter_raw_offers()` (le filtre est appliqué à la
  ligne parseée, avant `valid_offers++`).
- **Welcome to the Jungle** : en plus, le refinement est demandé **à la source** —
  `refinementList[office.country_code][]` ne contient plus les pays exclus, donc la
  France n'occupe même pas de place dans le flux. Double vérification locale ensuite.

### 2.4 Point d'entrée : `career/discovery.py::discover_stage_offers()`

La fonction n'existait pas dans `main` : elle est créée par cette mission et devient
l'entrée unique de l'explorateur de stages.

```python
excluded = list(DEFAULT_COUNTRIES_EXCLUDE) if countries_exclude is None else list(countries_exclude)
...
payload = connector.discover_internships(
    descriptor, selection_brief=brief, deadline=deadline, countries_exclude=excluded
)
```

- Sans argument → `["FR"]` : la France est exclue par défaut.
- `countries_exclude=[]` → aucune exclusion : la France revient, si la personne le demande.

### 2.5 Brief et vocabulaire : `career/stage_search.py`

Le brief du projet est un `dict` (pas un modèle pydantic) : la règle est implémentée
dans `validate_brief()`.

| Entrée du brief | Résultat |
|-----------------|----------|
| `countries_exclude` absent | `["FR"]` (défaut produit) |
| `countries_exclude: ["DE"]` | `["DE"]` — la France **revenue**, elle n'est plus exclue |
| `countries_exclude: []` | `[]` — plus aucune exclusion |
| `excluded_countries: []` (interface existante vidée) | `[]` — choix explicite, la France revient |
| `excluded_countries: ["Atlantis"]` | `["FR"]` — une liste qui ne nomme aucun pays connu garde le défaut au lieu de désactiver silencieusement le filtre |
| `countries: ["FR"]` | `[]` — un pays explicitement demandé n'est pas exclu |

`vocabulary()` expose `default_countries_exclude: ["FR"]` pour l'interface.

### 2.6 Métriques de santé

Chaque connecteur expose dans `health_check()` :

| Clé | Sens |
|-----|------|
| `raw_count` | lignes brutes lues sur la source |
| `filtered_count` | lignes écartées (pays exclu + critères) |
| `excluded_count` | lignes écartées, tous motifs confondus (contrat non conforme, pays exclu…) |
| `excluded_by_country` | `{pays canonique: nombre}` — ce que **chaque pays** a coûté |

`DiscoveryPayload` porte les mêmes chiffres (`country_excluded_count`,
`excluded_by_country`) et chaque offre conserve `country_canonical`.

> `excluded_count` ≥ `somme(excluded_by_country)` : le premier compte tous les motifs
> d'exclusion (contrat non conforme, durée, langue…), le second uniquement les pays.

---

## 3. Métriques — 3 runs réels (2026-10-21)

Mesures sur les sources publiques du registre curaté (`career/source_registry.py`),
lecture seule, `countries_exclude=["FR"]`, aucune soumission. Script :
`geo_metrics.py` (3 runs par connecteur).

| Connecteur | Lectures | `raw_count` | `filtered_count` | `excluded_count` | `excluded_by_country` | Offres gardées | **Offres FR gardées** |
|------------|---------:|------------:|-----------------:|-----------------:|-----------------------|---------------:|--------------------:|
| Greenhouse | 45 (15 boards × 3) | 4 109 | 2 118 | 1 592 | `{"FR": 192}` | 399 | **0** |
| Lever | 9 (3 sources × 3) | 606 | 192 | 411 | `{"FR": 219}` | 3 | **0** |
| Ashby | 9 (3 sources × 3) | 576 | 126 | 375 | `{"FR": 219}` | 75 | **0** |
| Welcome to the Jungle | 3 | 0 | 0 | 0 | `{}` | 0 | **0** |
| JobTeaser | 3 | 0 | 0 | 0 | `{}` | 0 | **0** |
| Talent.com | 3 | 0 | 0 | 0 | `{}` | 0 | **0** |
| APEC | 3 | 0 | 0 | 0 | `{}` | 0 | **0** |

**Résultat central : 0 offre française conservée, sur 5 291 lignes brutes lues et
630 offres exclues pour cause de pays.** C'est le critère de relecture.

**Fait constaté sur les 4 connecteurs HTML** : les pages publiques répondent 200 et
livrent le HTML (558 Ko pour Welcome to the Jungle), mais les cartes d'offres sont
rendues côté client : le parseur n'extrait 0 ligne sur les pages publiques du
2026-10-21. Leurs métriques de filtrage sont donc **non observables en conditions
réelles** et sont couvertes exclusivement par fixtures synthétiques. Ce comportement
d'extraction relève de la Mission 06, pas de cette mission ; il est signalé ici parce
qu'il rend les chiffres « runs réels » incomplets pour ces quatre connecteurs.

---

## 4. Preuves d'absence d'invention

- Aucune offre fabriquée : une ligne dont le pays est inconnu est **conservée** et
  marquée « à vérifier », jamais écartée ni reinterpretée.
- Aucun code pays deviné : `canonicalize_country` ne connaît que les libellés de son
  vocabulaire ; tout le reste renvoie `""`.
- Aucune ville transformée en pays : `"Frankfurt"` → `""`, `"Paris"` → `""`.
- Aucune exclusion inventée : `canonical_country_codes(["Atlantis"])` → `()`, une
  exclusion ne peut donc pas être déclenchée par un mot inconnu.
- Les métriques sont des compteurs, pas des estimations : elles comptent des lignes
  réellement lues.

---

## 5. Tests — couverture

**30 tests** dans `tests/test_connectors_geo_filter.py`, uniquement des fixtures
synthétiques (aucun socket ouvert).

| Test exigé par la mission | Test implémenté |
|---------------------------|-----------------|
| `test_greenhouse_excludes_france` | `test_greenhouse_excludes_france` |
| `test_welcome_jungle_excludes_france` | `test_welcome_jungle_excludes_france` |
| `test_jobteaser_excludes_france` | `test_jobteaser_excludes_france` |
| `test_talent_com_excludes_france` | `test_talent_com_excludes_france` |
| `test_apec_excludes_france` | `test_apec_excludes_france` |
| `test_canonicalize_country_fr_variants` | `test_canonicalize_country_fr_variants` |
| `test_frankfurt_not_excluded` | `test_greenhouse_frankfurt_is_not_excluded_by_the_fr_code` |
| `test_countries_exclude_empty` | `test_html_connector_can_be_told_to_allow_france` |
| `test_override_via_brief` | `test_greenhouse_brief_can_bring_france_back` |
| `test_default_is_fr_excluded` | `test_default_exclusion_is_france`, `test_greenhouse_default_is_fr_excluded` |
| `test_metrics_excluded_count` | `test_metrics_excluded_count` |
| `test_greenhouse_office_country_code` | `test_greenhouse_office_country_code_is_used_to_deduce_the_country` |
| `test_mixed_countries` | `test_mixed_countries_only_excludes_the_excluded_one` |
| `test_case_insensitive` | `test_case_insensitive_exclusion_list` |

Tests supplémentaires : `test_public_ats_connectors_exclude_france` (Lever / Ashby /
SmartRecruiters), `test_every_connector_exposes_the_geographic_metrics`,
`test_discover_stage_offers_excludes_france_by_default`,
`test_discover_stage_offers_forwards_the_default_exclusion_list`,
`test_discover_stage_offers_can_bring_france_back`,
`test_unknown_country_wording_excludes_nothing`,
`test_no_french_offer_survives_six_hundred_synthetic_offers` (600 offres synthétiques,
300 FR → 0 survivante).

Tests existants mis à jour (et non affaiblis) : les fixtures françaises de
`tests/test_career_agent.py` et `tests/test_career_discovery_selection.py` sont
devenues britanniques — une fixture France serait désormais écartée avant les
assertions — et les tests de `health_check()` des 4 connecteurs attendent désormais les
nouvelles clés de métrique.

---

## 6. Checklist Codex

| Commande | Résultat |
|----------|----------|
| `.venv/bin/python -m pytest -q tests/test_connectors_geo_filter.py` | **30 passed** |
| `.venv/bin/python -m pytest -q` | **1397 passed, 1 skipped** (suite complète, 465 s) |
| `.venv/bin/python -m ruff check .` | **All checks passed!** |
| `git diff --check` | propre |
| `./checklist_codex.sh` | vert |

---

## 7. Fichiers modifiés

| Fichier | Nature |
|---------|--------|
| `career/countries.py` | **nouveau** — vocabulaire ISO 3166-1 canonique |
| `career/discovery.py` | `DiscoveryPayload` (+2 champs), Greenhouse (filtre, `office.country_code`, `health_check`), **`discover_stage_offers()` nouveau** |
| `career/stage_search.py` | `countries_exclude` dans le brief et le vocabulaire |
| `career/connectors/public_ats.py` | filtre pays + `health_check` pour Lever / Ashby / SmartRecruiters |
| `career/connectors/welcome_jungle.py` | filtre pays + refinement source + métriques |
| `career/connectors/jobteaser.py` | idem |
| `career/connectors/talent_com.py` | idem |
| `career/connectors/apec.py` | idem (+ remplacement de l'ancienne heuristique villes françaises) |
| `tests/test_connectors_geo_filter.py` | **nouveau** — 30 tests synthétiques |
| `tests/test_career_agent.py`, `tests/test_career_discovery_selection.py`, `tests/test_*_connector.py` | fixtures passées hors France + nouvelles clés de métrique |

**Hors périmètre respecté** : `career/service.py`, `career/router.py`, `career_static/*`,
`requirements*.txt`, migrations, `SCHEMA_VERSION` — non touchés.

---

## 8. Écarts assumés par rapport au squelette de la mission

La mission décrivait un squelette écrit pour une API qui n'est pas celle du dépôt.
Les intentions ont été respectées, l'API réelle a été suivie :

| Squelette de la mission | API réelle du dépôt |
|--------------------------|---------------------|
| `iter_offers(..., countries_exclude=...)` | `discover_internships(..., countries_exclude=...)` (connecteurs publics) |
| `StageSearchPayload` (pydantic) | brief `dict` validé par `validate_brief()` |
| `discover_stage_offers()` déjà existant | créé dans `career/discovery.py` (absent de `main`) |
| `canonicalize_country` à écrire | écrit dans `career/countries.py`, module dédié et réutilisé |

`career/service.py` étant hors périmètre, le nouveau `discover_stage_offers()` n'est
pas encore branché sur le parcours `CareerService.discover_opportunities()` : le
câblage applicatif reste à faire lors de l'intégration.

---

## 9. Conclusion

Le filtre pays est maintenant appliqué **par la source**, avant toute matérialisation :
0 offre France conservée sur les 3 runs réels (5 291 lignes brutes lues) et 0 sur 600
offres synthétiques. Le défaut est `["FR"]`, il est visible, il est mesurable
(`excluded_by_country` par connecteur) et la personne peut le vider volontairement.
La normalisation ne devine jamais un pays : une ville n'est pas un pays, un libellé
inconnu n'est pas une exclusion.

Reste à faire à l'intégration : brancher `discover_stage_offers()` sur le parcours
`CareerService`, et traiter l'extraction des 4 connecteurs HTML (rendu client-side),
qui appartient à la Mission 06.
