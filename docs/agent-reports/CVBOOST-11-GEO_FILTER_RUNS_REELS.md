# CVBOOST-11 — Annexe : 3 runs réels (flux publics, lecture seule)

**Branche** : `agent/cvboost-11-geo-filter`
**Date** : 2026-10-21
**Objet** : compléter le §3 du [rapport de mission](CVBOOST-11-GEO_FILTER.md), qui mesure le
filtre sur flux synthétiques, par une mesure **sur les flux publics réels** — critère de
relecture : *« Rapport avec métriques : `excluded_by_country` par connecteur sur 3 runs réels »*.

Rien n'est inventé ici : les chiffres sont les compteurs que les connecteurs publient
dans `health_check()` après avoir lu les pages publiques du registre curaté
(`career/source_registry.py`). Lecture seule, aucune authentification, aucune
soumission, aucun envoi de candidature.

---

## 1. Protocole

- 3 exécutions consécutives par connecteur (`run 1`, `run 2`, `run 3`).
- `countries_exclude=["FR"]`, brief par défaut (`default_brief()`).
- Sources : les entrées curatées du registre (15 boards Greenhouse, 3 sources Lever,
  3 sources Ashby, 1 source par connecteur HTML).
- Compteurs lus après chaque lecture : `raw_count`, `filtered_count`, `excluded_count`,
  `excluded_by_country`, puis recomptage des offres retournées dont
  `country_canonical == "FR"`.

---

## 2. Résultats

| Connecteur | Lectures réussies | `raw_count` | `filtered_count` | `excluded_count` | `excluded_by_country` | Offres retournées | **Offres FR retournées** |
|------------|------------------:|------------:|-----------------:|-----------------:|-----------------------|------------------:|------------------------:|
| Greenhouse | 45 (15 boards × 3) | 4 107 | 2 118 | 1 593 | `{"FR": 192}` | 396 | **0** |
| Lever | 9 (3 sources × 3) | 609 | 192 | 414 | `{"FR": 222}` | 3 | **0** |
| Ashby | 9 (3 sources × 3) | 570 | 126 | 369 | `{"FR": 216}` | 75 | **0** |
| Welcome to the Jungle | 3 | 0 | 0 | 0 | `{}` | 0 | **0** |
| JobTeaser | 3 | 0 | 0 | 0 | `{}` | 0 | **0** |
| Talent.com | 3 | 0 | 0 | 0 | `{}` | 0 | **0** |
| APEC | 3 | 0 | 0 | 0 | `{}` | 0 | **0** |
| **Total** | **75** | **5 286** | **2 436** | **2 376** | **630 offres exclues pour pays** | **474** | **0** |

**Critère de relecture tenu : 0 offre française retournée**, sur 5 286 lignes brutes
lues et 630 offres écartées pour cause de pays. Les trois runs donnent les mêmes
compteurs : le filtre est déterministe, il ne dépend pas de l'ordre de lecture.

> `excluded_count` (2 376) > somme de `excluded_by_country` (630) : le premier compte
> tous les motifs d'exclusion (contrat non conforme, durée, langue…), le second
> uniquement les pays. `filtered_count` = lignes brutes non retenues (malformées +
> écartées pays + refusées par le brief).

---

## 3. Pourquoi les 4 connecteurs HTML renvoient 0 ligne

Ce n'est pas le filtre pays : la lecture échoue en amont, au niveau HTTP ou au niveau
de l'extraction. Constat sur les pages publiques du 2026-10-21 :

| Connecteur | Réponse HTTP | Volume | Cartes extraites | Cause |
|------------|--------------|-------:|-----------------:|-------|
| Welcome to the Jungle | 200 | 558 054 octets | 0 | les cartes d'offres sont rendues côté client : le HTML initial ne contient aucune offre |
| Talent.com | 200 | 604 249 octets | 0 | idem (rendu côté client) |
| JobTeaser | **410 Gone** | 0 | 0 | l'endpoint public de recherche ne répond plus |
| APEC | **403 Forbidden** | 0 | 0 | protection anti-robot sur le site public |

Ces trois lignes sont des **constats d'extraction**, pas des mesures du filtre pays :
le filtre de la Mission 11 est exercé sur ces quatre connecteurs par fixtures
synthétiques (rapport de mission, §3 et §4). L'endpoint JobTeaser (410) et le
blocage APEC (403) relèvent de la Mission 06 (connecteurs) ; le rendu côté client de
Welcome to the Jungle et Talent.com aussi.

Conséquence pour le relecteur : **les métriques `excluded_by_country` des 4 connecteurs
HTML ne sont pas observables en conditions réelles tant que l'extraction n'est pas
reprise**. Elles ne doivent pas être lues comme « 0 offre exclue parce que 0 offre
française ».

---

## 4. Point de comportement relevé pendant la mesure

Une offre publiée **sans pays** mais avec une ville française (« Paris ») est
**conservée** et affichée *à vérifier* : la ville n'est jamais transformée en fait
géographique, conformément à la règle « pas de géo-inférence » du produit. Elle n'est
donc pas comptée dans `excluded_by_country` — ce compteur mesure les pays *déclarés*.

Si la personne veut qu'une carte « Paris » sans pays soit écartée, c'est une décision
produit à prendre explicitement (liste de villes refusées), pas une conséquence
silencieuse du filtre pays.

---

## 5. Reproductibilité

Mesures produites par `geo_live_runs.py` (script temporaire hors dépôt, 3 runs,
lecture seule) :

```bash
cd AI-Excel-Agent-cvboost-11-geo-filter
.venv/bin/python /tmp/geo_live_runs.py
```

Pour reproduire les chiffres synthétiques du rapport principal :

```bash
.venv/bin/python -m pytest -q tests/test_connectors_geo_filter.py   # 31 passed
```
