#!/usr/bin/env bash
# Full Phase 11 checks. --docker additionally builds an isolated disposable stack.
set -euo pipefail
ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
PYTHON="${PYTHON:-$ROOT/.venv/bin/python}"
if [[ ! -x "$PYTHON" && -x "$ROOT/.venv/Scripts/python.exe" ]]; then
  PYTHON="$ROOT/.venv/Scripts/python.exe"
fi
if [[ ! -x "$PYTHON" ]]; then echo "Create the documented Python virtual environment first." >&2; exit 1; fi
if [[ $# -gt 1 || ( $# -eq 1 && "$1" != "--docker" ) ]]; then echo "Usage: $0 [--docker]" >&2; exit 2; fi
"$PYTHON" -m ruff check backend scripts
"$PYTHON" -m ruff format --check backend scripts
"$PYTHON" -m pip check
(
  cd frontend
  npm ci
  npm run typecheck
  npm test
  npm run build
)
"$PYTHON" scripts/verify_phase2.py
if [[ "${1:-}" == "--docker" ]]; then "$PYTHON" scripts/verify_phase11_docker.py; fi
