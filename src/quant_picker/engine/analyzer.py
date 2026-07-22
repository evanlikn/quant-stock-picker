from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

import pandas as pd

from quant_picker.backtest.report import BacktestReport
from quant_picker.config import load_settings, load_strategies_config
from quant_picker.data.bar_sync import BarSyncService
from quant_picker.data.registry import get_provider
from quant_picker.market.detector import Market, detect_market, normalize_symbol
from quant_picker.engine.position_tracker import (
    apply_atr_stop_signal,
    persist_trailing_stop,
    resolve_position,
    sell_amount_from_position,
)
from quant_picker.portfolio.position_sizer import PositionSizer, get_position_sizing_config
from quant_picker.storage.repository import Repository
from quant_picker.strategies.registry import build_strategy, list_enabled_strategies
from quant_picker.strategies.indicators import atr as calc_atr


@dataclass
class StrategyAdvice:
    strategy_name: str
    signal: Any
    amount: float
    shares: int
    params: dict[str, Any]
    params_display: str
    oos_backtest: BacktestReport | None
    confidence: str
    optimized: bool = False


@dataclass
class AnalysisResult:
    symbol: str
    market: str
    interval: str
    bar_time: datetime | None
    advices: list[StrategyAdvice] = field(default_factory=list)
    df: pd.DataFrame | None = None
    message: str = ""


def _report_from_dict(d: dict[str, Any], fold_count: int = 0) -> BacktestReport:
    return BacktestReport(
        total_return=float(d.get("total_return", 0)),
        win_rate=float(d.get("win_rate", 0)),
        trade_count=int(d.get("trade_count", 0)),
        max_drawdown=float(d.get("max_drawdown", 0)),
        sharpe_ratio=float(d.get("sharpe_ratio", 0)),
        profit_factor=float(d.get("profit_factor", 0)),
        fold_count=fold_count or int(d.get("fold_count", 0)),
    )


def _confidence_from_oos(oos: BacktestReport | None) -> str:
    if oos is None or oos.fold_count < 3:
        return "low"
    bt = load_settings().get("backtest", {})
    if oos.win_rate >= bt.get("high_win_rate", 0.55) and oos.max_drawdown > -bt.get(
        "max_drawdown_warn", 0.30
    ):
        return "high"
    if oos.win_rate < bt.get("low_win_rate", 0.40):
        return "low"
    return "medium"


class Analyzer:
    def __init__(self, repo: Repository | None = None):
        self.repo = repo
        self.sizer = PositionSizer()

    def analyze_instant(
        self,
        symbol: str,
        interval: str = "1d",
        market: str | None = None,
    ) -> AnalysisResult:
        m = detect_market(symbol, market)
        sym = normalize_symbol(symbol, m)
        if self.repo is not None:
            sync = BarSyncService(self.repo)
            df, _ = sync.sync(sym, m.value, interval, min_bars=1)
        else:
            provider = get_provider(m)
            df = provider.fetch_bars(sym, interval)
        advices = []
        atr_period = get_position_sizing_config()["atr_period"]
        atr_last = None
        if not df.empty and len(df) >= atr_period + 1:
            atr_series = calc_atr(df["high"], df["low"], df["close"], atr_period)
            val = atr_series.iloc[-1]
            if val is not None and not pd.isna(val):
                atr_last = float(val)

        for strat in list_enabled_strategies(interval):
            sig = strat.analyze(df)
            price = float(df["close"].iloc[-1]) if not df.empty else None
            conf = "medium"
            pos = self.sizer.compute(sig, m, conf, price, atr=atr_last)
            advices.append(
                StrategyAdvice(
                    strategy_name=strat.name,
                    signal=sig,
                    amount=pos.amount,
                    shares=pos.shares,
                    params=strat._params,  # type: ignore[attr-defined]
                    params_display=strat.format_params(),
                    oos_backtest=None,
                    confidence=conf,
                    optimized=False,
                )
            )
        bar_time = pd.Timestamp(df.index.max()).to_pydatetime() if not df.empty else None
        return AnalysisResult(
            symbol=sym,
            market=m.value,
            interval=interval,
            bar_time=bar_time,
            advices=advices,
            df=df,
            message="未逐股优化（即时分析使用 YAML 默认参数）",
        )

    def analyze_watchlist_item(self, item, *, sync_remote: bool = True) -> AnalysisResult:
        assert self.repo is not None
        if sync_remote:
            sync = BarSyncService(self.repo)
            df, _ = sync.sync(item.symbol, item.market, item.interval)
        else:
            df = self.repo.load_bars(item.symbol, item.market, item.interval)

        m = Market(item.market)
        advices = []
        atr_period = get_position_sizing_config()["atr_period"]
        atr_last = None
        if not df.empty and len(df) >= atr_period + 1:
            atr_series = calc_atr(df["high"], df["low"], df["close"], atr_period)
            val = atr_series.iloc[-1]
            if val is not None and not pd.isna(val):
                atr_last = float(val)

        for sc in load_strategies_config().get("strategies", []):
            if not sc.get("enabled", True):
                continue
            name = sc["name"]
            adaptive = self.repo.get_adaptive_params(
                item.symbol, item.market, item.interval, name
            )
            if adaptive:
                params = json.loads(adaptive.params_json)
                oos = _report_from_dict(
                    json.loads(adaptive.oos_metrics_json), adaptive.fold_count
                )
                optimized = True
            else:
                params = sc.get("default_params_by_interval", {}).get(item.interval, {})
                oos = None
                optimized = False
            strat = build_strategy(name, item.interval, params)
            sig = strat.analyze(df)
            close = float(df["close"].iloc[-1]) if not df.empty else None
            position = resolve_position(self.repo, item.id, name)
            if close is not None and position is not None and atr_last is not None:
                position = persist_trailing_stop(
                    self.repo, item.id, name, position, close, atr_last
                )
            if close is not None:
                sig = apply_atr_stop_signal(sig, position, close)

            conf = _confidence_from_oos(oos)
            if sig.action == "sell":
                amount, shares = sell_amount_from_position(position, close)
                if shares <= 0:
                    pos = self.sizer.compute(sig, m, conf, close, atr=atr_last)
                    amount, shares = pos.amount, pos.shares
            elif sig.action == "buy":
                pos = self.sizer.compute(sig, m, conf, close, atr=atr_last)
                amount, shares = pos.amount, pos.shares
            else:
                amount, shares = 0.0, 0

            advices.append(
                StrategyAdvice(
                    strategy_name=name,
                    signal=sig,
                    amount=amount,
                    shares=shares,
                    params=params,
                    params_display=strat.format_params(),
                    oos_backtest=oos,
                    confidence=conf,
                    optimized=optimized,
                )
            )
        bar_time = pd.Timestamp(df.index.max()).to_pydatetime() if not df.empty else None
        return AnalysisResult(
            symbol=item.symbol,
            market=item.market,
            interval=item.interval,
            bar_time=bar_time,
            advices=advices,
            df=df,
            message="",
        )
