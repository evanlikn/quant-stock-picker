from __future__ import annotations

from quant_picker.data.base import DataProvider
from quant_picker.data.providers.tickflow_provider import TickFlowProvider
from quant_picker.market.detector import Market

_provider: TickFlowProvider | None = None


def get_provider(market: Market) -> DataProvider:
    global _provider
    if _provider is None:
        _provider = TickFlowProvider()
    return _provider
