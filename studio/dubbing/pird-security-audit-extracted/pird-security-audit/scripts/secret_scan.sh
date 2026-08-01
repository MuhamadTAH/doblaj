#!/usr/bin/env bash
# secret_scan.sh - scan the working tree AND full git history for exposed secrets.
# A secret "removed from source" is still exposed if it's anywhere in git history -
# that's why this checks `git log -p --all`, not just the current tree.
#
# Usage: ./secret_scan.sh <path-to-repo-root>
set -uo pipefail

REPO="${1:-.}"
cd "$REPO" || { echo "Cannot cd into $REPO"; exit 1; }

echo "== Pird secret scan =="
echo "Repo: $(pwd)"
echo

if command -v gitleaks >/dev/null 2>&1; then
  echo "[1/3] gitleaks - full history, redacted output"
  gitleaks detect --source . --log-opts="--all" --redact -v || true
else
  echo "[1/3] gitleaks not found. Install it for a more reliable scan: https://github.com/gitleaks/gitleaks"
  echo "      Falling back to pattern grep below."
fi

echo
echo "[2/3] Pattern grep - working tree + full commit history"

scan() {
  local desc="$1" pattern="$2" flags="$3"
  echo "-- $desc --"
  grep -RnE $flags "$pattern" --exclude-dir=.git --exclude-dir=node_modules --exclude-dir=venv --exclude-dir=.venv . 2>/dev/null
  git log -p --all 2>/dev/null | grep -nE $flags "$pattern"
}

scan "Google API key shape"          'AIza[0-9A-Za-z_-]{35}'                     ""
scan "generic secret-key shape"      'sk-[A-Za-z0-9]{20,}'                       ""
scan "Clerk secret key shape"        'sk_(test|live)_[A-Za-z0-9]{16,}'           ""
scan "clerk_secret_key env"          'clerk_secret_key[[:space:]]*='             "-i"
scan "convex_deploy_key env"         'convex_deploy_key[[:space:]]*='            "-i"
scan "supabase_service_role_key"     'supabase_service_role_key[[:space:]]*='    "-i"
scan "supabase_jwt_secret"           'supabase_jwt_secret[[:space:]]*='          "-i"
scan "fish_api_key"                  'fish_api_key[[:space:]]*='                 "-i"
scan "internal_api_key"              'internal_api_key[[:space:]]*='             "-i"
scan "redis URL with embedded creds" 'redis://[^:@[:space:]]+:[^@[:space:]]+@'   ""

# Note: Clerk publishable keys (pk_test_.../pk_live_...) are DESIGNED to be public
# and client-exposed. Finding one is not a leak - don't flag it as one.

echo
echo "[3/3] .env* git-tracking check"
if git ls-files 2>/dev/null | grep -qE '^\.env'; then
  echo "!! .env file(s) are TRACKED BY GIT right now - this is a live leak, not a historical one."
  echo "   Untrack immediately: git rm --cached <file>, then confirm it's in .gitignore."
else
  echo "No .env* files currently tracked. History may still contain old versions if they were ever tracked - check the grep output above."
fi

echo
echo "This script finds exposed secrets. It does not rotate them."
echo "Every key found here - including keys already removed from current source - is compromised until rotated at the provider."
echo "Do not paste this script's raw output into any AI chat, ticket, or shared log. It contains real secret values."
