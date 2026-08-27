"""Walk-forward output is keyed by instrument, so users must not retrain it twice."""

from __future__ import annotations

from datetime import datetime, timedelta

import pytest

from quant_picker.auth import service
from quant_picker.optimization.trainer import Trainer, enabled_strategy_names
from quant_picker.storage.repository import Repository


@pytest.fixture
def two_users(session):
    alice = service.create_user(session, username="alice", password="pwd")
    bob = service.create_user(session, username="bob", password="pwd")
    return alice, bob


def _store_shared_params(repo: Repository, symbol="600519", market="cn", interval="1d"):
    for name in enabled_strategy_names():
        repo.upsert_adaptive_params(
            symbol, market, interval, name, {"fast": 5}, {"win_rate": 0.6}, 3
        )


def test_second_user_reuses_existing_params(session, two_users):
    alice, bob = two_users
    alice_repo = Repository(session, alice.id)
    alice_item = alice_repo.add_watchlist("600519", "cn", "1d")
    alice_item.retrain_cycle_bars = 90
    alice_item.retrain_cycle_source = "wfo"
    alice_repo.update_watchlist(alice_item)
    _store_shared_params(alice_repo)

    bob_repo = Repository(session, bob.id)
    bob_item = bob_repo.add_watchlist("600519", "cn", "1d")
    assert Trainer(bob_repo).adopt_shared_params(bob_item) is True

    assert bob_item.wfo_status == "done"
    assert bob_item.bars_since_optimization == 0
    assert bob_item.retrain_cycle_bars == 90


def test_no_reuse_without_stored_params(session, two_users):
    _, bob = two_users
    bob_repo = Repository(session, bob.id)
    item = bob_repo.add_watchlist("600519", "cn", "1d")
    assert Trainer(bob_repo).adopt_shared_params(item) is False
    assert item.wfo_status == "pending"


def test_no_reuse_when_own_params_are_newer(session, two_users):
    alice, _ = two_users
    repo = Repository(session, alice.id)
    item = repo.add_watchlist("600519", "cn", "1d")
    _store_shared_params(repo)
    item.last_optimized_at = datetime.utcnow() + timedelta(hours=1)
    repo.update_watchlist(item)

    assert Trainer(repo).adopt_shared_params(item) is False


def test_partial_strategy_coverage_forces_retrain(session, two_users):
    alice, bob = two_users
    alice_repo = Repository(session, alice.id)
    alice_repo.add_watchlist("600519", "cn", "1d")
    names = enabled_strategy_names()
    assert len(names) > 1, "此用例需要至少两个启用的策略"
    alice_repo.upsert_adaptive_params(
        "600519", "cn", "1d", names[0], {"fast": 5}, {"win_rate": 0.6}, 3
    )

    bob_repo = Repository(session, bob.id)
    item = bob_repo.add_watchlist("600519", "cn", "1d")
    assert Trainer(bob_repo).adopt_shared_params(item) is False


def test_different_interval_does_not_reuse(session, two_users):
    alice, bob = two_users
    alice_repo = Repository(session, alice.id)
    alice_repo.add_watchlist("600519", "cn", "1d")
    _store_shared_params(alice_repo, interval="1d")

    bob_repo = Repository(session, bob.id)
    hourly = bob_repo.add_watchlist("600519", "cn", "1h")
    assert Trainer(bob_repo).adopt_shared_params(hourly) is False
