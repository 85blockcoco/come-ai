# MISSION AGENT — Mission 13 : Ranking géographique (Boost étranger, Pénalité France)

> **Contexte** : Même avec le filtre connecteur (Mission 11), certaines offres France peuvent passer (données imparfaites). Le ranking DOIT pénaliser lourdement la France et booster les pays cibles.
> Base : `main` (tag `v3-cvboost-sources-2026-10-20`), 1318 tests verts.
> Dépendances : **Mission 11** (filtre connecteur) — **lancer en parallèle, merge séquentiel (11 avant 13)**.

---

## Périmètre autorisé

| Fichier | Rôle |
|---|---|
| `career/offer_qualification.py` | Modifier `qualify_offer()` — ajouter pénalité/bonus géographique dans le score |
| `career/discovery.py` | `discover_ranked()` — utiliser le score geo du `qualify_offer` |
| `career/stage_search.py` | Exposer `preferred_countries` / `excluded_countries` dans le brief |
| `career/models.py` | Étendre `StageSearchPayload` avec `preferred_countries`, `excluded_countries` |
| `career/discovery.py` | `stage_search_vocabulary()` — inclure pays dans le vocabulaire |
| `tests/test_geo_ranking.py` | **Nouveau** — tests unitaires ranking géographique |
| `docs/agent-reports/CVBOOST-13-GEO_RANKING.md` | Rapport obligatoire |

**Interdit** : `career/service.py`, `career/router.py`, `career_static/*`, `requirements*.txt`, migrations, `SCHEMA_VERSION`.

---

## Contraintes produit (non négociables)

1. **Pénalité France FORTE** : toute offre `country="FR"` → score global `-50` points (sur 100). Même si matching compétences parfait, l'offre France ne doit JAMAIS être en tête.
2. **Boost pays cibles** : pays déclarés dans `preferred_countries` (brief) → `+20` points par pays matché.
3. **Neutre** : pays ni exclu ni préféré → score geo = 0 (neutre).
4. **Transparence** : le détail du score geo doit apparaître dans `qualify_offer()` résultat (`geo_score`, `geo_reason`).
4. **Pas de géo-inférence** : on ne déduit JAMAIS le pays depuis la ville. Si `country` absent → score geo = 0 (neutre), pas de déduction.
5. **Configurable via brief** : l'utilisateur définit `preferred_countries` (ex: ["DE", "GB", "CH", "NL", "LU"]) et `excluded_countries` (défaut ["FR"]) dans son brief de recherche.

---

## Spécifications techniques

### 1. `career/models.py` — Extension StageSearchPayload

```python
class StageSearchPayload(BaseModel):
    # ... champs existants ...
    preferred_countries: list[str] = Field(default_factory=lambda: ["DE", "GB", "CH", "NL", "LU", "BE", "IE", "AT", "SE", "NO", "DK", "FI", "ES", "IT", "PT", "PL", "CZ", "HU", "RO", "BG", "HR", "SI", "SK", "EE", "LV", "LT", "MT", "CY"])
    excluded_countries: list[str] = Field(default_factory=lambda: ["FR"])
```

### 2. `career/offer_qualification.py` — Scoring géographique

```python
def qualify_offer(job: Job, brief: Brief, minimum_stage_duration_months: int = 3) -> OfferQualification:
    # ... code existant ...
    
    # NOUVEAU : Scoring géographique
    geo_score = 0
    geo_reason = ""
    job_country = (job.get("country") or "").upper()
    
    if job_country in excluded_countries:
        geo_score = -50
        geo_reason = f"Pays exclu ({job_country})"
    elif job_country in preferred_countries:
        geo_score = 20
        geo_reason = f"Pays ciblé ({job_country})"
    else:
        geo_score = 0
        geo_reason = "Pays neutre" if job_country else "Pays inconnu"
    
    # Intégrer dans le score total
    total_score = base_score + geo_score
    total_score = max(0, min(100, total_score))  # Borné 0-100
    
    return OfferQualification(
        ...,
        geo_score=geo_score,
        geo_reason=geo_reason,
        country=job_country,
    )
```

### 3. `career/discovery.py` — Ranking

```python
def discover_ranked(brief: Brief, ...) -> list[Job]:
    # Le ranking utilise maintenant le score total incluant geo_score
    qualified = [qualify_offer(job, brief) for job in jobs]
    qualified.sort(key=lambda q: q.total_score, reverse=True)
    return [q.job for q in qualified]
```

---

## Tests obligatoires (≥ 12)

| Test | Description |
|------|-------------|
| `test_france_penalty_50` | Offre France → `geo_score = -50`, `total_score` réduit de 50 |
| `test_preferred_country_boost_20` | Offre DE avec DE dans preferred → `geo_score = +20` |
| `test_multiple_preferred` | Offre NL + NL dans preferred → `+20` (pas cumulatif) |
| `test_neutral_country` | Offre US sans US dans preferred/excluded → `geo_score = 0` |
| `test_france_never_top` | Même avec score base 100, France score 50 → jamais premier |
| `test_preferred_override_default` | Brief sans preferred_countries → défaut UE utilisé |
| `test_excluded_override_default` | Brief avec `excluded_countries=[]` → France non pénalisée |
| `test_country_unknown_neutral` | Offre sans country → `geo_score = 0`, reason "Pays inconnu" |
| `test_frankfurt_not_france` | "Frankfurt" (DE) → boost si DE dans preferred, JAMAIS pénalité FR |
| `test_score_bounded_0_100` | Score total toujours entre 0 et 100 |
| `test_geo_reason_in_result` | `qualify_offer` retourne `geo_score`, `geo_reason`, `country` |
| `test_ranking_integration` | `discover_ranked` trie bien par score total incluant geo |

---

## Commandes de validation

```bash
./checklist_codex.sh
.venv/bin/python -m pytest -q tests/test_geo_ranking.py
.venv/bin/python -m pytest -q
git diff --check
```

---

## Critères de validation (relecteur)

- [ ] Offre France → `geo_score = -50`, jamais en tête de liste
- [ ] Pays préférés → `+20` points, remontent dans le ranking
- [ ] `geo_score` et `geo_reason` visibles dans `qualify_offer()` résultat
- [ ] `preferred_countries` / `excluded_countries` configurables via brief
- [ ] Pas de géo-inférence depuis ville (Frankfurt ≠ France)
- [ ] Ruff clean, 1318+ tests passent, `git diff --check` propre
- [ ] Rapport `CVBOOST-13-GEO_RANKING.md` avec exemples de ranking avant/après

---

## Squelette minimal

```python
# career/models.py — AJOUT dans StageSearchPayload
preferred_countries: list[str] = Field(default_factory=lambda: ["DE","GB","CH","NL","LU","BE","IE","AT","SE","NO","DK","FI","ES","IT","PT","PL","CZ","HU","RO","BG","HR","SI","SK","EE","LV","LT","MT","CY"])
excluded_countries: list[str] = Field(default_factory=lambda: ["FR"])

# career/offer_qualification.py — DANS qualify_offer
def _compute_geo_score(job_country: str, preferred: list[str], excluded: list[str]) -> tuple[int, str]:
    job_country = (job_country or "").upper()
    if job_country in [c.upper() for c in excluded]:
        return -50, f"Pays exclu ({job_country})"
    if job_country in [c.upper() for c in preferred]:
        return 20, f"Pays ciblé ({job_country})"
    return 0, "Pays neutre" if job_country else "Pays inconnu"

# Intégration dans OfferQualification
geo_score, geo_reason = _compute_geo_score(job.get("country",""), preferred_countries, excluded_countries)
total_score = max(0, min(100, base_score + geo_score))
```

---

**Tu as tout. Lance-toi.** Branche `agent/cvboost-13-geo-ranking`, worktree dédié, code, tests, rapport, push. Je relis et j'intègre **après Mission 11** (merge séquentiel : 11 → 13).