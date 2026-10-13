"""Vérifications sans appel réseau ni clé API.

Exécuter : .venv/bin/python test_v3_offline.py
"""

import tempfile
from pathlib import Path

from workspace_core import AppConfig, LocalTools, Workspace


with tempfile.TemporaryDirectory() as temporary:
    root = Path(temporary)
    config = AppConfig.load(root)
    workspace = Workspace(config)
    csv_file = config.data_dir / "ventes.csv"
    csv_file.write_text("mois;revenus;couts\nJanvier;100;60\nFévrier;130;80\n", encoding="utf-8")
    workspace.refresh()
    file_id = workspace.file_id_by_name("ventes.csv")
    assert file_id
    tools = LocalTools(workspace)
    inspected = tools.inspect_file(file_id)
    assert inspected["columns"] == 3
    analysis = tools.analyze_table(file_id)
    assert analysis["numeric_statistics"]["revenus"]["sum"] == 230.0
    report = tools.create_analysis_workbook(file_id)
    assert (config.output_dir / report["output_file"]).exists()

print("OK — import CSV, inspection, analyse et rapport Excel vérifiés sans IA.")
