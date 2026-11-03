# MISSION AGENT — Mission 11 : Filtre pays côté connecteurs (Zéro France)

> **Contexte** : 85% des offres viennent de Greenhouse qui ne filtre pas par pays. L'utilisateur ne veut **jamais** de France. Il faut pousser le filtre `countries_exclude=["FR"]` **côté connecteur** pour ne pas polluer la base.
> Base : `main` (tag `v3-cvboost-sources-2026-10-20`), 1318 tests verts.
> Dépendances : **Mission 06** (connecteurs) — **satisfaites**.

---

## Périmètre autorisé

| Fichier | Rôle |
|---|---|
| `career/connectors/public_ats.py` | Modifier `iter_offers()` pour accepter `countries_exclude` et filtrer côté source |
| `career/connectors/welcome_jungle.py` | Ajouter paramètre `countries_exclude` à `iter_offers()` |
| `career/connectors/jobteaser.py` | Idem |
| `career/connectors/talent_com.py` | Idem |
| `career/connectors/apec.py` | Idem |
| `career/discovery.py` | `discover_stage_offers()` : passer `countries_exclude=["FR"]` par défaut |
| `career/stage_search.py` | Ajouter `countries_exclude` au vocabulaire / brief |
| `tests/test_connectors_geo_filter.py` | **Nouveau** — tests unitaires filtrage géographique |
| `docs/agent-reports/CVBOOST-11-GEO_FILTER.md` | Rapport obligatoire |

**Interdit** : `career/service.py`, `career/router.py`, `career_static/*`, `requirements*.txt`, migrations, `SCHEMA_VERSION`.

---

## Contraintes produit (non négociables)

1. **Filtrage CÔTE SOURCE** : le connecteur ne doit JAMAIS retourner d'offre dont le pays est dans `countries_exclude`. Pas de post-filtrage dans `discovery.py` — ça gaspille quota/API.
2. **Détection pays robuste** : chaque connecteur doit normaliser le pays (`country_canonical`) AVANT de filtrer. Greenhouse n'a pas toujours `country` → déduire depuis `location` / `office.country_code`.
3. **Paramètre par défaut** : `countries_exclude=["FR"]` dans `discover_stage_offers()` — l'utilisateur ne veut JAMAIS de France.
4. **Override possible** : l'utilisateur peut vider la liste via `stage_search` brief (mais défaut = FR exclu).
5. **Métriques** : chaque connecteur loggue `raw_count`, `filtered_count`, `excluded_count` par pays dans `health_check()`.

---

## Spécifications techniques

### 1. `career/connectors/public_ats.py` — Base commune

```python
def iter_offers(
    query: str,
    location: str,
    *,
    countries_exclude: list[str] | None = None,
    max_pages: int = 5,
    rate_limit: float = 2.0,
) -> Iterator[RawOffer]:
    # 1. Appel API avec paramètres de localisation
    # 2. Pour chaque offre brute:
    #    - country = canonicalize_country(raw_office_country_code)
    #    - if country in countries_exclude: excluded_count += 1; continue
    #    - yield offer avec country_canonical
```

### 2. `career/connectors/welcome_jungle.py` — Override

```python
def iter_offers(query, location, *, countries_exclude=None, ...):
    # Utilise refinementList[office.country_code][] pour pré-filtrer côté API
    # Puis double-vérification locale avec country_canonical
```

### 3. `career/discovery.py` — Point d'entrée

```python
def discover_stage_offers(..., countries_exclude: list[str] | None = None) -> ...:
    if countries_exclude is None:
        countries_exclude = ["FR"]  # DÉFAUT : jamais France
    for connector in CONNECTOR_REGISTRY.values():
        for offer in connector.iter_offers(..., countries_exclude=countries_exclude):
            yield offer
```

### 4. `career/stage_search.py` — Brief utilisateur

```python
# Dans StageSearchPayload : countries_exclude: list[str] = Field(default_factory=lambda: ["FR"])
# Dans validate_brief : si countries_exclude non fourni → défaut ["FR"]
```

---

## Tests obligatoires (≥ 15)

| Test | Description |
|------|-------------|
| `test_greenhouse_excludes_france` | Greenhouse ne retourne pas d'offre `country="FR"` |
| `test_welcome_jungle_excludes_france` | WJ filtre via `office.country_code` + double-check |
| `test_jobteaser_excludes_france` | JobTeaser filtre pays |
| `test_talent_com_excludes_france` | Talent.com filtre |
| `test_apec_excludes_france` | APEC filtre (France par défaut) |
| `test_canonicalize_country_fr_variants` | "FR", "France", "FRA", "fr" → tous exclus |
| `test_frankfurt_not_excluded` | "Frankfurt" (DE) NE doit PAS être exclu par "fr" |
| `test_countries_exclude_empty` | `countries_exclude=[]` → aucune exclusion |
| `test_override_via_brief` | `countries_exclude=[]` dans brief → France revenue |
| `test_default_is_fr_excluded` | Sans brief → FR exclu par défaut |
| `test_metrics_excluded_count` | `health_check()` retourne `excluded_by_country: {"FR": 42}` |
| `test_greenhouse_office_country_code` | Greenhouse utilise `office.country_code` pour déduire pays |
| `test_mixed_countries` | Lot mélangé FR/DE/UK → seulement FR exclu |
| `test_case_insensitive` | "fr", "Fr", "FR" tous exclus |

---

## Commandes de validation

```bash
./checklist_codex.sh
.venv/bin/python -m pytest -q tests/test_connectors_geo_filter.py
.venv/bin/python -m pytest -q
git diff --check
```

---

## Critères de validation (relecteur)

- [ ] 0 offre France retournée par n'importe quel connecteur (testé sur 500+ offres synthétiques)
- [ ] `discover_stage_offers()` sans argument exclut France
- [ ] `countries_exclude=[]` dans brief → France revenue
- [ ] `health_check()` de chaque connecteur expose `excluded_by_country`
- [ ] Ruff clean, 1318+ tests passent, `git diff --check` propre
- [ ] Rapport `CVBOOST-11-GEO_FILTER.md` avec métriques : `excluded_by_country` par connecteur sur 3 runs réels

---

## Squelette minimal (copier-coller)

```python
# career/connectors/public_ats.py — AJOUT dans iter_offers signature
def iter_offers(
    query: str,
    location: str,
    *,
    countries_exclude: list[str] | None = None,
    max_pages: int = 5,
    rate_limit: float = 2.0,
) -> Iterator[RawOffer]:
    excluded = set(c.lower() for c in (countries_exclude or []))
    for raw in _fetch_raw_offers(query, location, max_pages, rate_limit):
        country = canonicalize_country(raw.get("office", {}).get("country_code") or raw.get("country"))
        if country and country.lower() in excluded:
            _HEALTH.excluded_by_country[country.upper()] = _HEALTH.excluded_by_country.get(country.upper(), 0) + 1
            continue
        yield _to_raw_offer(raw, country)

# career/discovery.py
def discover_stage_offers(..., countries_exclude: list[str] | None = None):
    if countries_exclude is None:
        countries_exclude = ["FR"]
    for connector in CONNECTOR_REGISTRY.values():
        for offer in connector.iter_offers(..., countries_exclude=countries_exclude):
            yield offer
```

---

**Tu as tout. Lance-toi.** Branche `agent/cvboost-11-geo-filter`, worktree dédié, code, tests, rapport, push. Je relis et j'intègre. **C'est LA mission bloquante — sans elle, tout le reste est pollué par la France.**