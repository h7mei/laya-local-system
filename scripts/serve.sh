#!/usr/bin/env bash
# Linux/macOS launcher for the one serve entry point (see serve.py).
# Usage: ./scripts/serve.sh
#        ./scripts/serve.sh --download-only
#        ./scripts/serve.sh --check-only

set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PYTHON="$ROOT/.venv/bin/python"

if [[ ! -x "$PYTHON" ]]; then
  echo "Missing $PYTHON. Create the venv and install deps first (see README.md)." >&2
  exit 1
fi

exec "$PYTHON" "$ROOT/scripts/serve.py" "$@"
