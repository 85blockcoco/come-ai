#!/bin/bash
# Côme IA Career — démarrage sur Mac (double-clic ou ./demarrer_come_ai_mac.command)
# Installe les dépendances dans un environnement isolé puis ouvre l'app locale.
# Aucune donnée ne quitte la machine. Aucune candidature n'est jamais envoyée.
set -e
cd "$(dirname "$0")/.."

echo ""
echo "  Côme IA Career — installation locale"
echo "  ------------------------------------"

if ! command -v python3 >/dev/null 2>&1; then
  echo "  Python 3 est absent. Installe-le depuis https://www.python.org/downloads/macos/"
  echo "  (ou via Homebrew : brew install python@3.12)"
  read -r -p "  Appuie sur Entrée pour fermer." _
  exit 1
fi

if [ ! -d ".venv" ]; then
  echo "  1/3 Création de l'environnement Python isolé..."
  python3 -m venv .venv
fi
# shellcheck disable=SC1091
source .venv/bin/activate

echo "  2/3 Installation des dépendances (une seule fois, ~2 min)..."
python3 -m pip install -q --upgrade pip
python3 -m pip install -q -r requirements-v3.txt

echo "  3/3 Démarrage du service local..."
python3 -m uvicorn come_ai_web:create_app --factory --host 127.0.0.1 --port 8747 &
SERVER_PID=$!
trap 'kill $SERVER_PID 2>/dev/null' EXIT

for _ in 1 2 3 4 5 6 7 8 9 10 11 12 13 14 15; do
  if curl -s -o /dev/null "http://127.0.0.1:8747/api/career/health" --max-time 2; then
    break
  fi
  sleep 1
done

echo ""
echo "  Prêt : http://127.0.0.1:8747/career"
echo "  (Garde cette fenêtre ouverte. Ctrl+C pour arrêter.)"
echo ""
open "http://127.0.0.1:8747/career" || true
wait $SERVER_PID
