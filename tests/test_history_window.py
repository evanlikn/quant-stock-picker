"""The per-watchlist 历史窗口 value drives how far back bars are fetched."""

from __future__ import annotations

from datetime import datetime, timedelta

import pandas as pd

from quant_picker.data.bar_sync import BarSyncService
from quant_picker.data.bars_util import effective_history_days, initial_history_days
from quant_picker.storage.repository import Repository


def _frame(days: int) -> pd.DataFrame:
    idx = pd.date_range(end=datetime.utcnow(), periods=days * 6, freq="h")
    return pd.DataFrame(
        {"open": 1.0, "high": 1.0, "low": 1.0, "close": 1.0, "volume": 1.0}, index=idx
    )


def test_saved_history_days_wins_over_yaml_default(session):
    from quant_picker.auth import service

    user = service.create_user(session, username="alice", password="pwd")
    repo = Repository(session, user.id)
    item = repo.add_watchlist("00700", "hk", "1h", history_days=100)

    assert item.history_days == 100
    assert effective_history_days(item) == 100
    assert effective_history_days(item) != initial_history_days("1h")


def test_blank_history_days_falls_back_to_yaml_default(session):
    from quant_picker.auth import service

    user = service.create_user(session, username="alice", password="pwd")
    repo = Repository(session, user.id)
    item = repo.add_watchlist("00700", "hk", "1h")

    assert item.history_days is None
    assert effective_history_days(item) == initial_history_days("1h")


def test_fetch_start_honours_the_watchlist_window(session, monkeypatch):
    """填 100 天就要从 100 天前开始拉，而不是 yaml 里的默认值。"""
    from quant_picker.auth import service

    user = service.create_user(session, username="alice", password="pwd")
    repo = Repository(session, user.id)
    item = repo.add_watchlist("00700", "hk", "1h", history_days=100)

    seen: dict[str, datetime] = {}

    class FakeProvider:
        def fetch_bars(self, symbol, interval, start=None, end=None):
            seen["start"] = start
            return _frame(100)

    monkeypatch.setattr(
        "quant_picker.data.bar_sync.get_provider", lambda market: FakeProvider()
    )

    BarSyncService(repo).sync("00700", "hk", "1h", force_full=True, item=item)

    span_days = (datetime.utcnow() - seen["start"]).days
    # history_fetch_start pads the window by 14 calendar days
    assert 100 <= span_days <= 100 + 20
    assert span_days < initial_history_days("1d")


def test_stored_bars_are_trimmed_to_the_window(session, monkeypatch):
    from quant_picker.auth import service

    user = service.create_user(session, username="alice", password="pwd")
    repo = Repository(session, user.id)
    item = repo.add_watchlist("00700", "hk", "1h", history_days=30)

    class FakeProvider:
        def fetch_bars(self, symbol, interval, start=None, end=None):
            return _frame(90)

    monkeypatch.setattr(
        "quant_picker.data.bar_sync.get_provider", lambda market: FakeProvider()
    )

    stored, _ = BarSyncService(repo).sync(
        "00700", "hk", "1h", force_full=True, item=item
    )
    span = stored.index.max() - stored.index.min()
    assert span <= timedelta(days=31)
