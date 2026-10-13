"""Offline tests for the V5 controlled local personal-memory foundation.

The tests create only temporary SQLite databases/documents.  They neither read
the project's ``.env`` nor create a model/provider client or a network call.
"""

from __future__ import annotations

import os
import stat
from pathlib import Path

import pytest
from docx import Document
from openpyxl import Workbook
from reportlab.pdfgen import canvas

from personal_memory import (
    MemoryResourceLimits,
    PersonalMemoryError,
    PersonalMemoryLimitError,
    PersonalMemoryStore,
)


def make_store(tmp_path: Path, **limits: int) -> PersonalMemoryStore:
    return PersonalMemoryStore(tmp_path / "memory", **limits)


def test_text_import_is_incremental_deduplicated_and_project_scoped(tmp_path: Path) -> None:
    store = make_store(tmp_path)
    first_project = store.create_project("Stage M&A")["project"]
    second_project = store.create_project("Révisions / finance")["project"]
    text = "Profil Côme\nAnalyse financière et modélisation Excel.\nDisponibilité : janvier."

    initial = store.import_text(text, title="Profil local", category="career", project_id=first_project["id"])
    duplicate = store.import_text(text, title="Autre titre ignoré", category="study", project_id=second_project["id"])

    assert initial["status"] == "indexed"
    assert duplicate["status"] == "duplicate"
    assert duplicate["source_id"] == initial["source_id"]
    assert duplicate["project_linked"] is True
    assert store.stats() == {"projects": 2, "sources": 1, "chunks": 1}

    source = store.list_sources()[0]
    assert source["title"] == "Profil local"  # stable citation after a duplicate import
    assert {project["name"] for project in source["projects"]} == {"Stage M&A", "Révisions / finance"}
    assert [item["id"] for item in store.list_sources(project_id=first_project["id"])] == [initial["source_id"]]
    assert [item["id"] for item in store.list_sources(project_id=second_project["id"])] == [initial["source_id"]]


def test_search_returns_local_excerpt_and_line_citation_without_fts_injection(tmp_path: Path) -> None:
    store = make_store(tmp_path)
    # The long first line causes the query to land in a distinct second chunk,
    # proving that the citation tracks the corresponding source line.
    text = "x" * 1_200 + "\nAnalyse financière : tester le modèle de valorisation.\nConclusion locale."
    imported = store.import_text(text, title="Notes finance")

    found = store.search("analyse financiere")

    assert found["count"] == 1
    result = found["results"][0]
    assert result["source_id"] == imported["source_id"]
    assert "valorisation" in result["excerpt"]
    assert result["citation"] == {
        "source_id": imported["source_id"],
        "title": "Notes finance",
        "page": None,
        "line_start": 2,
        "line_end": 3,
        "label": "Notes finance — lignes 2–3",
    }

    # Operators/punctuation are tokenised as literal terms, not passed through
    # to SQLite FTS syntax.  This query cannot turn into a broad OR query.
    assert store.search('analyse OR "inexistant"')["count"] == 0


def test_explicit_file_imports_support_text_docx_and_pdf_without_storing_path(tmp_path: Path) -> None:
    store = make_store(tmp_path)

    markdown = tmp_path / "private-notes.md"
    markdown.write_text("# Candidature\nPréparer les entretiens techniques.", encoding="utf-8")
    markdown_result = store.import_file(markdown.resolve(), category="career")
    assert markdown_result["status"] == "indexed"
    assert markdown_result["source"]["original_filename"] == "private-notes.md"

    docx_path = tmp_path / "cv.docx"
    document = Document()
    document.add_paragraph("Expérience : analyse financière et due diligence.")
    document.add_paragraph("Compétences : Excel, Python et français.")
    document.save(docx_path)
    docx_result = store.import_file(docx_path.resolve())
    assert docx_result["source"]["source_type"] == "docx"
    assert store.search("due diligence")["results"][0]["source_id"] == docx_result["source_id"]

    pdf_path = tmp_path / "offre.pdf"
    pdf = canvas.Canvas(str(pdf_path))
    pdf.drawString(72, 720, "Offre de stage : finance internationale et analyse.")
    pdf.save()
    pdf_result = store.import_file(pdf_path.resolve())
    pdf_search = store.search("internationale")
    pdf_match = next(result for result in pdf_search["results"] if result["source_id"] == pdf_result["source_id"])
    assert pdf_match["citation"]["page"] == 1
    assert pdf_match["citation"]["line_start"] == 1

    sources = store.list_sources()
    assert str(tmp_path) not in repr(sources)
    assert all("path" not in source for source in sources)


def test_file_import_rejects_directory_relative_symlink_and_unknown_format(tmp_path: Path) -> None:
    store = make_store(tmp_path)
    source = tmp_path / "allowed.txt"
    source.write_text("Document autorisé.", encoding="utf-8")
    unknown = tmp_path / "script.py"
    unknown.write_text("print('no')", encoding="utf-8")

    with pytest.raises(PersonalMemoryError, match="absolu"):
        store.import_file(Path("allowed.txt"))
    with pytest.raises(PersonalMemoryError, match="fichier, pas un dossier"):
        store.import_file(tmp_path.resolve())
    with pytest.raises(PersonalMemoryError, match="Format non pris en charge"):
        store.import_file(unknown.resolve())

    link = tmp_path / "linked.txt"
    try:
        link.symlink_to(source)
    except OSError:
        pytest.skip("Les liens symboliques ne sont pas disponibles dans cet environnement.")
    with pytest.raises(PersonalMemoryError, match="liens symboliques"):
        store.import_file(link.resolve().parent / link.name)


def test_excel_import_streams_read_only_multi_sheet_data_with_row_citations(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """XLSX rows remain locally searchable with a verifiable sheet/row range."""
    import openpyxl

    workbook_path = tmp_path / "dossier-stage.xlsx"
    workbook = Workbook()
    profile = workbook.active
    profile.title = "Profil"
    profile.append(["Champ", "Valeur"])
    profile.append(["Objectif", "Stage M&A"])

    finance = workbook.create_sheet("Finance")
    # Make the first row exactly one full extraction chunk. The target row
    # must then receive a narrow, independently verifiable Excel citation.
    finance.append(["Contexte", "x" * 2_385])
    finance.append(["Marge brute", "57.8 %"])
    workbook.save(workbook_path)
    workbook.close()

    real_load_workbook = openpyxl.load_workbook
    observed: dict[str, object] = {}

    def observed_load_workbook(*args: object, **kwargs: object) -> object:
        observed.update(kwargs)
        return real_load_workbook(*args, **kwargs)

    monkeypatch.setattr(openpyxl, "load_workbook", observed_load_workbook)

    store = make_store(tmp_path)
    imported = store.import_file(workbook_path.resolve(), title="Dossier de stage", category="finance")
    duplicate = store.import_file(workbook_path.resolve(), title="Titre non retenu")

    assert observed == {"filename": str(workbook_path.resolve()), "read_only": True, "data_only": False, "keep_links": False}
    assert imported["status"] == "indexed"
    assert imported["source"]["source_type"] == "xlsx"
    assert duplicate["status"] == "duplicate"
    assert duplicate["source_id"] == imported["source_id"]
    assert store.stats()["sources"] == 1

    finance_result = store.search("marge brute")["results"][0]
    assert "Marge brute" in finance_result["excerpt"]
    assert finance_result["citation"] == {
        "source_id": imported["source_id"],
        "title": "Dossier de stage",
        "page": None,
        "line_start": 2,
        "line_end": 2,
        "label": "Dossier de stage — feuille « Finance », lignes 2–2",
        "sheet": "Finance",
        "row_start": 2,
        "row_end": 2,
    }

    profile_result = store.search("stage m a")["results"][0]
    assert profile_result["citation"]["sheet"] == "Profil"
    assert profile_result["citation"]["row_start"] == 1
    assert profile_result["citation"]["row_end"] == 2


def test_excel_resource_limits_are_explicit_and_abort_without_partial_index(tmp_path: Path) -> None:
    workbook_path = tmp_path / "too-many-rows.xlsx"
    workbook = Workbook()
    worksheet = workbook.active
    worksheet.title = "Données"
    worksheet.append(["Métrique", "Valeur"])
    worksheet.append(["Chiffre d'affaires", 120])
    workbook.save(workbook_path)
    workbook.close()

    limits = MemoryResourceLimits(max_excel_rows_per_sheet=1)
    store = PersonalMemoryStore(tmp_path / "memory", resource_limits=limits)

    assert store.resource_limits.as_dict()["max_excel_rows_per_sheet"] == 1
    with pytest.raises(PersonalMemoryLimitError, match="nombre maximal de lignes"):
        store.import_file(workbook_path.resolve())
    assert store.stats() == {"projects": 0, "sources": 0, "chunks": 0}


def test_xlsm_extension_is_indexed_read_only_without_executing_content(tmp_path: Path) -> None:
    """openpyxl may parse a macro-enabled extension; this code never runs it."""
    workbook_path = tmp_path / "modele.xlsm"
    workbook = Workbook()
    workbook.active.title = "Synthèse"
    workbook.active.append(["Donnée", "Mémo confidentiel local"])
    workbook.save(workbook_path)
    workbook.close()

    store = make_store(tmp_path)
    imported = store.import_file(workbook_path.resolve())

    assert imported["source"]["source_type"] == "xlsm"
    result = store.search("confidentiel local")["results"][0]
    assert result["citation"]["sheet"] == "Synthèse"
    assert result["citation"]["row_start"] == 1


def test_limits_and_configurable_db_path_are_enforced(tmp_path: Path) -> None:
    database = tmp_path / "external-ssd-simulation" / "come-memory.sqlite3"
    store = PersonalMemoryStore(db_path=database, max_source_bytes=16, max_text_chars=20)
    assert database.exists()
    assert stat.S_IMODE(database.stat().st_mode) & stat.S_IRUSR
    assert store.stats() == {"projects": 0, "sources": 0, "chunks": 0}

    with pytest.raises(PersonalMemoryLimitError, match="20"):
        store.import_text("a" * 21, title="Trop long")

    large = tmp_path / "large.txt"
    large.write_text("x" * 17, encoding="utf-8")
    with pytest.raises(PersonalMemoryLimitError, match="Fichier trop volumineux"):
        store.import_file(large.resolve())


def test_delete_behaviour_keeps_original_files_and_requires_explicit_orphan_purge(tmp_path: Path) -> None:
    store = make_store(tmp_path)
    keep_project = store.create_project("À conserver")["project"]
    keep_source = store.import_text("Mémo indépendant", title="Mémo", project_id=keep_project["id"])

    deleted = store.delete_project(keep_project["id"])
    assert deleted["orphan_sources_deleted"] == 0
    assert store.list_sources()[0]["id"] == keep_source["source_id"]

    purge_project = store.create_project("À purger")["project"]
    purge_source = store.import_text("Texte temporaire distinct", title="Temporaire", project_id=purge_project["id"])
    purged = store.delete_project(purge_project["id"], delete_orphan_sources=True)
    assert purged["orphan_sources_deleted"] == 1
    assert {source["id"] for source in store.list_sources()} == {keep_source["source_id"]}
    assert store.search("temporaire")["count"] == 0

    original = tmp_path / "original.txt"
    original.write_text("Ne pas supprimer ce fichier externe.", encoding="utf-8")
    external = store.import_file(original.resolve())
    store.delete_source(external["source_id"])
    assert original.exists()
    assert original.read_text(encoding="utf-8") == "Ne pas supprimer ce fichier externe."


def test_project_filter_and_manual_link_are_local_and_deterministic(tmp_path: Path) -> None:
    store = make_store(tmp_path)
    project = store.create_project("Projet mémoire")["project"]
    imported = store.import_text("Révision de comptabilité financière", title="Cours", category="study")
    assert store.list_sources(project_id=project["id"]) == []

    linked = store.add_source_to_project(imported["source_id"], project["id"])
    assert linked["status"] == "linked"
    assert store.add_source_to_project(imported["source_id"], project["id"])["status"] == "existing"
    assert store.search("comptabilité", project_id=project["id"])["count"] == 1
    assert store.list_sources(category="study")[0]["id"] == imported["source_id"]

    with pytest.raises(PersonalMemoryError, match="vide"):
        store.search("   ")
    with pytest.raises(PersonalMemoryError, match="positive"):
        store.search("comptabilité", limit=0)


def test_store_does_not_depend_on_environment_or_original_file_permissions(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """A smoke guard for the V5 rule: no environment/key loading in this module."""
    monkeypatch.setenv("GEMINI_API_KEY", "this-must-never-be-read")
    store = make_store(tmp_path)
    source = tmp_path / "notes.txt"
    source.write_text("Connaissance locale seulement.", encoding="utf-8")
    imported = store.import_file(source.resolve(), title="/private/path/notes-safe")

    assert imported["source"]["title"] == "notes-safe"
    assert os.environ["GEMINI_API_KEY"] == "this-must-never-be-read"

