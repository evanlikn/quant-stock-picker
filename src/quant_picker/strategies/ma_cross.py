from __future__ import annotations

import pandas as pd

from quant_picker.strategies.base import Action, Interval, Signal, Strategy


class MACrossStrategy(Strategy):
    name = "ma_cross"

    def __init__(self, params: dict | None = None, param_space: dict | None = None):
        self._params = params or {"short_window": 5, "long_window": 20}
        self._param_space = param_space or {
            "short_window": [3, 5, 8, 10],
            "long_window": [15, 20, 30, 40],
        }

    def param_space(self, interval: Interval) -> dict[str, list]:
        return self._param_space

    def with_params(self, params: dict) -> Strategy:
        return MACrossStrategy(params=params, param_space=self._param_space)

    def _ma_series(self, df: pd.DataFrame) -> pd.Series:
        short = int(self._params["short_window"])
        long = int(self._params["long_window"])
        if len(df) < long + 2:
            return pd.Series(["hold"] * len(df), index=df.index, dtype=object)
        ma_s = df["close"].rolling(short).mean()
        ma_l = df["close"].rolling(long).mean()
        signals = []
        for i in range(len(df)):
            if i < long or pd.isna(ma_s.iloc[i]) or pd.isna(ma_l.iloc[i]):
                signals.append("hold")
                continue
            prev_s, prev_l = ma_s.iloc[i - 1], ma_l.iloc[i - 1]
            cur_s, cur_l = ma_s.iloc[i], ma_l.iloc[i]
            if prev_s <= prev_l and cur_s > cur_l:
                signals.append("buy")
            elif prev_s >= prev_l and cur_s < cur_l:
                signals.append("sell")
            else:
                signals.append("hold")
        return pd.Series(signals, index=df.index, dtype=object)

    def generate_signals(self, df: pd.DataFrame) -> pd.Series:
        return self._ma_series(df)

    def analyze(self, df: pd.DataFrame) -> Signal:
        if len(df) < 2:
            return Signal("hold", 0.0, "数据不足")
        series = self._ma_series(df)
        action = series.iloc[-1]
        short = int(self._params["short_window"])
        long = int(self._params["long_window"])
        if action == "buy":
            strength = min(1.0, 0.6 + 0.1 * (long - short) / long)
            return Signal("buy", strength, f"MA{short}上穿MA{long}，金叉")
        if action == "sell":
            return Signal("sell", 0.7, f"MA{short}下穿MA{long}，死叉")
        return Signal("hold", 0.0, f"MA{short}/MA{long} 无交叉信号")

    def format_params(self) -> str:
        return f"MA{self._params['short_window']}/{self._params['long_window']}"
