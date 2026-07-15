#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
export QUANT_PICKER_ROOT="$ROOT"
export PYTHONPATH="$ROOT/src:${PYTHONPATH:-}"
cd "$ROOT"
source .venv/bin/activate
python -m quant_picker.scheduler.runner "$@"
