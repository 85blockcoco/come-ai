"""Tests de robustesse des protections (contournements SQL et chemins).

Ces tests ciblent les cas limites pour renforcer les garde-fous sans casser
les usages légitimes.
"""

from __future__ import annotations

from pathlib import Path

import pytest

pytest.importorskip("duckdb")

from come_data.errors import UnsafeQueryError  # noqa: E402
from come_data.safety import (  # noqa: E402
    resolve_within,
    validate_readonly_query,
)


@pytest.mark.parametrize(
    "sql",
    [
        "SELECT 1; ; SELECT 2",
        "select 1; drop table t",
        "  SELECT 1  ;  CREATE TABLE t(x int)  ",
        "/* */ ; INSERT INTO t VALUES (1)",
        "SELECT 1;\nDELETE FROM t",
    ],
)
def test_multiple_statements_with_various_spacing_are_rejected(sql: str) -> None:
    with pytest.raises(UnsafeQueryError):
        validate_readonly_query(sql)


@pytest.mark.parametrize(
    "sql",
    [
        "EXECUTE some_proc()",
        "PREPARE q AS SELECT 1",
        "DEALLOCATE q",
        "CALL my_proc()",
        "LOAD '/tmp/ext.so'",
        "INSTALL httpfs",
        "VACUUM",
        "CHECKPOINT",
        "ATTACH DATABASE ':memory:' AS m",
        "DETACH m",
        "TRUNCATE TABLE data",
        "REPLACE INTO t VALUES (1)",
        "GRANT SELECT ON t TO u",
        "REVOKE SELECT ON t FROM u",
    ],
)
def test_forbidden_dml_ddl_are_rejected(sql: str) -> None:
    with pytest.raises(UnsafeQueryError):
        validate_readonly_query(sql)


@pytest.mark.parametrize(
    "sql",
    [
        "SELECT * FROM read_parquet('/etc/passwd')",
        "SELECT * FROM parquet_scan('/etc/shadow')",
        "SELECT * FROM read_json_auto('/tmp/x')",
        "SELECT * FROM read_ndjson('/tmp/x')",
        "SELECT * FROM read_blob('/etc/hosts')",
        "SELECT * FROM read_xlsx('/etc/passwd')",
        "SELECT * FROM arrow_scan('/tmp/x.arrow')",
        "SELECT parquet_metadata('/tmp/x.parquet')",
        "SELECT parquet_schema('/tmp/x.parquet')",
        "SELECT * FROM sqlite_scan('/tmp/db.sqlite', 't')",
        "SELECT * FROM postgres_scan('host', 'db', 't')",
        "SELECT * FROM mysql_scan('host', 'db', 't')",
    ],
)
def test_forbidden_file_reading_functions_are_rejected(sql: str) -> None:
    with pytest.raises(UnsafeQueryError):
        validate_readonly_query(sql)


def test_nul_character_is_rejected() -> None:
    with pytest.raises(UnsafeQueryError):
        validate_readonly_query("SELECT 1\x00")


def test_very_long_query_is_rejected() -> None:
    long_sql = "SELECT 1 " + "FROM data " * 6000  # >100000 chars approx
    with pytest.raises(UnsafeQueryError):
        validate_readonly_query(long_sql[:120000])


def test_case_insensitive_keywords_blocked() -> None:
    with pytest.raises(UnsafeQueryError):
        validate_readonly_query("select 1; Attach ':memory:' as m")
    with pytest.raises(UnsafeQueryError):
        validate_readonly_query("select * from read_csv_auto('/etc/passwd')")


def test_resolve_within_rejects_empty_root_list() -> None:
    from come_data.errors import UnsafeQueryError as U
    with pytest.raises(U):
        resolve_within([], "/tmp/x")


def test_resolve_within_accepts_expanded_user(tmp_path: Path) -> None:
    root = tmp_path / "data"
    root.mkdir()
    candidate = Path("~/nonexistent_but_path_test.txt").expanduser()
    # Just ensure it doesn't crash on expanduser; outside root → rejected
    with pytest.raises(UnsafeQueryError):
        resolve_within([root], candidate)


def test_resolve_within_handles_trailing_spaces(tmp_path: Path) -> None:
    root = tmp_path / "data"
    root.mkdir()
    target = root / "file.csv"
    target.write_text("a\n1\n", encoding="utf-8")
    resolved = resolve_within([root], str(target) + " ")
    assert resolved == target.resolve()


def test_resolve_within_rejects_nonexistent_outside(tmp_path: Path) -> None:
    root = tmp_path / "data"
    root.mkdir()
    # Un fichier inexistant DANS les racines autorisées est accepté (lecture différée)
    try:
        resolve_within([root], root / "does_not_exist.csv")
    except UnsafeQueryError:
        pytest.fail("Un fichier inexistant dans une racine autorisée ne doit pas être refusé.")
    # Un fichier inexistant HORS racines doit être refusé
    with pytest.raises(UnsafeQueryError):
        resolve_within([root], tmp_path / "outside_missing.csv")
