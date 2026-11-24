#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
if [ ! -x .venv/bin/python ] || [ ! -f frontend/dist/index.html ]; then echo 'Run ./setup.sh first to install dependencies and build the interface.'; exit 1; fi
exec .venv/bin/python scripts/launch.py "$@"
