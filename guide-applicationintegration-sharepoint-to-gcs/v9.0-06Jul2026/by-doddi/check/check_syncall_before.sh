#!/bin/bash
# check_syncall_before.sh - Bash launcher for V9.0 High-Speed Pre-Sync Verification
#
# Inspects target SharePoint site inventory (.aspx pages and document files),
# evaluates GCS delta cache, and outputs a comprehensive pre-sync verification report.

cd "$(dirname "$0")/.."
export PYTHONPATH="$(pwd)/util:${PYTHONPATH:-}"
set -e

if [ ! -f "parameters.json" ]; then
  echo "❌ Error: parameters.json not found in $(pwd)!"
  exit 1
fi

exec python3 check/check_syncall_before.py "$@"
