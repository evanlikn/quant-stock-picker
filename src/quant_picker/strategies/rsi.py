from __future__ import annotations

import pandas as pd

from quant_picker.strategies.base import Signal, Strategy
from quant_picker.strategies.indicators import rsi as calc_rsi


class RSIStrategy(Strategy):
    name = "rsi"

    def __init__(self, params: dict | None = None, param_space: dict | None = None):
        self._params = params or {"period": 14, "oversold": 30, "overbought": 70}
        self._param_space = param_space or {
            "period": [9, 14, 21],
            "oversold": [25, 30, 35],
            "overbought": [65, 70, 75],
        }

    def param_space(self, interval: str) -> dict[str, list]:
        return self._param_space

    def with_params(self, params: dict) -> Strategy:
        return RSIStrategy(params=params, param_space=self._param_space)

    def _rsi_series(self, df: pd.DataFrame) -> pd.Series:
        period = int(self._params["period"])
        return calc_rsi(df["close"], period)

    def generate_signals(self, df: pd.DataFrame) -> pd.Series:
        rsi = self._rsi_series(df)
        oversold = float(self._params["oversold"])
        overbought = float(self._params["overbought"])
        signals = []
        for i in range(len(df)):
            val = rsi.iloc[i]
            if pd.isna(val):
                signals.append("hold")
            elif val < oversold:
                signals.append("buy")
            elif val > overbought:
                signals.append("sell")
            else:
                signals.append("hold")
        return pd.Series(signals, index=df.index, dtype=object)

    def analyze(self, df: pd.DataFrame) -> Signal:
        if len(df) < int(self._params["period"]) + 2:
            return Signal("hold", 0.0, "数据不足")
        rsi = self._rsi_series(df)
        val = rsi.iloc[-1]
        if pd.isna(val):
            return Signal("hold", 0.0, "RSI 无法计算")
        oversold = float(self._params["oversold"])
        overbought = float(self._params["overbought"])
        period = int(self._params["period"])
        if val < oversold:
            strength = min(1.0, (oversold - val) / oversold + 0.5)
            return Signal("buy", strength, f"RSI({period})={val:.1f} 超卖")
        if val > overbought:
            return Signal("sell", 0.7, f"RSI({period})={val:.1f} 超买")
        return Signal("hold", 0.0, f"RSI({period})={val:.1f} 中性")

    def format_params(self) -> str:
        p = self._params
        return f"RSI{p['period']}/{p['oversold']}/{p['overbought']}"
