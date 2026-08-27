"""Headless page smoke tests: the login gate blocks, and pages render once past it."""

from __future__ import annotations

import pytest
from streamlit.testing.v1 import AppTest

from quant_picker.auth import service
from quant_picker.auth.guard import CurrentUser

PAGES = [
    "src/quant_picker/web/首页.py",
    "src/quant_picker/web/pages/1_自选管理.py",
    "src/quant_picker/web/pages/2_建议历史.py",
    "src/quant_picker/web/pages/3_推送设置.py",
    "src/quant_picker/web/pages/4_回测报告.py",
    "src/quant_picker/web/pages/5_多因子选股.py",
    "src/quant_picker/web/pages/6_账号管理.py",
]


@pytest.fixture
def logged_in(monkeypatch, session):
    from quant_picker.auth import guard

    user = service.create_user(
        session, username="alice", password="alice-pwd", is_admin=True
    )
    current = CurrentUser(
        id=user.id, username=user.username, display_name=user.username, is_admin=True
    )
    monkeypatch.setattr(guard, "require_login", lambda: current)
    monkeypatch.setattr(guard, "render_sidebar_account", lambda _user: None)
    monkeypatch.setattr(guard, "current_user_id", lambda: current.id)
    return current


@pytest.mark.parametrize("page", PAGES)
def test_page_requires_login(page):
    app = AppTest.from_file(page, default_timeout=60).run()
    assert not app.exception
    messages = [block.value for block in app.info] + [block.value for block in app.error]
    assert any("登录" in text for text in messages)


@pytest.mark.parametrize("page", PAGES)
def test_page_renders_for_logged_in_user(page, logged_in):
    app = AppTest.from_file(page, default_timeout=60).run()
    assert not app.exception


def test_pages_only_offer_own_symbols(logged_in, session):
    """The scoped repository must not leak another account's stocks into a picker."""
    from quant_picker.storage.repository import Repository

    bob = service.create_user(session, username="bob", password="bob-pwd")
    Repository(session, logged_in.id).add_watchlist(
        "600519", "cn", "1d", display_name="贵州茅台"
    )
    Repository(session, bob.id).add_watchlist(
        "000001", "cn", "1d", display_name="平安银行"
    )

    for page in ("src/quant_picker/web/pages/2_建议历史.py",
                 "src/quant_picker/web/pages/4_回测报告.py"):
        app = AppTest.from_file(page, default_timeout=60).run()
        assert not app.exception, page
        options = [opt for box in app.selectbox for opt in box.options]
        assert any("600519" in opt for opt in options), page
        assert not any("000001" in opt for opt in options), page
