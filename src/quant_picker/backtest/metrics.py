from __future__ import annotations

import math

import numpy as np
import pandas as pd

from quant_picker.backtest.report import BacktestReport


def compute_metrics(equity: pd.Series, trades: list[float], bars_per_year: int = 252) -> BacktestReport:
    if equity.empty:
        return BacktestReport()
    returns = equity.pct_change().dropna()
    total_return = float(equity.iloc[-1] / equity.iloc[0] - 1) if equity.iloc[0] else 0.0
    peak = equity.cummax()
    drawdown = (equity - peak) / peak
    max_dd = float(drawdown.min()) if len(drawdown) else 0.0
    wins = [t for t in trades if t > 0]
    losses = [t for t in trades if t < 0]
    win_rate = len(wins) / len(trades) if trades else 0.0
    gross_profit = sum(wins)
    gross_loss = abs(sum(losses))
    pf = gross_profit / gross_loss if gross_loss > 0 else (float("inf") if gross_profit > 0 else 0.0)
    sharpe = 0.0
    if len(returns) > 1 and returns.std() > 0:
        sharpe = float(returns.mean() / returns.std() * math.sqrt(bars_per_year))
    return BacktestReport(
        total_return=total_return,
        win_rate=win_rate,
        trade_count=len(trades),
        max_drawdown=max_dd,
        sharpe_ratio=sharpe,
        profit_factor=pf if pf != float("inf") else 999.0,
        equity_curve=equity.tolist(),
    )


def aggregate_oos_reports(reports: list[BacktestReport]) -> BacktestReport:
    if not reports:
        return BacktestReport()
    n = len(reports)
    agg = BacktestReport(
        total_return=sum(r.total_return for r in reports) / n,
        win_rate=sum(r.win_rate for r in reports) / n,
        trade_count=int(sum(r.trade_count for r in reports) / n),
        max_drawdown=min(r.max_drawdown for r in reports),
        sharpe_ratio=sum(r.sharpe_ratio for r in reports) / n,
        profit_factor=sum(r.profit_factor for r in reports) / n,
        fold_count=n,
        fold_metrics=[r.to_dict() for r in reports],
    )
    curves = []
    for r in reports:
        curves.extend(r.equity_curve)
    agg.equity_curve = curves
    return agg
