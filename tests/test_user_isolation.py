from __future__ import annotations

import pytest

from quant_picker.auth import service
from quant_picker.storage.repository import Repository


@pytest.fixture
def users(session):
    alice = service.create_user(session, username="alice", password="alice-pwd")
    bob = service.create_user(session, username="bob", password="bob-pwd")
    return alice, bob


def test_watchlist_is_private_per_user(session, users):
    alice, bob = users
    Repository(session, alice.id).add_watchlist("600519", "cn", "1d")
    Repository(session, bob.id).add_watchlist("000001", "cn", "1d")

    assert [i.symbol for i in Repository(session, alice.id).list_watchlist()] == ["600519"]
    assert [i.symbol for i in Repository(session, bob.id).list_watchlist()] == ["000001"]


def test_same_symbol_can_be_watched_by_two_users(session, users):
    alice, bob = users
    a = Repository(session, alice.id).add_watchlist("600519", "cn", "1d")
    b = Repository(session, bob.id).add_watchlist("600519", "cn", "1d")

    assert a.id != b.id
    assert a.user_id == alice.id and b.user_id == bob.id


def test_adding_twice_returns_the_same_row(session, users):
    alice, _ = users
    repo = Repository(session, alice.id)
    first = repo.add_watchlist("600519", "cn", "1d")
    second = repo.add_watchlist("600519", "cn", "1d")
    assert first.id == second.id


def test_other_users_item_is_invisible_by_id(session, users):
    alice, bob = users
    item = Repository(session, alice.id).add_watchlist("600519", "cn", "1d")
    assert Repository(session, bob.id).get_watchlist_by_id(item.id) is None


def test_writing_to_another_users_item_is_rejected(session, users):
    alice, bob = users
    item = Repository(session, alice.id).add_watchlist("600519", "cn", "1d")

    bob_repo = Repository(session, bob.id)
    with pytest.raises(PermissionError):
        bob_repo.update_watchlist(item)
    with pytest.raises(PermissionError):
        bob_repo.latest_recommendations(item.id)
    with pytest.raises(PermissionError):
        bob_repo.list_strategy_positions(item.id)


def test_delete_only_touches_own_items(session, users):
    alice, bob = users
    item = Repository(session, alice.id).add_watchlist("600519", "cn", "1d")

    Repository(session, bob.id).delete_watchlist(item.id)
    assert Repository(session, alice.id).get_watchlist_by_id(item.id) is not None

    Repository(session, alice.id).delete_watchlist(item.id)
    assert Repository(session, alice.id).get_watchlist_by_id(item.id) is None


def test_scheduler_repository_sees_every_user(session, users):
    alice, bob = users
    Repository(session, alice.id).add_watchlist("600519", "cn", "1d")
    Repository(session, bob.id).add_watchlist("000001", "cn", "1d")

    system = Repository(session)
    assert len(system.list_all_watchlist()) == 2
    assert system.get_watchlist_by_id(1) is not None


def test_adding_without_user_context_is_rejected(session):
    with pytest.raises(PermissionError):
        Repository(session).add_watchlist("600519", "cn", "1d")


def test_notification_logs_are_scoped_to_own_items(session, users):
    from datetime import datetime

    alice, bob = users
    alice_item = Repository(session, alice.id).add_watchlist("600519", "cn", "1d")
    bob_item = Repository(session, bob.id).add_watchlist("000001", "cn", "1d")

    system = Repository(session)
    bar_time = datetime(2026, 1, 2, 15, 0)
    system.log_notification(alice_item.id, "daily", bar_time, "email", "success")
    system.log_notification(bob_item.id, "daily", bar_time, "email", "failed")

    alice_logs = Repository(session, alice.id).list_notification_logs()
    assert [entry.watchlist_id for entry in alice_logs] == [alice_item.id]
