from __future__ import annotations

from datetime import datetime

import pandas as pd

from quant_picker.backtest.walk_forward import WalkForwardEngine
from quant_picker.backtest.wfo_windows import parse_window_days
from quant_picker.config import load_settings, load_strategies_config
from quant_picker.data.bar_sync import BarSyncService
from quant_picker.data.symbol_validate import validate_symbol
from quant_picker.market.detector import Market
from quant_picker.storage.models import WatchlistItem
from quant_picker.storage.repository import Repository


def should_retrain(item: WatchlistItem) -> bool:
    if item.wfo_status in ("pending", "failed") or item.last_optimized_at is None:
        return True
    cycle = item.retrain_cycle_bars
    if cycle is None:
        settings = load_settings()
        cycle = parse_window_days(
            settings.get("walk_forward", {}).get("step_bars", {}).get(item.interval, 20)
        )
    return item.bars_since_optimization >= cycle


class Trainer:
    def __init__(self, repo: Repository):
        self.repo = repo
        self.wfo = WalkForwardEngine()
        self.settings = load_settings()
        self.bar_sync = BarSyncService(repo)

    def _min_bars_needed(self, interval: str) -> int:
        return self.bar_sync.min_bars_for_wfo(interval)

    def fetch_and_store_bars(
        self, item: WatchlistItem, force_full: bool = False
    ) -> pd.DataFrame:
        stored, new_count = self.bar_sync.sync(
            item.symbol,
            item.market,
            item.interval,
            min_bars=self._min_bars_needed(item.interval),
            force_full=force_full,
            item=item,
        )
        if not stored.empty:
            latest = pd.Timestamp(stored.index.max()).to_pydatetime()
            if item.last_optimized_at is not None and new_count > 0:
                item.bars_since_optimization += new_count
            item.last_bar_time = latest
            self.repo.update_watchlist(item)
        return stored

    def run_walk_forward(
        self, item: WatchlistItem, force: bool = False
    ) -> WatchlistItem:
        if item.wfo_status == "running" and not force:
            return item

        item.wfo_status = "running"
        self.repo.update_watchlist(item)

        try:
            validate_symbol(item.symbol, Market(item.market))
            df = self.fetch_and_store_bars(item)
            if df.empty or len(df) < 50:
                item.wfo_status = "failed"
                self.repo.update_watchlist(item)
                return item

            strategies_cfg = [
                s["name"]
                for s in load_strategies_config().get("strategies", [])
                if s.get("enabled", True)
            ]
            proxy = strategies_cfg[0] if strategies_cfg else "ma_cross"
            best_step, _ = self.wfo.find_best_step_bars(df, proxy, item.interval)

            for name in strategies_cfg:
                params, report = self.wfo.run_for_strategy(
                    df, name, item.interval, step_bars=best_step
                )
                self.repo.upsert_adaptive_params(
                    item.symbol,
                    item.market,
                    item.interval,
                    name,
                    params,
                    report.to_dict(),
                    report.fold_count,
                )
                self.repo.save_backtest_result(
                    item.symbol,
                    item.market,
                    item.interval,
                    name,
                    report.to_dict(),
                )

            item.retrain_cycle_bars = best_step
            item.retrain_cycle_source = "wfo"
            item.last_optimized_at = datetime.utcnow()
            if not df.empty:
                item.last_optimized_bar_time = pd.Timestamp(df.index.max()).to_pydatetime()
            item.bars_since_optimization = 0
            item.wfo_status = "done"
        except Exception:
            item.wfo_status = "failed"
            self.repo.session.rollback()
            raise
        finally:
            try:
                self.repo.update_watchlist(item)
            except Exception:
                self.repo.session.rollback()
                raise
        return item
