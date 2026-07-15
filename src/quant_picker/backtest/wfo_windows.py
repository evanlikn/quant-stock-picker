from __future__ import annotations

from collections.abc import Iterator
from typing import Any

import pandas as pd

from quant_picker.config import load_settings


def parse_window_days(value: Any) -> int:
    """Parse walk-forward window size from YAML int or strings like '180d'."""
    if isinstance(value, int):
        return value
    s = str(value).strip().lower()
    if s.endswith("d"):
        return int(s[:-1] or "0")
    return int(s)


def uses_calendar_overlapping(interval: str) -> bool:
    wf = load_settings().get("walk_forward", {})
    mode = str(wf.get("mode", "sequential")).lower()
    unit = str(wf.get("window_unit", {}).get(interval, "bars")).lower()
    return mode == "overlapping" and unit == "calendar" and interval == "1d"


def window_sizes(interval: str) -> tuple[int, int, int]:
    wf = load_settings().get("walk_forward", {})
    train = parse_window_days(wf.get("train_bars", {}).get(interval, 120))
    test = parse_window_days(wf.get("test_bars", {}).get(interval, 40))
    step = parse_window_days(wf.get("step_bars", {}).get(interval, 20))
    return train, test, step


def min_calendar_span_days(interval: str) -> int | None:
    if not uses_calendar_overlapping(interval):
        return None
    train, test, step = window_sizes(interval)
    min_folds = int(load_settings().get("walk_forward", {}).get("min_folds", 3))
    return train + test + step * max(min_folds - 1, 0)


def min_trading_bars_for_wfo(interval: str) -> int:
    cal_days = min_calendar_span_days(interval)
    if cal_days is not None:
        # Calendar days -> approximate trading bars (buffer for holidays).
        return int(cal_days * 252 / 365) + 50

    wf = load_settings().get("walk_forward", {})
    train, test, step = window_sizes(interval)
    min_folds = int(wf.get("min_folds", 3))
    return train + test + step * max(min_folds - 1, 0)


def iter_bar_folds(
    df: pd.DataFrame,
    train_bars: int,
    test_bars: int,
    step_bars: int,
) -> Iterator[tuple[pd.DataFrame, pd.DataFrame]]:
    """Classic bar-index sliding windows (overlaps when step_bars < test_bars)."""
    start = 0
    n = len(df)
    while start + train_bars + test_bars <= n:
        train_slice = df.iloc[start : start + train_bars]
        test_slice = df.iloc[start + train_bars : start + train_bars + test_bars]
        yield train_slice, test_slice
        start += step_bars


def iter_calendar_overlapping_folds(
    df: pd.DataFrame,
    train_days: int,
    test_days: int,
    step_days: int,
    *,
    min_train_bars: int = 30,
    min_test_bars: int | None = None,
) -> Iterator[tuple[pd.DataFrame, pd.DataFrame]]:
    """
    Overlapping walk-forward on daily bars using calendar-day windows.

    Each fold:
      - train: [anchor, anchor + train_days)
      - test:  [anchor + train_days, anchor + train_days + test_days)
    Anchor advances by step_days calendar (test windows overlap when step_days < test_days).
    """
    if df.empty:
        return

    idx = df.index
    if not isinstance(idx, pd.DatetimeIndex):
        raise ValueError("Calendar overlapping WFO requires a DatetimeIndex")

    if min_test_bars is None:
        # Require ~80% of expected trading bars in a full calendar test window.
        min_test_bars = max(30, int(test_days * 252 / 365 * 0.8))

    anchor_pos = 0
    n = len(df)
    while anchor_pos < n:
        train_start = idx[anchor_pos]
        train_end = train_start + pd.Timedelta(days=train_days)
        test_end = train_end + pd.Timedelta(days=test_days)

        train_slice = df[(idx >= train_start) & (idx < train_end)]
        test_slice = df[(idx >= train_end) & (idx < test_end)]

        if train_slice.empty or test_slice.empty:
            break
        if len(train_slice) < min_train_bars or len(test_slice) < min_test_bars:
            break

        yield train_slice, test_slice

        step_target = train_start + pd.Timedelta(days=step_days)
        next_pos = int(idx.searchsorted(step_target, side="left"))
        if next_pos <= anchor_pos:
            next_pos = anchor_pos + 1
        anchor_pos = next_pos


def iter_walk_forward_folds(
    df: pd.DataFrame,
    interval: str,
    *,
    step_override: int | None = None,
) -> Iterator[tuple[pd.DataFrame, pd.DataFrame]]:
    train, test, step = window_sizes(interval)
    if step_override is not None:
        step = step_override

    if uses_calendar_overlapping(interval):
        yield from iter_calendar_overlapping_folds(df, train, test, step)
    else:
        yield from iter_bar_folds(df, train, test, step)
