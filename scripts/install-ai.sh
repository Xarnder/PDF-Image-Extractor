#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
if [ ! -x .venv/bin/python ]; then echo 'Run ./setup.sh first.'; exit 1; fi
echo 'Installing the optional Heron runtime (PyTorch + Transformers). This may download several hundred MB.'
echo 'No model weights are downloaded by this script. Use Settings > AI models afterward.'
.venv/bin/python -m pip install -r backend/requirements-ai.txt
echo 'Restart the application, then open Settings > AI models to download Heron explicitly.'
