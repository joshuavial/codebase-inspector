#!/usr/bin/env bash
# scripts/capture_demo.sh - Reproducible capture script for CBI CLI demo recording (docs/images/cbi-demo.gif)
# Explicitly marked as INTERNAL DRAFT DEMO; executes actual CLI commands on synthetic public demo data.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"

echo "=== Running CBI Demo Recording Asset Capture ==="
echo "Target asset: ${ROOT_DIR}/docs/images/cbi-demo.gif"

python3 "${SCRIPT_DIR}/capture_demo.py"

echo "=== Capture completed successfully ==="
