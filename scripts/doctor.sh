#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
if [ ! -x .venv/bin/python ]; then echo 'Missing virtual environment. Run ./setup.sh'; exit 1; fi
PYTHONPATH="$ROOT/backend" .venv/bin/python scripts/doctor.py
