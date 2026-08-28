from __future__ import annotations

from datetime import datetime

import pandas as pd

from quant_picker.config import load_settings
from quant_picker.data.bars_util import prepare_ohlcv
from quant_picker.data.base import Interval
from quant_picker.data.providers.tickflow_client import get_tickflow_client
from quant_picker.market.detector import Market, detect_market, to_tickflow_symbol

_PERIOD: dict[str, str] = {"1d": "1d", "1h": "60m", "1m": "1m"}
_MAX_BARS = 10_000


def _intraday_error_hint(exc_msg: str) -> str:
    import os

    from quant_picker.config import load_env

    load_env()
    has_key = bool(os.getenv("TICKFLOW_API_KEY", "").strip())
    if "无分钟K线查询权限" in exc_msg:
        if has_key:
            return (
                "当前 TICKFLOW_API_KEY 已配置，但账号无分钟/小时 K 线权限；"
                "请在 tickflow.org 开通支持分钟数据的套餐。"
            )
        return "分钟级 K 线需配置 TICKFLOW_API_KEY，并使用支持分钟数据的套餐（免费服务仅日K）。"
    if not has_key:
        return "分钟级 K 线需配置 TICKFLOW_API_KEY（免费服务仅支持日K）。"
    return ""


def _default_count(interval: Interval) -> int:
    history = load_settings().get("scheduler", {}).get("initial_history", {})
    window = history.get(interval, "365d")
    days = max(int(str(window).rstrip("d")), 1)
    if interval == "1d":
        return min(days + 30, _MAX_BARS)
    if interval == "1h":
        return min(days * 4, _MAX_BARS)
    return min(days * 240, _MAX_BARS)


def _normalize_klines(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return pd.DataFrame(columns=["open", "high", "low", "close", "volume"])
    out = df.copy()
    if "trade_time" in out.columns:
        out.index = pd.to_datetime(out["trade_time"])
    elif "timestamp" in out.columns:
        out.index = pd.to_datetime(out["timestamp"], unit="ms")
    else:
        raise ValueError("TickFlow klines missing trade_time/timestamp")
    out = out.sort_index()
    if isinstance(out.index, pd.DatetimeIndex) and out.index.tz is not None:
        out.index = out.index.tz_convert(None)
    return out[["open", "high", "low", "close", "volume"]].astype(float)


class TickFlowProvider:
    """Unified OHLCV provider for CN / US / HK via TickFlow SDK."""

    def fetch_bars(
        self,
        symbol: str,
        interval: Interval,
        start: datetime | None = None,
        end: datetime | None = None,
    ) -> pd.DataFrame:
        if interval not in _PERIOD:
            raise ValueError(f"Unsupported interval: {interval}")

        market = detect_market(symbol)
        tf_symbol = to_tickflow_symbol(symbol, market)
        period = _PERIOD[interval]
        tf = get_tickflow_client()

        kwargs: dict = {
            "period": period,
            "adjust": "forward_additive",
            "as_dataframe": True,
        }
        if start is not None:
            kwargs["start_time"] = int(pd.Timestamp(start).timestamp() * 1000)
            if end is not None:
                kwargs["end_time"] = int(pd.Timestamp(end).timestamp() * 1000)
            else:
                kwargs["end_time"] = int(pd.Timestamp.utcnow().timestamp() * 1000)
            kwargs["count"] = _MAX_BARS
        else:
            kwargs["count"] = _default_count(interval)

        try:
            raw = tf.klines.get(tf_symbol, **kwargs)
        except Exception as exc:
            if interval != "1d":
                if market in (Market.US, Market.HK):
                    hint = (
                        "港股/美股的分钟/小时 K 线请配置长桥 OpenAPI"
                        "（LONGBRIDGE_APP_KEY / LONGBRIDGE_APP_SECRET / LONGBRIDGE_ACCESS_TOKEN）。"
                    )
                    raise ValueError(
                        f"获取 {tf_symbol} {interval} 行情失败: {exc}。{hint}"
                    ) from exc
                hint = _intraday_error_hint(str(exc))
                msg = f"获取 {tf_symbol} {interval} 行情失败: {exc}"
                if hint:
                    msg += f"。{hint}"
                raise ValueError(msg) from exc
            raise ValueError(f"无法获取 {tf_symbol} 的行情数据: {exc}") from exc

        bars = _normalize_klines(raw)
        if start is not None:
            bars = bars[bars.index >= pd.Timestamp(start)]
        if end is not None:
            bars = bars[bars.index <= pd.Timestamp(end)]
        bars, _ = prepare_ohlcv(
            bars,
            interval,
            trim_history=(start is None),
            ensure_continuous=True,
        )
        if bars.empty:
            raise ValueError(f"无法获取 {tf_symbol} 的行情数据")
        return bars
