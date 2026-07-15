from __future__ import annotations

import re
from enum import Enum


class Market(str, Enum):
    CN = "cn"
    US = "us"
    HK = "hk"


def detect_market(symbol: str, override: str | None = None) -> Market:
    if override:
        return Market(override.lower())
    s = symbol.strip().upper()
    if re.fullmatch(r"[A-Z]{1,5}", s):
        return Market.US
    if re.fullmatch(r"\d{5}", s):
        return Market.HK
    if re.fullmatch(r"\d{6}", s):
        return Market.CN
    raise ValueError(f"无法识别股票代码市场: {symbol}")


def normalize_symbol(symbol: str, market: Market) -> str:
    s = symbol.strip()
    if market == Market.US:
        return s.upper()
    return s.zfill(6) if market == Market.CN else s.zfill(5)


def to_tickflow_symbol(symbol: str, market: Market) -> str:
    """Convert internal symbol to TickFlow format: CODE.MARKET_SUFFIX."""
    if market == Market.US:
        return f"{normalize_symbol(symbol, market)}.US"
    if market == Market.HK:
        return f"{normalize_symbol(symbol, market)}.HK"
    code = normalize_symbol(symbol, market)
    if code.startswith("6"):
        return f"{code}.SH"
    if code[0] in ("0", "3"):
        return f"{code}.SZ"
    if code[0] in ("4", "8", "9"):
        return f"{code}.BJ"
    return f"{code}.SZ"
