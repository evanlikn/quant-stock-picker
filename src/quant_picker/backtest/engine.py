from __future__ import annotations

import pandas as pd

from quant_picker.backtest.metrics import compute_metrics
from quant_picker.backtest.report import BacktestReport
from quant_picker.config import load_settings
from quant_picker.strategies.base import Strategy


def _bars_per_year(interval: str) -> int:
    return {"1d": 252, "1h": 252 * 4, "1m": 252 * 240}.get(interval, 252)


class BacktestEngine:
    def run(self, df: pd.DataFrame, strategy: Strategy, interval: str = "1d") -> BacktestReport:
        settings = load_settings()
        commission = settings.get("backtest", {}).get("commission_rate", 0.0003)
        signals = strategy.generate_signals(df)
        cash = 1.0
        position = 0.0
        entry_price = 0.0
        equity = []
        trades: list[float] = []

        for i in range(len(df) - 1):
            action = signals.iloc[i]
            next_open = float(df["open"].iloc[i + 1])
            if action == "buy" and position == 0:
                position = cash * (1 - commission) / next_open
                entry_price = next_open
                cash = 0.0
            elif action == "sell" and position > 0:
                proceeds = position * next_open * (1 - commission)
                pnl = proceeds - (position * entry_price)
                trades.append(pnl / (position * entry_price) if entry_price else 0)
                cash = proceeds
                position = 0.0
            mark = cash + position * float(df["close"].iloc[i])
            equity.append(mark)

        if position > 0:
            last = float(df["close"].iloc[-1])
            proceeds = position * last * (1 - commission)
            trades.append((proceeds - position * entry_price) / (position * entry_price))
            equity.append(proceeds)
        elif equity:
            equity.append(equity[-1])
        else:
            equity.append(1.0)

        eq_series = pd.Series(equity)
        return compute_metrics(eq_series, trades, _bars_per_year(interval))
