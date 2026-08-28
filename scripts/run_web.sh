#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
export QUANT_PICKER_ROOT="$ROOT"
export PYTHONPATH="$ROOT/src:${PYTHONPATH:-}"
cd "$ROOT"
source .venv/bin/activate
WEB_HOST="$(python -c 'from quant_picker.config import web_host; print(web_host())')"
WEB_PORT="$(python -c 'from quant_picker.config import web_port; print(web_port())')"
streamlit run src/quant_picker/web/首页.py \
  --server.address "$WEB_HOST" \
  --server.port "$WEB_PORT" \
  "$@"
