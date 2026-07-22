from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

import pandas as pd

from quant_picker.portfolio.position_sizer import (
    advance_trailing_stop,
    atr_stop_price,
    get_position_sizing_config,
)
from quant_picker.storage.models import StrategyPosition, WatchlistItem
from quant_picker.storage.repository import Repository
from quant_picker.strategies.base import Signal
from quant_picker.strategies.indicators import atr as calc_atr


@dataclass
class PositionSnapshot:
    entry_price: float
    entry_shares: int
    entry_atr: float | None = None
    trailing_stop: float | None = None
    manual_override: bool = False


def watchlist_manual_snapshot(item: WatchlistItem | None) -> PositionSnapshot | None:
    if (
        item is None
        or not item.position_manual_override
        or item.position_entry_shares <= 0
        or item.position_entry_price <= 0
    ):
        return None
    return PositionSnapshot(
        entry_price=float(item.position_entry_price),
        entry_shares=int(item.position_entry_shares),
        entry_atr=item.position_entry_atr,
        trailing_stop=item.position_trailing_stop,
        manual_override=True,
    )


def strategy_position_snapshot(row: StrategyPosition | None) -> PositionSnapshot | None:
    if row is None or row.entry_shares <= 0 or row.entry_price <= 0:
        return None
    return PositionSnapshot(
        entry_price=float(row.entry_price),
        entry_shares=int(row.entry_shares),
        entry_atr=row.entry_atr,
        trailing_stop=row.trailing_stop,
        manual_override=bool(row.manual_override),
    )


def resolve_position(
    repo: Repository,
    watchlist_id: int,
    strategy_name: str,
) -> PositionSnapshot | None:
    item = repo.get_watchlist_by_id(watchlist_id)
    manual = watchlist_manual_snapshot(item)
    if manual is not None:
        return manual
    return strategy_position_snapshot(repo.get_strategy_position(watchlist_id, strategy_name))


def atr_at_bar(
    df: pd.DataFrame,
    bar_time: datetime,
    period: int,
) -> float | None:
    if df.empty:
        return None
    ts = pd.Timestamp(bar_time)
    if ts not in df.index:
        idx = int(df.index.searchsorted(ts, side="right")) - 1
        if idx < 0:
            return None
        ts = df.index[idx]
    loc = df.index.get_loc(ts)
    if isinstance(loc, slice):
        loc = loc.start
    sub = df.iloc[: loc + 1]
    if len(sub) < period + 1:
        return None
    series = calc_atr(sub["high"], sub["low"], sub["close"], period)
    val = series.iloc[-1]
    if val is None or pd.isna(val):
        return None
    return float(val)


def refresh_trailing_stop(
    position: PositionSnapshot | StrategyPosition,
    close: float,
    atr_latest: float | None,
) -> float | None:
    """Compute ratcheted trailing stop from latest close and ATR."""
    stored = getattr(position, "trailing_stop", None)
    if atr_latest and atr_latest > 0 and close > 0:
        return advance_trailing_stop(
            stored,
            close,
            atr_latest,
            entry_price=position.entry_price,
            entry_atr=position.entry_atr,
        )
    if stored and stored > 0:
        return float(stored)
    if position.entry_atr and position.entry_atr > 0:
        return atr_stop_price(position.entry_price, position.entry_atr)
    return None


def persist_trailing_stop(
    repo: Repository,
    watchlist_id: int,
    strategy_name: str,
    position: PositionSnapshot,
    close: float,
    atr_latest: float | None,
) -> PositionSnapshot:
    """Advance trailing stop with latest ATR and persist when holding."""
    if position.entry_shares <= 0 or close <= 0:
        return position
    new_stop = refresh_trailing_stop(position, close, atr_latest)
    if new_stop is None or new_stop <= 0:
        return position
    if position.trailing_stop != new_stop:
        repo.update_position_trailing_stop(watchlist_id, strategy_name, new_stop)
    position.trailing_stop = new_stop
    return position


def effective_stop_price(position: PositionSnapshot | StrategyPosition | None) -> float | None:
    if position is None or position.entry_shares <= 0:
        return None
    stop = getattr(position, "trailing_stop", None)
    if stop and stop > 0:
        return float(stop)
    if position.entry_atr and position.entry_atr > 0:
        return atr_stop_price(position.entry_price, position.entry_atr)
    return None


def apply_atr_stop_signal(
    signal: Signal,
    position: PositionSnapshot | StrategyPosition | None,
    close: float,
) -> Signal:
    """Override to sell when close is at or below trailing ATR stop."""
    if get_position_sizing_config().get("mode") != "atr_risk":
        return signal
    if position is None or position.entry_shares <= 0 or position.entry_price <= 0:
        return signal

    stop = effective_stop_price(position)
    if stop is None or stop <= 0:
        return signal

    if close <= stop:
        cfg = get_position_sizing_config()
        return Signal(
            "sell",
            0.85,
            (
                f"ATR移动止损：收盘 {close:.2f} ≤ 止损 {stop:.2f} "
                f"（{cfg['stop_atr_mult']:.0f}×最新ATR，入场 {position.entry_price:.2f}，"
                f"{position.entry_shares}股）"
            ),
        )
    return signal


def sell_amount_from_position(
    position: PositionSnapshot | StrategyPosition | None,
    price: float | None,
) -> tuple[float, int]:
    if (
        position is None
        or position.entry_shares <= 0
        or not price
        or price <= 0
    ):
        return 0.0, 0
    shares = int(position.entry_shares)
    return round(shares * price, 2), shares


class PositionTracker:
    def __init__(self, repo: Repository):
        self.repo = repo

    def sync_after_signal(
        self,
        watchlist_id: int,
        strategy_name: str,
        signal: Signal,
        *,
        entry_price: float | None,
        entry_shares: int,
        entry_atr: float | None,
        bar_time: datetime | None,
    ) -> None:
        """Update stored position from finalized daily signal."""
        item = self.repo.get_watchlist_by_id(watchlist_id)
        if item and item.position_manual_override:
            if signal.action == "sell":
                self.repo.clear_watchlist_manual_position(watchlist_id)
            return

        existing = self.repo.get_strategy_position(watchlist_id, strategy_name)

        if signal.action == "sell":
            self.repo.clear_strategy_position(watchlist_id, strategy_name)
            return

        if signal.action != "buy":
            return

        if not entry_price or entry_price <= 0 or entry_shares <= 0:
            return

        initial_stop = (
            atr_stop_price(entry_price, entry_atr) if entry_atr and entry_atr > 0 else None
        )
        self.repo.upsert_strategy_position(
            watchlist_id,
            strategy_name,
            entry_price=entry_price,
            entry_shares=entry_shares,
            entry_atr=entry_atr,
            entry_bar_time=bar_time,
            manual_override=False,
            trailing_stop=initial_stop,
        )

    def restore_from_last_buy(
        self,
        watchlist_id: int,
        strategy_name: str,
        df: pd.DataFrame | None = None,
    ) -> StrategyPosition | None:
        rec = self.repo.last_buy_recommendation(watchlist_id, strategy_name)
        if rec is None or rec.shares <= 0 or rec.amount <= 0:
            return None

        entry_price = round(rec.amount / rec.shares, 4)
        period = get_position_sizing_config()["atr_period"]
        entry_atr = atr_at_bar(df, rec.bar_time, period) if df is not None else None
        if entry_atr is None:
            existing = self.repo.get_strategy_position(watchlist_id, strategy_name)
            if existing and existing.entry_bar_time == rec.bar_time and existing.entry_atr:
                entry_atr = existing.entry_atr

        initial_stop = (
            atr_stop_price(entry_price, entry_atr) if entry_atr and entry_atr > 0 else None
        )
        return self.repo.upsert_strategy_position(
            watchlist_id,
            strategy_name,
            entry_price=entry_price,
            entry_shares=int(rec.shares),
            entry_atr=entry_atr,
            entry_bar_time=rec.bar_time,
            manual_override=False,
            trailing_stop=initial_stop,
        )
