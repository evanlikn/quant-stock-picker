from __future__ import annotations

import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots

# Intraday bars only occupy a few hours of each day, so a continuous time axis
# renders them as a thin daily cluster separated by overnight/weekend blanks.
# Every trading terminal instead spaces bars evenly, which also sidesteps
# per-market sessions and holidays; we do the same via a categorical x axis.
_INTRADAY_INTERVALS = {"1m", "5m", "15m", "30m", "1h", "60m", "2h", "4h"}

_MAX_XTICKS = 10

# Plotly config for st.plotly_chart: lets the wheel zoom the time axis while
# drag pans it, which is how the fixed-width bar window is navigated.
PAN_CHART_CONFIG = {"scrollZoom": True, "displaylogo": False}


def _is_intraday(interval: str) -> bool:
    return interval.lower() in _INTRADAY_INTERVALS


def _window_range(total: int, window_bars: int | None) -> list[float] | None:
    """Initial x range holding the newest `window_bars` categories."""
    if not window_bars or total <= window_bars:
        return None
    return [total - window_bars - 0.5, total - 0.5]


def _visible_slice(n: int, window_bars: int | None) -> slice:
    if not window_bars or n <= window_bars:
        return slice(0, n)
    return slice(n - window_bars, n)


def _fit_y_range(low, high, pad: float = 0.04) -> list[float] | None:
    """Scale y to the visible bars.

    Without this the axis spans every loaded bar, so a window sitting far from
    the all-time range (a split, or a long downtrend) gets flattened into a
    sliver. Plotly cannot rescale y while panning, so double-click resets.
    """
    lo, hi = float(min(low)), float(max(high))
    if not (lo < hi):
        return None
    margin = (hi - lo) * pad
    return [lo - margin, hi + margin]


def _bar_labels(index: pd.Index, interval: str) -> list[str]:
    """Evenly spaced axis categories; intraday keeps the time-of-day."""
    fmt = "%m-%d %H:%M" if _is_intraday(interval) else "%Y-%m-%d"
    return [pd.Timestamp(ts).strftime(fmt) for ts in index]


def _hover_labels(index: pd.Index, interval: str) -> list[str]:
    fmt = "%Y-%m-%d %H:%M" if _is_intraday(interval) else "%Y-%m-%d"
    return [pd.Timestamp(ts).strftime(fmt) for ts in index]


def _apply_category_axis(
    fig: go.Figure,
    labels: list[str],
    *,
    window_bars: int | None = None,
    **kwargs,
) -> None:
    fig.update_xaxes(
        type="category",
        categoryorder="array",
        categoryarray=labels,
        nticks=_MAX_XTICKS,
        tickangle=-30,
        showticklabels=True,
        range=_window_range(len(labels), window_bars),
        **kwargs,
    )


def _tail_df(df: pd.DataFrame, max_bars: int) -> pd.DataFrame:
    if len(df) <= max_bars:
        return df
    return df.iloc[-max_bars:]


def price_chart_with_signals(
    df: pd.DataFrame,
    signals: pd.Series,
    *,
    interval: str = "1d",
    title: str = "",
    max_bars: int = 250,
    window_bars: int | None = 120,
    height: int = 460,
) -> go.Figure:
    """Candlestick chart with buy/sell markers overlaid."""
    view = _tail_df(df, max_bars)
    sig = signals.reindex(view.index).fillna("hold")
    labels = _bar_labels(view.index, interval)
    hovers = _hover_labels(view.index, interval)
    label_at = pd.Series(labels, index=view.index)
    hover_at = pd.Series(hovers, index=view.index)

    fig = go.Figure()
    fig.add_trace(
        go.Candlestick(
            x=labels,
            open=view["open"],
            high=view["high"],
            low=view["low"],
            close=view["close"],
            name="K线",
            text=hovers,
            increasing_line_color="#ef5350",
            decreasing_line_color="#26a69a",
        )
    )

    buy_mask = (sig == "buy").to_numpy()
    sell_mask = (sig == "sell").to_numpy()
    if buy_mask.any():
        fig.add_trace(
            go.Scatter(
                x=label_at[buy_mask].tolist(),
                y=view.loc[buy_mask, "low"] * 0.995,
                mode="markers",
                name="买入",
                marker=dict(symbol="triangle-up", size=12, color="#2e7d32"),
                customdata=list(
                    zip(hover_at[buy_mask], view.loc[buy_mask, "close"])
                ),
                hovertemplate="买入<br>%{customdata[0]}<br>收盘 %{customdata[1]:.2f}<extra></extra>",
            )
        )
    if sell_mask.any():
        fig.add_trace(
            go.Scatter(
                x=label_at[sell_mask].tolist(),
                y=view.loc[sell_mask, "high"] * 1.005,
                mode="markers",
                name="卖出",
                marker=dict(symbol="triangle-down", size=12, color="#c62828"),
                customdata=list(
                    zip(hover_at[sell_mask], view.loc[sell_mask, "close"])
                ),
                hovertemplate="卖出<br>%{customdata[0]}<br>收盘 %{customdata[1]:.2f}<extra></extra>",
            )
        )

    fig.update_layout(
        title=title,
        height=height,
        dragmode="pan",
        hovermode="x",
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
        margin=dict(l=50, r=20, t=50, b=20),
    )
    _apply_category_axis(fig, labels, window_bars=window_bars)
    fig.update_xaxes(rangeslider=dict(visible=True, thickness=0.08))
    vis = _visible_slice(len(view), window_bars)
    fig.update_yaxes(range=_fit_y_range(view["low"].iloc[vis], view["high"].iloc[vis]))
    return fig


def equity_curve_chart(
    equity_curve: list[float],
    *,
    title: str = "权益曲线",
    height: int = 320,
) -> go.Figure | None:
    if not equity_curve:
        return None
    eq = pd.Series(equity_curve)
    fig = go.Figure()
    fig.add_trace(
        go.Scatter(
            y=eq,
            mode="lines",
            name="净值",
            line=dict(color="#1565c0", width=2),
            fill="tozeroy",
            fillcolor="rgba(21, 101, 192, 0.08)",
        )
    )
    fig.update_layout(
        title=title,
        height=height,
        yaxis_title="净值",
        xaxis_title="Bar",
        margin=dict(l=40, r=20, t=50, b=40),
    )
    return fig


def backtest_dashboard_figure(
    df: pd.DataFrame,
    signals: pd.Series,
    equity_curve: list[float],
    *,
    interval: str = "1d",
    title: str = "",
    max_bars: int = 250,
    window_bars: int | None = 120,
    height: int = 760,
) -> go.Figure:
    """K-line + signals (top) and equity curve (bottom), sharing one bar axis.

    `max_bars` is how much history the figure holds; `window_bars` is how much
    of it is visible at once. The rest is reachable by dragging or via the
    range slider under the equity curve.
    """
    view = _tail_df(df, max_bars)
    sig = signals.reindex(view.index).fillna("hold")
    labels = _bar_labels(view.index, interval)
    hovers = _hover_labels(view.index, interval)
    label_at = pd.Series(labels, index=view.index)
    hover_at = pd.Series(hovers, index=view.index)
    eq_len = min(len(equity_curve), len(view))
    eq = equity_curve[-eq_len:] if eq_len else []

    # shared_xaxes=True would blank the K-line panel's own tick labels and
    # leave the only time axis stranded under the equity curve; link the axes
    # explicitly instead so both panels keep their labels.
    fig = make_subplots(
        rows=2,
        cols=1,
        shared_xaxes=False,
        row_heights=[0.68, 0.32],
        vertical_spacing=0.16,
        subplot_titles=("K 线与买卖信号", "全样本权益曲线"),
    )

    fig.add_trace(
        go.Candlestick(
            x=labels,
            open=view["open"],
            high=view["high"],
            low=view["low"],
            close=view["close"],
            name="K线",
            text=hovers,
            increasing_line_color="#ef5350",
            decreasing_line_color="#26a69a",
        ),
        row=1,
        col=1,
    )
    buy_mask = (sig == "buy").to_numpy()
    sell_mask = (sig == "sell").to_numpy()
    if buy_mask.any():
        fig.add_trace(
            go.Scatter(
                x=label_at[buy_mask].tolist(),
                y=view.loc[buy_mask, "low"] * 0.995,
                mode="markers",
                name="买入",
                marker=dict(symbol="triangle-up", size=11, color="#2e7d32"),
                customdata=list(
                    zip(hover_at[buy_mask], view.loc[buy_mask, "close"])
                ),
                hovertemplate="买入<br>%{customdata[0]}<br>收盘 %{customdata[1]:.2f}<extra></extra>",
                showlegend=True,
            ),
            row=1,
            col=1,
        )
    if sell_mask.any():
        fig.add_trace(
            go.Scatter(
                x=label_at[sell_mask].tolist(),
                y=view.loc[sell_mask, "high"] * 1.005,
                mode="markers",
                name="卖出",
                marker=dict(symbol="triangle-down", size=11, color="#c62828"),
                customdata=list(
                    zip(hover_at[sell_mask], view.loc[sell_mask, "close"])
                ),
                hovertemplate="卖出<br>%{customdata[0]}<br>收盘 %{customdata[1]:.2f}<extra></extra>",
                showlegend=True,
            ),
            row=1,
            col=1,
        )
    if eq:
        fig.add_trace(
            go.Scatter(
                x=labels[-eq_len:],
                y=eq,
                mode="lines",
                name="净值",
                line=dict(color="#1565c0", width=2),
            ),
            row=2,
            col=1,
        )

    fig.update_layout(
        title=title,
        height=height,
        dragmode="pan",
        hovermode="x",
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
        margin=dict(l=50, r=20, t=70, b=20),
    )
    _apply_category_axis(fig, labels, window_bars=window_bars, row=1, col=1)
    _apply_category_axis(fig, labels, window_bars=window_bars, row=2, col=1)
    # Panning either panel moves both; the slider under the equity curve
    # drives the whole window.
    fig.update_xaxes(matches="x2", rangeslider_visible=False, row=1, col=1)
    fig.update_xaxes(
        rangeslider=dict(visible=True, thickness=0.06),
        row=2,
        col=1,
    )

    vis = _visible_slice(len(view), window_bars)
    fig.update_yaxes(
        title_text="价格",
        range=_fit_y_range(view["low"].iloc[vis], view["high"].iloc[vis]),
        row=1,
        col=1,
    )
    # The price panel can be dragged vertically to reach values outside its
    # window-fitted range, but the equity panel cannot, so pin it to the whole
    # curve instead of the starting window or it clips as soon as you pan.
    fig.update_yaxes(
        title_text="净值",
        range=_fit_y_range(eq, eq) if eq else None,
        row=2,
        col=1,
    )
    return fig
