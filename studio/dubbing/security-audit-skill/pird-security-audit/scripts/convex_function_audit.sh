#!/usr/bin/env bash
# convex_function_audit.sh - sweep every Convex query/mutation/action/httpAction
# definition and flag ones that don't obviously check auth.
#
# Why this exists: Convex has no row-level security and no automatic per-row
# filtering. Every query, mutation, action, and httpAction is PUBLICLY CALLABLE
# the moment it's deployed unless it's declared with the internal* variant
# (internalQuery/internalMutation/internalAction) instead. Convex's own
# best-practices docs recommend exactly this sweep: search the codebase for
# every one of these definitions and confirm each has some access control.
# This script narrows down where to look - it does not replace reading the code.
#
# Usage: ./convex_function_audit.sh <path-to-convex-dir>
set -uo pipefail

DIR="${1:?Usage: convex_function_audit.sh <path-to-convex-dir>}"
[ -d "$DIR" ] || { echo "Not a directory: $DIR"; exit 1; }

echo "== Convex function audit: $DIR =="
echo

PUBLIC_DEF_RE='export const [A-Za-z0-9_]+ = (query|mutation|action|httpAction)\('

echo "[1/2] Public (client-callable) function definitions:"
echo "      (internalQuery/internalMutation/internalAction are not client-callable and are out of scope here)"
grep -RnE "$PUBLIC_DEF_RE" "$DIR" --include='*.ts' 2>/dev/null | grep -v internal

echo
echo "[2/2] For each file with a public function above, checking for a nearby auth call:"
FILES=$(grep -RlE "$PUBLIC_DEF_RE" "$DIR" --include='*.ts' 2>/dev/null | grep -v internal)
if [ -z "$FILES" ]; then
  echo "  No public function definitions found under $DIR."
else
  for f in $FILES; do
    if grep -qE 'ctx\.auth\.getUserIdentity|requireUser|requireAuth|authenticatedQuery|authenticatedMutation' "$f"; then
      echo "  [likely OK]   $f - contains an auth-check call somewhere in the file"
    else
      echo "  [CHECK THIS]  $f - no obvious auth-check call found. Read it manually."
    fi
  done
fi

echo
echo "This is a heuristic, not a guarantee. A file can call ctx.auth.getUserIdentity()"
echo "and still get the check wrong - e.g. confirming someone is logged in but never"
echo "confirming the specific document/workspace they're touching belongs to them."
echo "Per Convex's own guidance: access-control checks should use ctx.auth.getUserIdentity()"
echo "or an unguessable Convex ID - never a spoofable argument like an email."
