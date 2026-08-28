from __future__ import annotations

import time
from datetime import datetime

import pandas as pd

from quant_picker.config import load_settings
from quant_picker.data.bars_util import prepare_ohlcv
from quant_picker.data.base import Interval
from quant_picker.data.providers.longbridge_client import get_quote_context
from quant_picker.market.detector import Market, detect_market, to_longbridge_symbol

_MAX_PAGE = 1000
_PAGE_PAUSE = 0.55  # stay under 60 requests / 30s


def _period(interval: Interval):
    from longbridge.openapi import Period

    if interval == "1m":
        return Period.Min_1
    if interval == "1h":
        return Period.Min_60
    raise ValueError(f"长桥行情仅用于港股/美股的 1h/1m，不支持 {interval}")


def _default_count(interval: Interval) -> int:
    history = load_settings().get("scheduler", {}).get("initial_history", {})
    window = history.get(interval, "365d")
    days = max(int(str(window).rstrip("d")), 1)
    if interval == "1h":
        return min(days * 8, 50_000)
    return min(days * 390, 50_000)


def _bar_timestamp(candle) -> pd.Timestamp:
    ts = candle.timestamp
    if isinstance(ts, datetime):
        stamp = pd.Timestamp(ts)
    else:
        stamp = pd.Timestamp(int(ts), unit="s", tz="UTC")
    if stamp.tzinfo is not None:
        stamp = stamp.tz_convert("UTC").tz_localize(None)
    return stamp


def _normalize(candles) -> pd.DataFrame:
    if not candles:
        return pd.DataFrame(columns=["open", "high", "low", "close", "volume"])
    rows = []
    for candle in candles:
        rows.append(
            {
                "time": _bar_timestamp(candle),
                "open": float(candle.open),
                "high": float(candle.high),
                "low": float(candle.low),
                "close": float(candle.close),
                "volume": float(candle.volume),
            }
        )
    out = pd.DataFrame(rows).drop_duplicates(subset=["time"]).set_index("time").sort_index()
    return out[["open", "high", "low", "close", "volume"]]


def _as_naive(value: datetime) -> datetime:
    stamp = pd.Timestamp(value)
    if stamp.tzinfo is not None:
        stamp = stamp.tz_convert("UTC").tz_localize(None)
    return stamp.to_pydatetime()


class LongbridgeProvider:
    """HK / US 1h and 1m OHLCV via Longbridge OpenAPI."""

    def fetch_bars(
        self,
        symbol: str,
        interval: Interval,
        start: datetime | None = None,
        end: datetime | None = None,
    ) -> pd.DataFrame:
        market = detect_market(symbol)
        if market not in (Market.US, Market.HK):
            raise ValueError(f"长桥分钟 K 线仅用于港股/美股，收到 {market}")

        lb_symbol = to_longbridge_symbol(symbol, market)
        period = _period(interval)
        ctx = get_quote_context()
        try:
            if start is None:
                bars = self._recent(ctx, lb_symbol, period, interval)
            else:
                bars = self._range(ctx, lb_symbol, period, start, end)
        except ValueError:
            raise
        except Exception as exc:
            raise ValueError(f"长桥获取 {lb_symbol} {interval} 行情失败: {exc}") from exc

        if start is not None:
            bars = bars[bars.index >= pd.Timestamp(_as_naive(start))]
        if end is not None:
            bars = bars[bars.index <= pd.Timestamp(_as_naive(end))]
        bars, _ = prepare_ohlcv(
            bars,
            interval,
            trim_history=(start is None),
            ensure_continuous=True,
        )
        if bars.empty:
            raise ValueError(f"长桥未返回 {lb_symbol} 的 {interval} 行情")
        return bars

    def _recent(self, ctx, lb_symbol: str, period, interval: Interval) -> pd.DataFrame:
        from longbridge.openapi import AdjustType, TradeSessions

        count = min(_default_count(interval), _MAX_PAGE)
        raw = ctx.candlesticks(
            lb_symbol, period, count, AdjustType.ForwardAdjust, TradeSessions.Intraday
        )
        return _normalize(raw)

    def _range(
        self,
        ctx,
        lb_symbol: str,
        period,
        start: datetime,
        end: datetime | None,
    ) -> pd.DataFrame:
        from longbridge.openapi import AdjustType, TradeSessions

        start_naive = _as_naive(start)
        cursor = _as_naive(end) if end is not None else None
        chunks: list[pd.DataFrame] = []
        pages = 0
        while True:
            kwargs = {
                "symbol": lb_symbol,
                "period": period,
                "adjust_type": AdjustType.ForwardAdjust,
                "forward": False,
                "count": _MAX_PAGE,
                "trade_sessions": TradeSessions.Intraday,
            }
            if cursor is not None:
                kwargs["time"] = cursor
            raw = ctx.history_candlesticks_by_offset(**kwargs)
            page = _normalize(raw)
            pages += 1
            if page.empty:
                break
            chunks.append(page)
            oldest = page.index.min().to_pydatetime()
            if oldest <= start_naive or len(page) < _MAX_PAGE:
                break
            cursor = oldest
            time.sleep(_PAGE_PAUSE)

        if not chunks:
            return _normalize([])
        bars = pd.concat(chunks).sort_index()
        bars = bars[~bars.index.duplicated(keep="last")]
        return bars
