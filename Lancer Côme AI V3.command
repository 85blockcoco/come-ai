#!/bin/zsh
# Double-cliquer ce fichier dans Finder pour démarrer l'interface web locale.
set -e
cd "$(dirname "$0")"

if [[ ! -x ".venv/bin/python" ]]; then
  echo "Le venv .venv est introuvable dans ce dossier."
  echo "Installe d'abord les dépendances indiquées dans README_COME_AI_V3.md."
  read -k 1 "?Appuie sur une touche pour fermer."
  exit 1
fi

exec .venv/bin/python run_come_ai_v3.py
