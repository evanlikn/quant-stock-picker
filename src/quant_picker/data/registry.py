from __future__ import annotations

from quant_picker.config import longbridge_configured
from quant_picker.data.base import DataProvider, Interval
from quant_picker.data.providers.longbridge_provider import LongbridgeProvider
from quant_picker.data.providers.tickflow_provider import TickFlowProvider
from quant_picker.market.detector import Market, detect_market

_router = None


class RoutedProvider:
    """TickFlow for daily bars and A-share minutes; Longbridge for HK/US 1h and 1m."""

    def __init__(self) -> None:
        self._tickflow = TickFlowProvider()
        self._longbridge = LongbridgeProvider()

    def fetch_bars(
        self,
        symbol: str,
        interval: Interval,
        start=None,
        end=None,
    ):
        market = detect_market(symbol)
        if interval in ("1h", "1m") and market in (Market.US, Market.HK):
            if not longbridge_configured():
                raise ValueError(
                    "港股/美股的 1小时/1分钟 K 线走长桥 OpenAPI。"
                    "请在 config/.env 配置 LONGBRIDGE_APP_KEY、"
                    "LONGBRIDGE_APP_SECRET、LONGBRIDGE_ACCESS_TOKEN。"
                )
            return self._longbridge.fetch_bars(symbol, interval, start, end)
        return self._tickflow.fetch_bars(symbol, interval, start, end)


def get_provider(market: Market) -> DataProvider:
    del market  # kept so callers can pass the watchlist market; routing uses the symbol
    global _router
    if _router is None:
        _router = RoutedProvider()
    return _router


def clear_providers() -> None:
    global _router
    _router = None
