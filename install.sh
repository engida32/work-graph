#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PYTHON="${PYTHON:-python3}"

"$PYTHON" -m pip install --user --editable "$ROOT"
printf 'Installed work-graph. Run: work-graph doctor\n'
