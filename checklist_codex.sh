#!/usr/bin/env bash
# CÔME AI — CHECKLIST CODEX EXÉCUTABLE (script de validation)
# Usage : ./checklist_codex.sh [main|memory|career|study-coach|all]
# Défaut : all

# Portabilité : tout est résolu depuis la racine du dépôt (aucun chemin utilisateur en dur).
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENV_PY="${VENV_PY:-$ROOT/.venv/bin/python}"
MAIN_ROOT="${MAIN_ROOT:-$ROOT}"
MEM_ROOT="${MEM_ROOT:-$ROOT/../AI-Excel-Agent-memory}"
CAREER_ROOT="${CAREER_ROOT:-$ROOT/../AI-Excel-Agent-career}"
STUDY_ROOT="${STUDY_ROOT:-$ROOT/../AI-Excel-Agent-study-coach}"

RED='\033[0;31m'
GRN='\033[0;32m'
YLW='\033[1;33m'
NC='\033[0m'

ok()   { echo -e "${GRN}✓${NC} $*"; }
fail() { echo -e "${RED}✗${NC} $*"; EXIT=1; }
warn() { echo -e "${YLW}!${NC} $*"; }

EXIT=0

# Vérification du venv avant toute chose
if [ ! -x "$VENV_PY" ]; then
  fail "venv introuvable : $VENV_PY (créer .venv ou définir VENV_PY)"
  echo -e "\n${RED}ÉCHEC(S)${NC}"
  exit 1
fi

run_main() {
  echo "=== 1. Référence main ==="
  cd "$MAIN_ROOT"
  HEAD=$(git log --oneline -1)
  echo "HEAD: $HEAD"
  # pipefail actif : le code de sortie de pytest n'est plus masqué par tail.
  if ! $VENV_PY -m pytest -q 2>&1 | tail -3; then
    fail "tests main en échec"
  else
    ok "main tests passés"
  fi
}

run_memory() {
  echo "=== 2. Worktree mémoire : importabilité ==="
  if [ ! -d "$MEM_ROOT" ]; then
    warn "worktree mémoire absent ($MEM_ROOT) — étape ignorée"
    return 0
  fi
  cd "$MEM_ROOT"
  $VENV_PY -m py_compile come_ai_web.py personal_memory.py || fail "py_compile échoue"
  $VENV_PY -c "from come_ai_web import create_app; print('IMPORT OK')" || fail "import create_app échoue"
  ok "import OK"
}

run_routes() {
  echo "=== 3. Endpoints profil : pas de doublon, import != 500 ==="
  if [ ! -d "$MEM_ROOT" ]; then
    warn "worktree mémoire absent — étape ignorée"
    return 0
  fi
  cd "$MEM_ROOT"
  $VENV_PY - <<'PY'
import tempfile, pathlib, sys
from fastapi.testclient import TestClient
from come_ai_web import create_app
tmp = pathlib.Path(tempfile.mkdtemp())
app = create_app(tmp)
seen = {}
for r in app.routes:
    if getattr(r, "path", "").startswith("/api/v5/profile"):
        seen.setdefault(r.path, []).append(sorted(getattr(r, "methods", []) or []))
dups = {k:v for k,v in seen.items() if len(v)>1}
if dups:
    print("DUP_ROUTES", dups, file=sys.stderr)
    sys.exit(1)
c = TestClient(app, raise_server_exceptions=False)
status = c.post("/api/v5/profile/import", json={"schema":"come-personal-profile-pack/1","entries":[]}).status_code
print("IMPORT_STATUS", status)
if status == 500:
    sys.exit(1)
PY
  ok "routes uniques, import OK"
}

run_profile_tests() {
  echo "=== 4. Tests HTTP profil ==="
  if [ ! -d "$MEM_ROOT" ]; then
    warn "worktree mémoire absent — étape ignorée"
    return 0
  fi
  cd "$MEM_ROOT"
  $VENV_PY -m pytest -q tests/ -k "profile or personal" || fail "tests profil manquants/échoués"
  ok "tests profil présents"
}

run_secrets() {
  echo "=== 5. Aucun secret tracké ==="
  cd "$MAIN_ROOT"
  MATCHES=$(git ls-files | grep -iE '\.env$|\.db$|secret|key|token|password' | grep -v test_hybrid_secret_guards || true)
  if [ -n "$MATCHES" ]; then
    echo "$MATCHES" >&2
    fail "fichiers sensibles trackés"
  else
    ok "aucun secret tracké"
  fi
}

run_memory_injection() {
  echo "=== 6. Mémoire injectée dans le chat (après raccord) ==="
  cd "$MAIN_ROOT"
  if grep -q list_personal_memories hybrid_chat.py; then
    ok "list_personal_memories appelé côté chat"
  else
    warn "non encore raccordé (attendu après PROMPT 3)"
  fi
}

run_devkit() {
  echo "=== 7. DevKit (sandbox + rollback) ==="
  cd "$MAIN_ROOT"
  $VENV_PY -m pytest -q tests/test_devkit*.py tests/test_evolution*.py || fail "DevKit/tests évolution échoués"
  ok "DevKit vert"
}

run_study() {
  echo "=== 8. Study Coach (isolé) ==="
  if [ ! -d "$STUDY_ROOT" ]; then
    warn "worktree study-coach absent ($STUDY_ROOT) — étape ignorée"
    return 0
  fi
  cd "$STUDY_ROOT"
  $VENV_PY -m pytest -q tests/test_study_coach_*.py || fail "Study Coach échoué"
  ok "Study Coach tests passés"
}

run_fingerprint() {
  echo "=== 9. Empreinte source DevKit ==="
  cd "$MAIN_ROOT"
  if [ -f .devkit/diagnostics/latest.md ] && [ -f .devkit/diagnostics/latest.json ]; then
    ok "rapports DevKit présents"
  else
    warn "rapports DevKit absents"
  fi
}

run_lint() {
  echo "=== 10. Lint (ruff) ==="
  cd "$MAIN_ROOT"
  if [ -x "$ROOT/.venv/bin/ruff" ]; then
    $ROOT/.venv/bin/ruff check . || fail "ruff check en échec"
  else
    warn "ruff absent du venv — étape ignorée"
  fi
}

run_interdits() {
  echo "=== 11. Interdits (rappel) ==="
  echo "  - Pas de git reset --hard / clean / force-push sur main"
  echo "  - Pas de secrets dans le contexte modèle"
  echo "  - Pas de données perso réelles dans les fixtures"
  echo "  - Ne pas modifier main sans validation complète"
  ok "rappel affiché"
}

# --- Dispatch ---
CMD="${1:-all}"
case "$CMD" in
  main)       run_main ;;
  memory)     run_memory ;;
  routes)     run_routes ;;
  profile)    run_profile_tests ;;
  secrets)    run_secrets ;;
  injection)  run_memory_injection ;;
  devkit)     run_devkit ;;
  study)      run_study ;;
  fingerprint)run_fingerprint ;;
  lint)       run_lint ;;
  all)
    run_main
    run_memory
    run_routes
    run_profile_tests
    run_secrets
    run_memory_injection
    run_devkit
    run_study
    run_fingerprint
    run_lint
    run_interdits
    ;;
  *) echo "Usage: $0 [main|memory|routes|profile|secrets|injection|devkit|study|fingerprint|lint|all]"; exit 1 ;;
esac

if [ $EXIT -eq 0 ]; then
  echo -e "\n${GRN}TOUT VERT${NC}"
else
  echo -e "\n${RED}ÉCHEC(S)${NC}"
  exit 1
fi
