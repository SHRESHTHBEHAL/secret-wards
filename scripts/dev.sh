#!/usr/bin/env bash
# Local dev loop: run on the practice data, check the contract, score against the practice truth.
# Usage: scripts/dev.sh [extra args for check_dev.py, e.g. --show 10]
set -euo pipefail

REPO="$(cd "$(dirname "$0")/.." && pwd)"
KIT="${KIT:-$REPO/../Secret-Wards-ToolKit}"
OUT="${OUT:-$REPO/my_output}"
PY="${PY:-python3}"

rm -rf "$OUT"
RAKSHA_SECRET="${RAKSHA_SECRET:-practice}" "$PY" "$REPO/main.py" --input "$KIT/dev/input" --output "$OUT"
"$PY" "$KIT/validate_output.py" --input "$KIT/dev/input" --output "$OUT"
"$PY" "$KIT/check_dev.py" --output "$OUT" "$@"
