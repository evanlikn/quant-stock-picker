from __future__ import annotations

import pandas as pd

from quant_picker.strategies.base import Interval, Signal, Strategy
from quant_picker.strategies.indicators import atr, donchian


class TurtleSignalStrategy(Strategy):
    """海龟信号策略：唐奇安通道突破入场，ATR 止损 + 短周期唐奇安下轨出场。"""

    name = "turtle_signal"

    def __init__(self, params: dict | None = None, param_space: dict | None = None):
        self._params = params or {
            "entry_window": 20,
            "exit_window": 10,
            "atr_window": 20,
        }
        self._param_space = param_space or {
            "entry_window": [15, 20, 25, 30],
            "exit_window": [8, 10, 12],
            "atr_window": [14, 20, 26],
        }

    def param_space(self, interval: Interval) -> dict[str, list]:
        return self._param_space

    def with_params(self, params: dict) -> Strategy:
        return TurtleSignalStrategy(params=params, param_space=self._param_space)

    def _channels(self, df: pd.DataFrame) -> tuple[pd.Series, pd.Series, pd.Series, pd.Series, pd.Series]:
        entry_w = int(self._params["entry_window"])
        exit_w = int(self._params["exit_window"])
        atr_w = int(self._params["atr_window"])
        entry_up, entry_down = donchian(df["high"], df["low"], entry_w)
        exit_up, exit_down = donchian(df["high"], df["low"], exit_w)
        atr_val = atr(df["high"], df["low"], df["close"], atr_w)
        return entry_up, entry_down, exit_up, exit_down, atr_val

    def generate_signals(self, df: pd.DataFrame) -> pd.Series:
        entry_w = int(self._params["entry_window"])
        exit_w = int(self._params["exit_window"])
        min_bars = max(entry_w, exit_w, int(self._params["atr_window"])) + 1
        if len(df) < min_bars:
            return pd.Series(["hold"] * len(df), index=df.index, dtype=object)

        entry_up, _, _, exit_down, atr_val = self._channels(df)
        signals: list[str] = []
        position = 0
        long_stop = 0.0

        for i in range(len(df)):
            if (
                pd.isna(entry_up.iloc[i])
                or pd.isna(exit_down.iloc[i])
                or pd.isna(atr_val.iloc[i])
            ):
                signals.append("hold")
                continue

            high = float(df["high"].iloc[i])
            low = float(df["low"].iloc[i])

            if position == 0:
                if high >= float(entry_up.iloc[i]):
                    signals.append("buy")
                    position = 1
                    entry_atr = float(atr_val.iloc[i])
                    long_stop = high - 2 * entry_atr
                else:
                    signals.append("hold")
            else:
                exit_level = max(long_stop, float(exit_down.iloc[i]))
                if low <= exit_level:
                    signals.append("sell")
                    position = 0
                    long_stop = 0.0
                else:
                    signals.append("hold")

        return pd.Series(signals, index=df.index, dtype=object)

    def analyze(self, df: pd.DataFrame) -> Signal:
        entry_w = int(self._params["entry_window"])
        exit_w = int(self._params["exit_window"])
        min_bars = max(entry_w, exit_w, int(self._params["atr_window"])) + 1
        if len(df) < min_bars:
            return Signal("hold", 0.0, "数据不足")

        series = self.generate_signals(df)
        action = series.iloc[-1]
        entry_up, _, _, exit_down, atr_val = self._channels(df)
        up = float(entry_up.iloc[-1])
        down = float(exit_down.iloc[-1])
        atr_last = float(atr_val.iloc[-1])
        close = float(df["close"].iloc[-1])

        if action == "buy":
            strength = min(1.0, 0.6 + (close - up) / up * 5 if up else 0.6)
            return Signal(
                "buy",
                max(0.6, strength),
                f"海龟突破 {entry_w}日高点 {up:.2f}，ATR({self._params['atr_window']})={atr_last:.2f}",
            )
        if action == "sell":
            return Signal(
                "sell",
                0.75,
                f"海龟出场：触及 {exit_w}日低点 {down:.2f} 或 ATR 止损",
            )

        dist = (up - close) / close if close else 0
        if dist < 0.02:
            return Signal("hold", 0.3, f"接近 {entry_w}日突破位 {up:.2f}（距 {dist*100:.1f}%）")
        return Signal("hold", 0.0, f"唐奇安 {entry_w}/{exit_w} 无突破信号")

    def format_params(self) -> str:
        p = self._params
        return f"Turtle {p['entry_window']}/{p['exit_window']}/ATR{p['atr_window']}"
