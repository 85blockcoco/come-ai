import os
import json
from pathlib import Path

import pandas as pd
from google import genai


# =========================
# Configuration
# =========================

client = genai.Client(
    api_key=os.environ["GEMINI_API_KEY"]
)

MODEL = "gemini-3.8-flash"

BASE_DIR = Path(__file__).parent
DATA_DIR = BASE_DIR / "data"

DATA_DIR.mkdir(exist_ok=True)


# =========================
# Lecture des fichiers Excel
# =========================

def inspect_excel(file_path):
    """Analyse la structure et le contenu d'un fichier Excel."""

    path = Path(file_path)

    if not path.exists():
        return {"error": f"Fichier introuvable : {file_path}"}

    try:
        excel = pd.ExcelFile(path)

        result = {
            "file": path.name,
            "sheets": {}
        }

        for sheet in excel.sheet_names:
            df = pd.read_excel(path, sheet_name=sheet)

            result["sheets"][sheet] = {
                "rows": len(df),
                "columns": len(df.columns),
                "column_names": list(df.columns),
                "preview": df.head(5).to_dict(orient="records")
            }

        return result

    except Exception as e:
        return {"error": str(e)}


# =========================
# Agent
# =========================

def ask_agent(question):

    files = list(DATA_DIR.glob("*.xlsx"))

    context = []

    for file in files:
        analysis = inspect_excel(file)
        context.append(analysis)

    prompt = f"""
Tu es un analyste financier travaillant avec des fichiers Excel.

Voici les fichiers disponibles dans ton environnement :

{json.dumps(context, ensure_ascii=False, indent=2, default=str)}

Demande de l'utilisateur :

{question}

Analyse les données disponibles et réponds précisément.

Si la demande nécessite un calcul, explique brièvement la méthode
et donne le résultat.

Si les données disponibles sont insuffisantes, indique exactement
ce qui manque.
"""

    interaction = client.interactions.create(
        model=MODEL,
        input=prompt
    )

    return interaction.output_text


# =========================
# Interface
# =========================

print()
print("======================================")
print("       AI EXCEL AGENT")
print("======================================")
print()
print("Dépose tes fichiers .xlsx dans :")
print(DATA_DIR)
print()
print("Tape 'quit' pour quitter.")
print()

while True:

    question = input("🤖 Que veux-tu analyser ? ")

    if question.lower() in ["quit", "exit", "q"]:
        break

    print()
    print(ask_agent(question))
    print()
