#!/usr/bin/env bash
# dep_audit.sh - run vulnerability audits across every package manager in the Pird monorepo.
# Paths below are best-guess from the project description - adjust to match the real layout.
#
# Usage: ./dep_audit.sh <path-to-repo-root>
set -uo pipefail

ROOT="${1:-.}"
cd "$ROOT" || { echo "Cannot cd into $ROOT"; exit 1; }

run() {
  local label="$1"; shift
  echo
  echo "== $label =="
  ( "$@" ) || echo "(non-zero exit above - that's the audit tool reporting findings, not this script failing)"
}

[ -f dubbing/requirements.txt ] && run "dubbing: pip-audit" bash -c \
  "cd dubbing && (pip-audit -r requirements.txt || (pip install --break-system-packages pip-audit && pip-audit -r requirements.txt))"

[ -f store/package.json ] && run "store: yarn npm audit" bash -c "cd store && yarn npm audit"

[ -f storefront/package.json ] && run "storefront: yarn npm audit" bash -c "cd storefront && yarn npm audit"

[ -f chatwoot-clone/package.json ] && run "chatwoot-clone: pnpm audit" bash -c "cd chatwoot-clone && pnpm audit"

echo
echo "No findings here is not proof of safety - these tools only catch known, disclosed CVEs in their databases."
echo "Re-run this on a schedule (weekly, or on every dependency bump), not just once."
