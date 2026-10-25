"""Tests des garde-fous : SQL en lecture seule et confinement des chemins."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

pytest.importorskip("duckdb")

from come_data.errors import UnsafeQueryError  # noqa: E402
from come_data.safety import (  # noqa: E402
    quote_identifier,
    quote_literal,
    resolve_within,
    validate_readonly_query,
)


@pytest.mark.parametrize(
    "sql",
    [
        "SELECT 1",
        "SELECT * FROM data LIMIT 5",
        "WITH a AS (SELECT 1 AS x) SELECT * FROM a",
        "DESCRIBE SELECT 1",
        "SUMMARIZE SELECT 1 AS x",
        "SELECT replace(name, 'a', 'b') FROM data",
        'SELECT "set" AS set_col FROM data',
    ],
)
def test_readonly_queries_are_accepted(sql: str) -> None:
    assert validate_readonly_query(sql)


@pytest.mark.parametrize(
    "sql",
    [
        "ATTACH 'other.db'",
        "DETACH data",
        "DROP TABLE data",
        "CREATE TABLE t(a int)",
        "INSERT INTO data VALUES (1)",
        "UPDATE data SET a = 1",
        "DELETE FROM data",
        "COPY (SELECT 1) TO 'x.csv'",
        "PRAGMA database_list",
        "SET memory_limit='1GB'",
        "INSTALL httpfs",
        "SELECT * FROM read_csv_auto('/etc/passwd')",
        "SELECT * FROM glob('/**')",
        "SELECT * FROM read_text('/etc/hosts')",
        "SELECT getenv('HOME')",
        "SELECT * FROM duckdb_settings()",
        "SELECT * FROM sqlite_scan('x.db', 't')",
        "SELECT 1; DROP TABLE data",
        "SELECT 1; SELECT 2",
    ],
)
def test_dangerous_queries_are_rejected(sql: str) -> None:
    with pytest.raises(UnsafeQueryError):
        validate_readonly_query(sql)


def test_empty_and_non_string_queries_are_rejected() -> None:
    with pytest.raises(UnsafeQueryError):
        validate_readonly_query("   ")
    with pytest.raises(UnsafeQueryError):
        validate_readonly_query(None)  # type: ignore[arg-type]


def test_comments_cannot_smuggle_a_second_statement() -> None:
    # Un commentaire est inerte : le mot-clé qu'il contient ne doit pas faire
    # échouer une requête légitime...
    assert validate_readonly_query("SELECT 1 /* attach */ AS x FROM data")
    # ...mais il ne doit jamais permettre de glisser une seconde instruction.
    with pytest.raises(UnsafeQueryError):
        validate_readonly_query("SELECT 1 /* commentaire */; DROP TABLE data")
    # Un littéral contenant un mot-clé ne doit pas être refusé à tort.
    assert validate_readonly_query("SELECT 'pragma' AS mot FROM data")


def test_resolve_within_accepts_inside(tmp_path: Path) -> None:
    root = tmp_path / "data"
    root.mkdir()
    target = root / "ventes.csv"
    target.write_text("a,b\n1,2\n", encoding="utf-8")
    assert resolve_within([root], target) == target.resolve()


def test_resolve_within_rejects_outside(tmp_path: Path) -> None:
    root = tmp_path / "data"
    root.mkdir()
    outside = tmp_path / "secret.txt"
    outside.write_text("secret", encoding="utf-8")
    with pytest.raises(UnsafeQueryError):
        resolve_within([root], outside)


def test_resolve_within_rejects_parent_traversal(tmp_path: Path) -> None:
    root = tmp_path / "data"
    root.mkdir()
    with pytest.raises(UnsafeQueryError):
        resolve_within([root], root / ".." / "secret.txt")


def test_resolve_within_rejects_symlink_escape(tmp_path: Path) -> None:
    root = tmp_path / "data"
    root.mkdir()
    secret = tmp_path / "secret.txt"
    secret.write_text("secret", encoding="utf-8")
    link = root / "lien.csv"
    try:
        os.symlink(secret, link)
    except (OSError, NotImplementedError):  # pragma: no cover - selon la plateforme
        pytest.skip("Les liens symboliques ne sont pas disponibles ici.")
    with pytest.raises(UnsafeQueryError):
        resolve_within([root], link)


def test_quotes_are_safe() -> None:
    assert quote_identifier('we"ird') == '"we""ird"'
    assert quote_literal("O'Brien") == "'O''Brien'"
    with pytest.raises(UnsafeQueryError):
        quote_identifier("")
