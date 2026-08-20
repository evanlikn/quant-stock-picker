from __future__ import annotations

import numpy as np
import pandas as pd


def compute_price_factors(bars: pd.DataFrame) -> dict[str, float]:
    if bars.empty or len(bars) < 21:
        return {}

    close = bars["close"].astype(float)
    volume = bars["volume"].astype(float)

    factors: dict[str, float] = {}

    if len(close) >= 21:
        base = close.iloc[-21]
        if base > 0:
            factors["momentum_20d"] = float(close.iloc[-1] / base - 1)

    if len(close) >= 61:
        base = close.iloc[-61]
        if base > 0:
            factors["momentum_60d"] = float(close.iloc[-1] / base - 1)

    returns = close.pct_change().dropna()
    if len(returns) >= 20:
        factors["volatility_20d"] = float(returns.iloc[-20:].std())

    if len(volume) >= 25:
        recent = float(volume.iloc[-5:].mean())
        prior = float(volume.iloc[-25:-5].mean())
        if prior > 0:
            factors["volume_surge"] = recent / prior - 1

    if len(close) >= 20:
        ma20 = float(close.iloc[-20:].mean())
        if ma20 > 0:
            factors["ma_trend"] = float(close.iloc[-1] / ma20 - 1)

    return factors


def normalize_klines(raw: pd.DataFrame) -> pd.DataFrame:
    if raw.empty:
        return pd.DataFrame(columns=["open", "high", "low", "close", "volume"])
    out = raw.copy()
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


_FUNDAMENTAL_FIELD_MAP = {
    "roe": "roe",
    "revenue_yoy": "revenue_yoy",
    "net_margin": "net_margin",
    "roa": "roa",
    "debt_to_asset": "debt_to_asset_ratio",
}


def extract_fundamental_factors(row: pd.Series) -> dict[str, float]:
    factors: dict[str, float] = {}
    for factor_name, field in _FUNDAMENTAL_FIELD_MAP.items():
        if field not in row.index:
            continue
        val = row[field]
        if val is None or (isinstance(val, float) and np.isnan(val)):
            continue
        try:
            factors[factor_name] = float(val)
        except (TypeError, ValueError):
            continue
    return factors
