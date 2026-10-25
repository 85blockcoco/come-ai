"""Non-régression : le nouveau moteur cohabite avec les outils existants.

Ces tests montrent que, sur le même fichier, l'analyse Pandas historique
(``workspace_core.LocalTools``) et la nouvelle analyse DuckDB produisent des
statistiques numériques identiques. Aucune fonctionnalité existante n'est
modifiée : la couche ``come_data`` est purement additive.
"""

from __future__ import annotations

from pathlib import Path

import pytest

pytest.importorskip("duckdb")

import workspace_core  # noqa: E402
from come_data.integration import (  # noqa: E402
    analyze_file,
    available,
    cash_flow_analysis,
    engine_for_workspace,
    financial_analysis,
)


def test_duckdb_layer_is_available() -> None:
    assert available() is True


def test_numeric_statistics_match_between_pandas_and_duckdb(tmp_path: Path) -> None:
    config = workspace_core.AppConfig.load(tmp_path)
    workspace = workspace_core.Workspace(config)
    source = config.data_dir / "ventes.csv"
    source.write_text(
        "mois;revenus;couts\nJanvier;100;60\nFévrier;130;80\nMars;110;72\n",
        encoding="utf-8",
    )
    workspace.refresh()
    file_id = workspace.file_id_by_name(source.name)
    assert file_id

    # Chemin historique (Pandas, via les outils locaux existants).
    legacy = workspace_core.LocalTools(workspace).analyze_table(file_id)

    # Nouveau chemin (DuckDB, via l'adaptateur additif).
    with engine_for_workspace(workspace) as engine:
        modern = analyze_file(engine, source)

    for column in ("revenus", "couts"):
        for key in ("count", "sum", "mean", "median", "min", "max", "std_dev"):
            assert modern["numeric_statistics"][column][key] == pytest.approx(
                legacy["numeric_statistics"][column][key]
            ), f"désaccord {column}.{key}"


def test_source_file_is_never_modified(tmp_path: Path) -> None:
    config = workspace_core.AppConfig.load(tmp_path)
    workspace = workspace_core.Workspace(config)
    source = config.data_dir / "cours.csv"
    source.write_text("date,prix\n2024-01-01,100\n2024-01-02,110\n", encoding="utf-8")
    before = source.read_bytes()

    with engine_for_workspace(workspace) as engine:
        financial_analysis(engine, source, value_column="prix", time_column="date")

    assert source.read_bytes() == before


def test_financial_analysis_through_adapter(tmp_path: Path) -> None:
    config = workspace_core.AppConfig.load(tmp_path)
    workspace = workspace_core.Workspace(config)
    source = config.data_dir / "cours.csv"
    source.write_text(
        "date,prix\n2024-01-01,100\n2024-01-02,110\n2024-01-03,99\n", encoding="utf-8"
    )
    with engine_for_workspace(workspace) as engine:
        report = financial_analysis(engine, source, value_column="prix", time_column="date")
        assert report["total_return"] == pytest.approx(99 / 100 - 1)
        assert "conseil" in report["interpretation"]


def test_cash_flow_analysis_through_adapter(tmp_path: Path) -> None:
    config = workspace_core.AppConfig.load(tmp_path)
    workspace = workspace_core.Workspace(config)
    source = config.data_dir / "flux.csv"
    source.write_text("date,montant\n2023-01-01,-1000\n2024-01-01,1100\n", encoding="utf-8")
    with engine_for_workspace(workspace) as engine:
        metrics = cash_flow_analysis(engine, source, amount_column="montant", date_column="date")
        assert metrics["xirr"] == pytest.approx(0.10, abs=1e-6)


def test_legacy_tools_are_untouched_by_import() -> None:
    """Importer come_data ne doit pas modifier TOOL_SCHEMAS ni LocalTools."""
    assert [schema["name"] for schema in workspace_core.TOOL_SCHEMAS] == [
        "list_workspace_files",
        "inspect_file",
        "analyze_table",
        "search_documents",
        "create_analysis_workbook",
    ]
