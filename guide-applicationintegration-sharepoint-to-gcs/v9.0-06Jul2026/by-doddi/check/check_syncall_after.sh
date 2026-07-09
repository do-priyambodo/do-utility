#!/bin/bash
# check_syncall_after.sh - Bash launcher for V9.0 High-Speed Post-Sync Verification
#
# Verifies target SharePoint site inventory against GCS bucket contents,
# confirms delta completion, and outputs a comprehensive post-sync audit report.

cd "$(dirname "$0")/.."
export PYTHONPATH="$(pwd)/util:${PYTHONPATH:-}"
set -e

if [ ! -f "parameters.json" ]; then
  echo "❌ Error: parameters.json not found in $(pwd)!"
  exit 1
fi

exec python3 check/check_syncall_after.py "$@"
