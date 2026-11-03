#!/bin/bash
# Lance tout : worktree + orchestrateur + mission_driver
# Usage: ./launch_full_auto.sh

set -e

PROJECT_DIR="/Users/comedelavenne/AI-Excel-Agent"
cd "$PROJECT_DIR"

echo "🔧 Création worktree worker..."
opencode worktree_create --name agent-worker 2>/dev/null || echo "Worktree existe déjà"

echo "📁 Préparation messages/"
mkdir -p messages
[ -f messages/result.json ] || echo '[]' > messages/result.json

echo "🤖 Lancement orchestrateur (relais A ↔ Worker)..."
nohup python3 orchestrator.py > orchestrator.log 2>&1 &
ORCH_PID=$!
echo $ORCH_PID > .orchestrator.pid

echo "🎯 Lancement Mission Driver (enchaînement missions 01→13)..."
nohup python3 mission_driver.py > mission_driver.log 2>&1 &
DRIVER_PID=$!
echo $DRIVER_PID > .mission_driver.pid

echo ""
echo "✅ TOUT EST LANCÉ EN BACKGROUND"
echo "   Orchestrateur PID: $ORCH_PID (logs: orchestrator.log)"
echo "   Mission Driver  PID: $DRIVER_PID (logs: mission_driver.log)"
echo ""
echo "📊 Surveiller :"
echo "   tail -f orchestrator.log"
echo "   tail -f mission_driver.log"
echo "   cat missions_registry.json | jq '.missions[] | {id, title, status}'"
echo ""
echo "🛑 Arrêt complet : ./stop_all.sh"
echo ""
echo "😴 DORS. Les missions s'enchaînent toutes seules : 07 → 08 → 04 → 11 → 13 → 10..."