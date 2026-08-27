from __future__ import annotations

import json
import os
import sys

_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "..", ".."))
if _ROOT not in sys.path:
    sys.path.insert(0, os.path.join(_ROOT, "src"))
os.environ.setdefault("QUANT_PICKER_ROOT", _ROOT)

import pandas as pd
import streamlit as st

from quant_picker.auth.guard import render_sidebar_account, require_login
from quant_picker.config import load_screener_config
from quant_picker.screener.runner import ScreenerRunner
from quant_picker.web.db_session import web_session
from quant_picker.storage.repository import Repository

st.set_page_config(page_title="多因子选股", page_icon="🧮", layout="wide")

_MARKET_LABELS = {"cn": "A股", "hk": "港股", "us": "美股"}

user = require_login()
render_sidebar_account(user)


def _repo() -> Repository:
    return Repository(web_session(), user.id)


def _factor_labels() -> dict[str, str]:
    cfg = load_screener_config()
    return {
        str(f["name"]): str(f.get("label") or f["name"])
        for f in (cfg.get("factors") or [])
    }


def _results_to_dataframe(rows) -> pd.DataFrame:
    labels = _factor_labels()
    table_rows: list[dict] = []
    for row in rows:
        try:
            factor_scores = json.loads(row.factor_scores_json or "{}")
        except json.JSONDecodeError:
            factor_scores = {}
        item = {
            "排名": row.rank,
            "代码": row.symbol,
            "名称": row.display_name or "—",
            "市场": row.market.upper(),
            "综合得分": round(float(row.composite_score), 4),
        }
        for key, val in factor_scores.items():
            label = labels.get(key, key)
            item[label] = round(float(val), 4) if val is not None else None
        table_rows.append(item)
    return pd.DataFrame(table_rows)


st.title("多因子选股")
st.caption(
    "基于 Multi-Factor Model 从 TickFlow 全市场股票池中筛选 Top 100。"
    " 价量因子来自日K；基本面因子需 TickFlow 财务权限。"
)

cfg = load_screener_config()
top_n = int(cfg.get("top_n") or 100)
repo = _repo()

try:
    c1, c2 = st.columns([1.5, 1.2], vertical_alignment="bottom")
except TypeError:
    c1, c2 = st.columns([1.5, 1.2])
with c1:
    market = st.selectbox(
        "市场",
        options=["cn", "hk", "us"],
        format_func=lambda x: _MARKET_LABELS.get(x, x),
        index=["cn", "hk", "us"].index(str(cfg.get("default_market") or "cn")),
    )
with c2:
    run_clicked = st.button("开始筛选", type="primary", use_container_width=True)

st.info(
    f"预计扫描全市场数千只股票并拉取日K，A股约需 10–40 分钟（取决于 API 速率）。"
    f" 结果将保存，下次打开可直接查看最近一次 {top_n} 强。"
)

if run_clicked:
    progress = st.progress(0.0, text="准备中…")
    status = st.empty()

    def _on_progress(ratio: float, message: str) -> None:
        progress.progress(min(max(ratio, 0.0), 1.0), text=message)
        status.caption(message)

    try:
        with st.spinner("多因子筛选运行中，请勿关闭页面…"):
            result = ScreenerRunner(repo).run(market, progress=_on_progress)
        progress.progress(1.0, text="筛选完成")
        st.success(
            f"完成：从 {result.universe_size} 只股票中筛出 Top {len(result.results)} "
            f"（有效样本 {result.screened_count}）"
        )
        for warning in result.warnings:
            st.warning(warning)
        st.session_state["screener_view_market"] = market
        st.rerun()
    except Exception as exc:
        progress.empty()
        st.error(f"筛选失败: {exc}")

view_market = st.session_state.get("screener_view_market", market)
latest = repo.get_latest_screener_run(view_market)
if latest is None:
    st.info("暂无筛选结果，请选择市场后点击「开始筛选」。")
else:
    finished = latest.finished_at.strftime("%Y-%m-%d %H:%M") if latest.finished_at else "—"
    st.subheader(f"{_MARKET_LABELS.get(latest.market, latest.market)} Top {latest.top_n}")
    st.caption(
        f"股票池 {latest.universe_id} · 候选 {latest.universe_size} 只 · "
        f"有效样本 {latest.screened_count} 只 · 完成于 {finished}"
    )
    try:
        warnings = json.loads(latest.warnings_json or "[]")
    except json.JSONDecodeError:
        warnings = []
    for warning in warnings:
        st.warning(warning)

    rows = repo.list_screener_results(latest.id)
    if not rows:
        st.info("该次运行没有结果。")
    else:
        df = _results_to_dataframe(rows)
        st.dataframe(df, use_container_width=True, hide_index=True)

        st.markdown("##### 批量加入自选（日K）")
        selected_symbols = st.multiselect(
            "选择要加入自选的股票",
            options=[f"{r.symbol} ({r.display_name or '—'})" for r in rows],
            default=[],
        )
        if st.button("加入自选", disabled=not selected_symbols):
            symbol_map = {f"{r.symbol} ({r.display_name or '—'})": r for r in rows}
            added = 0
            for label in selected_symbols:
                row = symbol_map[label]
                repo.add_watchlist(
                    row.symbol,
                    row.market,
                    "1d",
                    notify_enabled=False,
                    display_name=row.display_name,
                )
                added += 1
            st.success(f"已加入 {added} 只股票到自选（日K）")
