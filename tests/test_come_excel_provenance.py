"""Tests de provenance et d'audit (Objectif 4 : justification et traçabilité)."""

from __future__ import annotations

import json
from pathlib import Path

from come_excel.provenance import (  # noqa: E402
    AuditLog,
    ColumnLineage,
    Provenance,
    SourceRef,
    fingerprint_file,
)


def test_fingerprint_is_stable_and_detects_change(tmp_path: Path) -> None:
    path = tmp_path / "f.csv"
    path.write_text("a\n1\n", encoding="utf-8")
    first = fingerprint_file(path)
    assert first == fingerprint_file(path)
    path.write_text("a\n2\n", encoding="utf-8")
    assert fingerprint_file(path) != first


def test_audit_log_records_ordered_steps(tmp_path: Path) -> None:
    log = AuditLog()
    log.record("load", "Chargement", inputs=("a.csv",), checks=("sha256=abc",))
    log.record("compute", "Calcul EBITDA", formula="=ebit+amort", assumptions=("amort hors cash",))
    assert len(log) == 2
    assert [entry.step for entry in log.entries()] == [1, 2]
    payload = log.as_dict()
    assert payload["steps"] == 2
    assert json.dumps(payload)  # sérialisable
    assert log.entries()[1].formula == "=ebit+amort"
    assert "amort hors cash" in log.entries()[1].assumptions


def test_audit_extend_preserves_chain() -> None:
    first = AuditLog()
    first.record("a", "étape A")
    second = AuditLog()
    second.record("b", "étape B")
    first.extend(second)
    assert [entry.operation for entry in first.entries()] == ["a", "b"]


def test_source_ref_hides_path_and_exposes_provenance(tmp_path: Path) -> None:
    ref = SourceRef(
        source_id="src_1",
        file_name="bilan.xlsx",
        path="/secret/bilan.xlsx",
        kind="xlsx",
        fingerprint="f" * 64,
        size_bytes=123,
        sheet="Bilan",
        cell_range="A1:F200",
        rows=199,
        columns=6,
        registered_table="bilan",
    )
    hidden = ref.as_dict()
    assert "path" not in hidden
    assert hidden["sheet"] == "Bilan"
    assert hidden["cell_range"] == "A1:F200"
    assert "path" in ref.as_dict(include_path=True)


def test_provenance_links_sources_and_lineage() -> None:
    source = SourceRef(
        source_id="src_1",
        file_name="ventes.csv",
        path="ventes.csv",
        kind="csv",
        fingerprint="a" * 64,
        size_bytes=10,
    )
    lineage = ColumnLineage(
        output_column="montant",
        sources=("ventes.csv.montant",),
        transform="union aligné par nom normalisé",
    )
    provenance = Provenance(
        label="consolidated_union",
        sources=(source,),
        transform="UNION ALL",
        assumptions=("colonnes absentes = NULL",),
        checks=("lignes=6",),
        lineage=(lineage,),
    )
    payload = provenance.as_dict()
    assert payload["sources"][0]["file_name"] == "ventes.csv"
    assert payload["lineage"][0]["output_column"] == "montant"
    assert json.dumps(payload)
