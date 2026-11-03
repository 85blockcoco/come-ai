# MISSION AGENT — Mission 07 : Déduplication multi-source

> **Contexte** : avec 4 nouvelles sources (Mission 06) + les existantes, les mêmes offres remontent depuis plusieurs ATS (Greenhouse, Ashby, Lever, Welcome to the Jungle, JobTeaser, Talent.com, APEC). Il faut **fusionner les vrais doublons sans fusionner deux postes différents**.
> Base : `main` (tag `v3-cvboost-sources-2026-10-20`), 1269 tests verts.
> Dépendances : **Mission 06** (sources) — **dépendances satisfaites**.

---

## Périmètre autorisé

| Fichier | Rôle |
|---|---|
| `career/cv_quality/job_deduplication.py` | **existant** — logique de déduplication à compléter/étendre (`deduplicate_jobs`, `canonicalize_url`, `company_canonical`, `title_similarity`) |
| `career/discovery.py` | **UNIQUEMENT** : appel de `deduplicate_jobs()` dans `discover_stage_offers()` après collecte multi-source |
| `career/models.py` | **si nécessaire** — champs additionnels pour la traçabilité (ex. `merged_from: list[str]`) |
| `tests/test_job_deduplication.py` | **tests unitaires** (fixtures synthétiques uniquement) |
| `docs/agent-reports/CVBOOST-07-DEDUP.md` | rapport obligatoire |

**Interdit** : `career/service.py`, `career/router.py`, `career_static/*`, `requirements*.txt`, migrations, `SCHEMA_VERSION`.

---

## Contraintes produit (non négociables)

1. **Déduplication robuste** basée sur **clés composites** (pas une seule clé) :
   - **URL canonique** : `canonicalize_url(raw_url)` → scheme `https`, sans query params de tracking (`utm_*`, `ref`, `source`), sans fragment, host normalisé (`www.` → ``), trailing slash supprimé.
   - **Identifiant externe** : `external_id` fourni par le connecteur (ex. `gh_jid_123`, `ashby_abc`) — si présent, clé primaire.
   - **Entreprise canonique** : `company_canonical(name)` → minuscules, suppression suffixes juridiques (`SA`, `SAS`, `Ltd`, `Inc`, `GmbH`, `AG`, `SRL`, `SpA`, `BV`, `NV`, `PLC`, `Group`, `Groupe`), accents normalisés, espaces réduits.
   - **Titre normalisé** : `title_canonical(title)` → minuscules, suppression ponctuation, synonymes (stage/internship, CDI/permanent, alternance/apprentissage).
   - **Lieu normalisé** : `location_canonical(city, country)` → pays ISO-2 si possible, ville normalisée (accents, tirets).
   - **Alias / traductions** : mapping interne (ex. "Data Analyst" ≈ "Analyste de données", "M&A" ≈ "Fusion-Acquisition").
   - **Fraîcheur** : si deux offres passent toutes les clés, garder la plus récente (`posted_date` ou `discovered_at`).

2. **Algorithme** (déterministe, 100 % local) :
   - Étape 1 : index par `external_id` si présent → groupes exacts.
   - Étape 2 : pour les restants, index par `canonical_url` → groupes exacts.
   - Étape 3 : pour les restants, clustering par similarité : `(company_canonical, title_canonical, location_canonical)` — seuil Jaro-Winkler ≥ 0.92 sur titre + entreprise identique + lieu identique.
   - Étape 4 : pour chaque cluster, choisir le **représentant** : priorité `external_id` > `source_priority` (Ashby > Greenhouse > Lever > WelcomeJungle > JobTeaser > Talent.com > APEC) > `posted_date` plus récente.
   - Les offres fusionnées gardent une trace `merged_from: list[source_name]` pour l'audit.

3. **Sortie** : liste d'offres dédupliquées + rapport de fusion (`merged_count`, `clusters`, `representatives`).

4. **Tests** : fixtures **synthétiques** — cas exacts (même URL), cas quasi-identiques (titre "Data Analyst" vs "Analyste Data"), cas entreprise avec suffixes, cas multi-sites, cas titres synonymes, cas faux positifs (deux postes différents même entreprise), cas frais vs ancien. 20+ cas.

5. **Performance** : ≤ 200 ms pour 500 offres.

---

## Commandes de validation

```bash
./checklist_codex.sh
/Users/comedelavenne/AI-Excel-Agent/.venv/bin/python -m pytest -q tests/test_job_deduplication.py
/Users/comedelavenne/AI-Excel-Agent/.venv/bin/python -m pytest -q
git diff --check
```

---

## Critères de validation (relecteur)

- [ ] `deduplicate_jobs(jobs: list[Job]) -> tuple[list[Job], DedupReport]` pure, déterministe.
- [ ] 4 niveaux de clés (external_id → canonical_url → clustering Jaro-Winkler → fraîcheur).
- [ ] `canonicalize_url`, `company_canonical`, `title_canonical`, `location_canonical` exportées et testées unitairement.
- [ ] `merged_from` tracé sur chaque offre fusionnée.
- [ ] Tests synthétiques ≥ 20 (cas exacts, quasi, synonymes, faux positifs, fraîcheur).
- [ ] Suite globale ≥ 1269 tests.
- [ ] Rapport avec exemples de fusion et non-fusion.
- [ ] Branche `agent/cvboost-07-dedup` prête.

---

## Squelette minimal (existant à étendre)

```python
# career/cv_quality/job_deduplication.py (existant — à compléter)
from __future__ import annotations
from dataclasses import dataclass
from typing import Literal
import re
import urllib.parse

@dataclass
class DedupReport:
    merged_count: int
    clusters: list[dict]
    representatives: list[str]  # job_ids

def canonicalize_url(url: str) -> str:
    # https, sans www, sans query tracking, sans fragment, slash final unique
    ...

def company_canonical(name: str) -> str:
    # minuscules, accents, suffixes juridiques, espaces
    ...

def title_canonical(title: str) -> str:
    # minuscules, ponctuation, synonymes FR/EN
    ...

def location_canonical(city: str, country: str) -> str:
    # pays ISO-2, ville normalisée
    ...

def jaro_winkler(s1: str, s2: str) -> float:
    # implémentation standard (pas de lib externe)
    ...

def deduplicate_jobs(jobs: list[Job]) -> tuple[list[Job], DedupReport]:
    # 1. index external_id
    # 2. index canonical_url
    # 3. clustering (company, title, location) + jaro_winkler >= 0.92
    # 4. choix représentant (external_id > source_priority > posted_date)
    # 5. merged_from tracé
    ...
```

---

## Critères de validation (relecteur)

- [ ] `deduplicate_jobs()` pure, déterministe, sans réseau.
- [ ] 4 niveaux de clés + fraîcheur.
- [ ] Fonctions utilitaires exportées et testées.
- [ ] `merged_from` tracé.
- [ ] Tests synthétiques ≥ 20.
- [ ] Suite globale ≥ 1269 tests.
- [ ] Rapport avec exemples fusion / non-fusion.
- [ ] Branche `agent/cvboost-07-dedup` prête.

---

**Tu as tout. Lance-toi.** Branche `agent/cvboost-07-dedup`, worktree dédié, code, tests, rapport, push. Je relis et j'intègre. **Indépendante de Mission 01/04 — peut démarrer maintenant.**