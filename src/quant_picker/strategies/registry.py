from __future__ import annotations

from typing import Any

from quant_picker.config import load_strategies_config
from quant_picker.strategies.base import Interval, Strategy
from quant_picker.strategies.king_keltner import KingKeltnerStrategy
from quant_picker.strategies.ma_cross import MACrossStrategy
from quant_picker.strategies.macd import MACDStrategy
from quant_picker.strategies.rsi import RSIStrategy
from quant_picker.strategies.turtle_signal import TurtleSignalStrategy

STRATEGY_CLASSES: dict[str, type] = {
    "ma_cross": MACrossStrategy,
    "macd": MACDStrategy,
    "rsi": RSIStrategy,
    "turtle_signal": TurtleSignalStrategy,
    "king_keltner": KingKeltnerStrategy,
}


def _cfg_for(name: str) -> dict[str, Any]:
    for s in load_strategies_config().get("strategies", []):
        if s["name"] == name:
            return s
    raise KeyError(f"Strategy not in config: {name}")


def build_strategy(name: str, interval: Interval, params: dict | None = None) -> Strategy:
    cfg = _cfg_for(name)
    cls = STRATEGY_CLASSES[name]
    space = cfg.get("param_space_by_interval", {}).get(interval, {})
    defaults = cfg.get("default_params_by_interval", {}).get(interval, {})
    merged = {**defaults, **(params or {})}
    return cls(params=merged, param_space=space or None)


def list_enabled_strategies(interval: Interval) -> list[Strategy]:
    strategies = []
    for cfg in load_strategies_config().get("strategies", []):
        if not cfg.get("enabled", True):
            continue
        strategies.append(build_strategy(cfg["name"], interval))
    return strategies


def count_enabled_strategies() -> int:
    return sum(
        1
        for cfg in load_strategies_config().get("strategies", [])
        if cfg.get("enabled", True)
    )
