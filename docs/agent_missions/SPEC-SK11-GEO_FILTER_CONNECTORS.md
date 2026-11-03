# MISSION SPEC KIT — SK-11 : Filtre pays côté connecteurs

> **Priorité : P0 — PRÉREQUIS ABSOLU** — Sans ça, les offres France polluent tout le pipeline. Module indépendant, worktree dédié.

---

## Contexte

Le connecteur Greenhouse (85% du corpus) ne filtre **PAS** par pays côté source. `canonicalize_url` et `location_canonical` existent mais le filtre `country` n'est pas poussé aux connecteurs. `discover_stage_offers()` appelle les connecteurs sans passer le filtre `country` → 120 offres dont ~60% France.

**Impact** : L'utilisateur voit des offres France qu'il ne veut pas.

---

## Modules à modifier

```
career/discovery.py
career/connectors/public_ats.py
career/connectors/welcome_jungle.py
career/connectors/jobteaser.py
career/connectors/talent_com.py
career/connectors/apec.py
career/service.py
tests/test_geo_filter_connectors.py
tests/fixtures/geo_filter/
```

---

## Règles non négociables

1. **Le filtre s'applique AU NIVEAU DU CONNECTEUR** — pas après coup dans le pipeline
2. **Paramètre `countries_exclude` passé à `iter_offers()` / `discover_internships()`** — liste de codes ISO-2 (ex: `["FR"]`)
3. **Paramètre `countries_include` optionnel** — pour sources 100% ciblées (EURES, LinkedIn Europe)
4. **Zéro régression** : connecteur sans paramètre = comportement actuel (tous pays)
5. **Filtrage AVANT qualification** — économise quota, CPU, bande passante
6. **Métrique `offers_filtered_geo`** dans `DiscoveryPayload` pour audit

---

## Changements par connecteur

### Greenhouse (`discovery.py`)

```python
# Ligne ~339-342: discover_ranked accepte nouveau paramètre
def discover_ranked(
    self, board: GreenhouseBoard, *, selection_brief: dict[str, Any] | None = None,
    internships_only: bool = False, deadline: float | None = None,
    countries_exclude: list[str] | None = None,  # NOUVEAU
) -> DiscoveryPayload:

# Ligne ~413: _location_parts appelle AVANT normalisation
city, country = _location_parts(location.get("name"), preserve_multi_locations=internships_only)
# AJOUTER IMMÉDIATEMENT APRÈS:
if countries_exclude and country:
    code = canonical_country_code(country)
    if code in countries_exclude:
        filtered_geo_count += 1
        continue
```

### Public ATS (`public_ats.py`)

```python
# Ligne ~151: discover_internships signature
def discover_internships(self, source: dict[str, Any], *, selection_brief: dict[str, Any],
                         deadline: float | None = None,
                         countries_exclude: list[str] | None = None) -> DiscoveryPayload:  # NOUVEAU

# Dans _normalise_one (ligne ~348-393):
country = clean_text(country or country_from_location, limit=120)
# AJOUTER:
if countries_exclude:
    code = canonical_country_code(country)
    if code in countries_exclude:
        return None  # Skip avant yield
```

### Welcome to the Jungle (`welcome_jungle.py`)

```python
# Ligne ~168: _build_search_url accepte déjà country_codes
# Ligne ~187: _is_france_location existe → GÉNÉRALISER
def _is_excluded_location(city: str, country: str, excluded_codes: list[str]) -> bool:
    code = canonical_country_code(country) or _infer_country_from_city(city)
    return code in excluded_codes

# Dans _iter_raw_offers (ligne ~283):
if _is_excluded_location(city, country, countries_exclude or ["FR"]):
    continue
```

### JobTeaser / Talent.com / APEC

Même pattern : filtre précoce sur `country` canonique ISO-2.

---

## Service : passage du paramètre

```python
# career/service.py dans la méthode qui appelle les connecteurs
brief = validate_brief(selection_brief)
countries_exclude = brief.get("geo_excluded_countries") or brief.get("excluded_countries") or ["FR"]

payload = connector.discover_internships(
    source, selection_brief=brief, deadline=deadline,
    countries_exclude=countries_exclude
)
```

---

## Validation

### Fixtures synthétiques (minimum 12)

| Connecteur | Cas | Attendu |
|------------|-----|---------|
| Greenhouse | Offre Paris, France | Filtrée (excluded) |
| Greenhouse | Offre London, UK | Gardée |
| Greenhouse | Offre "Paris/London" multi-loc | Gardée (preserve_multi_locations) |
| Greenhouse | Offre sans country | Gardée (unknown ≠ France) |
| Lever | Offre Frankfurt, DE | Gardée |
| Lever | Offre Paris, FR | Filtrée |
| Ashby | Offre sans country | Gardée |
| SmartRecruiters | Offre multi-pays dont FR | Gardée (si autre pays autorisé) |
| WTTJ | Scraping retourne Paris | Filtrée côté client |
| WTTJ | Scraping retourne Berlin | Gardée |
| JobTeaser | Offre remote, company FR | Gardée (remote ≠ France) |
| APEC | Offre Paris (source FR-only) | Filtrée |

### Tests live (bornés, séparés)

- 1 board Greenhouse réel avec offres FR + non-FR
- Vérifier `DiscoveryPayload.filtered_geo_count > 0`

---

## Commandes de validation

```bash
./checklist_codex.sh
.venv/bin/python -m pytest -q tests/test_geo_filter_connectors.py
.venv/bin/python -m pytest -q
git diff --check
```

---

## Critères de réussite

- [ ] `countries_exclude` passé à **tous** les 8 connecteurs
- [ ] Filtrage **avant** normalisation complète (économie ressources)
- [ ] `DiscoveryPayload` inclut `filtered_geo_count`
- [ ] 12+ fixtures synthétiques couvrant tous connecteurs + cas multi-loc
- [ ] Test live : 0 offres France dans résultats avec `geo_excluded_countries=["FR"]`
- [ ] Ruff clean, suite complète verte, `git diff --check` propre
- [ ] Rapport `docs/agent-reports/SPEC-SK11-GEO_FILTER_CONNECTORS.md`

---

## Squelette minimal (test)

```python
# tests/test_geo_filter_connectors.py
import pytest
from career.discovery import GreenhouseJobBoardConnector
from career.connectors.public_ats import LeverConnector, AshbyConnector

class TestGeoFilter:
    @pytest.fixture
    def greenhouse_connector(self):
        return GreenhouseJobBoardConnector()

    def test_greenhouse_excludes_france(self, greenhouse_connector, monkeypatch):
        # Mock transport retourne offres Paris + London
        # Vérifier que seulement London reste
        ...

    def test_multi_location_preserved(self, greenhouse_connector):
        # "Paris/London/Berlin" → gardée car preserve_multi_locations=True
        ...

    def test_unknown_country_not_filtered(self, greenhouse_connector):
        # country="" → gardée (pas de filtrage sur unknown)
        ...

    def test_all_connectors_accept_parameter(self):
        for connector_cls in [LeverConnector, AshbyConnector, ...]:
            assert "countries_exclude" in inspect.signature(connector_cls.discover_internships).parameters
```

---

**Tu as tout. Lance-toi.** Branche `agent/spec-sk11-geo-filter-connectors`, worktree dédié, code (8 connecteurs), tests (12+ fixtures), rapport, push. Je relis et j'intègre. **Mission bloquante pour tout le reste.**