# Rapport d'évaluation Côme AI — run `1b61969df1a4`

**Label :** DÉMO 2/3 — injection de fautes (mauvaise réponse)

- **Cible exécutée :** `simulated+fault:wrong_answer`
- **Horodatage (UTC) :** 2026-10-13T16:33:01+00:00
- **Environnement :** Python 3.12.10 / macOS-14.8.9-x86_64-i386-64bit

> ⚠️ **Cette exécution utilise une cible simulée.** Elle valide le laboratoire (runner, détection, métriques) mais ne mesure **aucune** qualité de modèle IA réel.

## Métriques

| Indicateur | Valeur | Nature |
|---|---|---|
| Cas au total | 60 | mesuré |
| Cas exécutés | 49 | mesuré |
| Cas réussis | 23 | mesuré |
| Cas en échec | 26 | mesuré |
| Cas non pris en charge | 11 | mesuré |
| Taux de réussite (exécutables) | 46.9 % | mesuré |
| Exactitude des calculs (numeric_close) | 35.0 % | mesuré |
| Validité des structures (structure/plan) | 66.7 % | mesuré |
| Traçabilité des sources (citations) | 100.0 % | mesuré |
| Garde anti-hallucination (faits) | 100.0 % | mesuré |
| Erreurs critiques | 15 | mesuré |
| Durée totale | 0.005 s | mesuré |
| Mémoire pic | 13900.0 MiB | mesuré |
| Appels API payants | 0 | mesuré (aucun réseau) |

## Erreurs critiques

- **CONV-002** — contrôles en échec : exact_value
- **CONV-003** — contrôles en échec : exact_value
- **CONV-008** — contrôles en échec : exact_value
- **DOC-002** — contrôles en échec : numeric_close
- **DOC-009** — contrôles en échec : exact_value
- **FIN-001** — contrôles en échec : numeric_close
- **FIN-002** — contrôles en échec : numeric_close
- **FIN-003** — contrôles en échec : numeric_close
- **FIN-004** — contrôles en échec : numeric_close
- **FIN-008** — contrôles en échec : numeric_close
- **FIN-010** — contrôles en échec : numeric_close
- **FIN-011** — contrôles en échec : numeric_close
- **FIN-013** — contrôles en échec : numeric_close
- **MEM-012** — contrôles en échec : numeric_close
- **MEM-018** — contrôles en échec : exact_value

## Cas non pris en charge (fonctionnalités futures)

- CONV-010
- DOC-012
- DOC-013
- DOC-014
- DOC-015
- FIN-014
- FIN-015
- MEM-016
- MEM-017
- MEM-019
- MEM-020

## Détail des échecs

### CONV-002 (conversation, sévérité critical)
- ❌ `exact_value` : structured.result: attendu 7006652, obtenu 'valeur incorrecte (injetée)'

### CONV-003 (conversation, sévérité critical)
- ❌ `exact_value` : structured.action: attendu 'refused', obtenu 'valeur incorrecte (injetée)'

### CONV-008 (conversation, sévérité critical)
- ❌ `exact_value` : structured.key_present: attendu True, obtenu 'valeur incorrecte (injetée)'

### DOC-001 (documents, sévérité major)
- ❌ `structure_valid` : champ sheet_count de type incorrect : str
- ❌ `exact_value` : structured.sheet_count: attendu 2, obtenu 'valeur incorrecte (injetée)'

### DOC-002 (documents, sévérité critical)
- ❌ `numeric_close` : structured.mean: attendu 180.0±0.01, obtenu 198.0 (|Δ|=18)

### DOC-003 (documents, sévérité major)
- ❌ `exact_value` : structured.total_missing: attendu 3, obtenu 'valeur incorrecte (injetée)'

### DOC-004 (documents, sévérité major)
- ❌ `exact_value` : structured.data_types.quantite: attendu 'int64', obtenu 'valeur incorrecte (injetée)'

### DOC-007 (documents, sévérité major)
- ❌ `exact_value` : structured.hits: attendu 1, obtenu 'valeur incorrecte (injetée)'

### DOC-008 (documents, sévérité major)
- ❌ `exact_value` : structured.capped: attendu True, obtenu 'valeur incorrecte (injetée)'

### DOC-009 (documents, sévérité critical)
- ❌ `exact_value` : structured.source_modified: attendu False, obtenu 'valeur incorrecte (injetée)'

### FIN-001 (finance, sévérité critical)
- ❌ `numeric_close` : structured.total: attendu 4000.0±0.005, obtenu 4400.0 (|Δ|=400)

### FIN-002 (finance, sévérité critical)
- ❌ `numeric_close` : structured.ttc: attendu 420.0±0.005, obtenu 462.0 (|Δ|=42)

### FIN-003 (finance, sévérité critical)
- ❌ `numeric_close` : structured.growth_pct: attendu 25.0±0.01, obtenu 27.5 (|Δ|=2.5)

### FIN-004 (finance, sévérité critical)
- ❌ `numeric_close` : structured.margin: attendu 90.0±0.005, obtenu 99.0 (|Δ|=9)

### FIN-005 (finance, sévérité major)
- ❌ `numeric_close` : structured.weighted_mean: attendu 13.8±0.005, obtenu 15.180000000000001 (|Δ|=1.38)

### FIN-006 (finance, sévérité major)
- ❌ `numeric_close` : structured.interest: attendu 560.0±0.01, obtenu 616.0 (|Δ|=56)

### FIN-008 (finance, sévérité critical)
- ❌ `numeric_close` : structured.computed_total: attendu 900.0±0.005, obtenu 990.0 (|Δ|=90)

### FIN-009 (finance, sévérité major)
- ❌ `numeric_close` : structured.variance: attendu 1450.0±0.005, obtenu 1595.0 (|Δ|=145)

### FIN-010 (finance, sévérité critical)
- ❌ `numeric_close` : structured.converted: attendu 540.0±0.005, obtenu 594.0 (|Δ|=54)

### FIN-011 (finance, sévérité critical)
- ❌ `numeric_close` : structured.value: attendu 42500.0±0.5, obtenu 46750.0 (|Δ|=4.25e+03)

### FIN-013 (finance, sévérité critical)
- ❌ `numeric_close` : structured.sum_parts: attendu 90000.0±0.01, obtenu 99000.0 (|Δ|=9e+03)

### MEM-010 (memoire, sévérité major)
- ❌ `structure_valid` : champ hits de type incorrect : str
- ❌ `exact_value` : structured.hits: attendu 2, obtenu 'valeur incorrecte (injetée)'

### MEM-011 (memoire, sévérité major)
- ❌ `exact_value` : structured.action: attendu 'clarifier', obtenu 'valeur incorrecte (injetée)'

### MEM-012 (memoire, sévérité critical)
- ❌ `numeric_close` : structured.total: attendu 1240.5±0.005, obtenu 1364.55 (|Δ|=124)

### MEM-013 (memoire, sévérité major)
- ❌ `exact_value` : structured.rule: attendu 'recency', obtenu 'valeur incorrecte (injetée)'

### MEM-018 (memoire, sévérité critical)
- ❌ `exact_value` : structured.project_id: attendu 'alpha', obtenu 'valeur incorrecte (injetée)'

---

_Rapport généré par le laboratoire d'évaluations (`evals/`). Fichier JSON du run : `/Users/comedelavenne/AI-Excel-Agent-evals/evals/runs/1b61969df1a4.json`_
