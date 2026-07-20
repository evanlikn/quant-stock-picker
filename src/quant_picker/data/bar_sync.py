from __future__ import annotations

import pandas as pd

from quant_picker.backtest.wfo_windows import min_trading_bars_for_wfo
from quant_picker.config import load_settings
from quant_picker.data.bars_util import prepare_ohlcv
from quant_picker.data.registry import get_provider
from quant_picker.market.detector import Market
from quant_picker.storage.repository import Repository


class BarSyncService:
    """Load OHLCV from DB first; fetch missing history or incremental bars from providers."""

    def __init__(self, repo: Repository):
        self.repo = repo
        self.settings = load_settings()

    def min_bars_for_wfo(self, interval: str) -> int:
        return min_trading_bars_for_wfo(interval)

    def sync(
        self,
        symbol: str,
        market: str,
        interval: str,
        *,
        min_bars: int | None = None,
        force_full: bool = False,
    ) -> tuple[pd.DataFrame, int]:
        """
        Ensure local DB has enough bars for analysis/WFO.

        Returns (bars dataframe, newly_inserted_count).
        """
        min_needed = min_bars or self.min_bars_for_wfo(interval)
        before = self.repo.count_bars(symbol, market, interval)
        stored = self.repo.load_bars(symbol, market, interval)
        provider = get_provider(Market(market))

        need_full = force_full or before == 0 or before < min_needed
        try:
            if need_full:
                remote = provider.fetch_bars(symbol, interval, start=None)
                clean, _ = prepare_ohlcv(
                    remote, interval, trim_history=False, ensure_continuous=True
                )
                self.repo.replace_bars(symbol, market, interval, clean)
            else:
                latest = self.repo.latest_bar_time(symbol, market, interval)
                remote = provider.fetch_bars(symbol, interval, start=latest)
                if not remote.empty:
                    self.repo.save_bars(symbol, market, interval, remote)
        except Exception:
            if before >= min_needed and not stored.empty:
                return stored, 0
            raise

        stored = self.repo.load_bars(symbol, market, interval)
        inserted = self.repo.count_bars(symbol, market, interval) - before
        return stored, max(inserted, 0)
