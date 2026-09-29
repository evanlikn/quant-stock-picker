"""WeChat title only mentions 买入/卖出 when those actions appear."""

from __future__ import annotations

from types import SimpleNamespace

from quant_picker.notifications.formatter import format_wechat_title


def _item(symbol="600519", display_name="贵州茅台"):
    return SimpleNamespace(symbol=symbol, display_name=display_name)


def _rec(action: str):
    return SimpleNamespace(action=action)


def test_all_hold_omits_action_from_title():
    title = format_wechat_title(_item(), [_rec("hold"), _rec("hold")])
    assert title == "600519 贵州茅台"


def test_buy_is_appended_in_parentheses():
    title = format_wechat_title(_item(), [_rec("hold"), _rec("buy")])
    assert title == "600519 贵州茅台(买入)"


def test_sell_is_appended_in_parentheses():
    title = format_wechat_title(_item(), [_rec("sell"), _rec("hold")])
    assert title == "600519 贵州茅台(卖出)"


def test_buy_and_sell_keep_first_seen_order():
    title = format_wechat_title(_item(), [_rec("sell"), _rec("buy"), _rec("sell")])
    assert title == "600519 贵州茅台(卖出/买入)"


def test_nameless_symbol_still_gets_the_suffix():
    title = format_wechat_title(_item(display_name=None), [_rec("buy")])
    assert title == "600519(买入)"


def test_no_recommendations_keeps_plain_title():
    assert format_wechat_title(_item()) == "600519 贵州茅台"
    assert format_wechat_title(_item(), []) == "600519 贵州茅台"
