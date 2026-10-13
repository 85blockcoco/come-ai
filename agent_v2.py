import os
import json
from pathlib import Path

import pandas as pd
from openpyxl import load_workbook
from google import genai


# ============================================================
# CONFIGURATION
# ============================================================

BASE_DIR = Path(__file__).parent
DATA_DIR = BASE_DIR / "data"
OUTPUT_DIR = BASE_DIR / "output"

DATA_DIR.mkdir(exist_ok=True)
OUTPUT_DIR.mkdir(exist_ok=True)

client = genai.Client(
    api_key=os.environ["GEMINI_API_KEY"]
)

MODEL = "gemini-3.8-flash"


# ============================================================
# OUTILS EXCEL
# ============================================================

def list_files():
    """Liste les fichiers Excel disponibles."""

    files = list(DATA_DIR.glob("*.xlsx"))

    return [
        {
            "name": file.name,
            "path": str(file)
        }
        for file in files
    ]


def inspect_excel(filename):
    """Inspecte la structure d'un fichier Excel."""

    path = DATA_DIR / filename

    if not path.exists():
        return {
            "error": f"Fichier introuvable : {filename}"
        }

    try:
        excel = pd.ExcelFile(path)

        result = {
            "file": filename,
            "sheets": {}
        }

        for sheet in excel.sheet_names:

            df = pd.read_excel(
                path,
                sheet_name=sheet
            )

            result["sheets"][sheet] = {
                "rows": len(df),
                "columns": len(df.columns),
                "columns_names": list(df.columns),
                "missing_values": df.isna().sum().to_dict(),
                "preview": df.head(10).to_dict(
                    orient="records"
                )
            }

        return result

    except Exception as e:

        return {
            "error": str(e)
        }


def analyze_excel(filename, sheet_name=None):
    """Effectue une analyse statistique d'un fichier Excel."""

    path = DATA_DIR / filename

    if not path.exists():
        return {
            "error": f"Fichier introuvable : {filename}"
        }

    try:

        df = pd.read_excel(
            path,
            sheet_name=sheet_name
        )

        numeric = df.select_dtypes(
            include="number"
        )

        analysis = {
            "file": filename,
            "rows": len(df),
            "columns": len(df.columns),
            "numeric_columns": list(numeric.columns),
            "statistics": numeric.describe().round(2).to_dict(),
            "missing_values": df.isna().sum().to_dict()
        }

        return analysis

    except Exception as e:

        return {
            "error": str(e)
        }


def create_excel_copy(filename):
    """Crée une copie du fichier dans output."""

    source = DATA_DIR / filename

    if not source.exists():
        return {
            "error": f"Fichier introuvable : {filename}"
        }

    destination = OUTPUT_DIR / f"analysed_{filename}"

    try:

        workbook = load_workbook(source)

        workbook.save(destination)

        return {
            "success": True,
            "output_file": str(destination)
        }

    except Exception as e:

        return {
            "error": str(e)
        }


# ============================================================
# OUTILS DISPONIBLES POUR GEMINI
# ============================================================

tools = [

    {
        "name": "list_files",
        "description": (
            "Liste les fichiers Excel disponibles "
            "dans le dossier data."
        ),
        "parameters": {}
    },

    {
        "name": "inspect_excel",
        "description": (
            "Inspecte un fichier Excel : feuilles, "
            "dimensions, colonnes, valeurs manquantes "
            "et aperçu des données."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "filename": {
                    "type": "string"
                }
            },
            "required": ["filename"]
        }
    },

    {
        "name": "analyze_excel",
        "description": (
            "Effectue une analyse statistique "
            "des colonnes numériques d'un fichier Excel."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "filename": {
                    "type": "string"
                },
                "sheet_name": {
                    "type": "string"
                }
            },
            "required": ["filename"]
        }
    },

    {
        "name": "create_excel_copy",
        "description": (
            "Crée une copie d'un fichier Excel "
            "dans le dossier output."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "filename": {
                    "type": "string"
                }
            },
            "required": ["filename"]
        }
    }
]


# ============================================================
# AGENT
# ============================================================

def ask_agent(question):

    available_files = list_files()

    prompt = f"""
Tu es un analyste financier travaillant avec Excel.

Tu disposes des outils suivants :

1. list_files
2. inspect_excel
3. analyze_excel
4. create_excel_copy

Fichiers actuellement disponibles :

{json.dumps(
    available_files,
    ensure_ascii=False,
    indent=2
)}

Demande de l'utilisateur :

{question}

Tu dois :

- comprendre précisément la demande ;
- utiliser les outils disponibles lorsque nécessaire ;
- ne jamais inventer de données ;
- expliquer clairement les résultats ;
- signaler lorsqu'une information manque.

Si la demande nécessite une modification complexe du fichier,
indique quelles opérations supplémentaires seraient nécessaires.
"""

    response = client.models.generate_content(
        model=MODEL,
        contents=prompt
    )

    return response.text


# ============================================================
# INTERFACE
# ============================================================

print()
print("==========================================")
print("        AI EXCEL AGENT — V2")
print("==========================================")
print()
print("Fichiers Excel :")
print(DATA_DIR)
print()
print("Fichiers de sortie :")
print(OUTPUT_DIR)
print()
print("Tape 'quit' pour quitter.")
print()

while True:

    question = input("🤖 Que veux-tu faire ? ")

    if question.lower() in [
        "quit",
        "exit",
        "q"
    ]:
        break

    print()

    try:

        answer = ask_agent(question)

        print(answer)

    except Exception as e:

        print("❌ Erreur :", e)

    print()
