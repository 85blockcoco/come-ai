#!/bin/zsh
# Nom historique conservé : ce lanceur ouvre désormais l'interface web
# Côme AI V3. Le programme Tkinter app_v3.py reste disponible séparément.
cd "$(dirname "$0")"
exec .venv/bin/python run_come_ai_v3.py
