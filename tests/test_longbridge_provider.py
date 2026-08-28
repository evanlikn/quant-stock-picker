from __future__ import annotations

from datetime import datetime
from types import SimpleNamespace

import pandas as pd
import pytest

from quant_picker.data.providers import longbridge_provider as lb
from quant_picker.data.registry import RoutedProvider, clear_providers, get_provider
from quant_picker.market.detector import Market, to_longbridge_symbol


def _candle(ts: datetime, close: float = 10.0):
    return SimpleNamespace(
        timestamp=ts,
        open=close,
        high=close + 1,
        low=close - 1,
        close=close,
        volume=100,
    )


def test_longbridge_symbol_strips_hk_leading_zeros():
    assert to_longbridge_symbol("00700", Market.HK) == "700.HK"
    assert to_longbridge_symbol("AAPL", Market.US) == "AAPL.US"
    assert to_longbridge_symbol("BRK.B", Market.US) == "BRK.B.US"


def test_router_sends_hk_us_intraday_to_longbridge(monkeypatch):
    clear_providers()
    monkeypatch.setenv("LONGBRIDGE_APP_KEY", "k")
    monkeypatch.setenv("LONGBRIDGE_APP_SECRET", "s")
    monkeypatch.setenv("LONGBRIDGE_ACCESS_TOKEN", "t")

    seen: list[tuple[str, str]] = []

    def fake_fetch(self, symbol, interval, start=None, end=None):
        seen.append((symbol, interval))
        idx = pd.date_range("2026-01-02 09:30", periods=3, freq="min")
        return pd.DataFrame(
            {"open": 1, "high": 1, "low": 1, "close": 1, "volume": 1}, index=idx
        )

    monkeypatch.setattr(lb.LongbridgeProvider, "fetch_bars", fake_fetch)
    provider = get_provider(Market.HK)
    provider.fetch_bars("00700", "1m")
    provider.fetch_bars("AAPL", "1h")
    assert seen == [("00700", "1m"), ("AAPL", "1h")]
    clear_providers()


def test_router_keeps_daily_and_cn_minutes_on_tickflow(monkeypatch):
    clear_providers()
    monkeypatch.setenv("LONGBRIDGE_APP_KEY", "k")
    monkeypatch.setenv("LONGBRIDGE_APP_SECRET", "s")
    monkeypatch.setenv("LONGBRIDGE_ACCESS_TOKEN", "t")

    def boom(self, *args, **kwargs):
        raise AssertionError("daily/CN must not call Longbridge")

    monkeypatch.setattr(lb.LongbridgeProvider, "fetch_bars", boom)

    from quant_picker.data.providers import tickflow_provider as tf

    called: list[tuple[str, str]] = []

    def fake_tf(self, symbol, interval, start=None, end=None):
        called.append((symbol, interval))
        idx = pd.date_range("2026-01-02", periods=3, freq="D")
        return pd.DataFrame(
            {"open": 1, "high": 1, "low": 1, "close": 1, "volume": 1}, index=idx
        )

    monkeypatch.setattr(tf.TickFlowProvider, "fetch_bars", fake_tf)
    provider = RoutedProvider()
    provider.fetch_bars("00700", "1d")
    provider.fetch_bars("600519", "1m")
    assert called == [("00700", "1d"), ("600519", "1m")]


def test_router_explains_missing_longbridge_credentials(monkeypatch):
    clear_providers()
    monkeypatch.delenv("LONGBRIDGE_APP_KEY", raising=False)
    monkeypatch.delenv("LONGBRIDGE_APP_SECRET", raising=False)
    monkeypatch.delenv("LONGBRIDGE_ACCESS_TOKEN", raising=False)
    with pytest.raises(ValueError, match="长桥"):
        get_provider(Market.US).fetch_bars("AAPL", "1m")
    clear_providers()


def test_longbridge_provider_normalizes_candles(monkeypatch):
    candles = [
        _candle(datetime(2026, 1, 2, 9, 31), 11),
        _candle(datetime(2026, 1, 2, 9, 30), 10),
    ]
    ctx = SimpleNamespace(
        candlesticks=lambda *a, **k: candles,
        history_candlesticks_by_offset=lambda **k: candles,
    )
    monkeypatch.setattr(lb, "get_quote_context", lambda: ctx)
    bars = lb.LongbridgeProvider().fetch_bars("AAPL", "1m")
    assert list(bars.columns) == ["open", "high", "low", "close", "volume"]
    assert bars.index[0] == pd.Timestamp("2026-01-02 09:30:00")
    assert float(bars.iloc[0]["close"]) == 10


def test_longbridge_paginates_until_start(monkeypatch):
    page1 = [_candle(datetime(2026, 1, 2, 10, i), float(i)) for i in range(10)]
    page2 = [_candle(datetime(2026, 1, 2, 9, i), float(i)) for i in range(5)]
    calls = {"n": 0}

    def history(**kwargs):
        calls["n"] += 1
        if calls["n"] == 1:
            return page1
        return page2

    ctx = SimpleNamespace(history_candlesticks_by_offset=history)
    monkeypatch.setattr(lb, "get_quote_context", lambda: ctx)
    monkeypatch.setattr(lb, "_MAX_PAGE", 10)
    monkeypatch.setattr(lb, "_PAGE_PAUSE", 0)
    bars = lb.LongbridgeProvider().fetch_bars(
        "00700", "1m", start=datetime(2026, 1, 2, 9, 0)
    )
    assert calls["n"] == 2
    assert len(bars) >= 5
