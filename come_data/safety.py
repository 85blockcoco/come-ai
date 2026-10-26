"""Garde-fous de sûreté du moteur de données.

Deux responsabilités, testables isolément :

* ``validate_readonly_query`` n'autorise qu'une seule instruction de type
  ``SELECT`` (ce qui couvre ``WITH``, ``DESCRIBE`` et ``SUMMARIZE``) et refuse
  toute fonction capable de lire un fichier arbitraire depuis le SQL.
* ``resolve_within`` confine tout accès fichier à une liste de racines
  autorisées, en résolvant les liens symboliques et les ``..`` avant contrôle.

Le contrôle SQL s'appuie sur le parseur de DuckDB : le type d'instruction est
décidé par le moteur lui-même, puis une seconde barrière analyse le texte pour
interdire les fonctions de lecture de fichiers. Le SQL n'est jamais concaténé
avec des valeurs utilisateur : les valeurs passent par des marqueurs ``?``.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from pathlib import Path

from .errors import UnsafeQueryError

#: Types d'instruction DuckDB autorisés. ``SELECT`` couvre ``WITH``, ``DESCRIBE``
#: et ``SUMMARIZE``; tout le reste (DDL/DML/ATTACH/COPY/PRAGMA/SET...) est refusé.
ALLOWED_STATEMENT_TYPES: frozenset[str] = frozenset({"SELECT"})

#: Fonctions/tables interdites dans le SQL utilisateur : lecture de fichier
#: arbitraire, inspection d'environnement ou chargement d'extension. Le moteur
#: charge lui-même les fichiers autorisés sous forme de vues ; une requête ne
#: doit donc jamais pouvoir ouvrir un chemin arbitraire ni lire un secret.
FORBIDDEN_FILE_FUNCTIONS: frozenset[str] = frozenset(
    {
        "read_csv",
        "read_csv_auto",
        "read_parquet",
        "parquet_scan",
        "read_json",
        "read_json_auto",
        "read_json_objects",
        "read_ndjson",
        "read_ndjson_auto",
        "read_text",
        "read_blob",
        "read_xlsx",
        "read_arrow",
        "arrow_scan",
        "parquet_metadata",
        "parquet_schema",
        "glob",
        "sniff_csv",
        "sqlite_scan",
        "sqlite_query",
        "postgres_scan",
        "postgres_query",
        "mysql_scan",
        "mysql_query",
        "load_extension",
        "getenv",
        "duckdb_settings",
        "duckdb_variables",
    }
)

#: Barrière secondaire : quelques jetons de niveau instruction qui n'ont aucun
#: sens dans un SELECT pur et signalent une tentative d'écriture, d'attachement
#: ou de chargement d'extension. Volontairement minimal pour ne pas refuser des
#: requêtes légitimes (par ex. la fonction ``replace``).
FORBIDDEN_TOKEN_PATTERN = re.compile(
    r"\b(attach|detach|install|pragma|vacuum|checkpoint)\b",
    re.IGNORECASE,
)

_FUNCTION_PATTERN = re.compile(
    r"\b(" + "|".join(sorted(FORBIDDEN_FILE_FUNCTIONS)) + r")\b",
    re.IGNORECASE,
)

_MAX_SQL_CHARS = 100_000


def _require_duckdb():
    try:
        import duckdb  # noqa: PLC0415 - import paresseux pour message d'erreur clair
    except ImportError as error:  # pragma: no cover - dépend de l'environnement
        from .errors import DataEngineUnavailableError

        raise DataEngineUnavailableError(
            "Le moteur DuckDB n'est pas installé dans le venv. "
            "Installe-le une seule fois : .venv/bin/python -m pip install 'duckdb>=1.1,<2'"
        ) from error
    return duckdb


def validate_readonly_query(sql: str) -> str:
    """Renvoie la requête nettoyée si elle est en lecture seule sûre.

    Lève ``UnsafeQueryError`` sinon. La fonction ne modifie jamais la requête :
    elle la renvoie telle quelle après validation pour que l'appelant garde le
    contrôle exact de ce qui est exécuté.
    """
    if not isinstance(sql, str):
        raise UnsafeQueryError("La requête SQL doit être une chaîne de caractères.")
    cleaned = sql.strip().rstrip(";").strip()
    if not cleaned:
        raise UnsafeQueryError("La requête SQL est vide.")
    if len(cleaned) > _MAX_SQL_CHARS:
        raise UnsafeQueryError("La requête SQL est trop longue pour être analysée en sûreté.")
    if "\x00" in cleaned:
        raise UnsafeQueryError("La requête SQL contient un caractère interdit.")

    duckdb = _require_duckdb()
    try:
        statements = duckdb.extract_statements(cleaned)
    except Exception as error:  # noqa: BLE001 - le message brut du parseur peut fuiter
        raise UnsafeQueryError("La requête SQL n'a pas pu être analysée.") from error

    if not statements:
        raise UnsafeQueryError("La requête SQL est vide.")
    if len(statements) != 1:
        raise UnsafeQueryError("Une seule instruction SQL à la fois est autorisée.")

    statement_type = _statement_type_name(statements[0])
    if statement_type not in ALLOWED_STATEMENT_TYPES:
        raise UnsafeQueryError(
            "Seules les requêtes de lecture (SELECT) sont autorisées par le moteur de données."
        )

    forbidden_function = _FUNCTION_PATTERN.search(cleaned)
    if forbidden_function:
        raise UnsafeQueryError(
            "Cette fonction d'accès fichier est interdite dans une requête du moteur de données."
        )
    forbidden_token = FORBIDDEN_TOKEN_PATTERN.search(_strip_string_literals(cleaned))
    if forbidden_token:
        raise UnsafeQueryError("La requête contient un mot-clé interdit par le moteur de données.")
    return sql


def _statement_type_name(statement) -> str:
    value = getattr(statement, "type", None)
    name = getattr(value, "name", None)
    if isinstance(name, str):
        return name.upper()
    return str(value or "").upper()


def _strip_string_literals(sql: str) -> str:
    """Neutralise le contenu des littéraux avant l'analyse de mots-clés.

    Sans cela, une valeur légitime comme ``'copy'`` déclencherait un refus à
    tort. Les commentaires sont également retirés car ils peuvent masquer un
    mot-clé aux analyses naïves.
    """
    without_blocks = re.sub(r"/\*.*?\*/", " ", sql, flags=re.DOTALL)
    without_lines = re.sub(r"--[^\n]*", " ", without_blocks)
    without_strings = re.sub(r"'(?:[^']|'')*'", "''", without_lines)
    return re.sub(r'"(?:[^"]|"")*"', '""', without_strings)


def resolve_within(allowed_roots: Iterable[Path], candidate: str | Path) -> Path:
    """Résout ``candidate`` et vérifie qu'il reste sous une racine autorisée.

    Les liens symboliques et les segments ``..`` sont résolus avant le
    contrôle : impossible de sortir de l'espace de travail par ce biais.
    """
    roots = [Path(root).expanduser().resolve() for root in allowed_roots]
    if not roots:
        raise UnsafeQueryError("Aucune racine de fichiers autorisée n'est configurée.")
    resolved = Path(str(candidate).strip()).expanduser()
    try:
        resolved = resolved.resolve(strict=False) if hasattr(resolved, 'resolve') else resolved.resolve()
    except (OSError, RuntimeError) as error:
        raise UnsafeQueryError("Ce chemin de fichier est invalide.") from error
    for root in roots:
        if resolved == root or root in resolved.parents:
            return resolved
    raise UnsafeQueryError("Ce fichier est en dehors des dossiers autorisés du moteur de données.")


def quote_identifier(name: str) -> str:
    """Citation sûre d'un identifiant SQL (nom de table, colonne, alias)."""
    text = str(name)
    if not text or len(text) > 200 or "\x00" in text:
        raise UnsafeQueryError("Nom d'identifiant SQL invalide.")
    return '"' + text.replace('"', '""') + '"'


def quote_literal(value: str) -> str:
    """Citation sûre d'un littéral SQL de type chaîne (chemins, motifs)."""
    return "'" + str(value).replace("'", "''") + "'"
