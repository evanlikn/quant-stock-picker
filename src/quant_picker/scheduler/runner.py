from __future__ import annotations

import logging
from datetime import datetime
from zoneinfo import ZoneInfo

from apscheduler.schedulers.blocking import BlockingScheduler
from apscheduler.triggers.cron import CronTrigger

from quant_picker.config import auto_sync_intervals, load_settings, market_daily_run_schedule
from quant_picker.engine.updater import Updater
from quant_picker.storage.db import get_session_factory, init_db
from quant_picker.storage.repository import Repository

SUPPORTED_MARKETS = ("cn", "hk", "us")

logger = logging.getLogger(__name__)


def _parse_hhmm(value: str) -> tuple[int, int]:
    hour, minute = map(int, value.split(":"))
    return hour, minute


def _in_trading_hours(now: datetime, market: str = "cn") -> bool:
    settings = load_settings()
    sessions = (
        settings.get("scheduler", {})
        .get("trading_hours", {})
        .get(market, {})
        .get("sessions", [["09:30", "11:30"], ["13:00", "15:00"]])
    )
    t = now.time()
    for start, end in sessions:
        sh, sm = map(int, start.split(":"))
        eh, em = map(int, end.split(":"))
        from datetime import time as dt_time

        if dt_time(sh, sm) <= t <= dt_time(eh, em):
            return True
    return False


def run_market_interval_updates(market: str, interval: str) -> None:
    """Sync + analyze + notify for one market and K-line interval."""
    init_db()
    session = get_session_factory()()
    repo = Repository(session)
    updater = Updater(repo)
    tz = ZoneInfo(load_settings().get("scheduler", {}).get("timezone", "Asia/Shanghai"))
    now = datetime.now(tz)
    market_key = market.lower()

    for item in repo.list_watchlist(enabled_only=True):
        if item.interval != interval:
            continue
        if item.market.lower() != market_key:
            continue
        if interval in ("1h", "1m") and not _in_trading_hours(now, item.market.lower()):
            continue
        try:
            updater.update_watchlist_item(item)
        except Exception:
            # 逐只跳过而不中断整轮，但必须留下痕迹，否则「某只没更新」无从排查
            logger.exception(
                "update failed: %s %s %s", item.symbol, item.market, item.interval
            )


def run_interval_updates(interval: str) -> None:
    """Legacy hook: all markets for intraday interval jobs."""
    init_db()
    session = get_session_factory()()
    repo = Repository(session)
    updater = Updater(repo)
    tz = ZoneInfo(load_settings().get("scheduler", {}).get("timezone", "Asia/Shanghai"))
    now = datetime.now(tz)

    for item in repo.list_watchlist(enabled_only=True):
        if item.interval != interval:
            continue
        if interval in ("1h", "1m") and not _in_trading_hours(now, item.market.lower()):
            continue
        try:
            updater.update_watchlist_item(item)
        except Exception:
            logger.exception(
                "update failed: %s %s %s", item.symbol, item.market, item.interval
            )


def run_daily_close_once(market: str | None = None) -> None:
    """Run post-close daily jobs once; all markets if market is omitted."""
    targets = (market.lower(),) if market else SUPPORTED_MARKETS
    for m in targets:
        if m not in SUPPORTED_MARKETS:
            continue
        run_market_interval_updates(m, "1d")


def _register_market_daily_jobs(scheduler: BlockingScheduler, tz: str) -> list[str]:
    schedule = market_daily_run_schedule()
    labels: list[str] = []
    for market in SUPPORTED_MARKETS:
        cfg = schedule.get(market, {})
        run_time = cfg.get("time", "15:35")
        days = cfg.get("days", "mon-fri")
        hour, minute = _parse_hhmm(run_time)
        scheduler.add_job(
            run_market_interval_updates,
            CronTrigger(day_of_week=days, hour=hour, minute=minute, timezone=tz),
            args=[market, "1d"],
            id=f"update_1d_{market}",
            replace_existing=True,
        )
        labels.append(f"{market}@{run_time} ({days})")
    return labels


def _register_intraday_job(scheduler: BlockingScheduler, tz: str, interval: str) -> str:
    """Register an intraday job aligned to K-line boundaries.

    用 cron 而不是 interval 触发：interval 是相对调度器启动时刻计时的，进程什么时候
    起、任务就什么时候跑，和 K 线收线时间对不上。cron 固定落在整点/整分之后，拿到的
    才是刚收完的那根 K 线。各市场是否在交易时段由 run_interval_updates 逐只判断。
    """
    if interval == "1h":
        trigger = CronTrigger(minute=2, timezone=tz)
        label = "1h@每小时 02 分"
    else:
        trigger = CronTrigger(second=20, timezone=tz)
        label = "1m@每分钟 20 秒"
    scheduler.add_job(
        run_interval_updates,
        trigger,
        args=[interval],
        id=f"update_{interval}",
        replace_existing=True,
        max_instances=1,
        coalesce=True,
    )
    return label


def _warn_uncovered_intervals(sync_intervals: set[str]) -> None:
    """自选里存在但没有对应定时任务的周期，会永远不自动更新，启动时点出来。"""
    session = get_session_factory()()
    try:
        repo = Repository(session)
        uncovered: dict[str, list[str]] = {}
        for item in repo.list_watchlist(enabled_only=True):
            if item.interval not in sync_intervals:
                uncovered.setdefault(item.interval, []).append(item.symbol)
    finally:
        session.close()

    for interval, symbols in sorted(uncovered.items()):
        preview = ", ".join(symbols[:5]) + (" ..." if len(symbols) > 5 else "")
        print(
            f"[warn] {len(symbols)} 只自选是 {interval} 周期，但 auto_sync_intervals "
            f"未包含 {interval}，它们不会被自动更新：{preview}"
        )


def main() -> None:
    import sys

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    if "--once" in sys.argv:
        init_db()
        idx = sys.argv.index("--once")
        market = sys.argv[idx + 1].lower() if idx + 1 < len(sys.argv) else None
        if market and market not in SUPPORTED_MARKETS:
            print(f"Unknown market {market!r}; use cn, hk, or us.")
            raise SystemExit(1)
        run_daily_close_once(market)
        target = market or "cn+hk+us"
        print(f"Daily close update finished ({target}).")
        return

    init_db()
    settings = load_settings()
    sched_cfg = settings.get("scheduler", {})
    tz = sched_cfg.get("timezone", "Asia/Shanghai")

    scheduler = BlockingScheduler(timezone=tz)
    sync_intervals = set(auto_sync_intervals())
    market_labels: list[str] = []
    if "1d" in sync_intervals:
        market_labels = _register_market_daily_jobs(scheduler, tz)
    intraday_labels = [
        _register_intraday_job(scheduler, tz, interval)
        for interval in ("1h", "1m")
        if interval in sync_intervals
    ]

    parts = [f"intervals={sorted(sync_intervals)}"]
    if market_labels:
        parts.append("daily=" + ", ".join(market_labels))
    if intraday_labels:
        parts.append("intraday=" + ", ".join(intraday_labels))
    print(f"Quant picker scheduler started ({'; '.join(parts)})...")
    _warn_uncovered_intervals(sync_intervals)
    scheduler.start()


if __name__ == "__main__":
    main()
