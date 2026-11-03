# Côme Excel Advanced V6 — architecture et plan

Branche : `feature/excel-advanced-v6` (worktree dédié, basée sur `feature/opencode-data`).
Aucune modification de `main` ni du worktree V6. Aucun commit sans autorisation.

Ce document décrit l'architecture modulaire, le plan priorisé et les critères de
réussite mesurables. Il accompagne du **code réellement exécuté et testé**, pas
seulement une intention.

## 1. Principes d'architecture

- **Additif** : `come_excel` s'appuie sur `come_data` (moteur DuckDB, garde-fous
  SQL/chemins, sérialisation, `finance`) et n'altère ni `workspace_core` ni
  l'orchestrateur.
- **Inspection avant chargement** : découvrir feuilles, entêtes, formules,
  fusions, noms définis et dimensions sans matérialiser le fichier.
- **Calcul déterministe côté machine** : Python/SQL exécutent ; un LLM ne calcule
  jamais un résultat vérifiable.
- **Traçabilité d'abord** : chaque table dérivée porte une provenance
  (fichier, feuille, plage, empreinte SHA-256, transformations, hypothèses,
  contrôles) et une traçabilité colonne → source. Granularité ligne via des
  colonnes scalaires, pas d'objets par ligne.
- **RAM bornée** : vues DuckDB paresseuses, agrégations diffusées, limites
  explicites (`memory_limit`, `query_timeout_seconds`, `temp_dir`).
- **Seuils et honnêteté** : une donnée incertaine/manquante est signalée, jamais
  inventée.

## 2. Modules livrés (Lot 1)

```
come_excel/
  __init__.py        API publique (exports)
  errors.py          ExcelEngineError, InspectionError, UnsupportedSpreadsheetError, ConsolidationError
  provenance.py      SourceRef, AuditLog/AuditEntry, ColumnLineage, Provenance, fingerprint_file (SHA-256 en flux)
  inspect.py         inspect_file() : XLSX/XLSM (read_only), CSV/TSV, XLS (pandas), Parquet (métadonnées DuckDB)
  catalog.py         SourceCatalog : enregistrement multi-fichiers + provenance + audit
  quality.py         analyze_quality() : manquants, doublons, types mixtes, anomalies de Tukey
  consolidate.py     normalize_name, align_sources, consolidate (union/join) + lineage
benchmarks/
  benchmark_come_excel.py   mesures réelles inspect/register/consolidate/quality/export + pic RSS
tests/ (37 nouveaux tests)
  test_come_excel_inspect.py, _catalog.py, _quality.py, _consolidate.py, _provenance.py, _bigdata.py
```

Réutilisation : `come_data.engine.DataEngine`, `come_data.safety.resolve_within`,
`quote_identifier`/`quote_literal`, `come_data.errors`.

## 3. Plan priorisé des lots

| Lot | Contenu | Critère de réussite mesurable | État |
| --- | --- | --- | --- |
| **L1** | Inspection légère + catalogue + provenance/audit + qualité + consolidation union/join | 37 tests verts ; 1,2 M lignes consolidées et exportées sans erreur ; pic RSS ≤ 512 Mo | **Livré** |
| **L2** | Bibliothèque de calculs (entreprise, marché, quant) | chaque fonction teste une valeur de référence indépendante calculée à la main ; hypothèses/unités documentées ; `npv/xirr` recroisés | À faire |
| **L3** | Génération Excel professionnelle | classeur réouvert par openpyxl : formules `=`, graphiques, feuilles Hypothèses/Scénarios/Contrôles/Sources, en-têtes FR | À faire |
| **L4** | Tests A–E bout en bout + valeurs de référence | A (multi-classeurs hétérogènes), B (analyse + Excel justifié), C (volumes), D (formules/manquants/incohérences), E (réouverture + contrôle) | Partiel (A et C couverts) |
| **L5** | Performance, interruption, reprise | benchmarks reproductibles ; annulation propre ; reprise d'une tâche longue | Partiel (benchmarks L1) |

## 4. Périmètre livré et vérifié (L1)

- Inspection `read_only` : feuilles, entêtes, types apparents, formules,
  plages fusionnées (lues dans le XML interne), noms définis, dimensions ;
  fichiers sources **inchangés** (test dédié).
- Catalogue idempotent par (fichier, feuille) ; `add_all_sheets` ; isolation
  des chemins via `resolve_within` ; le `path` n'est pas exposé par défaut.
- Qualité : valeurs manquantes par colonne, doublons exacts, types mixtes
  (colonne texte à majorité numérique), anomalies numériques (bornes de Tukey).
- Consolidation : alignement des colonnes par nom normalisé (accents/casse/
  ponctuation), `UNION ALL` avec `NULL` pour colonnes absentes, `JOIN` interne
  sur clés normalisées, colonnes de provenance `_source_file`, `_source_sheet`,
  `_source_row`, détection des doublons inter-sources, lineage colonne → source.
- Audit : journal ordonné avec entrées, hypothèses, contrôles et formules.

## 5. Performances mesurées (MacBook Pro Intel i7, 16 Go)

Données synthétiques, venv projet (`duckdb 1.5.6`, `pandas 3.0.6`).

| Scénario | Fichiers × lignes | Inspection | Enregistrement | Consolidation | Qualité | Export | Pic RSS |
| --- | --- | --- | --- | --- | --- | --- | --- |
| Smoke | 4 × 25 000 | 0,018 s | 0,34 s | 0,63 s | 0,65 s | 0,11 s | 102 Mo |
| Volume | 12 × 100 000 | 0,25 s | 2,39 s | 8,17 s | 8,73 s | 2,27 s | **319 Mo** |

Le pic RSS reste très inférieur aux 16 Go ; l'inspection est quasi gratuite.
`consolidate` et `analyze_quality` incluent chacun un `DISTINCT *` (détection de
doublons) qui domine leur coût sur 1,2 M lignes — optimisable par `GROUP BY`
clé ou en rendant la détection de doublons optionnelle sur très gros volumes.

## 6. Limites connues (signalées, non masquées)

- `.xls` : inspecté via pandas/xlrd (échantillon borné) ; les formules et
  fusions ne sont pas accessibles dans ce format.
- Plages fusionnées : extraites du XML pour XLSX/XLSM ; non exposées en lecture
  seule par openpyxl.
- Détection de doublons et de types mixtes : coût de balayage à surveiller sur
  plusieurs millions de lignes (options d'activation à prévoir en L5).
- Relations inter-classeurs : L1 consolide et joint sur noms/colonnes ; la
  découverte **automatique** de relations par valeurs est prévue en L2/L4.

## 7. Commandes reproductibles

```bash
.venv/bin/python -m pytest tests/test_come_excel_inspect.py tests/test_come_excel_catalog.py \
    tests/test_come_excel_quality.py tests/test_come_excel_consolidate.py \
    tests/test_come_excel_provenance.py tests/test_come_excel_bigdata.py -q
.venv/bin/python -m benchmarks.benchmark_come_excel --files 12 --rows 100000 \
    --json benchmarks/results/come_excel_1m2.json
```
