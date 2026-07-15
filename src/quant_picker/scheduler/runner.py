from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

from apscheduler.schedulers.blocking import BlockingScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger

from quant_picker.config import auto_sync_intervals, load_settings, market_daily_run_schedule
from quant_picker.engine.updater import Updater
from quant_picker.storage.db import get_session_factory, init_db
from quant_picker.storage.repository import Repository

SUPPORTED_MARKETS = ("cn", "hk", "us")


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
            continue


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
            continue


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


def main() -> None:
    import sys

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
    if "1h" in sync_intervals:
        scheduler.add_job(
            run_interval_updates,
            IntervalTrigger(hours=1),
            args=["1h"],
            id="update_1h",
            replace_existing=True,
        )
    if "1m" in sync_intervals:
        scheduler.add_job(
            run_interval_updates,
            IntervalTrigger(minutes=1),
            args=["1m"],
            id="update_1m",
            replace_existing=True,
        )

    parts = [f"intervals={sorted(sync_intervals)}"]
    if market_labels:
        parts.append("daily=" + ", ".join(market_labels))
    print(f"Quant picker scheduler started ({'; '.join(parts)})...")
    scheduler.start()


if __name__ == "__main__":
    main()
