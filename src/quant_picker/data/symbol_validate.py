from __future__ import annotations

from quant_picker.data.providers.tickflow_client import get_tickflow_client
from quant_picker.market.detector import Market, to_tickflow_symbol


class SymbolNotFoundError(ValueError):
    """Raised when TickFlow has no instrument for the symbol."""


def lookup_instrument(symbol: str, market: Market) -> dict:
    """Return TickFlow instrument metadata; raise SymbolNotFoundError if missing."""
    tf_symbol = to_tickflow_symbol(symbol, market)
    inst = get_tickflow_client().instruments.get(tf_symbol)
    if not inst or not inst.get("symbol") or not inst.get("name"):
        raise SymbolNotFoundError(f"股票代码不存在: {symbol}（{tf_symbol}）")
    return inst


def validate_symbol(symbol: str, market: Market) -> str:
    """Validate symbol exists; return display name."""
    return str(lookup_instrument(symbol, market)["name"])
