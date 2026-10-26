#!/usr/bin/env bash
# Applique la protection de main décrite dans main.yml (SPEC-007).
#
# Prérequis : gh CLI authentifié avec le scope "admin:repo" (ou un token
# équivalent). Le script échoue proprement si le dépôt ou les droits manquent.
# Il n'écrit jamais dans le dépôt : il ne fait qu'appeler l'API GitHub.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
REPO="${REPO:-$(gh repo view --json nameWithOwner --jq .nameWithOwner)}"
BRANCH="${BRANCH:-main}"

echo "Application de la protection sur ${REPO}:${BRANCH}…"

payload="$(ROOT="${ROOT}" python3 - <<'PY'
import json, os, sys
try:
    import yaml
except ModuleNotFoundError:
    sys.exit("PyYAML est requis : pip install pyyaml")
path = os.path.join(os.environ["ROOT"], ".github", "branch-protection", "main.yml")
data = yaml.safe_load(open(path, encoding="utf-8"))
print(json.dumps(data["protection"], ensure_ascii=False))
PY
)"

gh api \
  --method PUT \
  -H "Accept: application/vnd.github+json" \
  "/repos/${REPO}/branches/${BRANCH}/protection" \
  --input - <<<"${payload}"

echo "OK — protection appliquée. Vérification :"
gh api "/repos/${REPO}/branches/${BRANCH}/protection" --jq '{
  strict: .required_status_checks.strict,
  contexts: .required_status_checks.contexts,
  enforce_admins: .enforce_admins.enabled,
  reviews: .required_pull_request_reviews.required_approving_review_count,
  force_pushes: .allow_force_pushes.enabled,
  deletions: .allow_deletions.enabled
}'
