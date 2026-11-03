# Côme Data — API destinée à l’orchestrateur V6

Révision de référence : branche `feature/opencode-data`, moteur validé par
**875 tests réussis** (dont 30 tests `come_data`) et corrections acceptées.

Ce document décrit l’interface publique de la couche `come_data` telle qu’elle
doit être appelée par l’orchestrateur V6. Il ne modifie ni `main`, ni le
worktree V6 : c’est le contrat de la couche additive.

## 1. Rôle et périmètre

`come_data` est une couche d’analyse **additive** au-dessus de DuckDB. Elle :

- lit un fichier tabulaire (CSV, TSV, Parquet, Excel) sans charger tout le
  contenu en mémoire (vue paresseuse par défaut) ;
- expose des statistiques descriptives, des requêtes SQL **en lecture seule**
  et des métriques financières ;
- renvoie des structures **JSON-safe** (dictionnaires, listes, scalaires).

Elle **ne remplace pas** `workspace_core`, `v5_orchestrator`, le routeur IA ni la
mémoire. Elle n’est pas importée tant que l’orchestrateur ne l’active pas.

Non-objectifs explicites : aucun appel réseau, aucune donnée envoyée à un cloud,
aucune recommandation d’investissement (`interpretation` le rappelle dans chaque
rapport financier).

## 2. Installation reproductible

Dépendance déclarée dans `requirements-v3.txt` :

```text
duckdb>=1.1,<2
```

Disponibilité à tester avant usage :

```python
from come_data.integration import available

if not available():
    ...  # dégrader proprement vers les outils Pandas existants
```

`available()` ne lève jamais d’exception : il indique seulement si DuckDB est
importable dans l’environnement courant.

## 3. Démarrage rapide (chemin recommandé pour V6)

L’adaptateur relie la façade `ComeDataEngine` à un `Workspace` existant sans
créer de dossier tant que le moteur n’est pas utilisé.

```python
from come_data.integration import engine_for_workspace, financial_analysis

with engine_for_workspace(workspace) as engine:
    report = financial_analysis(
        engine, "data/cours.csv",
        value_column="cloture", time_column="date",
    )
```

`workspace` est n’importe quel objet exposant `config.data_dir` et
`config.output_dir` (c’est le cas du `Workspace` de Côme AI). Le contexte
`with` ferme la connexion DuckDB en fin de bloc.

## 4. Adaptateur `come_data.integration`

| Fonction | Rôle | Retour |
| --- | --- | --- |
| `available() -> bool` | DuckDB importable ? | booléen |
| `engine_for_workspace(workspace, *, memory_limit="2GB", spill_dir=None, query_timeout_seconds=30.0) -> ComeDataEngine` | Construit la façade sur `data_dir`/`output_dir` | façade (context manager) |
| `analyze_file(engine, path, *, sheet=None) -> dict` | Analyse descriptive (profil + statistiques) | dict JSON-safe |
| `financial_analysis(engine, path, *, value_column, time_column=None, sheet=None, periods_per_year=252, risk_free_rate=0.0) -> dict` | Performance d’une série | dict JSON-safe |
| `cash_flow_analysis(engine, path, *, amount_column, date_column=None, sheet=None, discount_rate=0.0) -> dict` | Totaux, VAN et XIRR | dict JSON-safe |

`engine_for_workspace` lève `DataEngineUnavailableError` si DuckDB est absent.
Appelez d’abord `available()` pour éviter l’exception, ou capturez-la pour
basculer sur le chemin Pandas historique.

## 5. Façade `ComeDataEngine`

Import : `from come_data import ComeDataEngine`.

Constructeur :

```python
ComeDataEngine(
    data_dir, output_dir=None, *,
    memory_limit="2GB", threads=None,
    temp_dir=None, query_timeout_seconds=30.0,
)
```

Tous les chemins sont résolus et **confinés** à `data_dir` (+ `output_dir`) :
toute tentative de sortie lève `UnsafeQueryError`.

### 5.1 Chargement et inspection

| Méthode | Description |
| --- | --- |
| `register(path, *, name=None, sheet=None)` | Enregistre un fichier en vue paresseuse |
| `describe(path, *, sheet=None, name=None, materialize=True)` | Nombre de lignes et colonnes typées |
| `analyze(path, *, sheet=None, name=None, materialize=True)` | `AnalysisResult` (profil + stats) |
| `preview(path, *, rows=20, sheet=None)` | Premières lignes JSON-safe |
| `columns(path, ...)` | `[{"column_name", "column_type"}]` |
| `row_count(path, ...)` | Entier |
| `numeric_statistics(path, ...)` | `count/sum/mean/median/min/max/std_dev` (ddof=0, aligné sur Pandas) |

### 5.2 SQL en lecture seule

| Méthode | Description |
| --- | --- |
| `query_file(path, sql, *, params=None, sheet=None, alias="data")` | Enregistre le fichier sous `alias`, exécute un `SELECT` |
| `query(sql, params=None)` | `SELECT` sur les tables déjà enregistrées |
| `register_frame(frame, name)` | Enregistre un DataFrame Pandas existant |

Seul `SELECT` (ce qui couvre `WITH`, `DESCRIBE`, `SUMMARIZE`) est autorisé.
Les requêtes multiples, le DDL/DML, `ATTACH`, `LOAD`/`INSTALL`, les fonctions de
lecture de fichiers (`read_csv_auto`, `read_parquet`, `read_blob`…), les
caractères NUL et les requêtes trop longues sont **refusés** (`UnsafeQueryError`).
Les valeurs passent par des marqueurs `?`, jamais par concaténation SQL.

### 5.3 Finance

| Méthode | Description |
| --- | --- |
| `performance(path, value_column, *, time_column=None, sheet=None, periods_per_year=252, risk_free_rate=0.0)` | Rendement total, annualisé, volatilité, Sharpe, drawdown |
| `cash_flows(path, amount_column, *, date_column=None, sheet=None, discount_rate=0.0)` | Entrées/sorties, net, VAN, XIRR |
| `profit_and_loss(path, value_column, *, cost_column=None, sheet=None)` | P&L, coût, retour sur coût, taux de réussite |
| `group_summary(path, group_column, *, aggregate="count(*)", sheet=None, order_by=None)` | Agrégation par groupe |
| `period_summary(path, date_column, *, period="month", amount_column=None, sheet=None)` | Agrégation `day`/`week`/`month`/`quarter`/`year` |

Sans `time_column`, la performance est calculée en Python dans l’ordre d’entrée
et refusée au-delà de `max_series_rows` (1 000 000 par défaut) ; fournissez une
colonne temporelle pour un calcul diffusé par DuckDB.

### 5.4 Export

| Méthode | Description |
| --- | --- |
| `export_rows(rows, target_name, *, format=None)` | Écrit un CSV ou XLSX dans `output_dir` |
| `export_query(sql, target_name, *, delimiter=",")` | Exporte un `SELECT` en CSV |

Les exports neutralisent les formules Excel (`=`, `+`, `-`, `@`) et refusent
d’écrire hors de `output_dir`.

## 6. Bas niveau : `DataEngine` et `FinancialAnalytics`

Import : `from come_data import DataEngine, FinancialAnalytics`.

- `DataEngine` expose `register_file`, `register_frame`, `query`, `query_frame`,
  `scalars`, `scalar`, `columns`, `row_count`, `preview`, `profile`,
  `numeric_statistics`, `export_query_to_csv`, `export_frame`, `close`.
- `FinancialAnalytics(engine)` expose `performance`, `returns_frame`,
  `moving_average`, `cash_flow_metrics`, `running_balance`, `profit_and_loss`,
  `period_summary` sur un nom de table déjà enregistré.
- `registered()` liste les tables/vues connues avec leur source.

À utiliser uniquement si l’orchestrateur gère lui-même les noms de tables.

## 7. Fonctions pures `come_data.finance`

Import : `from come_data import finance`.

Rendements et risque : `simple_returns`, `log_returns`, `total_return`, `cagr`,
`mean`, `sample_stdev`, `annualized_volatility`, `sharpe_ratio`,
`drawdown_series`, `max_drawdown`, `moving_average`.

Flux datés : `npv(rate, cashflows, dates=None)` et `xirr(cashflows, dates)`.
L’XIRR utilise la **base 365 jours** (convention XIRR/Excel), y compris sur les
années bissextiles (366 jours réels) ; il renvoie `None` sans changement de signe
ou sans racine dans l’intervalle exploré.

P&L : `profit_and_loss(values, costs=None)`.

Conventions explicites : rendements simples par période, volatilité avec
`ddof=1`, Sharpe annualisé. Ces choix changent les résultats : ne pas les
réinterpréter.

## 8. Valeurs manquantes et qualité des données

À l’enregistrement d’un CSV, les marqueurs `""`, `NA`, `NaN`, `null`, `#N/A`,
`NULL`, `<NA>` sont convertis en **vrais NULL** avant inférence de type. Une
colonne numérique contenant des trous est donc correctement typée et les calculs
SQL (`(v - prev)`, agrégations) n’échouent pas. Ce comportement peut être
ajusté via `read_options={"nullstr": [...]}` sur `register_file`.

## 9. Erreurs à présenter à l’utilisateur

Toutes dérivent de `DataEngineError` (`from come_data import DataEngineError`) :

| Exception | Sens |
| --- | --- |
| `DataEngineUnavailableError` | DuckDB absent ou non démarrable |
| `UnsupportedDataError` | Format ou fichier non pris en charge |
| `UnsafeQueryError` | SQL ou chemin refusé (sécurité) |
| `DataLimitError` | Volume, mémoire ou délai dépassés |
| `DataEngineError` | Erreur générique |

Ces messages sont sûrs à afficher : ils ne contiennent ni chemin absolu, ni
secret, ni trace technique. En cas d’écriture, l’orchestrateur doit conserver sa
règle de **confirmation avant action**.

## 10. Garanties vérifiées par les tests

- Import de `come_data` ne modifie pas `workspace_core.TOOL_SCHEMAS` ni
  `LocalTools` (additivité).
- Les statistiques numériques DuckDB égalent celles de Pandas (ddof=0).
- Le fichier source n’est jamais modifié par une analyse.
- Recoupement `xirr`/`npv` : la VAN au taux trouvé est nulle à `1e-5`.
- Contournements SQL et sorties de dossier refusés (sécurité).

## 11. Reproduire les preuves

Depuis la racine du worktree, avec le venv du projet :

```bash
.venv/bin/python -m pytest tests/test_come_data_finance.py tests/test_come_data_finance_edge.py -q
.venv/bin/python -m pytest tests/test_come_data_engine.py tests/test_come_data_analytics.py \
    tests/test_come_data_integration.py tests/test_come_data_safety.py tests/test_come_data_security.py -q
.venv/bin/python -m pytest -q
```

## 12. Commits locaux de référence

| Commit | Contenu |
| --- | --- |
| `e5a2560` | `feat(data): add verified local DuckDB engine for Côme Data` |
| `c4b090b` | `perf(data): add reproducible Pandas vs DuckDB benchmark harness` |
| `f06c53c` | `build(deps): declare duckdb>=1.1,<2 for reproducible data engine install` |

Aucune fusion ni push : la branche reste `feature/opencode-data`. Toute
intégration dans `main` ou dans V6 requiert une autorisation explicite.
