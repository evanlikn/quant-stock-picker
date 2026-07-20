from __future__ import annotations

import os

from tickflow import TickFlow

from quant_picker.config import load_env

_client: TickFlow | None = None


def get_tickflow_client() -> TickFlow:
    """Return TickFlow client: full service if TICKFLOW_API_KEY set, else free tier."""
    global _client
    if _client is None:
        load_env()
        api_key = os.getenv("TICKFLOW_API_KEY", "").strip()
        if api_key:
            _client = TickFlow(api_key=api_key)
        else:
            _client = TickFlow.free()
    return _client


def clear_tickflow_client() -> None:
    global _client
    _client = None
