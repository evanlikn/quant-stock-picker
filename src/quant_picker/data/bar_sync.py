from __future__ import annotations

import pandas as pd

from quant_picker.backtest.wfo_windows import min_trading_bars_for_wfo
from quant_picker.config import load_settings
from quant_picker.data.bars_util import (
    effective_history_days,
    history_fetch_start,
    initial_history_days,
    prepare_ohlcv,
    trim_bars,
    trim_to_history_days,
)
from quant_picker.data.registry import get_provider
from quant_picker.market.detector import Market
from quant_picker.storage.models import WatchlistItem
from quant_picker.storage.repository import Repository


class BarSyncService:
    """Load OHLCV from DB first; fetch missing history or incremental bars from providers."""

    def __init__(self, repo: Repository):
        self.repo = repo
        self.settings = load_settings()

    def min_bars_for_wfo(self, interval: str) -> int:
        return min_trading_bars_for_wfo(interval)

    def _resolve_history_days(
        self,
        interval: str,
        history_days: int | None,
        item: WatchlistItem | None,
    ) -> int:
        if history_days is not None and history_days > 0:
            return int(history_days)
        if item is not None:
            return effective_history_days(item)
        return initial_history_days(interval)

    def _enforce_history_window(
        self,
        symbol: str,
        market: str,
        interval: str,
        history_days: int,
    ) -> pd.DataFrame:
        stored = self.repo.load_bars(symbol, market, interval)
        if stored.empty:
            return stored
        trimmed = trim_to_history_days(stored, history_days)
        if len(trimmed) < len(stored):
            self.repo.replace_bars(symbol, market, interval, trimmed)
            return trimmed
        return stored

    def sync(
        self,
        symbol: str,
        market: str,
        interval: str,
        *,
        min_bars: int | None = None,
        force_full: bool = False,
        history_days: int | None = None,
        item: WatchlistItem | None = None,
    ) -> tuple[pd.DataFrame, int]:
        """
        Ensure local DB has enough bars for analysis/WFO.

        Returns (bars dataframe, newly_inserted_count).
        """
        window_days = self._resolve_history_days(interval, history_days, item)
        min_needed = min_bars or self.min_bars_for_wfo(interval)
        before = self.repo.count_bars(symbol, market, interval)
        stored = self.repo.load_bars(symbol, market, interval)
        provider = get_provider(Market(market))

        need_full = force_full or before == 0 or before < min_needed
        try:
            if need_full:
                start = history_fetch_start(window_days)
                remote = provider.fetch_bars(symbol, interval, start=start)
                clean, _ = prepare_ohlcv(
                    remote, interval, trim_history=False, ensure_continuous=True
                )
                clean = trim_bars(
                    clean,
                    interval,
                    start=None,
                    end=None,
                    history_days=window_days,
                )
                self.repo.replace_bars(symbol, market, interval, clean)
            else:
                latest = self.repo.latest_bar_time(symbol, market, interval)
                remote = provider.fetch_bars(symbol, interval, start=latest)
                if not remote.empty:
                    self.repo.save_bars(symbol, market, interval, remote)
                self._enforce_history_window(symbol, market, interval, window_days)
        except Exception:
            if before >= min_needed and not stored.empty:
                return stored, 0
            raise

        stored = self.repo.load_bars(symbol, market, interval)
        inserted = self.repo.count_bars(symbol, market, interval) - before
        return stored, max(inserted, 0)
