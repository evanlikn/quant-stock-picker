"""Intraday charts must give every bar its own slot on the x axis.

A continuous time axis squeezes a trading day's hourly bars into a thin
cluster, so an hourly chart looks like a daily one. These tests pin the
categorical axis that keeps each bar distinct.
"""

from __future__ import annotations

import pandas as pd
import pytest

from quant_picker.web.charts import backtest_dashboard_figure, price_chart_with_signals


def _hourly_frame(days: int = 5, per_day: int = 7) -> pd.DataFrame:
    """Mimic HK hours: 7 bars a day, then an overnight gap."""
    stamps = []
    for d in range(days):
        day = pd.Timestamp("2026-08-03") + pd.Timedelta(days=d)
        for h in (9.5, 10.5, 11.5, 13, 14, 15, 16):
            stamps.append(day + pd.Timedelta(hours=h))
        if len(stamps) >= days * per_day:
            continue
    idx = pd.DatetimeIndex(stamps)
    n = len(idx)
    return pd.DataFrame(
        {
            "open": range(1, n + 1),
            "high": range(2, n + 2),
            "low": range(0, n),
            "close": range(1, n + 1),
            "volume": [100] * n,
        },
        index=idx,
        dtype=float,
    )


def _signals(df: pd.DataFrame) -> pd.Series:
    sig = pd.Series("hold", index=df.index)
    sig.iloc[1] = "buy"
    sig.iloc[4] = "sell"
    # two signals inside the same trading day must stay separately visible
    sig.iloc[2] = "sell"
    return sig


def test_hourly_bars_each_get_a_distinct_axis_slot():
    df = _hourly_frame()
    fig = price_chart_with_signals(df, _signals(df), interval="1h")

    assert fig.layout.xaxis.type == "category"
    categories = list(fig.data[0].x)
    assert len(categories) == len(df)
    assert len(set(categories)) == len(df), "重复的分类会让同一天的时K 叠在一起"


def test_hourly_labels_carry_the_time_of_day():
    df = _hourly_frame()
    fig = price_chart_with_signals(df, _signals(df), interval="1h")
    assert list(fig.data[0].x)[:3] == ["08-03 09:30", "08-03 10:30", "08-03 11:30"]


def test_daily_labels_stay_date_only():
    idx = pd.date_range("2026-08-03", periods=6, freq="D")
    df = pd.DataFrame(
        {"open": 1.0, "high": 2.0, "low": 0.5, "close": 1.5, "volume": 10.0}, index=idx
    )
    fig = price_chart_with_signals(df, pd.Series("hold", index=idx), interval="1d")
    assert list(fig.data[0].x)[0] == "2026-08-03"


def test_intraday_signal_markers_land_on_bar_categories():
    df = _hourly_frame()
    sig = _signals(df)
    fig = price_chart_with_signals(df, sig, interval="1h")

    categories = set(fig.data[0].x)
    marker_traces = [t for t in fig.data if t.name in {"买入", "卖出"}]
    assert marker_traces, "应当画出买卖标记"
    for trace in marker_traces:
        assert set(trace.x) <= categories, "标记落在了 K 线分类之外"

    buy = next(t for t in fig.data if t.name == "买入")
    assert list(buy.x) == ["08-03 10:30"]
    sell = next(t for t in fig.data if t.name == "卖出")
    assert list(sell.x) == ["08-03 11:30", "08-03 14:00"]


def test_dashboard_aligns_equity_curve_with_the_kline_axis():
    df = _hourly_frame()
    equity = [1.0 + i * 0.01 for i in range(len(df))]
    fig = backtest_dashboard_figure(df, _signals(df), equity, interval="1h")

    kline = fig.data[0]
    eq = next(t for t in fig.data if t.name == "净值")
    assert list(eq.x) == list(kline.x), "权益曲线必须与 K 线共用同一条 X 轴"
    assert fig.layout.xaxis.type == "category"
    assert fig.layout.xaxis2.type == "category"


def test_dashboard_trims_axis_to_max_bars():
    df = _hourly_frame(days=5)
    equity = [1.0] * len(df)
    fig = backtest_dashboard_figure(df, _signals(df), equity, interval="1h", max_bars=10)
    assert len(fig.data[0].x) == 10


def test_both_panels_keep_their_time_axis():
    """shared_xaxes would blank the K-line labels and strand them under equity."""
    df = _hourly_frame(days=5)
    fig = backtest_dashboard_figure(df, _signals(df), [1.0] * len(df), interval="1h")
    assert fig.layout.xaxis.showticklabels is True
    assert fig.layout.xaxis2.showticklabels is True


def test_only_the_window_is_visible_and_the_rest_is_reachable():
    df = _hourly_frame(days=20)
    equity = [1.0 + i * 0.01 for i in range(len(df))]
    fig = backtest_dashboard_figure(
        df, _signals(df), equity, interval="1h", max_bars=140, window_bars=30
    )

    assert len(fig.data[0].x) == 140, "全部数据仍要载入，才能左右拖动"
    lo, hi = fig.layout.xaxis2.range
    assert hi - lo == 30, "一屏只显示 window_bars 根"
    assert hi == 139.5, "默认停在最新一根"
    assert fig.layout.xaxis2.rangeslider.visible is True
    assert fig.layout.dragmode == "pan"


def test_panels_pan_together():
    df = _hourly_frame(days=10)
    fig = backtest_dashboard_figure(
        df, _signals(df), [1.0] * len(df), interval="1h", window_bars=20
    )
    assert fig.layout.xaxis.matches == "x2"


def test_window_shorter_than_data_leaves_range_unset():
    df = _hourly_frame(days=2)
    fig = backtest_dashboard_figure(
        df, _signals(df), [1.0] * len(df), interval="1h", window_bars=500
    )
    assert fig.layout.xaxis2.range is None


def test_price_axis_fits_the_visible_window_not_all_history():
    """A far-away historical range (e.g. an unadjusted split) must not flatten
    the visible candles into a sliver."""
    df = _hourly_frame(days=20)
    df.iloc[: len(df) // 2, df.columns.get_loc("high")] = 5000.0
    fig = backtest_dashboard_figure(
        df, _signals(df), [1.0] * len(df), interval="1h", window_bars=20
    )
    lo, hi = fig.layout.yaxis.range
    assert hi < 1000, "y 轴被早期极值撑开了"
    visible_high = df["high"].iloc[-20:].max()
    assert hi >= visible_high


def test_equity_axis_covers_the_whole_curve_not_just_the_window():
    """The price panel can be dragged vertically to reach clipped values, the
    equity panel cannot. Fitting it to the starting window hid the curve as
    soon as you panned to a stretch that traded outside that range."""
    df = _hourly_frame(days=20)
    window = 20
    # equity ends up far from where the initial window sits
    equity = [1.0 + i * 0.05 for i in range(len(df))]

    fig = backtest_dashboard_figure(
        df, _signals(df), equity, interval="1h", window_bars=window
    )
    lo, hi = fig.layout.yaxis2.range
    assert lo <= min(equity) and hi >= max(equity)

    # every window the user can pan to stays inside the axis
    for start in range(0, len(equity) - window, window):
        chunk = equity[start : start + window]
        assert lo <= min(chunk) and max(chunk) <= hi


def test_price_axis_is_still_window_fitted_alongside_it():
    """Changing the equity axis must not widen the price axis."""
    df = _hourly_frame(days=20)
    df.iloc[: len(df) // 2, df.columns.get_loc("high")] = 5000.0
    fig = backtest_dashboard_figure(
        df, _signals(df), [1.0 + i * 0.05 for i in range(len(df))],
        interval="1h", window_bars=20,
    )
    assert fig.layout.yaxis.range[1] < 1000


def test_single_chart_also_windows_and_pans():
    df = _hourly_frame(days=20)
    fig = price_chart_with_signals(df, _signals(df), interval="1h", window_bars=25)
    lo, hi = fig.layout.xaxis.range
    assert hi - lo == 25
    assert fig.layout.xaxis.rangeslider.visible is True
    assert fig.layout.dragmode == "pan"


@pytest.mark.parametrize("interval", ["1m", "1h"])
def test_all_intraday_intervals_use_category_axis(interval):
    df = _hourly_frame()
    fig = price_chart_with_signals(df, _signals(df), interval=interval)
    assert fig.layout.xaxis.type == "category"
