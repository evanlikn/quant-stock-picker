from __future__ import annotations

import os
import sys

# Ensure src on path when running via streamlit
_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
if _ROOT not in sys.path:
    sys.path.insert(0, os.path.join(_ROOT, "src"))
os.environ.setdefault("QUANT_PICKER_ROOT", _ROOT)

import streamlit as st

from quant_picker.config import project_root
from quant_picker.engine.analyzer import Analyzer
from quant_picker.storage.db import get_session_factory, init_db
from quant_picker.storage.repository import Repository

st.set_page_config(page_title="量化选股", page_icon="📈", layout="wide")

init_db()
session = get_session_factory()()
repo = Repository(session)
analyzer = Analyzer(repo)

st.title("量化选股分析")
st.caption("即时分析 — 使用 YAML 默认参数，未做逐股 Walk-forward 优化")

_INTERVAL_LABEL = {"1d": "日K", "1h": "时K", "1m": "分K"}

c1, c2, c3, c4 = st.columns([2, 3, 1, 1])
with c1:
    symbol = st.text_input("股票代码", value="600519", placeholder="如 600519")
with c2:
    interval = st.radio(
        "K线周期",
        options=["1d", "1h", "1m"],
        format_func=lambda x: _INTERVAL_LABEL[x],
        horizontal=True,
        index=0,
        help="选择拉取的 K 线频率",
    )
with c3:
    market = st.selectbox("市场", ["auto", "cn", "us", "hk"])
with c4:
    st.write("")
    analyze_clicked = st.button("分析", type="primary")

if analyze_clicked:
    with st.spinner("拉取数据并分析..."):
        try:
            m = None if market == "auto" else market
            result = analyzer.analyze_instant(symbol, interval, m)
            st.info(result.message)
            if result.bar_time:
                st.write(f"最新 K 线: {result.bar_time}")

            rows = []
            for adv in result.advices:
                oos = adv.oos_backtest
                rows.append(
                    {
                        "策略": adv.strategy_name,
                        "建议": {"buy": "买入", "hold": "观望", "sell": "卖出"}.get(
                            adv.signal.action, adv.signal.action
                        ),
                        "强度": f"{adv.signal.strength:.2f}",
                        "参数": adv.params_display,
                        "建议金额": f"¥{adv.amount:,.0f}"
                        + (" (不足一手)" if adv.amount > 0 and adv.shares == 0 else ""),
                        "股数": adv.shares if adv.shares > 0 else ("-" if adv.amount > 0 else 0),
                        "理由": adv.signal.reason,
                    }
                )
            st.dataframe(rows, use_container_width=True)

            if result.df is not None and not result.df.empty:
                st.subheader("收盘价走势")
                st.line_chart(result.df["close"])
        except Exception as e:
            st.error(f"分析失败: {e}")

st.divider()
st.markdown(
    "**免责声明**: 本程序仅供学习研究，不构成任何投资建议。"
)
st.markdown("前往侧边栏 **自选管理** 页面进行 Walk-forward 逐股优化。")
