# MISSION SPEC KIT — SK-14 : Sources spécialisées étranger (100% hors-France)

> **Priorité : P0** — Après SK-11 validé. Module indépendant, worktree dédié, peut tourner en parallèle SK-11/SK-13.

---

## Contexte

Greenhouse = 85% du corpus mais filtre France imparfait. Besoin de **4 nouvelles sources 100% hors-France** pour garantir le volume d'offres ciblées.

---

## 4 Connecteurs à créer

| Source | Pays couverts | Type | API/Scraping | Priorité |
|--------|---------------|------|--------------|----------|
| **LinkedIn Europe** | DE, GB, NL, CH, BE, LU, IE, AT, SE, NO, DK, FI, ES, IT, PT, PL | ATS public | HTML scraping (search) | P0 |
| **EURES** | 27 EU + IS, LI, NO, CH | Portail officiel EU | JSON API publique | P0 |
| **JobTeaser International** | DE, GB, NL, BE, CH, ES, IT, PT | Career center écoles | API partenaire / scraping | P1 |
| **Glassdoor International** | US, GB, DE, FR (exclu), CA, AU, etc. | Avis + offres | HTML scraping | P1 |

---

## Modules à créer

```
career/connectors/linkedin_europe.py
career/connectors/eures.py
career/connectors/jobteaser_intl.py
career/connectors/glassdoor_intl.py
career/connectors/__init__.py (registration)
tests/test_intl_sources.py
tests/fixtures/intl_sources/
```

---

## Règles non négociables

1. **Même contrat que connecteurs existants** — `discover_internships(source, selection_brief, deadline) -> DiscoveryPayload`
2. **Filtre pays NATIF** — chaque connecteur reçoit `countries_exclude` et l'applique côté source
3. **`source_verified = True`** — sources officielles documentées
4. **`source_tier = "employer"` ou `"official"`** — priorité déduplication haute
5. **Rate limiting strict** — respect `robots.txt`, `Crawl-delay`, max 1 req/2s
6. **Zéro dépendance externe** — stdlib seulement (urllib, html.parser)
7. **Fixtures synthétiques** — 1 par connecteur (pas de vraies requêtes en CI)

---

## Spécifications par connecteur

### 1. LinkedIn Europe (`linkedin_europe.py`)

```python
# Basé sur welcome_jungle.py pattern
_LINKEDIN_BASE = "https://www.linkedin.com"
_LINKEDIN_JOBS_SEARCH = _LINKEDIN_BASE + "/jobs-guest/jobs/api/seeMoreJobPostings/search"

# Paramètres: keywords, location, f_TPR (time), f_WT (work type), f_E (experience), f_C (company), f_SB (sort)
# Filtre pays natif via location="Germany", "United Kingdom", etc.
# Rate limit: 1 req/3s, max 10 pages
```

**Champs à extraire** : title, company, location (city, country), contract_type, description, official_url, posted_date

### 2. EURES (`eures.py`)

```python
# API publique: https://ec.europa.eu/eures/eures-api/search
# Documentation: https://ec.europa.eu/eures/eures-api/swagger-ui.html
# Filtre pays natif: `countryCodes=DE,GB,NL,BE,LU,CH,IE,AT,SE,NO,DK,FI,ES,IT,PT,PL`
# Rate limit: généreux (service public)
# Retourne: title, employer, location (city, country), contractType, description, applicationUrl, publicationDate, startDate, duration
```

**Avantage** : API JSON structurée, filtre pays natif, 100% EU/EEA/CH

### 3. JobTeaser International (`jobteaser_intl.py`)

```python
# Étendre connecteur jobteaser.py existant
# Filtre: country_codes=["DE", "GB", "NL", "BE", "CH", "ES", "IT", "PT"]
# Endpoint: https://www.jobteaser.com/en/jobs/search?countries=DE,GB,NL...
# Rate limit: respectueux, max 5 pages
```

### 4. Glassdoor International (`glassdoor_intl.py`)

```python
# Scraping HTML search results
# URL: https://www.glassdoor.com/Job/jobs.htm?sc.keyword=finance+internship&locT=C&locId=... 
# Filtre pays via locId (country codes)
# Rate limit: strict (1 req/5s), max 3 pages
# Attention: anti-bot, user-agent rotation, headers réalistes
```

---

## Enregistrement dans `__init__.py`

```python
# career/connectors/__init__.py

def _init_connector_registry() -> dict[str, tuple]:
    registry = ...
    # AJOUTER:
    from .linkedin_europe import LinkedInEuropeConnector, register_linkedin_europe_connector
    from .eures import EuresConnector, register_eures_connector
    from .jobteaser_intl import JobTeaserIntlConnector, register_jobteaser_intl_connector
    from .glassdoor_intl import GlassdoorIntlConnector, register_glassdoor_intl_connector
    
    register_linkedin_europe_connector(registry)
    register_eures_connector(registry)
    register_jobteaser_intl_connector(registry)
    register_glassdoor_intl_connector(registry)
    return registry


def default_exploration_connectors(greenhouse_connector):
    return {
        "greenhouse": greenhouse_connector,
        "lever": LeverConnector(enabled=True),
        "ashby": AshbyConnector(enabled=True),
        "smartrecruiters": SmartRecruitersConnector(enabled=True),
        "welcome_jungle": WelcomeJungleConnector(enabled=True),
        "jobteaser": JobTeaserConnector(enabled=True),
        "talent_com": TalentComConnector(enabled=True),
        "apec": ApecConnector(enabled=True),
        # NOUVEAUX:
        "linkedin_europe": LinkedInEuropeConnector(enabled=True),
        "eures": EuresConnector(enabled=True),
        "jobteaser_intl": JobTeaserIntlConnector(enabled=True),
        "glassdoor_intl": GlassdoorIntlConnector(enabled=True),
    }
```

---

## Health Checks obligatoires

Chaque connecteur implémente `health_check() -> dict` :

```python
{
    "last_ok": bool,
    "last_error": str | None,
    "consecutive_failures": int,
    "raw_offers": int,
    "valid_offers": int,
    "finance_offers": int,
    "stage_offers": int,
    "conforming_offers": int,
    "to_verify_offers": int,
    "countries_seen": dict[str, int],  # ex: {"DE": 45, "GB": 32, "NL": 18}
    "france_ratio": float,  # doit être 0.0 ou < 0.05
}
```

---

## Validation

### Fixtures synthétiques (1 par connecteur = 4 minimum)

| Connecteur | Fixture | Contenu |
|------------|---------|---------|
| LinkedIn Europe | `linkedin_europe_search.html` | 5 offres (DE, GB, NL, CH, BE), 1 France (doit être filtrée) |
| EURES | `eures_search.json` | 10 offres structurées (tous pays EU hors FR) |
| JobTeaser Intl | `jobteaser_intl_search.html` | 5 offres multi-pays |
| Glassdoor Intl | `glassdoor_intl_search.html` | 5 offres US/GB/DE |

### Tests d'intégration

- Chaque connecteur retourne `DiscoveryPayload` valide
- `filtered_geo_count > 0` quand `countries_exclude=["FR"]`
- `france_ratio < 0.05` sur fixture
- `source_verified = True` sur toutes offres

---

## Commandes de validation

```bash
./checklist_codex.sh
.venv/bin/python -m pytest -q tests/test_intl_sources.py
.venv/bin/python -m pytest -q
git diff --check
```

---

## Critères de réussite

- [ ] 4 nouveaux connecteurs créés et enregistrés
- [ ] Tous implémentent `discover_internships` + `health_check`
- [ ] Filtre `countries_exclude` natif côté source
- [ ] `source_verified = True`, `source_tier = "employer"` ou `"official"`
- [ ] Rate limiting respectueux (configurable)
- [ ] 4 fixtures synthétiques + health checks
- [ ] Intégrés dans `default_exploration_connectors()`
- [ ] Ruff clean, suite complète verte, `git diff --check` propre
- [ ] Rapport `docs/agent-reports/SPEC-SK14-INTL_SOURCES.md`

---

## Squelette minimal (connecteur type)

```python
# career/connectors/eures.py
"""EURES public job search connector - 100% EU/EEA/CH, no France by config."""

from __future__ import annotations
import json
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Callable, Iterator

from ..discovery import DiscoveryPayload, PublicSourceError
from ..models import clean_text, canonical_url
from ..exploration import classify_internship, criteria_admit, ranking_key
from ..offer_qualification import qualify_offer
from ..stage_search import default_brief, score_brief_match, validate_brief

_EURES_API = "https://ec.europa.eu/eures/eures-api/search"
_EURES_TIMEOUT = 15
_EURES_MAX_PAGES = 5
_EURES_PAGE_SIZE = 100
_EURES_MAX_ROWS = 400
_EURES_RATE_LIMIT = 1.0
_EURES_USER_AGENT = "ComeAI-Career/1.0 (EURES public API)"

# Country codes EU/EEA/CH excluant FR
_EURES_DEFAULT_COUNTRIES = "DE,GB,NL,BE,LU,CH,IE,AT,SE,NO,DK,FI,ES,IT,PT,PL,CZ,HU,RO,BG,HR,SI,SK,EE,LV,LT,MT,CY,IS,LI"

@dataclass
class EuresHealth:
    last_ok: bool = False
    last_error: str | None = None
    consecutive_failures: int = 0
    raw_offers: int = 0
    valid_offers: int = 0
    finance_offers: int = 0
    stage_offers: int = 0
    conforming_offers: int = 0
    to_verify_offers: int = 0
    countries_seen: dict[str, int] = None

_HEALTH = EuresHealth()
_HEALTH.countries_seen = {}

class EuresConnector:
    def __init__(self, *, clock=None, monotonic=None, sleeper=None, max_pages=5, max_results=150, enabled=False):
        self.enabled = enabled
        self.clock = clock or (lambda: datetime.now(timezone.utc).isoformat(timespec="seconds"))
        self.monotonic = monotonic or time.monotonic
        self.sleeper = sleeper or time.sleep
        self.max_pages = max_pages
        self.max_results = max_results

    def discover_internships(self, source: dict[str, Any], *, selection_brief: dict[str, Any], deadline: float | None = None) -> DiscoveryPayload:
        if not self.enabled:
            raise PublicSourceError("Connecteur désactivé", code="connector_disabled")
        brief = validate_brief(selection_brief) if selection_brief else default_brief()
        countries_exclude = brief.get("geo_excluded_countries") or ["FR"]
        
        # Reset health
        _HEALTH.raw_offers = _HEALTH.valid_offers = 0
        _HEALTH.countries_seen = {}
        
        # Build API URL with country filter
        country_codes = source.get("country_codes", _EURES_DEFAULT_COUNTRIES)
        # ... pagination, filtering, qualification ...
        return DiscoveryPayload(...)

    @staticmethod
    def health_check() -> dict[str, Any]:
        countries = _HEALTH.countries_seen or {}
        total = sum(countries.values())
        france_count = countries.get("FR", 0)
        return {
            "last_ok": _HEALTH.last_ok,
            "last_error": _HEALTH.last_error,
            "consecutive_failures": _HEALTH.consecutive_failures,
            "raw_offers": _HEALTH.raw_offers,
            "valid_offers": _HEALTH.valid_offers,
            "finance_offers": _HEALTH.finance_offers,
            "stage_offers": _HEALTH.stage_offers,
            "conforming_offers": _HEALTH.conforming_offers,
            "to_verify_offers": _HEALTH.to_verify_offers,
            "countries_seen": countries,
            "france_ratio": france_count / total if total else 0.0,
        }

def register_eures_connector(registry: dict[str, tuple]) -> None:
    registry["eures"] = (EuresConnector, "class")
```

---

**Tu as tout. Lance-toi.** Branche `agent/spec-sk14-intl-sources`, worktree dédié, 4 connecteurs, tests (4 fixtures + health), rapport, push. Je relis et j'intègre.