#!/bin/zsh
PROMPT="Clôture uniquement : ne lance aucune nouvelle optimisation. (1) Termine la suite complète en cours. (2) Commit si l'arbre est modifié. (3) git push -u origin codex/v3-stable-consolidation (jamais --force, jamais main, aucun merge). (4) Prouve : git ls-remote --heads origin codex/v3-stable-consolidation + git log --oneline -3 origin/codex/v3-stable-consolidation + résultat brut de la suite (passed/failed/skipped, durée). (5) Rapport 10 lignes max : SHA, tests, durée, fichiers, risques. Si un rouge résiste >15 min : commit, pousse, écris-le noir sur blanc. Aucun vert sans preuve, aucune donnée personnelle."
cd "/Users/comedelavenne/Documents/Codex/2026-10-25/codex-op-ration-v3-stable-consolidation/candidate-worktree" || exit 1
for i in $(seq 1 120); do
  echo "[$(date +%H:%M:%S)] tentative $i"
  OUT=$(codex exec resume 01a1706f-a5d6-7850-a50d-6b05e3a1e2ee "$PROMPT" 2>&1)
  if echo "$OUT" | grep -q "already has an active writer"; then
    sleep 45; continue
  fi
  echo "[$(date +%H:%M:%S)] === ENVOYÉ ==="
  echo "$OUT"
  break
done
