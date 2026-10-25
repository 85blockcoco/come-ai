"""Fabriques de données **synthétiques** pour les tests de ``come_excel``.

Aucune donnée réelle n'est lue : tous les classeurs/CSV sont créés à la volée.
Ce fichier ne contient pas de fonction ``test_*`` et n'est donc pas collecté.
"""

from __future__ import annotations

from pathlib import Path

from openpyxl import Workbook
from openpyxl.workbook.defined_name import DefinedName


def write_workbook(path: Path, sheets: dict[str, list[list[object]]]) -> Path:
    """Écrit un ``.xlsx`` avec une ou plusieurs feuilles."""
    workbook = Workbook()
    default = workbook.active
    workbook.remove(default)
    for name, rows in sheets.items():
        worksheet = workbook.create_sheet(title=name)
        for row in rows:
            worksheet.append(row)
    workbook.save(path)
    return path


def write_budget_workbook(path: Path) -> Path:
    """Classeur réaliste : 2 feuilles, formules, fusion, nom défini."""
    workbook = Workbook()
    budget = workbook.active
    budget.title = "Budget"
    budget.append(["poste", "2023", "2024"])
    budget.append(["Chiffre d'affaires", 1000, 1100])
    budget.append(["Charges", 600, "=B2*1.05"])
    budget.append(["Resultat", "=B2-B3", "=C2-C3"])
    budget.merge_cells("A6:B6")
    budget["A6"] = "Total"
    notes = workbook.create_sheet("Notes")
    notes.append(["commentaire"])
    notes.append(["Budget prévisionnel synthétique"])
    workbook.defined_names.add(DefinedName("Taux_Croissance", attr_text="Budget!$C$2"))
    workbook.save(path)
    return path


def write_csv(path: Path, text: str, *, encoding: str = "utf-8") -> Path:
    path.write_text(text, encoding=encoding)
    return path


def monthly_sales(prefix: str, amounts: list[float], *, extra: dict[str, float] | None = None) -> str:
    """CSV synthétique ``poste;montant`` (séparateur point-virgule)."""
    lines = ["poste;montant"]
    for index, amount in enumerate(amounts, start=1):
        lines.append(f"{prefix}{index};{amount}")
    return "\n".join(lines) + "\n"
