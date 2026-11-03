#!/bin/bash
# Lance l'orchestrateur + worktree worker (en arrière-plan)

set -e

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT"

echo "=== LANCEMENT ORCHESTRATEUR ==="

# 1. Vérifier que le venv existe
if [[ ! -x ".venv/bin/python" ]]; then
    echo "ERREUR: .venv/bin/python introuvable. Crée le venv d'abord."
    exit 1
fi

# 2. Créer le dossier messages
mkdir -p messages

# 3. Initialiser from_A.json s'il n'existe pas
if [[ ! -f messages/from_A.json ]]; then
    cat > messages/from_A.json <<'EOF'
{
  "order_id": "",
  "status": "waiting",
  "verifications_done": [],
  "prompt_for_worker": ""
}
EOF
    echo "messages/from_A.json initialisé"
fi

# 3. Initialiser to_A.json
cat > messages/to_A.json <<'EOF'
{
  "from": "orchestrator",
  "to": "agent_A",
  "worker_result": null,
  "completed_at": ""
}
EOF

# 4. Créer les fichiers de communication inter-processus
touch messages/task.json messages/result.json 2>/dev/null || true

# 5. Vérifier opencode
if ! command -v opencode &> /dev/null; then
    echo "ATTENTION: 'opencode' non trouvé dans PATH. Installe-le : npm install -g @openai/codex"
fi

# 5. Lancer l'orchestrateur en arrière-plan
echo "Démarrage orchestrateur.py..."
nohup .venv/bin/python orchestrator.py > orchestrator.log 2>&1 &
ORCH_PID=$!
echo $ORCH_PID > .orchestrator.pid

echo "=== ORCHESTRATEUR DÉMARRÉ (PID: $ORCH_PID) ==="
echo "Logs: tail -f orchestrator.log"
echo "Arrêt: ./stop_all.sh"
echo ""
echo "Pour envoyer une mission, écris dans messages/from_A.json :"
cat <<'EOF'
{
  "order_id": "mission-001",
  "status": "ready_for_worker",
  "verifications_done": ["check1"],
  "prompt_for_worker": "Ton prompt complet pour le worker ici..."
}
EOF