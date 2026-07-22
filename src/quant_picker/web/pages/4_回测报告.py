from __future__ import annotations

import json
import os
import sys

_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "..", ".."))
if _ROOT not in sys.path:
    sys.path.insert(0, os.path.join(_ROOT, "src"))
os.environ.setdefault("QUANT_PICKER_ROOT", _ROOT)

import streamlit as st

from quant_picker.backtest.engine import BacktestEngine
from quant_picker.backtest.oos_quality import oos_sample_warning
from quant_picker.backtest.report import BacktestReport
from quant_picker.config import load_strategies_config
from quant_picker.data.bar_sync import BarSyncService
from quant_picker.data.bars_util import bars_calendar_span_days, bars_cover_history, initial_history_days
from quant_picker.storage.db import get_session_factory, init_db
from quant_picker.storage.repository import Repository
from quant_picker.strategies.registry import build_strategy
from quant_picker.portfolio.position_sizer import get_position_sizing_config
from quant_picker.web.charts import backtest_dashboard_figure, equity_curve_chart

st.set_page_config(page_title="回测报告", page_icon="📊", layout="wide")
init_db()
repo = Repository(get_session_factory()())

st.title("回测报告")
st.caption("展示 Walk-forward 优化后的 OOS 指标、全样本回测与 K 线买卖信号")

items = repo.list_watchlist()
if not items:
    st.info("暂无自选，请先在「自选管理」中添加并完成 Walk-forward 训练。")
    st.stop()

options = {f"{i.symbol} ({i.market.upper()} · {i.interval})": i for i in items}
selected_label = st.selectbox("选择自选", list(options.keys()))
item = options[selected_label]

strategies_cfg = [
    s["name"]
    for s in load_strategies_config().get("strategies", [])
    if s.get("enabled", True)
]
if not strategies_cfg:
    st.warning("未启用任何策略，请检查 config/strategies.yaml")
    st.stop()

strategy_name = st.selectbox("选择策略", strategies_cfg)

df = repo.load_bars(item.symbol, item.market, item.interval)
raw_bar_count = repo.count_bars(item.symbol, item.market, item.interval)
sync_col, info_col = st.columns([1, 3])
with sync_col:
    if st.button("同步行情", type="secondary"):
        with st.spinner("拉取历史 K 线..."):
            sync = BarSyncService(repo)
            df, inserted = sync.sync(
                item.symbol, item.market, item.interval, force_full=True
            )
        st.success(f"已同步，新增 {inserted} 根")
        st.rerun()

if df.empty:
    st.error("本地无 K 线数据，请点击「同步行情」或在「自选管理」中刷新该自选。")
    st.stop()

span_days = bars_calendar_span_days(df)
required_days = initial_history_days(item.interval)
with info_col:
    st.caption(
        f"本地 K 线：**{len(df)}** 根（连续段）· "
        f"{df.index.min().strftime('%Y-%m-%d')} ~ {df.index.max().strftime('%Y-%m-%d')} "
        f"（跨度 {span_days} 天，配置目标 {required_days} 天）"
    )
if raw_bar_count > len(df):
    st.info(
        f"检测到历史断档或脏数据，已丢弃较早的 **{raw_bar_count - len(df)}** 根 K 线，"
        f"仅使用最近连续段（自 {df.index.min().strftime('%Y-%m-%d')} 起）。"
    )
if not bars_cover_history(df, item.interval):
    st.warning(
        f"连续 K 线仅覆盖 {span_days} 天（未满 {required_days} 天），"
        "可能为新上市或历史数据源不完整；回测与 WFO 将基于现有连续段进行。"
    )

default_bars = min(len(df), 500)
max_bars = st.slider(
    "K 线展示根数",
    min_value=60,
    max_value=max(len(df), 60),
    value=default_bars,
    step=10,
    help="默认展示全部本地 K 线（最多 500 根）；此前默认 250 根约等于一年",
)

adaptive = repo.get_adaptive_params(item.symbol, item.market, item.interval, strategy_name)
if adaptive is None:
    st.warning(
        f"{item.symbol} / {strategy_name} 尚未完成 Walk-forward 训练。"
        "请前往「自选管理」重新训练。"
    )
    st.stop()

params = json.loads(adaptive.params_json)
oos = BacktestReport.from_dict(json.loads(adaptive.oos_metrics_json))
oos.fold_count = adaptive.fold_count

strategy = build_strategy(strategy_name, item.interval, params)
signals = strategy.generate_signals(df)
full_report = BacktestEngine().run(df, strategy, item.interval)

oos_warn = oos_sample_warning(oos)
if oos_warn:
    st.warning(oos_warn)

c1, c2, c3, c4, c5, c6 = st.columns(6)
c1.metric("OOS 胜率", f"{oos.win_rate * 100:.1f}%")
c2.metric("OOS 收益", f"{oos.total_return * 100:+.1f}%")
c3.metric("OOS 回撤", f"{oos.max_drawdown * 100:.1f}%")
c4.metric("Sharpe", f"{oos.sharpe_ratio:.2f}")
c5.metric("WFO 折数", str(oos.fold_count))
c6.metric("优化时间", adaptive.optimized_at.strftime("%Y-%m-%d %H:%M"))

st.subheader("优化参数")
st.code(json.dumps(params, ensure_ascii=False, indent=2), language="json")

tab_oos, tab_full, tab_history = st.tabs(["WFO 样本外", "全样本回测", "历史记录"])

with tab_oos:
    st.markdown("**Walk-forward 样本外（OOS）汇总** — 训练阶段在测试窗上的聚合结果")
    oos_rows = [
        {
            "指标": "总收益",
            "OOS": f"{oos.total_return * 100:+.2f}%",
        },
        {"指标": "胜率", "OOS": f"{oos.win_rate * 100:.1f}%"},
        {"指标": "最大回撤", "OOS": f"{oos.max_drawdown * 100:.2f}%"},
        {"指标": "Sharpe", "OOS": f"{oos.sharpe_ratio:.3f}"},
        {"指标": "盈亏比", "OOS": f"{oos.profit_factor:.2f}"},
        {"指标": "交易次数", "OOS": str(oos.trade_count)},
        {"指标": "WFO 折数", "OOS": str(oos.fold_count)},
    ]
    st.dataframe(oos_rows, use_container_width=True, hide_index=True)

    if oos.fold_metrics:
        st.markdown("**各折 OOS 明细**")
        fold_rows = []
        for i, fold in enumerate(oos.fold_metrics, start=1):
            fold_rows.append(
                {
                    "折": i,
                    "收益": f"{fold.get('total_return', 0) * 100:+.2f}%",
                    "胜率": f"{fold.get('win_rate', 0) * 100:.1f}%",
                    "回撤": f"{fold.get('max_drawdown', 0) * 100:.2f}%",
                    "Sharpe": f"{fold.get('sharpe_ratio', 0):.3f}",
                    "交易": fold.get("trade_count", 0),
                }
            )
        st.dataframe(fold_rows, use_container_width=True, hide_index=True)

    if oos.equity_curve:
        eq_fig = equity_curve_chart(
            oos.equity_curve, title="OOS 权益曲线（各折拼接）"
        )
        if eq_fig:
            st.plotly_chart(eq_fig, use_container_width=True)

with tab_full:
    st.markdown("**全样本回测** — 使用 WFO 优化参数在历史 K 线上回测（含图表信号标注）")
    _ps = get_position_sizing_config()
    if _ps.get("mode") == "atr_risk":
        st.caption(
            f"仓位：ATR 定仓（风险 {_ps['risk_pct'] * 100:.1f}% / 笔，"
            f"{_ps['stop_atr_mult']:.0f}×ATR({_ps['atr_period']}) 止损）；"
            "信号卖出或触及止损时在下一根开盘价平仓。"
        )
    st.caption("全样本结果含未参与 OOS 验证的历史区间，收益通常高于 OOS 汇总，仅供参考。")
    full_rows = [
        {"指标": "总收益", "全样本": f"{full_report.total_return * 100:+.2f}%"},
        {"指标": "胜率", "全样本": f"{full_report.win_rate * 100:.1f}%"},
        {"指标": "最大回撤", "全样本": f"{full_report.max_drawdown * 100:.2f}%"},
        {"指标": "Sharpe", "全样本": f"{full_report.sharpe_ratio:.3f}"},
        {"指标": "盈亏比", "全样本": f"{full_report.profit_factor:.2f}"},
        {"指标": "交易次数", "全样本": str(full_report.trade_count)},
    ]
    st.dataframe(full_rows, use_container_width=True, hide_index=True)

    buy_count = int((signals == "buy").sum())
    sell_count = int((signals == "sell").sum())
    st.caption(f"信号统计：买入 {buy_count} 次 · 卖出 {sell_count} 次")

    fig = backtest_dashboard_figure(
        df,
        signals,
        full_report.equity_curve,
        title=f"{item.symbol} · {strategy_name} · {item.interval}",
        max_bars=max_bars,
    )
    st.plotly_chart(fig, use_container_width=True)

with tab_history:
    st.markdown("**历次训练保存的回测快照**")
    history = repo.list_backtest_results(
        item.symbol, item.market, item.interval, strategy_name=strategy_name, limit=20
    )
    if not history:
        st.info("暂无历史快照（新训练后会自动记录）")
    else:
        hist_rows = []
        for row in history:
            try:
                report = json.loads(row.report_json)
            except json.JSONDecodeError:
                continue
            hist_rows.append(
                {
                    "时间": row.computed_at,
                    "收益": f"{report.get('total_return', 0) * 100:+.2f}%",
                    "胜率": f"{report.get('win_rate', 0) * 100:.1f}%",
                    "回撤": f"{report.get('max_drawdown', 0) * 100:.2f}%",
                    "Sharpe": f"{report.get('sharpe_ratio', 0):.3f}",
                    "折数": report.get("fold_count", "-"),
                }
            )
        st.dataframe(hist_rows, use_container_width=True, hide_index=True)
