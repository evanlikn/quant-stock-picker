from __future__ import annotations

from datetime import datetime
from typing import Protocol

import pandas as pd

Interval = str


class DataProvider(Protocol):
    def fetch_bars(
        self,
        symbol: str,
        interval: Interval,
        start: datetime | None = None,
        end: datetime | None = None,
    ) -> pd.DataFrame:
        """Return OHLCV DataFrame with datetime index."""


def normalize_bars(df: pd.DataFrame) -> pd.DataFrame:
    """Standardize columns to open, high, low, close, volume."""
    col_map = {
        "日期": "date",
        "时间": "date",
        "datetime": "date",
        "开盘": "open",
        "收盘": "close",
        "最高": "high",
        "最低": "low",
        "成交量": "volume",
        "Open": "open",
        "High": "high",
        "Low": "low",
        "Close": "close",
        "Volume": "volume",
    }
    out = df.rename(columns=col_map).copy()
    if "date" in out.columns:
        out["date"] = pd.to_datetime(out["date"])
        out = out.set_index("date")
    elif not isinstance(out.index, pd.DatetimeIndex):
        out.index = pd.to_datetime(out.index)
    out = out.sort_index()
    if isinstance(out.index, pd.DatetimeIndex) and out.index.tz is not None:
        out.index = out.index.tz_convert(None)
    for c in ("open", "high", "low", "close", "volume"):
        if c not in out.columns:
            raise ValueError(f"Missing column: {c}")
    return out[["open", "high", "low", "close", "volume"]].astype(float)
