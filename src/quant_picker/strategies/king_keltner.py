from __future__ import annotations

import pandas as pd

from quant_picker.strategies.base import Interval, Signal, Strategy
from quant_picker.strategies.indicators import keltner


class KingKeltnerStrategy(Strategy):
    """肯特纳通道突破策略：上轨突破做多，移动止损出场。"""

    name = "king_keltner"

    def __init__(self, params: dict | None = None, param_space: dict | None = None):
        self._params = params or {
            "kk_length": 11,
            "kk_dev": 1.6,
            "trailing_percent": 0.8,
        }
        self._param_space = param_space or {
            "kk_length": [8, 11, 14, 20],
            "kk_dev": [1.2, 1.6, 2.0],
            "trailing_percent": [0.5, 0.8, 1.0, 1.5],
        }

    def param_space(self, interval: Interval) -> dict[str, list]:
        return self._param_space

    def with_params(self, params: dict) -> Strategy:
        return KingKeltnerStrategy(params=params, param_space=self._param_space)

    def _bands(self, df: pd.DataFrame) -> tuple[pd.Series, pd.Series]:
        length = int(self._params["kk_length"])
        dev = float(self._params["kk_dev"])
        return keltner(df["high"], df["low"], df["close"], length, dev)

    def generate_signals(self, df: pd.DataFrame) -> pd.Series:
        length = int(self._params["kk_length"])
        trailing = float(self._params["trailing_percent"])
        if len(df) < length + 2:
            return pd.Series(["hold"] * len(df), index=df.index, dtype=object)

        kk_up, kk_down = self._bands(df)
        signals: list[str] = []
        position = 0
        intra_trade_high = 0.0

        for i in range(len(df)):
            if pd.isna(kk_up.iloc[i]) or pd.isna(kk_down.iloc[i]):
                signals.append("hold")
                continue

            high = float(df["high"].iloc[i])
            low = float(df["low"].iloc[i])
            up = float(kk_up.iloc[i])

            if position == 0:
                if high >= up:
                    signals.append("buy")
                    position = 1
                    intra_trade_high = high
                else:
                    signals.append("hold")
            else:
                intra_trade_high = max(intra_trade_high, high)
                stop = intra_trade_high * (1 - trailing / 100)
                if low <= stop:
                    signals.append("sell")
                    position = 0
                    intra_trade_high = 0.0
                else:
                    signals.append("hold")

        return pd.Series(signals, index=df.index, dtype=object)

    def analyze(self, df: pd.DataFrame) -> Signal:
        length = int(self._params["kk_length"])
        trailing = float(self._params["trailing_percent"])
        if len(df) < length + 2:
            return Signal("hold", 0.0, "数据不足")

        series = self.generate_signals(df)
        action = series.iloc[-1]
        kk_up, kk_down = self._bands(df)
        up = float(kk_up.iloc[-1])
        down = float(kk_down.iloc[-1])
        close = float(df["close"].iloc[-1])
        dev = float(self._params["kk_dev"])

        if action == "buy":
            return Signal(
                "buy",
                0.75,
                f"肯特纳上轨突破 {up:.2f}（{length}日×{dev}ATR）",
            )
        if action == "sell":
            return Signal(
                "sell",
                0.7,
                f"肯特纳移动止损出场（回撤 {trailing}%）",
            )

        if close > up:
            return Signal("hold", 0.4, f"价格在上轨之上 {up:.2f}")
        if close < down:
            return Signal("hold", 0.2, f"价格在下轨之下 {down:.2f}")
        return Signal("hold", 0.0, f"肯特纳 {length}/{dev} 通道内震荡")

    def format_params(self) -> str:
        p = self._params
        return f"KK{p['kk_length']}/{p['kk_dev']}/{p['trailing_percent']}%"
