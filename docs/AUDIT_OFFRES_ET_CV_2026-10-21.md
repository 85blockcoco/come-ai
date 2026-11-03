# AUDIT : PERTINENCE OFFRES + QUALITÉ CV — 2026-10-21

## Constats actuels

### 1. Filtrage géographique (R1 — PAS DE FRANCE)
- **Problème** : Le connecteur Greenhouse (85% du corpus) ne filtre PAS par pays côté source
- `canonicalize_url` et `location_canonical` existent mais le filtre `country` n'est pas poussé aux connecteurs
- `discover_stage_offers()` appelle les connecteurs sans passer le filtre `country` → 120 offres dont ~60% France
- **Impact** : L'utilisateur voit des offres France qu'il ne veut pas

### 2. Exhaustivité résumés offres (R2 — RÉSUMÉ COMPLET)
- Mission 01 (cv_quality) analyse le CV, PAS les offres
- `offer_qualification.py` extrait 9 champs mais `description_original` souvent vide (Greenhouse)
- `summarize_offer()` dans `application_prep.py` n'a que 7 champs → 0% rémunération, 0% conditions, 47% missions
- **Impact** : L'utilisateur ne voit pas les infos clés (salaire, conditions, missions) pour décider

### 3. Conseils CV actionnables
- Mission 01 détecte (longueur, sections manquantes, non-quantifié, répétitions, tableaux, OCR)
- MAIS pas de liaison avec les offres ciblées → conseils génériques, pas "pour CETTE offre"
- Mission 02 (exigences offres) existe mais pas branchée sur `analyze_cv()` → pas de matching CV ↔ offre
- **Impact** : L'utilisateur n'a pas de "change X pour matcher l'offre Y"

---

## 20 MISSIONS CORRECTIVES (Priorisées)

### Phase 1 — Filtrage géographique & Sources (Semaine 1)

| # | Mission | Dépendance | Fichiers cibles |
|---|---------|------------|-----------------|
| 11 | **Filtre pays côté connecteurs** | 06 | `career/connectors/*.py`, `discovery.py` — passer `countries_exclude=["FR"]` à chaque connecteur, ajouter param `countries` à `iter_offers()` |
| 12 | **Déduplication géographique** | 07, 11 | `career/cv_quality/job_deduplication.py` — fusionner offres même poste multi-pays, garder version hors-France |
| 13 | **Score localité dans ranking** | 02, 11 | `career/offer_qualification.py` — booster offres pays cibles, pénaliser France (score -50) |
| 14 | **Sources spécialisées étranger** | 11 | Nouveaux connecteurs : `linkedin_europe.py`, `eures.py`, `jobteaser_intl.py`, `glassdoor_intl.py` — 4 sources 100% hors-France |
| 15 | **Health check géographique** | 14 | `health_check()` retourne `% offres France` par source, alerte si > 10% |

### Phase 2 — Exhaustivité résumés offres (Semaine 2)

| # | Mission | Dépendance | Fichiers cibles |
|---|---------|------------|-----------------|
| 16 | **Extracteur rémunération offres** | 01 | `career/cv_quality/parser.py` — regex salaire (€, k€, k, $, £, "package", "package annuel", "rémunération") + `evidence_excerpt` |
| 17 | **Extracteur conditions** | 01 | `parser.py` — télétravail, horaires, flexibilité, avantages, formation, mobilité |
| 18 | **Extracteur missions complètes** | 01 | `parser.py` — détection sections "Missions", "Responsabilités", "Vos missions", "What you'll do" |
| 19 | **Extracteur niveau d'études requis** | 01 | `parser.py` — "Bac+5", "Master", "PhD", "Diplôme d'ingénieur", "Bachelor" |
| 20 | **Scoring exhaustivité par offre** | 16-19 | `offer_qualification.py` — champ `exhaustivity_score` (0-100) affiché dans Stage Hunter |

### Phase 3 — Conseils CV ultra-ciblés (Semaine 3)

| # | Mission | Dépendance | Fichiers cibles |
|---|---------|------------|-----------------|
| 21 | **Matching CV ↔ Offre** | 01, 02 | Nouveau `career/cv_quality/matching.py` — `match_cv_to_offer(cv_result, offer)` → liste actions concrètes |
| 22 | **Générateur conseils par exigence** | 21 | Pour CHAQUE exigence offre → action CV précise (mettre en avant / reformuler / ajouter preuve / quantifier) |
| 23 | **Preuve par citation** | 22 | Chaque conseil cite l'exact excerpt CV + l'exact excerpt offre |
| 24 | **Priorisation par impact** | 23 | Score impact = (exigence obligatoire * gap CV) → top 5 actions prioritaires |
| 24 | **Export "Plan d'action pour cette offre"** | 24 | Bouton "Générer mon plan pour cette offre" → PDF/Markdown avec 5 actions prioritaires |

### Phase 4 — UX & Boucle de rétroaction (Semaine 4)

| # | Mission | Dépendance | Fichiers cibles |
|---|---------|------------|-----------------|
| 25 | **Filtre "Zéro France" en UI** | 11 | `career_static/career.js` — toggle "Exclure France" (défaut ON), badge "X offres France masquées" |
| 26 | **Badge exhaustivité par offre** | 20 | Stage Hunter : badge "Exhaustivité 85%" / "Rémunération : non communiquée" |
| 27 | **Comparateur offres** | 20 | Vue "Comparer" côté à côté : exhaustivité, rémunération, localisation, match CV |
| 28 | **Historique "Pourquoi cette offre ?"** | 24 | Traçabilité : pourquoi cette offre remonte (match compétences + localité + exhaustivité) |
| 29 | **Itération "Améliore ton CV pour cette offre"** | 24 | Loop : conseil → modif CV → re-match → score mis à jour |
| 30 | **Rapport hebdo "Ton marché"** | 25-29 | Email/summary local : X offres ciblées, Y actions CV, Z entretiens probables |

---

## Ordre d'exécution suggéré (par vagues parallèles)

```
VAGUE 1 (immédiat, cette nuit) :     11, 13, 14  (filtrage geo + ranking + sources étranger)
VAGUE 2 (demain) :                   11, 12, 15  (filtre connecteurs + dedup geo + health)
VAGUE 3 (après 11-15) :              16, 17, 18, 19, 20  (exhaustivité offres — parallélisable)
VAGUE 4 (après 16-20) :              21, 22, 23, 24  (matching CV↔offre + conseils)
VAGUE 5 (après 21-24) :              25, 26, 27    (UX filtres + badges + comparateur)
VAGUE 6 (après 27) :                 28, 29, 30    (boucle rétroaction + rapport hebdo)
```

---

## Points d'attention critiques

1. **Mission 11 (filtre pays connecteurs)** = PRÉREQUIS ABSOLU pour tout le reste. Sans ça, les offres France polluent tout.
2. **Mission 16-19 (extracteurs offres)** = doivent réutiliser `cv_quality.parser` (Mission 01) pour cohérence.
3. **Mission 21 (matching)** = cœur de valeur. Doit produire des actions CONCRÈTES : "Ajoute 'Python 3.10' dans Compétences car l'offre exige 'Python 3.8+'".
4. **Pas de régression** : chaque vague doit passer `pytest -q` (1318 tests) + `ruff check .` + `git diff --check`.
5. **Tests synthétiques** : chaque extracteur/matching doit avoir ≥ 10 tests avec fixtures synthétiques (pas de vraies données).

---

## Livraison attendue par vague

| Vague | Livrable | Validation |
|-------|----------|------------|
| 1-2   | 0 offres France dans Stage Hunter + ranking boost étranger | Audit manuel Stage Hunter |
| 3     | Exhaustivité moyenne offres > 60% (vs 11.7% actuel) | `measure_exhaustiveness.py` > 60% |
| 4     | Pour 5 offres test : 5 actions CV concrètes par offre | Audit manuel matching |
| 5     | UI : 0 France visible, badges exhaustivité, comparateur | Test navigateur headless |
| 6     | Rapport hebdo auto-généré valide | Audit rapport généré |

---

**Prochaine action immédiate** : Lancer Mission 11 (Filtre pays connecteurs) + Mission 13 (Ranking geo) en parallèle — ce sont les prérequis absolus.
