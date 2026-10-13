"""Offline behavioural tests for the bounded V5 local orchestrator."""

from __future__ import annotations

from pathlib import Path

from openpyxl import Workbook

from v5_orchestrator import LocalOrchestrator
from workspace_core import AppConfig, LocalTools, Workspace


class FakeMemory:
    def __init__(self) -> None:
        self.imported: list[Path] = []

    def import_file(self, path: Path, *, project_id: str | None = None, title: str | None = None) -> dict[str, object]:
        self.imported.append(path)
        return {"source_id": "src_demo", "title": title or path.name, "chunk_count": 2, "project_id": project_id}

    def search(self, query: str, *, project_id: str | None = None, limit: int = 8) -> dict[str, object]:
        return {
            "count": 1,
            "results": [
                {
                    "source_id": "src_demo",
                    "source_title": "cours.md",
                    "citation": "cours.md, lignes 1–2",
                    "line_start": 1,
                    "line_end": 2,
                    "excerpt": f"Passage contenant {query}",
                }
            ],
        }


def make_orchestrator(tmp_path: Path) -> tuple[AppConfig, Workspace, LocalOrchestrator, FakeMemory]:
    config = AppConfig.load(tmp_path)
    workspace = Workspace(config)
    memory = FakeMemory()
    return config, workspace, LocalOrchestrator(workspace, LocalTools(workspace), memory), memory


def add_csv(config: AppConfig) -> Path:
    path = config.data_dir / "budget.csv"
    path.write_text("mois;revenus;couts\nJanvier;100;40\nFevrier;120;55\n", encoding="utf-8")
    return path


def test_orchestrator_executes_real_multi_tool_finance_plan_offline(tmp_path: Path) -> None:
    config, workspace, orchestrator, _ = make_orchestrator(tmp_path)
    source = add_csv(config)
    workspace.refresh()
    file_id = workspace.file_id_by_name(source.name)
    assert file_id

    result = orchestrator.run(
        "Analyse financière en profondeur le fichier sélectionné et crée un rapport.",
        selected_file_ids=[file_id],
        allow_write=True,
    )

    assert [event["tool"] for event in result["events"]] == [
        "inspect_file",
        "analyze_table",
        "create_analysis_workbook",
    ]
    assert all(event["status"] == "done" for event in result["events"])
    report = result["events"][-1]["result"]["output_file"]
    assert (config.output_dir / report).is_file()
    assert result["remote_model_used"] is False


def test_orchestrator_keeps_write_blocked_without_explicit_confirmation(tmp_path: Path) -> None:
    config, workspace, orchestrator, _ = make_orchestrator(tmp_path)
    source = add_csv(config)
    workspace.refresh()
    file_id = workspace.file_id_by_name(source.name)
    assert file_id

    result = orchestrator.run("Analyse ce fichier et crée un rapport.", selected_file_ids=[file_id])

    assert result["events"][-1]["tool"] == "create_analysis_workbook"
    assert result["events"][-1]["status"] == "needs_confirmation"
    assert not list(config.output_dir.glob("*.xlsx"))


def test_orchestrator_analyzes_an_excel_workbook_after_sheet_inspection(tmp_path: Path) -> None:
    config, workspace, orchestrator, _ = make_orchestrator(tmp_path)
    source = config.data_dir / "budget.xlsx"
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "Budget"
    sheet.append(["mois", "revenus", "couts"])
    sheet.append(["Janvier", 100, 40])
    sheet.append(["Février", 120, 55])
    workbook.save(source)
    workspace.refresh()
    file_id = workspace.file_id_by_name(source.name)
    assert file_id

    result = orchestrator.run("Analyse financière le fichier sélectionné.", selected_file_ids=[file_id])

    assert [event["tool"] for event in result["events"]] == ["inspect_file", "analyze_table"]
    assert [event["status"] for event in result["events"]] == ["done", "done"]
    assert result["events"][-1]["result"]["numeric_statistics"]["revenus"]["sum"] == 220.0


def test_orchestrator_indexes_and_cites_local_memory_without_model(tmp_path: Path) -> None:
    config, workspace, orchestrator, memory = make_orchestrator(tmp_path)
    course = config.data_dir / "cours.md"
    course.write_text("La VAN actualise les flux futurs.", encoding="utf-8")
    workspace.refresh()
    file_id = workspace.file_id_by_name(course.name)
    assert file_id

    indexed = orchestrator.run(
        "Indexe ce document dans la mémoire.",
        selected_file_ids=[file_id],
        memory_project_id="p_finance",
    )
    searched = orchestrator.run("Cherche \"VAN\" dans ma mémoire.")

    assert memory.imported == [course]
    assert any(event["tool"] == "index_memory" and event["status"] == "done" for event in indexed["events"])
    assert searched["citations"] == [
        {
            "source_id": "src_demo",
            "source_title": "cours.md",
            "citation": "cours.md, lignes 1–2",
            "line_start": 1,
            "line_end": 2,
            "excerpt": "Passage contenant VAN",
        }
    ]
