"""A sell closes only the strategy that signaled it."""

from __future__ import annotations

from quant_picker.engine.position_tracker import PositionTracker, resolve_position
from quant_picker.storage.repository import Repository
from quant_picker.strategies.base import Signal


def _repo(session):
    from quant_picker.auth import service

    user = service.create_user(session, username="alice", password="pwd")
    return Repository(session, user.id)


def test_one_strategy_sell_keeps_the_shared_cost_for_the_others(session):
    repo = _repo(session)
    item = repo.add_watchlist("600519", "cn", "1d")
    repo.set_watchlist_manual_position(
        item.id,
        entry_price=1400.0,
        entry_shares=100,
        entry_atr=20.0,
        entry_bar_time=None,
        trailing_stop=1360.0,
    )
    tracker = PositionTracker(repo)

    tracker.sync_after_signal(
        item.id,
        "ma_cross",
        Signal("sell", 0.8, "死叉"),
        entry_price=1500.0,
        entry_shares=100,
        entry_atr=20.0,
        bar_time=None,
    )
    tracker.sync_after_signal(
        item.id,
        "rsi",
        Signal("hold", 0.0, "观望"),
        entry_price=1500.0,
        entry_shares=0,
        entry_atr=20.0,
        bar_time=None,
    )

    session.refresh(item)
    assert item.position_manual_override is True
    assert item.position_entry_price == 1400.0
    assert item.position_entry_shares == 100

    assert resolve_position(repo, item.id, "ma_cross") is None
    kept = resolve_position(repo, item.id, "rsi")
    assert kept is not None
    assert kept.entry_price == 1400.0
    assert kept.entry_shares == 100


def test_resaving_manual_cost_restores_a_strategy_closed_by_sell(session):
    repo = _repo(session)
    item = repo.add_watchlist("600519", "cn", "1d")
    repo.set_watchlist_manual_position(
        item.id,
        entry_price=1400.0,
        entry_shares=100,
        entry_atr=20.0,
        entry_bar_time=None,
    )
    PositionTracker(repo).sync_after_signal(
        item.id,
        "ma_cross",
        Signal("sell", 0.8, "死叉"),
        entry_price=1500.0,
        entry_shares=100,
        entry_atr=20.0,
        bar_time=None,
    )
    assert resolve_position(repo, item.id, "ma_cross") is None

    repo.set_watchlist_manual_position(
        item.id,
        entry_price=1410.0,
        entry_shares=200,
        entry_atr=20.0,
        entry_bar_time=None,
    )
    restored = resolve_position(repo, item.id, "ma_cross")
    assert restored is not None
    assert restored.entry_price == 1410.0
    assert restored.entry_shares == 200
