from __future__ import annotations

import json
from datetime import date, datetime, time
from typing import Any

import pandas as pd
from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from quant_picker.data.bars_util import prepare_ohlcv
from quant_picker.storage.models import (
    AdaptiveStrategyParams,
    BacktestResult,
    Bar,
    NotificationLog,
    Recommendation,
    ScreenerResult,
    ScreenerRun,
    StrategyPosition,
    WatchlistItem,
)

# SQLite SQLITE_MAX_VARIABLE_NUMBER defaults to 999; Bar rows use 9 columns each.
_BAR_INSERT_BATCH = 100


class Repository:
    """Data access layer.

    Market data (bars, walk-forward params, backtests, screener runs) is shared
    by everyone; watchlists and everything hanging off them are per-user. Pass
    ``user_id`` from the web layer so a request can never touch another
    account's rows. The scheduler runs system-wide and leaves it unset.
    """

    def __init__(self, session: Session, user_id: int | None = None):
        self.session = session
        self.user_id = user_id

    def for_user(self, user_id: int) -> "Repository":
        return Repository(self.session, user_id)

    def _require_user(self) -> int:
        if self.user_id is None:
            raise PermissionError("该操作需要用户上下文（Repository 未绑定 user_id）")
        return self.user_id

    def _owns(self, item: WatchlistItem | None) -> bool:
        if item is None:
            return False
        return self.user_id is None or item.user_id == self.user_id

    def _assert_owns(self, watchlist_id: int) -> None:
        """Reject watchlist ids belonging to another account."""
        if self.user_id is None:
            return
        owner = self.session.scalar(
            select(WatchlistItem.user_id).where(WatchlistItem.id == watchlist_id)
        )
        if owner != self.user_id:
            raise PermissionError(f"无权访问自选 {watchlist_id}")

    def _own_watchlist_ids(self):
        """Subquery of the current user's watchlist ids, or None when unscoped."""
        if self.user_id is None:
            return None
        return select(WatchlistItem.id).where(WatchlistItem.user_id == self.user_id)

    # --- Watchlist ---
    def add_watchlist(
        self,
        symbol: str,
        market: str,
        interval: str,
        notify_enabled: bool = False,
        display_name: str | None = None,
        history_days: int | None = None,
    ) -> WatchlistItem:
        user_id = self._require_user()
        existing = self.get_watchlist(symbol, market, interval)
        if existing:
            if display_name and not existing.display_name:
                existing.display_name = display_name
                self.update_watchlist(existing)
            return existing
        item = WatchlistItem(
            user_id=user_id,
            symbol=symbol,
            market=market,
            interval=interval,
            notify_enabled=notify_enabled,
            display_name=display_name,
            history_days=int(history_days) if history_days and history_days > 0 else None,
            wfo_status="pending",
        )
        self.session.add(item)
        self.session.commit()
        self.session.refresh(item)
        return item

    def get_watchlist(self, symbol: str, market: str, interval: str) -> WatchlistItem | None:
        q = select(WatchlistItem).where(
            WatchlistItem.symbol == symbol,
            WatchlistItem.market == market,
            WatchlistItem.interval == interval,
        )
        if self.user_id is not None:
            q = q.where(WatchlistItem.user_id == self.user_id)
        return self.session.scalar(q)

    def get_watchlist_by_id(self, item_id: int) -> WatchlistItem | None:
        item = self.session.get(WatchlistItem, item_id)
        return item if self._owns(item) else None

    def list_watchlist(self, enabled_only: bool = False) -> list[WatchlistItem]:
        q = select(WatchlistItem)
        if self.user_id is not None:
            q = q.where(WatchlistItem.user_id == self.user_id)
        if enabled_only:
            q = q.where(WatchlistItem.enabled.is_(True))
        return list(self.session.scalars(q.order_by(WatchlistItem.added_at.desc())))

    def list_all_watchlist(self, enabled_only: bool = False) -> list[WatchlistItem]:
        """Every user's items; for the scheduler, which has no user context."""
        q = select(WatchlistItem)
        if enabled_only:
            q = q.where(WatchlistItem.enabled.is_(True))
        return list(self.session.scalars(q.order_by(WatchlistItem.added_at.desc())))

    def distinct_watchlist_symbols(self, enabled_only: bool = True) -> list[tuple[str, str, str]]:
        """Unique (symbol, market, interval) triples across all users.

        Market data is shared, so syncing bars once per triple avoids repeating
        the same download for every user watching the same stock.
        """
        q = select(
            WatchlistItem.symbol, WatchlistItem.market, WatchlistItem.interval
        ).distinct()
        if enabled_only:
            q = q.where(WatchlistItem.enabled.is_(True))
        return [tuple(row) for row in self.session.execute(q)]

    def shared_retrain_cycle(
        self, symbol: str, market: str, interval: str, exclude_id: int | None = None
    ) -> int | None:
        """Retrain cadence another row already derived for the same instrument.

        Walk-forward picks the cadence from the price series, which is shared, so
        a new row for an already-trained stock can inherit it instead of showing
        an unknown cycle until its first optimization.
        """
        q = select(WatchlistItem.retrain_cycle_bars).where(
            WatchlistItem.symbol == symbol,
            WatchlistItem.market == market,
            WatchlistItem.interval == interval,
            WatchlistItem.retrain_cycle_source == "wfo",
            WatchlistItem.retrain_cycle_bars.is_not(None),
        )
        if exclude_id is not None:
            q = q.where(WatchlistItem.id != exclude_id)
        return self.session.scalar(q.limit(1))

    def update_watchlist(self, item: WatchlistItem) -> None:
        if not self._owns(item):
            raise PermissionError("无权修改他人的自选")
        self.session.add(item)
        self.session.commit()

    def delete_watchlist(self, item_id: int) -> None:
        item = self.get_watchlist_by_id(item_id)
        if item:
            self.session.execute(
                delete(StrategyPosition).where(StrategyPosition.watchlist_id == item_id)
            )
            self.session.execute(
                delete(Recommendation).where(Recommendation.watchlist_id == item_id)
            )
            self.session.execute(
                delete(NotificationLog).where(NotificationLog.watchlist_id == item_id)
            )
            self.session.delete(item)
            self.session.commit()

    # --- Bars ---
    def count_bars(self, symbol: str, market: str, interval: str) -> int:
        return int(
            self.session.scalar(
                select(func.count())
                .select_from(Bar)
                .where(
                    Bar.symbol == symbol,
                    Bar.market == market,
                    Bar.interval == interval,
                )
            )
            or 0
        )

    def latest_bar_time(
        self, symbol: str, market: str, interval: str
    ) -> datetime | None:
        row = self.session.scalar(
            select(Bar.bar_time)
            .where(
                Bar.symbol == symbol,
                Bar.market == market,
                Bar.interval == interval,
            )
            .order_by(Bar.bar_time.desc())
            .limit(1)
        )
        return row

    def _bar_records_from_df(
        self, symbol: str, market: str, interval: str, df: pd.DataFrame
    ) -> list[dict]:
        records = []
        for ts, row in df.iterrows():
            records.append(
                {
                    "symbol": symbol,
                    "market": market,
                    "interval": interval,
                    "bar_time": pd.Timestamp(ts).to_pydatetime(),
                    "open": float(row["open"]),
                    "high": float(row["high"]),
                    "low": float(row["low"]),
                    "close": float(row["close"]),
                    "volume": float(row["volume"]),
                }
            )
        return records

    def save_bars(
        self, symbol: str, market: str, interval: str, df: pd.DataFrame
    ) -> int:
        if df.empty:
            return 0

        records = self._bar_records_from_df(symbol, market, interval, df)
        if not records:
            return 0

        try:
            total_inserted = self._insert_bar_batches(records)
            self.session.commit()
            return total_inserted
        except Exception:
            self.session.rollback()
            raise

    def _insert_bar_batches(self, records: list[dict]) -> int:
        dialect = self.session.get_bind().dialect.name
        if dialect == "postgresql":
            from sqlalchemy.dialects.postgresql import insert as dialect_insert
        else:
            from sqlalchemy.dialects.sqlite import insert as dialect_insert

        batch_size = _BAR_INSERT_BATCH if dialect == "sqlite" else len(records)
        total_inserted = 0
        for i in range(0, len(records), batch_size):
            chunk = records[i : i + batch_size]
            stmt = dialect_insert(Bar).values(chunk)
            if dialect == "postgresql":
                stmt = stmt.on_conflict_do_nothing(constraint="uq_bar")
            else:
                stmt = stmt.on_conflict_do_nothing(
                    index_elements=["symbol", "market", "interval", "bar_time"]
                )
            result = self.session.execute(stmt)
            if result.rowcount and result.rowcount > 0:
                total_inserted += int(result.rowcount)
        return total_inserted

    def replace_bars(
        self, symbol: str, market: str, interval: str, df: pd.DataFrame
    ) -> int:
        """Replace all stored bars with a cleaned continuous segment."""
        if df.empty:
            return 0

        records = self._bar_records_from_df(symbol, market, interval, df)
        if not records:
            return 0

        try:
            self.session.execute(
                delete(Bar).where(
                    Bar.symbol == symbol,
                    Bar.market == market,
                    Bar.interval == interval,
                )
            )
            total_inserted = self._insert_bar_batches(records)
            self.session.commit()
            return total_inserted
        except Exception:
            self.session.rollback()
            raise

    def load_bars(
        self, symbol: str, market: str, interval: str
    ) -> pd.DataFrame:
        rows = self.session.scalars(
            select(Bar)
            .where(
                Bar.symbol == symbol,
                Bar.market == market,
                Bar.interval == interval,
            )
            .order_by(Bar.bar_time)
        ).all()
        if not rows:
            return pd.DataFrame()
        data = {
            "open": [r.open for r in rows],
            "high": [r.high for r in rows],
            "low": [r.low for r in rows],
            "close": [r.close for r in rows],
            "volume": [r.volume for r in rows],
        }
        idx = pd.DatetimeIndex([r.bar_time for r in rows])
        df = pd.DataFrame(data, index=idx)
        cleaned, _ = prepare_ohlcv(df, interval, trim_history=False, ensure_continuous=True)
        return cleaned

    # --- Adaptive params ---
    def upsert_adaptive_params(
        self,
        symbol: str,
        market: str,
        interval: str,
        strategy_name: str,
        params: dict[str, Any],
        oos_metrics: dict[str, Any],
        fold_count: int,
    ) -> AdaptiveStrategyParams:
        q = select(AdaptiveStrategyParams).where(
            AdaptiveStrategyParams.symbol == symbol,
            AdaptiveStrategyParams.market == market,
            AdaptiveStrategyParams.interval == interval,
            AdaptiveStrategyParams.strategy_name == strategy_name,
        )
        row = self.session.scalar(q)
        if row:
            row.params_json = json.dumps(params)
            row.oos_metrics_json = json.dumps(oos_metrics)
            row.fold_count = fold_count
            row.optimized_at = datetime.utcnow()
            row.param_version += 1
        else:
            row = AdaptiveStrategyParams(
                symbol=symbol,
                market=market,
                interval=interval,
                strategy_name=strategy_name,
                params_json=json.dumps(params),
                oos_metrics_json=json.dumps(oos_metrics),
                fold_count=fold_count,
            )
            self.session.add(row)
        self.session.commit()
        self.session.refresh(row)
        return row

    def get_adaptive_params(
        self, symbol: str, market: str, interval: str, strategy_name: str
    ) -> AdaptiveStrategyParams | None:
        return self.session.scalar(
            select(AdaptiveStrategyParams).where(
                AdaptiveStrategyParams.symbol == symbol,
                AdaptiveStrategyParams.market == market,
                AdaptiveStrategyParams.interval == interval,
                AdaptiveStrategyParams.strategy_name == strategy_name,
            )
        )

    def list_adaptive_params(
        self, symbol: str, market: str, interval: str
    ) -> list[AdaptiveStrategyParams]:
        return list(
            self.session.scalars(
                select(AdaptiveStrategyParams).where(
                    AdaptiveStrategyParams.symbol == symbol,
                    AdaptiveStrategyParams.market == market,
                    AdaptiveStrategyParams.interval == interval,
                )
            )
        )

    def save_backtest_result(
        self,
        symbol: str,
        market: str,
        interval: str,
        strategy_name: str,
        report: dict[str, Any],
    ) -> None:
        self.session.add(
            BacktestResult(
                symbol=symbol,
                market=market,
                interval=interval,
                strategy_name=strategy_name,
                report_json=json.dumps(report),
            )
        )
        self.session.commit()

    def list_backtest_results(
        self,
        symbol: str,
        market: str,
        interval: str,
        strategy_name: str | None = None,
        limit: int = 50,
    ) -> list[BacktestResult]:
        q = (
            select(BacktestResult)
            .where(
                BacktestResult.symbol == symbol,
                BacktestResult.market == market,
                BacktestResult.interval == interval,
            )
            .order_by(BacktestResult.computed_at.desc())
            .limit(limit)
        )
        if strategy_name:
            q = q.where(BacktestResult.strategy_name == strategy_name)
        return list(self.session.scalars(q))

    def get_latest_backtest_result(
        self,
        symbol: str,
        market: str,
        interval: str,
        strategy_name: str,
    ) -> BacktestResult | None:
        rows = self.list_backtest_results(
            symbol, market, interval, strategy_name=strategy_name, limit=1
        )
        return rows[0] if rows else None

    # --- Recommendations ---
    def save_recommendation(
        self,
        watchlist_id: int,
        strategy_name: str,
        bar_time: datetime,
        action: str,
        strength: float,
        amount: float,
        shares: int,
        reason: str,
        params_snapshot: dict,
        oos_snapshot: dict,
    ) -> Recommendation | None:
        self._assert_owns(watchlist_id)
        existing = self.session.scalar(
            select(Recommendation).where(
                Recommendation.watchlist_id == watchlist_id,
                Recommendation.strategy_name == strategy_name,
                Recommendation.bar_time == bar_time,
            )
        )
        if existing:
            return existing
        rec = Recommendation(
            watchlist_id=watchlist_id,
            strategy_name=strategy_name,
            bar_time=bar_time,
            action=action,
            strength=strength,
            amount=amount,
            shares=shares,
            reason=reason,
            params_snapshot=json.dumps(params_snapshot),
            oos_metrics_snapshot=json.dumps(oos_snapshot),
        )
        self.session.add(rec)
        self.session.commit()
        self.session.refresh(rec)
        return rec

    def latest_recommendations(self, watchlist_id: int) -> list[Recommendation]:
        self._assert_owns(watchlist_id)
        items = self.session.scalars(
            select(Recommendation)
            .where(Recommendation.watchlist_id == watchlist_id)
            .order_by(Recommendation.bar_time.desc(), Recommendation.created_at.desc())
        ).all()
        seen: set[str] = set()
        latest: list[Recommendation] = []
        for r in items:
            if r.strategy_name not in seen:
                seen.add(r.strategy_name)
                latest.append(r)
        return latest

    def previous_recommendations_before(
        self, watchlist_id: int, bar_time: datetime
    ) -> list[Recommendation]:
        self._assert_owns(watchlist_id)
        return list(
            self.session.scalars(
                select(Recommendation)
                .where(
                    Recommendation.watchlist_id == watchlist_id,
                    Recommendation.bar_time < bar_time,
                )
                .order_by(Recommendation.bar_time.desc())
            )
        )

    def list_recommendation_history(
        self, watchlist_id: int | None = None, limit: int = 200
    ) -> list[Recommendation]:
        q = select(Recommendation).order_by(Recommendation.created_at.desc()).limit(limit)
        if watchlist_id:
            self._assert_owns(watchlist_id)
            q = q.where(Recommendation.watchlist_id == watchlist_id)
        else:
            own_ids = self._own_watchlist_ids()
            if own_ids is not None:
                q = q.where(Recommendation.watchlist_id.in_(own_ids))
        return list(self.session.scalars(q))

    def last_buy_recommendation(
        self, watchlist_id: int, strategy_name: str
    ) -> Recommendation | None:
        self._assert_owns(watchlist_id)
        return self.session.scalar(
            select(Recommendation)
            .where(
                Recommendation.watchlist_id == watchlist_id,
                Recommendation.strategy_name == strategy_name,
                Recommendation.action == "buy",
                Recommendation.shares > 0,
            )
            .order_by(Recommendation.bar_time.desc(), Recommendation.created_at.desc())
            .limit(1)
        )

    # --- Strategy positions (ATR stop) ---
    def get_strategy_position(
        self, watchlist_id: int, strategy_name: str
    ) -> StrategyPosition | None:
        self._assert_owns(watchlist_id)
        return self.session.scalar(
            select(StrategyPosition).where(
                StrategyPosition.watchlist_id == watchlist_id,
                StrategyPosition.strategy_name == strategy_name,
            )
        )

    def list_strategy_positions(self, watchlist_id: int) -> list[StrategyPosition]:
        self._assert_owns(watchlist_id)
        return list(
            self.session.scalars(
                select(StrategyPosition)
                .where(StrategyPosition.watchlist_id == watchlist_id)
                .order_by(StrategyPosition.strategy_name)
            )
        )

    def upsert_strategy_position(
        self,
        watchlist_id: int,
        strategy_name: str,
        *,
        entry_price: float,
        entry_shares: int,
        entry_atr: float | None,
        entry_bar_time: datetime | None,
        manual_override: bool,
        trailing_stop: float | None = None,
    ) -> StrategyPosition:
        row = self.get_strategy_position(watchlist_id, strategy_name)
        if row is None:
            row = StrategyPosition(
                watchlist_id=watchlist_id,
                strategy_name=strategy_name,
            )
            self.session.add(row)
        row.entry_price = float(entry_price)
        row.entry_shares = int(entry_shares)
        row.entry_atr = entry_atr
        row.entry_bar_time = entry_bar_time
        row.manual_override = manual_override
        if trailing_stop is not None:
            row.trailing_stop = trailing_stop
        row.updated_at = datetime.utcnow()
        self.session.commit()
        self.session.refresh(row)
        return row

    def update_position_trailing_stop(
        self,
        watchlist_id: int,
        strategy_name: str,
        trailing_stop: float,
    ) -> None:
        item = self.get_watchlist_by_id(watchlist_id)
        if item and item.position_manual_override and item.position_entry_shares > 0:
            item.position_trailing_stop = float(trailing_stop)
            self.session.commit()
            return
        row = self.get_strategy_position(watchlist_id, strategy_name)
        if row and row.entry_shares > 0:
            row.trailing_stop = float(trailing_stop)
            row.updated_at = datetime.utcnow()
            self.session.commit()

    def clear_strategy_position(self, watchlist_id: int, strategy_name: str) -> None:
        row = self.get_strategy_position(watchlist_id, strategy_name)
        if row:
            self.session.delete(row)
            self.session.commit()

    def clear_all_strategy_positions(self, watchlist_id: int) -> None:
        self._assert_owns(watchlist_id)
        self.session.execute(
            delete(StrategyPosition).where(StrategyPosition.watchlist_id == watchlist_id)
        )
        self.session.commit()

    def set_watchlist_manual_position(
        self,
        watchlist_id: int,
        *,
        entry_price: float,
        entry_shares: int,
        entry_atr: float | None,
        entry_bar_time: datetime | None,
        trailing_stop: float | None = None,
    ) -> WatchlistItem | None:
        item = self.get_watchlist_by_id(watchlist_id)
        if item is None:
            return None
        item.position_manual_override = True
        item.position_entry_price = float(entry_price)
        item.position_entry_shares = int(entry_shares)
        item.position_entry_atr = entry_atr
        item.position_entry_bar_time = entry_bar_time
        item.position_trailing_stop = trailing_stop
        self.session.commit()
        self.session.refresh(item)
        return item

    def clear_watchlist_manual_position(self, watchlist_id: int) -> None:
        item = self.get_watchlist_by_id(watchlist_id)
        if item is None:
            return
        item.position_manual_override = False
        item.position_entry_price = 0.0
        item.position_entry_shares = 0
        item.position_entry_atr = None
        item.position_entry_bar_time = None
        item.position_trailing_stop = None
        self.session.commit()
        self.clear_all_strategy_positions(watchlist_id)

    # --- Notifications ---
    def log_notification(
        self,
        watchlist_id: int,
        strategy_name: str,
        bar_time: datetime,
        channel: str,
        status: str,
        error_message: str | None = None,
    ) -> None:
        self.session.add(
            NotificationLog(
                watchlist_id=watchlist_id,
                strategy_name=strategy_name,
                bar_time=bar_time,
                channel=channel,
                status=status,
                error_message=error_message,
            )
        )
        self.session.commit()

    def notification_exists(
        self,
        watchlist_id: int,
        strategy_name: str,
        bar_time: datetime,
        channel: str,
    ) -> bool:
        return (
            self.session.scalar(
                select(NotificationLog).where(
                    NotificationLog.watchlist_id == watchlist_id,
                    NotificationLog.strategy_name == strategy_name,
                    NotificationLog.bar_time == bar_time,
                    NotificationLog.channel == channel,
                )
            )
            is not None
        )

    def notification_sent_on_date(
        self,
        watchlist_id: int,
        channel: str,
        on_date: date,
        strategy_name: str = "daily",
    ) -> bool:
        start = datetime.combine(on_date, time.min)
        end = datetime.combine(on_date, time.max)
        return (
            self.session.scalar(
                select(NotificationLog).where(
                    NotificationLog.watchlist_id == watchlist_id,
                    NotificationLog.strategy_name == strategy_name,
                    NotificationLog.channel == channel,
                    NotificationLog.sent_at >= start,
                    NotificationLog.sent_at <= end,
                )
            )
            is not None
        )

    def list_notification_logs(self, limit: int = 20) -> list[NotificationLog]:
        q = select(NotificationLog).order_by(NotificationLog.sent_at.desc()).limit(limit)
        own_ids = self._own_watchlist_ids()
        if own_ids is not None:
            q = q.where(NotificationLog.watchlist_id.in_(own_ids))
        return list(self.session.scalars(q))

    # --- Screener ---
    def create_screener_run(
        self,
        *,
        market: str,
        universe_id: str,
        top_n: int,
        factor_config_json: str,
        universe_size: int,
    ) -> ScreenerRun:
        run = ScreenerRun(
            market=market,
            universe_id=universe_id,
            top_n=top_n,
            factor_config_json=factor_config_json,
            universe_size=universe_size,
            status="running",
        )
        self.session.add(run)
        self.session.commit()
        self.session.refresh(run)
        return run

    def finish_screener_run(
        self,
        run_id: int,
        *,
        status: str,
        screened_count: int,
        warnings: list[str] | None = None,
        error_message: str | None = None,
    ) -> None:
        run = self.session.get(ScreenerRun, run_id)
        if run is None:
            return
        run.status = status
        run.screened_count = screened_count
        run.warnings_json = json.dumps(warnings or [], ensure_ascii=False)
        run.error_message = error_message
        run.finished_at = datetime.utcnow()
        self.session.add(run)
        self.session.commit()

    def save_screener_results(self, run_id: int, ranked: list) -> None:
        self.session.execute(delete(ScreenerResult).where(ScreenerResult.run_id == run_id))
        for row in ranked:
            self.session.add(
                ScreenerResult(
                    run_id=run_id,
                    rank=int(row.rank),
                    tf_symbol=row.tf_symbol,
                    symbol=row.symbol,
                    market=row.market,
                    display_name=row.display_name,
                    composite_score=row.composite_score,
                    factor_scores_json=json.dumps(row.factor_scores, ensure_ascii=False),
                )
            )
        self.session.commit()

    def get_latest_screener_run(self, market: str | None = None) -> ScreenerRun | None:
        q = select(ScreenerRun).where(ScreenerRun.status == "done")
        if market:
            q = q.where(ScreenerRun.market == market.lower())
        return self.session.scalar(q.order_by(ScreenerRun.finished_at.desc()).limit(1))

    def list_screener_results(self, run_id: int) -> list[ScreenerResult]:
        return list(
            self.session.scalars(
                select(ScreenerResult)
                .where(ScreenerResult.run_id == run_id)
                .order_by(ScreenerResult.rank.asc())
            )
        )
