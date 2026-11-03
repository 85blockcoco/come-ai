"""Couche d'analyse DuckDB réutilisable pour Côme IA.

Le moteur ouvre une base DuckDB **en mémoire** et n'expose qu'une poignée
d'opérations contrôlées. Il ne charge pas un CSV en mémoire : il crée une vue
paresseuse au-dessus du fichier et laisse DuckDB diffuser les agrégations par
flux, avec une limite mémoire et un répertoire de dépassement disque explicites.

Les fichiers Excel restent lus par Pandas/openpyxl (opérations de classeur),
puis enregistrés comme table DuckDB pour l'analyse. Rien n'est supprimé du
chemin existant : cette couche est additive.
"""

from __future__ import annotations

import csv
import os
import re
import threading
import zipfile
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .errors import (
    DataEngineError,
    DataEngineUnavailableError,
    DataLimitError,
    UnsupportedDataError,
)
from .safety import quote_identifier, quote_literal, resolve_within, validate_readonly_query

TABULAR_SUFFIXES = {".csv", ".tsv", ".parquet", ".xlsx", ".xlsm", ".xls"}
EXCEL_SUFFIXES = {".xlsx", ".xlsm", ".xls"}
CSV_SUFFIXES = {".csv", ".tsv"}

#: Garde anti « zip bomb » avant d'ouvrir un classeur Excel (mêmes ordres de
#: grandeur que ``workspace_core``), sans en dépendre pour rester autonome.
MAX_OFFICE_ARCHIVE_ENTRIES = 20_000
MAX_OFFICE_UNCOMPRESSED_BYTES = 150 * 1024 * 1024
MAX_EXCEL_ROWS = 1_000_000
MAX_EXCEL_COLUMNS = 1_024
DEFAULT_MEMORY_LIMIT = "2GB"
DEFAULT_QUERY_TIMEOUT_SECONDS = 30.0

_NAME_PATTERN = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


@dataclass
class RegisteredTable:
    """Métadonnées d'une table/vue enregistrée dans le moteur."""

    name: str
    kind: str  # 'view' (paresseux, fichier) ou 'table' (matérialisé)
    source: str | None
    sheet: str | None = None
    options: dict[str, Any] = field(default_factory=dict)


def _load_duckdb():
    try:
        import duckdb  # noqa: PLC0415
    except ImportError as error:  # pragma: no cover - dépend de l'environnement
        raise DataEngineUnavailableError(
            "Le moteur DuckDB est absent du venv. Installe-le une seule fois : "
            ".venv/bin/python -m pip install 'duckdb>=1.1,<2'"
        ) from error
    return duckdb


def is_available() -> bool:
    """Indique si DuckDB est importable, sans lever d'exception."""
    try:
        _load_duckdb()
    except DataEngineUnavailableError:
        return False
    return True


def safe_identifier(name: str, fallback: str = "table") -> str:
    """Renvoie un identifiant SQL simple, sans caractère spécial."""
    text = re.sub(r"[^A-Za-z0-9_]", "_", str(name or ""))
    text = re.sub(r"_+", "_", text).strip("_")
    if not text or not _NAME_PATTERN.match(text):
        text = f"{fallback}_{abs(hash(str(name))) % 10_000_000:07d}"
    return text


def _validate_office_archive(path: Path) -> None:
    if path.suffix.lower() not in {".xlsx", ".xlsm"}:
        return
    try:
        with zipfile.ZipFile(path) as archive:
            entries = archive.infolist()
            total_uncompressed = sum(entry.file_size for entry in entries)
    except zipfile.BadZipFile as error:
        raise UnsupportedDataError("Classeur Excel illisible ou corrompu.") from error
    if len(entries) > MAX_OFFICE_ARCHIVE_ENTRIES:
        raise DataLimitError("Classeur Excel trop complexe pour une lecture sûre.")
    if total_uncompressed > MAX_OFFICE_UNCOMPRESSED_BYTES:
        raise DataLimitError("Classeur Excel trop volumineux une fois décompressé.")


def sniff_delimiter(path: Path, default: str = ",") -> str:
    try:
        with path.open("r", encoding="utf-8-sig", errors="replace") as handle:
            sample = handle.read(8192)
        return csv.Sniffer().sniff(sample, delimiters=",;\t|").delimiter
    except (OSError, csv.Error):
        return default


class DataEngine:
    """Moteur DuckDB en mémoire, à durée de vie contrôlée par l'appelant."""

    def __init__(
        self,
        allowed_dirs: Iterable[Path],
        *,
        memory_limit: str = DEFAULT_MEMORY_LIMIT,
        threads: int | None = None,
        temp_dir: Path | None = None,
        query_timeout_seconds: float = DEFAULT_QUERY_TIMEOUT_SECONDS,
        preserve_insertion_order: bool = True,
        database: str | Path = ":memory:",
    ) -> None:
        self._allowed_dirs = [Path(item).expanduser().resolve() for item in allowed_dirs]
        if not self._allowed_dirs:
            raise DataEngineError("Le moteur de données requiert au moins un dossier autorisé.")
        self.memory_limit = memory_limit
        self.query_timeout_seconds = float(query_timeout_seconds)
        self._tables: dict[str, RegisteredTable] = {}
        self._lock = threading.Lock()

        duckdb = _load_duckdb()
        # La connexion est monothread côté requêtes ; ``interrupt()`` reste le
        # moyen documenté d'annuler une requête depuis un autre fil.
        if isinstance(database, Path) or (isinstance(database, str) and database != ":memory:"):
            db_path = resolve_within(self._allowed_dirs, database)
            self._con = duckdb.connect(str(db_path))
        else:
            self._con = duckdb.connect(":memory:")

        resolved_threads = threads if threads is not None else max(1, min(4, os.cpu_count() or 1))
        self._configure(resolved_threads, temp_dir, preserve_insertion_order)

    def _configure(self, threads: int, temp_dir: Path | None, preserve_insertion_order: bool) -> None:
        self._con.execute("SET enable_progress_bar=false")
        self._con.execute(f"SET memory_limit={quote_literal(self.memory_limit)}")
        self._con.execute(f"SET threads={int(max(1, threads))}")
        self._con.execute(
            f"SET preserve_insertion_order={'true' if preserve_insertion_order else 'false'}"
        )
        if temp_dir is not None:
            spill = Path(temp_dir).expanduser().resolve()
            spill.mkdir(parents=True, exist_ok=True)
            self._con.execute(f"SET temp_directory={quote_literal(str(spill))}")

    # ------------------------------------------------------------------ #
    # Cycle de vie
    # ------------------------------------------------------------------ #
    @classmethod
    def for_workspace(cls, data_dir: Path, output_dir: Path | None = None, **kwargs: Any) -> "DataEngine":
        """Construit un moteur autorisé à lire ``data_dir`` et écrire dans ``output_dir``."""
        roots = [Path(data_dir)]
        if output_dir is not None:
            roots.append(Path(output_dir))
        return cls(roots, **kwargs)

    def close(self) -> None:
        try:
            self._con.close()
        except Exception:  # noqa: BLE001 - fermeture best-effort
            pass
        self._tables.clear()

    def __enter__(self) -> "DataEngine":
        return self

    def __exit__(self, *_exc: object) -> None:
        self.close()

    # ------------------------------------------------------------------ #
    # Enregistrement de données
    # ------------------------------------------------------------------ #
    def registered(self) -> list[RegisteredTable]:
        return list(self._tables.values())

    def register_file(
        self,
        path: str | Path,
        *,
        name: str | None = None,
        sheet: str | None = None,
        materialize: bool = False,
        read_options: dict[str, Any] | None = None,
    ) -> RegisteredTable:
        """Rend un fichier interrogeable, sous forme de vue paresseuse par défaut."""
        resolved = resolve_within(self._allowed_dirs, path)
        if not resolved.is_file():
            raise UnsupportedDataError("Ce fichier est introuvable dans les dossiers autorisés.")
        suffix = resolved.suffix.lower()
        if suffix not in TABULAR_SUFFIXES:
            raise UnsupportedDataError("Le moteur de données lit les CSV, TSV, Parquet et Excel.")

        # Enregistrement idempotent : une façade qui analyse deux fois le même
        # fichier ne doit pas empiler des tables identiques en mémoire.
        wanted_kind = "table" if (materialize or suffix in EXCEL_SUFFIXES) else "view"
        for existing in self._tables.values():
            if existing.source == str(resolved) and existing.sheet == sheet and existing.kind == wanted_kind:
                return existing

        table_name = safe_identifier(name or resolved.stem, "table")
        table_name = self._unique_name(table_name)

        if suffix in CSV_SUFFIXES:
            info = self._register_csv(resolved, table_name, read_options, materialize)
        elif suffix == ".parquet":
            info = self._register_parquet(resolved, table_name, materialize)
        else:
            info = self._register_excel(resolved, table_name, sheet, read_options)

        self._tables[table_name] = info
        return info

    def register_frame(self, frame: Any, name: str) -> RegisteredTable:
        """Enregistre un DataFrame Pandas déjà construit sous un nom de table."""
        table_name = self._unique_name(safe_identifier(name, "frame"))
        self._con.register(table_name, frame)
        self._con.execute(
            f"CREATE OR REPLACE TABLE {quote_identifier(table_name)} AS "
            f"SELECT * FROM {quote_identifier(table_name)}"
        )
        info = RegisteredTable(table_name, "table", None)
        self._tables[table_name] = info
        return info

    def _register_csv(
        self,
        path: Path,
        name: str,
        read_options: dict[str, Any] | None,
        materialize: bool = False,
    ) -> RegisteredTable:
        delimiter = "\t" if path.suffix.lower() == ".tsv" else sniff_delimiter(path)
        options = {
            "header": True,
            "delim": delimiter,
            "sample_size": 20_480,
            "nullstr": ["", "NA", "NaN", "null", "#N/A", "NULL", "<NA>"],
        }
        options.update(read_options or {})
        clauses = []
        for key, value in options.items():
            if key == "nullstr":
                # DuckDB attend une liste de littéraux pour ``nullstr``. On la
                # rend explicitement (et non via ``_sql_literal``) pour que les
                # valeurs manquantes CSV (``NA``, ``NaN``, vides...) deviennent
                # de vrais NULL : sans cela la colonne est inférée VARCHAR et
                # les calculs numériques échouent (BinderException).
                markers = value if isinstance(value, (list, tuple)) else [value]
                rendered = ", ".join(quote_literal(str(item)) for item in markers)
                clauses.append(f"nullstr=[{rendered}]")
                continue
            clauses.append(f"{key}={_sql_literal(value)}")
        clauses = ", ".join(clauses) if clauses else ""
        kind = "table" if materialize else "view"
        sql = (
            f"CREATE OR REPLACE {kind.upper()} {quote_identifier(name)} AS "
            f"SELECT * FROM read_csv_auto({quote_literal(str(path))}, {clauses})"
        )
        try:
            self._con.execute(sql)
        except Exception as error:  # noqa: BLE001 - message générique à l'utilisateur
            raise UnsupportedDataError("Ce fichier CSV n'a pas pu être lu comme tableau.") from error
        return RegisteredTable(name, kind, str(path), None, options)

    def _register_parquet(self, path: Path, name: str, materialize: bool = False) -> RegisteredTable:
        kind = "table" if materialize else "view"
        sql = (
            f"CREATE OR REPLACE {kind.upper()} {quote_identifier(name)} AS "
            f"SELECT * FROM read_parquet({quote_literal(str(path))})"
        )
        try:
            self._con.execute(sql)
        except Exception as error:  # noqa: BLE001
            raise UnsupportedDataError("Ce fichier Parquet n'a pas pu être lu.") from error
        return RegisteredTable(name, kind, str(path))

    def _register_excel(
        self,
        path: Path,
        name: str,
        sheet: str | None,
        read_options: dict[str, Any] | None,
    ) -> RegisteredTable:
        _validate_office_archive(path)
        import pandas as pd  # noqa: PLC0415

        options = {"sheet_name": sheet if sheet else 0}
        options.update(read_options or {})
        try:
            frame = pd.read_excel(path, nrows=MAX_EXCEL_ROWS, **options)
        except Exception as error:  # noqa: BLE001
            raise UnsupportedDataError("Ce classeur Excel n'a pas pu être lu.") from error
        if not isinstance(frame, pd.DataFrame):  # pragma: no cover - sécurité de type
            raise UnsupportedDataError("La feuille demandée n'est pas un tableau exploitable.")
        if len(frame.columns) > MAX_EXCEL_COLUMNS:
            frame = frame.iloc[:, :MAX_EXCEL_COLUMNS]
        self._con.register(name, frame)
        self._con.execute(
            f"CREATE OR REPLACE TABLE {quote_identifier(name)} AS SELECT * FROM {quote_identifier(name)}"
        )
        resolved_sheet = str(options["sheet_name"])
        return RegisteredTable(name, "table", str(path), resolved_sheet)

    def _unique_name(self, name: str) -> str:
        # On s'appuie uniquement sur notre registre interne : interroger
        # ``information_schema`` coûte ~0,4 s sur DuckDB (introspection complète
        # du catalogue), ce qui dominerait le temps d'enregistrement.
        candidate = name
        counter = 2
        while candidate in self._tables:
            candidate = f"{name}_{counter}"
            counter += 1
        return candidate

    # ------------------------------------------------------------------ #
    # Requêtes contrôlées
    # ------------------------------------------------------------------ #
    def query(self, sql: str, params: Sequence[Any] | None = None, *, timeout: float | None = None) -> list[dict[str, Any]]:
        """Exécute une requête de lecture validée et renvoie des enregistrements.

        On renvoie des dictionnaires Python natifs (et non un DataFrame) : cela
        évite d'initialiser la passerelle Arrow/Pandas de DuckDB (~0,4 s au
        premier appel) et produit des valeurs déjà proches du JSON.
        """
        validate_readonly_query(sql)
        return self._run(lambda: self._records(self._execute(sql, params)), timeout)

    def query_frame(self, sql: str, params: Sequence[Any] | None = None, *, timeout: float | None = None) -> Any:
        """Comme ``query`` mais renvoie un DataFrame Pandas (conversion explicite)."""
        validate_readonly_query(sql)
        return self._run(lambda: self._execute(sql, params).df(), timeout)

    def scalars(self, sql: str, params: Sequence[Any] | None = None, *, timeout: float | None = None) -> list[Any]:
        """Renvoie la première colonne de chaque ligne (liste de valeurs)."""
        validate_readonly_query(sql)
        return self._run(
            lambda: [row[0] for row in self._execute(sql, params).fetchall()], timeout
        )

    def _execute(self, sql: str, params: Sequence[Any] | None) -> Any:
        return self._con.execute(sql, params) if params else self._con.execute(sql)

    @staticmethod
    def _records(cursor: Any) -> list[dict[str, Any]]:
        names = [description[0] for description in cursor.description]
        return [dict(zip(names, row)) for row in cursor.fetchall()]

    def scalar(self, sql: str, params: Sequence[Any] | None = None, *, timeout: float | None = None) -> Any:
        """Exécute une requête de lecture et renvoie la première valeur."""
        validate_readonly_query(sql)
        def run() -> Any:
            row = self._con.execute(sql, params).fetchone() if params else self._con.execute(sql).fetchone()
            return None if row is None else row[0]
        return self._run(run, timeout)

    def _run(self, action, timeout: float | None = None):
        effective = self.query_timeout_seconds if timeout is None else float(timeout)
        with self._lock:
            if not effective or effective <= 0:
                return action()
            finished = threading.Event()

            def watchdog() -> None:
                if not finished.wait(effective):
                    try:
                        self._con.interrupt()
                    except Exception:  # noqa: BLE001
                        pass

            timer = threading.Thread(target=watchdog, daemon=True)
            timer.start()
            try:
                return action()
            except Exception as error:  # noqa: BLE001
                if isinstance(error, DataEngineError):
                    raise
                text = str(error).lower()
                if "interrupt" in text or "cancel" in text:
                    raise DataLimitError(
                        "La requête a dépassé le délai autorisé et a été interrompue."
                    ) from error
                # Le message brut du moteur peut contenir un chemin local : on
                # ne l'expose jamais tel quel.
                raise DataEngineError("La requête n'a pas pu être exécutée par le moteur de données.") from error
            finally:
                finished.set()

    # ------------------------------------------------------------------ #
    # Introspection et profils
    # ------------------------------------------------------------------ #
    def columns(self, table: str) -> list[dict[str, Any]]:
        """Colonnes et types via les métadonnées du curseur (sans ``.df()``)."""
        statement = f"SELECT * FROM {quote_identifier(table)} LIMIT 0"
        validate_readonly_query(statement)
        cursor = self._run(lambda: self._execute(statement, None))
        return [
            {"column_name": description[0], "column_type": str(description[1])}
            for description in cursor.description
        ]

    def row_count(self, table: str) -> int:
        value = self.scalar(f"SELECT count(*) FROM {quote_identifier(table)}")
        return int(value or 0)

    def preview(self, table: str, limit: int = 50) -> list[dict[str, Any]]:
        safe_limit = max(1, min(int(limit), 5_000))
        return self.query(
            f"SELECT * FROM {quote_identifier(table)} LIMIT ?", [safe_limit]
        )

    def profile(self, table: str) -> list[dict[str, Any]]:
        """Profil de colonnes via ``SUMMARIZE`` (une seule agrégation)."""
        return self.query(f"SUMMARIZE SELECT * FROM {quote_identifier(table)}")

    def numeric_statistics(self, table: str, max_columns: int = 30) -> dict[str, Any]:
        """Statistiques numériques compatibles avec ``workspace_core.numeric_statistics``.

        ``std_dev`` utilise l'écart-type de population (ddof=0), comme la version
        Pandas existante, afin de permettre une comparaison sans régression.
        """
        columns = self.columns(table)
        numeric_types = ("INT", "BIGINT", "SMALLINT", "TINYINT", "INTEGER", "HUGEINT",
                         "DOUBLE", "FLOAT", "REAL", "DECIMAL", "NUMERIC")
        numeric = [c["column_name"] for c in columns if str(c["column_type"]).upper().startswith(numeric_types)]
        result: dict[str, Any] = {}
        for column in numeric[:max_columns]:
            qcol = quote_identifier(column)
            row = self._con.execute(
                f"SELECT count({qcol}), sum({qcol}), avg({qcol}), median({qcol}), "
                f"min({qcol}), max({qcol}), stddev_pop({qcol}) "
                f"FROM {quote_identifier(table)} WHERE {qcol} IS NOT NULL"
            ).fetchone()
            count = int(row[0] or 0)
            if count == 0:
                continue
            result[column] = {
                "count": count,
                "sum": _rounded(row[1]),
                "mean": _rounded(row[2]),
                "median": _rounded(row[3]),
                "min": _rounded(row[4]),
                "max": _rounded(row[5]),
                "std_dev": _rounded(row[6]),
            }
        return result

    # ------------------------------------------------------------------ #
    # Import / export de résultats
    # ------------------------------------------------------------------ #
    def export_query_to_csv(
        self,
        sql: str,
        target_path: str | Path,
        *,
        delimiter: str = ",",
    ) -> Path:
        validate_readonly_query(sql)
        target = self._writable_target(target_path)
        statement = (
            f"COPY ({sql.rstrip().rstrip(';')}) TO {quote_literal(str(target))} "
            f"(HEADER, DELIMITER {quote_literal(delimiter)})"
        )
        self._con.execute(statement)
        return target

    def export_frame(self, frame: Any, target_path: str | Path) -> Path:
        """Exporte un DataFrame vers CSV ou Excel, en neutralisant les formules Excel."""
        target = self._writable_target(target_path)
        suffix = target.suffix.lower()
        safe_frame = frame.copy()
        for column in safe_frame.columns:
            # Pandas 3 utilise un dtype ``str`` dédié : couvrir object ET str.
            dtype = safe_frame[column].dtype
            if dtype is object or str(dtype) in {"string", "str"}:
                safe_frame[column] = safe_frame[column].map(_excel_safe)
        if suffix == ".csv":
            safe_frame.to_csv(target, index=False, encoding="utf-8")
        elif suffix in EXCEL_SUFFIXES:
            if suffix == ".xls":
                raise UnsupportedDataError("L'export Excel utilise .xlsx, pas l'ancien format .xls.")
            safe_frame.to_excel(target, index=False, engine="openpyxl")
        else:
            raise UnsupportedDataError("L'export accepte .csv ou .xlsx.")
        return target

    def _writable_target(self, target_path: str | Path) -> Path:
        target = resolve_within(self._allowed_dirs, target_path)
        target.parent.mkdir(parents=True, exist_ok=True)
        return target


def _sql_literal(value: Any) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return str(value)
    return quote_literal(str(value))


def _rounded(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return round(float(value), 4)
    except (TypeError, ValueError):
        return None


def _excel_safe(value: Any) -> Any:
    if isinstance(value, str) and value.startswith(("=", "+", "-", "@")):
        return "'" + value
    return value
