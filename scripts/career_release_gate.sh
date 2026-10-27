#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PYTHON="${CAREER_GATE_PYTHON:-python3}"

exec "$PYTHON" "$ROOT/scripts/career_release_gate.py" "$@"
