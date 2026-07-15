from __future__ import annotations

import pandas as pd

from quant_picker.strategies.base import Signal, Strategy
from quant_picker.strategies.indicators import macd


class MACDStrategy(Strategy):
    name = "macd"

    def __init__(self, params: dict | None = None, param_space: dict | None = None):
        self._params = params or {"fast": 12, "slow": 26, "signal": 9}
        self._param_space = param_space or {
            "fast": [8, 10, 12],
            "slow": [20, 26, 30],
            "signal": [7, 9, 11],
        }

    def param_space(self, interval: str) -> dict[str, list]:
        return self._param_space

    def with_params(self, params: dict) -> Strategy:
        return MACDStrategy(params=params, param_space=self._param_space)

    def _macd_df(self, df: pd.DataFrame) -> pd.DataFrame:
        fast = int(self._params["fast"])
        slow = int(self._params["slow"])
        sig = int(self._params["signal"])
        return macd(df["close"], fast=fast, slow=slow, signal=sig)

    def generate_signals(self, df: pd.DataFrame) -> pd.Series:
        macd = self._macd_df(df)
        if macd.empty:
            return pd.Series(["hold"] * len(df), index=df.index, dtype=object)
        col_macd = "macd"
        col_sig = "signal"
        hist = "hist"
        signals = []
        for i in range(len(df)):
            if i < 1 or pd.isna(macd[col_macd].iloc[i]):
                signals.append("hold")
                continue
            d_prev, s_prev = macd[col_macd].iloc[i - 1], macd[col_sig].iloc[i - 1]
            d_cur, s_cur = macd[col_macd].iloc[i], macd[col_sig].iloc[i]
            h_cur = macd[hist].iloc[i]
            if d_prev <= s_prev and d_cur > s_cur and h_cur > 0:
                signals.append("buy")
            elif d_prev >= s_prev and d_cur < s_cur:
                signals.append("sell")
            else:
                signals.append("hold")
        return pd.Series(signals, index=df.index, dtype=object)

    def analyze(self, df: pd.DataFrame) -> Signal:
        if len(df) < 30:
            return Signal("hold", 0.0, "数据不足")
        series = self.generate_signals(df)
        action = series.iloc[-1]
        p = self._params
        if action == "buy":
            return Signal("buy", 0.75, f"MACD({p['fast']}/{p['slow']}/{p['signal']}) 金叉且柱为正")
        if action == "sell":
            return Signal("sell", 0.7, f"MACD({p['fast']}/{p['slow']}/{p['signal']}) 死叉")
        return Signal("hold", 0.0, "MACD 无明确信号")

    def format_params(self) -> str:
        p = self._params
        return f"{p['fast']}/{p['slow']}/{p['signal']}"
