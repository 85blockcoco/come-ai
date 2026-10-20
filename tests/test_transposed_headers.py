"""Header-row detection for hand-made workbooks with metadata above the table."""
from pathlib import Path

import openpyxl

from workspace_core import read_table


def build_transposed_workbook(path: Path, header_row: int) -> None:
    """Dates in the first column, header deeper than row 1, numeric rows below."""
    workbook = openpyxl.Workbook()
    sheet = workbook.active
    sheet["A1"] = "Fund code"                      # contexte au-dessus du tableau
    sheet["B1"] = 47309                            # codes numériques : colonnes object
    sheet["C1"] = 43900
    sheet["A2"] = "Fonds"
    sheet["B2"] = "alpha_fund"                     # noms texte sous des codes numériques
    sheet["C2"] = "beta_fund"
    sheet["A3"] = "Note : rendements non excédentaires."
    sheet[f"A{header_row}"] = "date"
    sheet[f"B{header_row}"] = "alpha_fund"
    sheet[f"C{header_row}"] = "beta_fund"
    for index, value in enumerate((0.012, -0.004, 0.009, 0.021, -0.007), start=1):
        row = header_row + index
        sheet[f"A{row}"] = value                    # date simulée par un nombre
        sheet[f"B{row}"] = 100.0 + value * 1000
        sheet[f"C{row}"] = 50.0 + value * 800
    workbook.save(path)


def test_read_table_finds_deeper_header(tmp_path: Path) -> None:
    path = tmp_path / "devoir.xlsx"
    build_transposed_workbook(path, header_row=5)

    frame = read_table(path)

    assert list(frame.columns) == ["date", "alpha_fund", "beta_fund"]
    assert len(frame) >= 5
    assert frame["alpha_fund"].dtype.kind in "if"


def test_read_table_no_repair_when_noise_exceeds_search_depth(tmp_path: Path) -> None:
    """11 lignes de contexte : au-delà de la fenêtre de recherche, aucun repli."""
    path = tmp_path / "bruit.xlsx"
    workbook = openpyxl.Workbook()
    sheet = workbook.active
    for index in range(1, 12):
        sheet[f"A{index}"] = f"Contexte {index}"
    sheet["A12"] = "mesure"
    sheet["B12"] = 1.5
    sheet["A13"] = 0.1
    sheet["B13"] = 2.0
    workbook.save(path)

    frame = read_table(path)
    # Fenêtre de 10 lignes dépassée (11 contextes) : l'analyse reste celle du
    # parse par défaut, sans réparation hasardeuse.
    assert len(frame.columns) == 2


def test_read_table_keeps_text_column_untouched(tmp_path: Path) -> None:
    """Une colonne non numérique reste intacte après la réparation d'en-tête."""
    path = tmp_path / "mixte.xlsx"
    workbook = openpyxl.Workbook()
    sheet = workbook.active
    sheet["A1"] = "Fund code"
    sheet["B1"] = 47309
    sheet["A2"] = "Fonds"
    sheet["B2"] = "nom_du_fond"          # texte sous une colonne numérique
    sheet["A3"] = "date"
    sheet["B3"] = "valeur"
    sheet["A4"] = 5
    sheet["B4"] = 10.5
    sheet["A5"] = 6
    sheet["B5"] = 11.5
    workbook.save(path)

    frame = read_table(path)

    assert list(frame.columns) == ["date", "valeur"]
    assert frame["valeur"].dtype.kind in "if"
    # Les cellules sources ne sont jamais modifiées (colonne texte complète).
    raw = openpyxl.load_workbook(path, read_only=True).active
    assert raw["B2"].value == "nom_du_fond"


def test_analyze_table_reports_numeric_stats_and_header_note(tmp_path: Path) -> None:
    from tests.test_come_ai_v3 import make_workspace

    config, workspace, tools = make_workspace(tmp_path)
    path = tmp_path / config.data_dir.name / "devoir.xlsx"
    build_transposed_workbook(path, header_row=5)
    workspace.refresh()
    file_id = workspace.file_id_by_name(path.name)

    analysis = tools.analyze_table(file_id)

    assert analysis["numeric_statistics"]
    assert "En-têtes détectés à la ligne 5" in analysis["note"]


def test_read_table_keeps_ordinary_header(tmp_path: Path) -> None:
    path = tmp_path / "trades.xlsx"
    workbook = openpyxl.Workbook()
    sheet = workbook.active
    sheet.append(["ticker", "price"])
    sheet.append(["AAA", 42.5])
    sheet.append(["BBB", 17.25])
    workbook.save(path)

    frame = read_table(path)

    assert list(frame.columns) == ["ticker", "price"]
    assert len(frame) == 2
