#!/bin/bash
cd /Users/comedelavenne/AI-Excel-Agent

echo "🛑 Arrêt de tout..."

if [ -f .orchestrator.pid ]; then
    PID=$(cat .orchestrator.pid)
    kill $PID 2>/dev/null && echo "   Orchestrateur arrêté (PID: $PID)"
    rm .orchestrator.pid
fi

if [ -f .mission_driver.pid ]; then
    PID=$(cat .mission_driver.pid)
    kill $PID 2>/dev/null && echo "   Mission Driver arrêté (PID: $PID)"
    rm .mission_driver.pid
fi

# Nettoyer subagents workers orphelins
pkill -f "opencode subagent.*background" 2>/dev/null && echo "   Subagents workers nettoyés"

echo "✅ Tout arrêté."