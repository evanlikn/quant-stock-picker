from __future__ import annotations

import pandas as pd

from quant_picker.backtest.metrics import compute_metrics
from quant_picker.backtest.report import BacktestReport
from quant_picker.config import load_settings
from quant_picker.portfolio.position_sizer import (
    atr_stop_price,
    compute_atr_risk_units,
    get_position_sizing_config,
    trailing_stop_candidate,
)
from quant_picker.strategies.base import Strategy
from quant_picker.strategies.indicators import atr as calc_atr


def _bars_per_year(interval: str) -> int:
    return {"1d": 252, "1h": 252 * 4, "1m": 252 * 240}.get(interval, 252)


class BacktestEngine:
    def run(self, df: pd.DataFrame, strategy: Strategy, interval: str = "1d") -> BacktestReport:
        settings = load_settings()
        commission = settings.get("backtest", {}).get("commission_rate", 0.0003)
        sizing = get_position_sizing_config()
        use_atr = sizing["mode"] == "atr_risk"

        signals = strategy.generate_signals(df)
        atr_series = (
            calc_atr(df["high"], df["low"], df["close"], sizing["atr_period"])
            if use_atr
            else None
        )

        initial_capital = 1.0
        cash = initial_capital
        position = 0.0
        entry_price = 0.0
        long_stop = 0.0
        equity: list[float] = []
        trades: list[float] = []

        def _close_position(exit_price: float) -> None:
            nonlocal cash, position, entry_price, long_stop
            if position <= 0 or entry_price <= 0:
                return
            proceeds = position * exit_price * (1 - commission)
            cost_basis = position * entry_price
            trades.append((proceeds - cost_basis) / cost_basis if cost_basis else 0.0)
            cash += proceeds
            position = 0.0
            entry_price = 0.0
            long_stop = 0.0

        for i in range(len(df) - 1):
            next_open = float(df["open"].iloc[i + 1])
            bar_low = float(df["low"].iloc[i])

            if position > 0 and long_stop > 0 and bar_low <= long_stop:
                _close_position(next_open)

            if position <= 0:
                action = signals.iloc[i]
                if action == "buy":
                    if use_atr and atr_series is not None:
                        atr_i = float(atr_series.iloc[i])
                        if atr_i > 0 and not pd.isna(atr_i):
                            max_val = initial_capital * float(
                                settings.get("max_single_position_pct", 0.30)
                            )
                            units = compute_atr_risk_units(
                                initial_capital,
                                atr_i,
                                next_open,
                                max_position_value=min(max_val, cash),
                            )
                            cost = units * next_open * (1 + commission)
                            if units > 0 and cost <= cash:
                                position = units
                                entry_price = next_open
                                cash -= cost
                                long_stop = atr_stop_price(entry_price, atr_i)
                    else:
                        position = cash * (1 - commission) / next_open
                        entry_price = next_open
                        cash = 0.0
                        long_stop = 0.0
            elif signals.iloc[i] == "sell" and position > 0:
                _close_position(next_open)

            if position > 0 and use_atr and atr_series is not None:
                atr_i = float(atr_series.iloc[i])
                close_i = float(df["close"].iloc[i])
                if atr_i > 0 and not pd.isna(atr_i) and close_i > 0:
                    candidate = trailing_stop_candidate(close_i, atr_i)
                    long_stop = max(long_stop, candidate) if long_stop > 0 else candidate

            mark = cash + position * float(df["close"].iloc[i])
            equity.append(mark)

        if position > 0:
            last = float(df["close"].iloc[-1])
            _close_position(last)
            equity.append(cash)
        elif equity:
            equity.append(equity[-1])
        else:
            equity.append(initial_capital)

        eq_series = pd.Series(equity)
        return compute_metrics(eq_series, trades, _bars_per_year(interval))
