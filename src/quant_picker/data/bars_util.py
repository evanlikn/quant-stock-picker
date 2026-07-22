from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta

import pandas as pd

from quant_picker.config import load_settings
from quant_picker.data.base import Interval


@dataclass
class ContinuityInfo:
    original_count: int = 0
    kept_count: int = 0
    dropped_count: int = 0
    segment_start: datetime | None = None
    gap_break_found: bool = False

    @property
    def was_trimmed(self) -> bool:
        return self.dropped_count > 0


def initial_history_days(interval: Interval) -> int:
    history = load_settings().get("scheduler", {}).get("initial_history", {})
    window = history.get(interval, "365d")
    return max(int(str(window).rstrip("d")), 1)


def effective_history_days(item) -> int:
    """Per-watchlist history window, falling back to global scheduler defaults."""
    days = getattr(item, "history_days", None)
    if days is not None and int(days) > 0:
        return int(days)
    return initial_history_days(getattr(item, "interval", "1d"))


def history_fetch_start(history_days: int) -> datetime:
    """Calendar start for remote fetch (extra buffer for non-trading days)."""
    days = max(int(history_days), 1)
    return datetime.utcnow() - timedelta(days=days + 14)


def max_bar_gap_days(interval: Interval) -> int:
    """Max calendar days between adjacent bars before treating as a data break."""
    dq = load_settings().get("data_quality", {}) or {}
    gaps = dq.get("max_bar_gap_days", {}) or {}
    return int(gaps.get(interval, gaps.get("1d", 30)))


def bars_calendar_span_days(df: pd.DataFrame) -> int:
    if df.empty or not isinstance(df.index, pd.DatetimeIndex):
        return 0
    return max((df.index.max() - df.index.min()).days, 0)


def bars_cover_history(
    df: pd.DataFrame,
    interval: Interval,
    *,
    slack_days: int = 14,
    history_days: int | None = None,
) -> bool:
    """True when continuous bars span at least the configured initial_history window."""
    if df.empty:
        return False
    required = history_days if history_days is not None else initial_history_days(interval)
    return bars_calendar_span_days(df) + slack_days >= required


def _normalize_ohlcv_index(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return df
    out = df.sort_index()
    out = out[~out.index.duplicated(keep="last")]
    return out


def trim_latest_continuous(
    df: pd.DataFrame,
    interval: Interval,
    *,
    max_gap_days: int | None = None,
) -> tuple[pd.DataFrame, ContinuityInfo]:
    """
    Keep only the latest contiguous segment.

    Scans backward; the first gap larger than max_gap_days marks where
    the recent continuous segment begins (older bars may be dirty/sparse).
    """
    info = ContinuityInfo(original_count=len(df))
    if df.empty or len(df) < 2:
        info.kept_count = len(df)
        if not df.empty:
            info.segment_start = pd.Timestamp(df.index.min()).to_pydatetime()
        return df, info

    view = _normalize_ohlcv_index(df)
    gap_limit = max_gap_days if max_gap_days is not None else max_bar_gap_days(interval)
    idx = view.index
    start_pos = 0

    for i in range(len(view) - 1, 0, -1):
        gap_days = (idx[i] - idx[i - 1]).total_seconds() / 86400.0
        if gap_days > gap_limit:
            start_pos = i
            break

    trimmed = view.iloc[start_pos:].copy()
    info.original_count = len(view)
    info.kept_count = len(trimmed)
    info.dropped_count = info.original_count - info.kept_count
    info.gap_break_found = start_pos > 0
    if not trimmed.empty:
        info.segment_start = pd.Timestamp(trimmed.index.min()).to_pydatetime()
    return trimmed, info


def trim_bars(
    bars: pd.DataFrame,
    interval: Interval,
    start: datetime | None,
    end: datetime | None,
    *,
    history_days: int | None = None,
) -> pd.DataFrame:
    if start is not None:
        bars = bars[bars.index >= pd.Timestamp(start)]
    if end is not None:
        bars = bars[bars.index <= pd.Timestamp(end)]

    if start is None and not bars.empty:
        days = history_days if history_days is not None else initial_history_days(interval)
        cutoff = bars.index.max() - timedelta(days=max(int(days), 1))
        bars = bars[bars.index >= cutoff]
    return bars


def trim_to_history_days(df: pd.DataFrame, history_days: int) -> pd.DataFrame:
    if df.empty or history_days <= 0:
        return df
    cutoff = df.index.max() - timedelta(days=int(history_days))
    return df[df.index >= cutoff]


def prepare_ohlcv(
    df: pd.DataFrame,
    interval: Interval,
    *,
    trim_history: bool = False,
    ensure_continuous: bool = True,
    history_days: int | None = None,
) -> tuple[pd.DataFrame, ContinuityInfo]:
    """
    Standard OHLCV cleanup pipeline: sort/dedupe -> optional history window -> continuity trim.
    """
    if df.empty:
        return df, ContinuityInfo()

    out = _normalize_ohlcv_index(df)
    if trim_history:
        out = trim_bars(out, interval, start=None, end=None, history_days=history_days)

    if ensure_continuous:
        out, info = trim_latest_continuous(out, interval)
        return out, info

    info = ContinuityInfo(original_count=len(out), kept_count=len(out))
    if not out.empty:
        info.segment_start = pd.Timestamp(out.index.min()).to_pydatetime()
    return out, info
