#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
PYTHON_BIN="${PDF_EXTRACTOR_PYTHON:-}"
if [ -z "$PYTHON_BIN" ]; then
  for candidate in python3.12 /opt/homebrew/bin/python3.12 "$HOME/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3" python3; do
    if command -v "$candidate" >/dev/null 2>&1 && "$candidate" -c 'import sys; assert sys.version_info[:2] == (3,12)' 2>/dev/null; then PYTHON_BIN="$candidate"; break; fi
  done
fi
if [ -z "$PYTHON_BIN" ]; then echo 'Python 3.12 is required. Install it with: brew install python@3.12'; exit 1; fi
if ! command -v node >/dev/null || ! command -v npm >/dev/null; then echo 'Node.js 22.12+ is required. Install Node 22 LTS, then run setup again.'; exit 1; fi
node -e 'const [a,b]=process.versions.node.split(".").map(Number); if(a<22||(a===22&&b<12)){console.error("Node 22.12+ is required");process.exit(1)}'
"$PYTHON_BIN" -c 'import shutil; assert shutil.disk_usage(".").free > 2*1024**3, "At least 2 GB free disk space is required"'
if [ ! -x .venv/bin/python ]; then "$PYTHON_BIN" -m venv .venv; fi
.venv/bin/python -m pip install -r backend/requirements.lock
cd frontend
npm ci --legacy-peer-deps
npm run check
npm run build
cd "$ROOT"
./scripts/doctor.sh
echo 'Setup complete. Run ./start.sh to open PDF Image Extractor.'
