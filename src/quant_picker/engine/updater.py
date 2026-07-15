from __future__ import annotations

import json
from datetime import datetime

import pandas as pd

from quant_picker.engine.analyzer import Analyzer
from quant_picker.notifications.dispatcher import NotificationDispatcher
from quant_picker.optimization.trainer import Trainer, should_retrain
from quant_picker.storage.models import WatchlistItem
from quant_picker.storage.repository import Repository


class Updater:
    def __init__(self, repo: Repository):
        self.repo = repo
        self.trainer = Trainer(repo)
        self.analyzer = Analyzer(repo)
        self.notifier = NotificationDispatcher(repo)

    def update_watchlist_item(
        self, item: WatchlistItem, force_retrain: bool = False
    ) -> WatchlistItem:
        prev_recs = self.repo.latest_recommendations(item.id)
        prev_map = {r.strategy_name: r for r in prev_recs}

        if force_retrain or should_retrain(item):
            item = self.trainer.run_walk_forward(item, force=force_retrain)
        else:
            self.trainer.fetch_and_store_bars(item)

        if item.wfo_status != "done":
            return item

        result = self.analyzer.analyze_watchlist_item(item)
        if result.bar_time is None:
            return item

        new_recs = []
        for adv in result.advices:
            oos_snap = adv.oos_backtest.to_dict() if adv.oos_backtest else {}
            rec = self.repo.save_recommendation(
                watchlist_id=item.id,
                strategy_name=adv.strategy_name,
                bar_time=result.bar_time,
                action=adv.signal.action,
                strength=adv.signal.strength,
                amount=adv.amount,
                shares=adv.shares,
                reason=adv.signal.reason,
                params_snapshot=adv.params,
                oos_snapshot=oos_snap,
            )
            if rec:
                new_recs.append(rec)

        item.last_run_at = datetime.utcnow()
        self.repo.update_watchlist(item)

        if new_recs and result.bar_time is not None:
            ref_price = (
                float(result.df["close"].iloc[-1])
                if result.df is not None and not result.df.empty
                else None
            )
            self.notifier.notify_after_update(
                item,
                new_recs,
                list(prev_map.values()),
                result.bar_time,
                ref_price,
            )

        return item

    def update_all_enabled(self) -> int:
        count = 0
        for item in self.repo.list_watchlist(enabled_only=True):
            try:
                self.update_watchlist_item(item)
                count += 1
            except Exception:
                continue
        return count
