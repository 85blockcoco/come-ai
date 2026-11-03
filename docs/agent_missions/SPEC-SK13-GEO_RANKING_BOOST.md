# MISSION SPEC KIT — SK-13 : Score localité dans ranking

> **Priorité : P0** — Après SK-11 validé. Module indépendant, worktree dédié, peut tourner en parallèle SK-11/SK-14.

---

## Contexte

Le signal géographique existe (`geo_score_for` dans `offer_qualification.py`) mais :
- Boost pays ciblés : +20 points
- Pénalité pays exclus : -50 points
- **MAIS** le score final `total_score = base_score + geo_score` n'est pas utilisé comme clé de tri principale dans tous les chemins

**Objectif** : Un'offre publiée dans un pays exclu ne peut **JAMAIS** mener une liste, quelle que soit sa pertinence.

---

## Modules à modifier

```
career/offer_qualification.py
career/stage_search.py
career/exploration.py
career/service.py
tests/test_geo_ranking.py
tests/fixtures/geo_ranking/
```

---

## Règles non négociables

1. **`geo_score` appliqué UNE SEULE FOIS** — jamais cumulé boost + pénalité
2. **Clé de tri = `(geo_rank, -total_score, ...)`** — `geo_rank = 1` si pays exclu, `0` sinon
3. **Pays inconnu = neutre (0)** — jamais inféré depuis la ville
4. **Configuration par brief** — `preferred_countries`, `geo_excluded_countries` (liste ISO-2)
5. **Défaut** : `geo_excluded_countries = ["FR"]` si non configuré, liste vide = pénalité désactivée
6. **Traçabilité** : `geo_reason` dans chaque résultat pour audit UI

---

## Changements précis

### `offer_qualification.py` — `geo_score_for` (ligne 177-204) ✅ DÉJÀ PRÊT

La fonction existe et est correcte. Vérifier qu'elle est appelée partout.

### `stage_search.py` — `score_brief_match` (ligne 705-712)

```python
# ACTUEL (ligne 705-710):
geo_score, geo_reason = geo_score_for(
    job.get("country"),
    preferred_countries=brief.get("preferred_countries"),
    excluded_countries=_geo_excluded_countries(brief),
)
score = None if base_score is None else max(0, min(100, base_score + geo_score))

# AJOUTER geo_rank dans le retour:
geo_rank = 1 if geo_score < 0 else 0
return {
    ...,
    "geo_score": geo_score,
    "geo_reason": geo_reason,
    "geo_rank": geo_rank,  # NOUVEAU
    "total_score": score,
}
```

### `exploration.py` — `ranking_key` (ligne 174-180)

```python
# ACTUEL:
def ranking_key(job: dict[str, Any], match: dict[str, Any]) -> tuple[Any, ...]:
    digest = hashlib.sha256(...).hexdigest()
    status = (job.get("qualification") or {}).get("target_status")
    eligibility_order = {"conforming": 0, "to_verify": 1, "non_conforming": 2}.get(status, 0)
    return (eligibility_order, -(int(match["score"]) if match.get("score") is not None else 0),
            (match.get("education_access") or {}).get("priority_rank", 2),
            str(job.get("company") or "").casefold(), str(job.get("source_name") or ""),
            str(job.get("source_id") or ""), canonical_url(job.get("official_url")), digest)

# NOUVEAU: geo_rank EN PREMIER après eligibility
geo_rank = match.get("geo_rank", 0)
return (eligibility_order, geo_rank, -(int(match["score"]) if match.get("score") is not None else 0), ...)
```

### `discovery.py` — `_normalise` (ligne 486-491)

```python
# ACTUEL (ligne 487-488):
geo_rank = 1 if geo_score < 0 else 0
key = (geo_rank, status_rank, -(int(total_score)...), ...)

# ✅ DÉJÀ FAIT — vérifier cohérence avec stage_search
```

---

## Configuration Brief

```python
# stage_search.py validate_brief (ligne 308-326) ✅ DÉJÀ PRÊT
# preferred_countries, geo_excluded_countries lus depuis brief
# Défaut: geo_excluded_countries = ["FR"] si ni brief ni excluded_countries
```

---

## Validation

### Fixtures synthétiques (minimum 10)

| Cas | Pays offre | preferred | excluded | geo_score | geo_rank | Position relative |
|-----|------------|-----------|----------|-----------|----------|-------------------|
| 1 | DE | [DE, GB] | [FR] | +20 | 0 | Boostée |
| 2 | FR | [DE, GB] | [FR] | -50 | 1 | Pénalisée (dernière) |
| 3 | FR | [] | [] | -50 | 1 | Pénalisée (défaut) |
| 4 | FR | [] | [] (explicit empty) | 0 | 0 | Neutre (pénalité off) |
| 5 | US | [DE, GB] | [FR] | 0 | 0 | Neutre |
| 6 | "" (unknown) | [DE] | [FR] | 0 | 0 | Neutre |
| 7 | "France" (wording) | [] | ["FR"] | -50 | 1 | Pénalisée (alias) |
| 8 | "Deutschland" | ["DE"] | [] | +20 | 0 | Boostée (alias) |
| 9 | CH | [DE, CH] | [FR] | +20 | 0 | Boostée |
| 10 | FR + base_score=90 | [] | [FR] | -50 | 1 | **Après** offre DE score=40 |

### Test d'intégration

```python
def test_excluded_country_never_leads():
    jobs = [
        {"country": "FR", "base_score": 90, ...},
        {"country": "DE", "base_score": 40, ...},
    ]
    ranked = sorted(jobs, key=lambda j: ranking_key(j, score_brief_match(brief, j)))
    assert ranked[0]["country"] == "DE"  # France ne mène JAMAIS
```

---

## Commandes de validation

```bash
./checklist_codex.sh
.venv/bin/python -m pytest -q tests/test_geo_ranking.py
.venv/bin/python -m pytest -q
git diff --check
```

---

## Critères de réussite

- [ ] `geo_rank` dans `score_brief_match` retour
- [ ] `ranking_key` utilise `geo_rank` comme **critère #2** (après eligibility)
- [ ] `geo_score` appliqué une seule fois (pas de double comptage)
- [ ] Pays inconnu = neutre (0), jamais inféré depuis ville
- [ ] Liste vide `geo_excluded_countries` = pénalité désactivée
- [ ] 10+ fixtures synthétiques couvrant tous cas
- [ ] Test d'intégration : offre FR score 90 **après** offre DE score 40
- [ ] Ruff clean, suite complète verte, `git diff --check` propre
- [ ] Rapport `docs/agent-reports/SPEC-SK13-GEO_RANKING_BOOST.md`

---

## Squelette minimal (test)

```python
# tests/test_geo_ranking.py
import pytest
from career.stage_search import score_brief_match, ranking_key, validate_brief
from career.exploration import ranking_key as exploration_ranking_key

brief = validate_brief({
    "preferred_countries": ["DE", "GB"],
    "geo_excluded_countries": ["FR"],
    "domains": ["M&A"],
    "contract_types": ["stage"],
})

def test_excluded_country_geo_rank_1():
    job = {"country": "FR", "title": "M&A Intern", "description_original": "M&A...", "city": "Paris"}
    match = score_brief_match(brief, job)
    assert match["geo_score"] == -50
    assert match["geo_rank"] == 1
    assert "Pays exclu" in match["geo_reason"]

def test_preferred_country_boost():
    job = {"country": "DE", "title": "M&A Intern", "description_original": "M&A...", "city": "Frankfurt"}
    match = score_brief_match(brief, job)
    assert match["geo_score"] == 20
    assert match["geo_rank"] == 0

def test_excluded_never_leads_list():
    job_fr = {"id": "1", "country": "FR", "title": "M&A Intern", "description_original": "M&A...", "company": "A", "city": "Paris", "official_url": "https://boards.greenhouse.io/a/jobs/1"}
    job_de = {"id": "2", "country": "DE", "title": "M&A Intern", "description_original": "M&A...", "company": "B", "city": "Frankfurt", "official_url": "https://boards.greenhouse.io/b/jobs/2"}
    # Simuler scores de base différents
    match_fr = score_brief_match(brief, job_fr)
    match_de = score_brief_match(brief, job_de)
    # Forcer base_score différent pour test
    match_fr["base_score"] = 90
    match_fr["total_score"] = 40  # 90 - 50
    match_de["base_score"] = 40
    match_de["total_score"] = 60  # 40 + 20
    
    ranked = sorted([job_fr, job_de], key=lambda j: ranking_key(j, score_brief_match(brief, j)))
    assert ranked[0]["country"] == "DE"
```

---

**Tu as tout. Lance-toi.** Branche `agent/spec-sk13-geo-ranking-boost`, worktree dédié, code (3 fichiers), tests (10+ fixtures), rapport, push. Je relis et j'intègre.