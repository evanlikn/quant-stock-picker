from __future__ import annotations

import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots


def _tail_df(df: pd.DataFrame, max_bars: int) -> pd.DataFrame:
    if len(df) <= max_bars:
        return df
    return df.iloc[-max_bars:]


def price_chart_with_signals(
    df: pd.DataFrame,
    signals: pd.Series,
    *,
    title: str = "",
    max_bars: int = 250,
    height: int = 420,
) -> go.Figure:
    """Candlestick chart with buy/sell markers overlaid."""
    view = _tail_df(df, max_bars)
    sig = signals.reindex(view.index).fillna("hold")

    fig = go.Figure()
    fig.add_trace(
        go.Candlestick(
            x=view.index,
            open=view["open"],
            high=view["high"],
            low=view["low"],
            close=view["close"],
            name="K线",
            increasing_line_color="#ef5350",
            decreasing_line_color="#26a69a",
        )
    )

    buy_mask = sig == "buy"
    sell_mask = sig == "sell"
    if buy_mask.any():
        fig.add_trace(
            go.Scatter(
                x=view.index[buy_mask],
                y=view.loc[buy_mask, "low"] * 0.995,
                mode="markers",
                name="买入",
                marker=dict(symbol="triangle-up", size=12, color="#2e7d32"),
                hovertemplate="买入<br>%{x}<br>收盘 %{customdata:.2f}<extra></extra>",
                customdata=view.loc[buy_mask, "close"],
            )
        )
    if sell_mask.any():
        fig.add_trace(
            go.Scatter(
                x=view.index[sell_mask],
                y=view.loc[sell_mask, "high"] * 1.005,
                mode="markers",
                name="卖出",
                marker=dict(symbol="triangle-down", size=12, color="#c62828"),
                hovertemplate="卖出<br>%{x}<br>收盘 %{customdata:.2f}<extra></extra>",
                customdata=view.loc[sell_mask, "close"],
            )
        )

    fig.update_layout(
        title=title,
        height=height,
        xaxis_rangeslider_visible=False,
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
        margin=dict(l=40, r=20, t=50, b=40),
    )
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
    title: str = "",
    max_bars: int = 250,
    height: int = 680,
) -> go.Figure:
    """K-line + signals (top) and equity curve (bottom)."""
    view = _tail_df(df, max_bars)
    sig = signals.reindex(view.index).fillna("hold")
    eq_len = min(len(equity_curve), len(view))
    eq = equity_curve[-eq_len:] if eq_len else []

    fig = make_subplots(
        rows=2,
        cols=1,
        shared_xaxes=False,
        row_heights=[0.62, 0.38],
        vertical_spacing=0.06,
        subplot_titles=("K 线与买卖信号", "全样本权益曲线"),
    )

    fig.add_trace(
        go.Candlestick(
            x=view.index,
            open=view["open"],
            high=view["high"],
            low=view["low"],
            close=view["close"],
            name="K线",
            increasing_line_color="#ef5350",
            decreasing_line_color="#26a69a",
        ),
        row=1,
        col=1,
    )
    buy_mask = sig == "buy"
    sell_mask = sig == "sell"
    if buy_mask.any():
        fig.add_trace(
            go.Scatter(
                x=view.index[buy_mask],
                y=view.loc[buy_mask, "low"] * 0.995,
                mode="markers",
                name="买入",
                marker=dict(symbol="triangle-up", size=11, color="#2e7d32"),
                showlegend=True,
            ),
            row=1,
            col=1,
        )
    if sell_mask.any():
        fig.add_trace(
            go.Scatter(
                x=view.index[sell_mask],
                y=view.loc[sell_mask, "high"] * 1.005,
                mode="markers",
                name="卖出",
                marker=dict(symbol="triangle-down", size=11, color="#c62828"),
                showlegend=True,
            ),
            row=1,
            col=1,
        )
    if eq:
        fig.add_trace(
            go.Scatter(
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
        xaxis_rangeslider_visible=False,
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
        margin=dict(l=40, r=20, t=60, b=40),
    )
    fig.update_yaxes(title_text="价格", row=1, col=1)
    fig.update_yaxes(title_text="净值", row=2, col=1)
    return fig
