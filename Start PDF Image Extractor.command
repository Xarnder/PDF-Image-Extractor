#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")" && pwd)"
cd "$ROOT"
if ! ./start.sh; then
  echo
  read -r -p "Unable to start. Read the error above. Press Return to close. " _reply
  exit 1
fi
