#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
export QUANT_PICKER_ROOT="$ROOT"
export PYTHONPATH="$ROOT/src:${PYTHONPATH:-}"
cd "$ROOT"
source .venv/bin/activate
streamlit run src/quant_picker/web/首页.py "$@"
