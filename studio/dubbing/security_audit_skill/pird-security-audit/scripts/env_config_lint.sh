#!/usr/bin/env bash
# env_config_lint.sh - check deploy-time config WITHOUT ever printing secret values.
# Usage: ./env_config_lint.sh path/to/.env.production
set -uo pipefail

FILE="${1:?Usage: env_config_lint.sh <path-to-env-file>}"
[ -f "$FILE" ] || { echo "File not found: $FILE"; exit 1; }

fail=0
ok()   { echo "  [OK]   $1"; }
warn() { echo "  [WARN] $1"; }
crit() { echo "  [CRIT] $1"; fail=1; }

get() { grep -E "^${1}=" "$FILE" | tail -n1 | cut -d'=' -f2-; }

echo "== env_config_lint: $FILE =="

env_val=$(get PIRD_ENV)
if [ "$env_val" = "prod" ]; then
  ok "PIRD_ENV=prod"
else
  warn "PIRD_ENV is '${env_val:-<unset>}', not 'prod' - the cookie Secure flag and other prod-only gating will NOT engage."
fi

redis_val=$(get REDIS_URL)
if [ -z "$redis_val" ]; then
  crit "REDIS_URL is not set."
elif [[ "$redis_val" =~ redis://[^:@/]+:[^@/]+@ ]]; then
  ok "REDIS_URL appears to include embedded credentials."
else
  crit "REDIS_URL has no embedded credentials - Redis is likely reachable without auth. (value not printed)"
fi

for key in CLERK_SECRET_KEY CLERK_JWT_ISSUER_DOMAIN CONVEX_DEPLOY_KEY FISH_API_KEY GEMINI_API_KEY OPEN_ROUTER_API_KEY INTERNAL_API_KEY; do
  v=$(get "$key")
  if [ -z "$v" ]; then
    warn "$key is not set."
  else
    ok "$key is set (value not printed)."
  fi
done

# Supabase should be fully retired, not just unused. A key that's no longer called
# but is still valid at the provider is still a live attack surface (see PIRD-008).
for key in SUPABASE_JWT_SECRET SUPABASE_SERVICE_ROLE_KEY; do
  v=$(get "$key")
  [ -n "$v" ] && warn "$key is still set. If Supabase is retired, this should be rotated/revoked at Supabase, not just left unused here."
done

# Vite (the dashboard) and Next.js (the storefront) expose client-side env vars
# under different prefixes. Copying the wrong one silently breaks client-side Clerk.
vite_pk=$(get VITE_CLERK_PUBLISHABLE_KEY)
next_pk=$(get NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY)
if [ -n "$vite_pk" ] && [ -n "$next_pk" ]; then
  ok "Both VITE_CLERK_PUBLISHABLE_KEY and NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY are set - fine if this .env is shared across apps, but confirm the Vite dashboard reads the VITE_ one and the Next.js storefront reads the NEXT_PUBLIC_ one."
elif [ -n "$vite_pk" ]; then
  ok "VITE_CLERK_PUBLISHABLE_KEY is set - correct prefix for the Vite-based dubbing dashboard."
elif [ -n "$next_pk" ]; then
  warn "Only NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY is set (correct for the Next.js storefront). If this file is meant for the Vite dashboard too, that app needs its own VITE_CLERK_PUBLISHABLE_KEY - the NEXT_PUBLIC_ one will not reach its client code."
else
  warn "Neither VITE_CLERK_PUBLISHABLE_KEY nor NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY is set."
fi

echo
echo "This script never prints secret VALUES - only whether they're present and correctly shaped."
echo "Its output is safe to paste anywhere. The .env file itself, and raw output from secret_scan.sh, are not."

[ "$fail" = "1" ] && exit 1
exit 0
