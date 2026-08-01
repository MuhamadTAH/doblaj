#!/usr/bin/env bash
# clean_pycache.sh — remove __pycache__/ directories that may contain stale
# bytecode of deleted source (e.g. a previously-hardcoded API key that lived
# in the source). See PIRD-015 in findings_ledger.json.
#
# Usage: ./scripts/clean_pycache.sh
set -euo pipefail

echo "== Pird __pycache__ cleanup =="
find . -type d -name __pycache__ -print -exec rm -rf {} + 2>/dev/null
echo "Done."