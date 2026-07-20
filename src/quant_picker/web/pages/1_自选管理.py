from __future__ import annotations

import inspect
import os
import sys

_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "..", ".."))
if _ROOT not in sys.path:
    sys.path.insert(0, os.path.join(_ROOT, "src"))
os.environ.setdefault("QUANT_PICKER_ROOT", _ROOT)

import streamlit as st

from quant_picker.backtest.oos_quality import oos_sample_warning
from quant_picker.data.symbol_validate import SymbolNotFoundError, validate_symbol
from quant_picker.engine.analyzer import Analyzer
from quant_picker.engine.updater import Updater
from quant_picker.market.detector import detect_market, normalize_symbol
from quant_picker.optimization.trainer import Trainer
from quant_picker.storage.db import get_session_factory, init_db
from quant_picker.storage.models import WatchlistItem
from quant_picker.storage.repository import Repository
from quant_picker.strategies.registry import build_strategy
from quant_picker.web.charts import price_chart_with_signals

st.set_page_config(page_title="自选管理", page_icon="⭐", layout="wide")

_INTERVAL_LABEL = {"1d": "日K", "1h": "时K", "1m": "分K"}
_ROW_COLS = [0.35, 1.0, 1.15, 0.55, 0.55, 0.65, 0.75, 0.45, 3.5]
_TEXT_COL_WEIGHTS = _ROW_COLS[2:8]
_DATA_ROW_COLS = [_ROW_COLS[0], _ROW_COLS[1], sum(_TEXT_COL_WEIGHTS), _ROW_COLS[8]]
_ROW_LABELS = ["", "代码", "股票名称", "市场", "周期", "WFO", "再训练周期", "提醒", "操作"]

if "expanded_id" not in st.session_state:
    st.session_state.expanded_id = None


@st.cache_resource
def _session_factory():
    init_db()
    return get_session_factory()


def _repo() -> Repository:
    return Repository(_session_factory()())


def _list_name(item: WatchlistItem) -> str:
    """List view only — read from DB, never call remote APIs."""
    return item.display_name or "—"


def _resolve_name(item: WatchlistItem) -> str:
    """Resolve name for detail/config; may call API once and persist."""
    if item.display_name:
        return item.display_name
    try:
        from quant_picker.market.detector import Market

        name = validate_symbol(item.symbol, Market(item.market))
        item.display_name = name
        _repo().update_watchlist(item)
        return name
    except SymbolNotFoundError:
        return "—"


def _toggle_expand(item_id: int) -> None:
    if st.session_state.expanded_id == item_id:
        st.session_state.expanded_id = None
        st.session_state.pop(f"loaded_{item_id}", None)
        st.session_state.pop(f"detail_result_{item_id}", None)
    else:
        prev = st.session_state.expanded_id
        if prev is not None:
            st.session_state.pop(f"loaded_{prev}", None)
            st.session_state.pop(f"detail_result_{prev}", None)
        st.session_state.expanded_id = item_id
        st.session_state[f"loaded_{item_id}"] = True


def _row_icon_button(label: str, key: str, *, help_text: str | None = None) -> bool:
    kwargs: dict = {"key": key, "use_container_width": True}
    if help_text:
        kwargs["help"] = help_text
    if "type" in inspect.signature(st.button).parameters:
        kwargs["type"] = "tertiary"
    return st.button(label, **kwargs)


def _row_text_button(label: str, key: str) -> bool:
    kwargs: dict = {"key": key, "use_container_width": True}
    if "type" in inspect.signature(st.button).parameters:
        kwargs["type"] = "tertiary"
    return st.button(label, **kwargs)


def _config_form(item_id: int) -> None:
    repo = _repo()
    item = repo.get_watchlist_by_id(item_id)
    if item is None:
        return

    st.caption(
        f"{item.symbol} · {_resolve_name(item)} · "
        f"{_INTERVAL_LABEL.get(item.interval, item.interval)}"
    )
    new_cycle = st.number_input(
        "再训练周期(bars)",
        min_value=1,
        value=int(item.retrain_cycle_bars or 20),
        key=f"dlg_cycle_{item.id}",
    )
    notify_on = st.checkbox("提醒", value=item.notify_enabled, key=f"dlg_notify_{item.id}")
    enabled_on = st.checkbox("定时更新", value=item.enabled, key=f"dlg_enabled_{item.id}")

    c1, c2, c3 = st.columns(3)
    with c1:
        if st.button("保存", type="primary", key=f"dlg_save_{item.id}"):
            item.retrain_cycle_bars = int(new_cycle)
            item.retrain_cycle_source = "manual"
            item.notify_enabled = notify_on
            item.enabled = enabled_on
            repo.update_watchlist(item)
            st.success("已保存")
            st.rerun()
    with c2:
        if st.button("取消", key=f"dlg_cancel_{item.id}"):
            st.rerun()
    with c3:
        if st.button("删除自选", type="secondary", key=f"dlg_del_{item.id}"):
            repo.delete_watchlist(item.id)
            if st.session_state.expanded_id == item.id:
                st.session_state.expanded_id = None
            st.session_state.pop(f"loaded_{item.id}", None)
            st.session_state.pop(f"detail_result_{item.id}", None)
            st.rerun()


if hasattr(st, "dialog"):

    @st.dialog("配置自选", on_dismiss="rerun")
    def _open_config_dialog(item_id: int) -> None:
        _config_form(item_id)

else:

    def _open_config_dialog(item_id: int) -> None:
        with st.container(border=True):
            st.subheader("配置自选")
            _config_form(item_id)


def _render_detail(item: WatchlistItem) -> None:
    cache_key = f"detail_result_{item.id}"
    if cache_key not in st.session_state:
        with st.spinner("加载分析..."):
            analyzer = Analyzer(_repo())
            st.session_state[cache_key] = analyzer.analyze_watchlist_item(
                item, sync_remote=False
            )

    result = st.session_state[cache_key]
    if result.df is None or result.df.empty:
        st.warning("本地无 K 线数据，请点击「同步行情并刷新」。")
        return

    for adv in result.advices:
        warn = oos_sample_warning(adv.oos_backtest)
        if warn:
            st.warning(f"{adv.strategy_name}: {warn}")

    rows = []
    for adv in result.advices:
        oos = adv.oos_backtest
        rows.append(
            {
                "策略": adv.strategy_name,
                "建议": adv.signal.action,
                "参数": adv.params_display,
                "OOS胜率": f"{oos.win_rate*100:.0f}%" if oos else "-",
                "OOS收益": f"{oos.total_return*100:+.1f}%" if oos else "-",
                "OOS回撤": f"{oos.max_drawdown*100:.1f}%" if oos else "-",
                "folds": oos.fold_count if oos else 0,
                "可信度": adv.confidence,
                "金额": f"¥{adv.amount:,.0f}"
                + (" (不足一手)" if adv.amount > 0 and adv.shares == 0 else ""),
                "股数": adv.shares if adv.shares > 0 else ("-" if adv.amount > 0 else 0),
                "理由": adv.signal.reason,
            }
        )
    st.dataframe(rows, use_container_width=True, hide_index=True)

    strategy_names = [adv.strategy_name for adv in result.advices]
    chart_strategy = st.selectbox(
        "K 线信号策略",
        strategy_names,
        key=f"chart_strat_{item.id}",
    )
    adv_map = {a.strategy_name: a for a in result.advices}
    chart_adv = adv_map[chart_strategy]
    strat = build_strategy(chart_strategy, item.interval, chart_adv.params)
    sig = strat.generate_signals(result.df)
    fig = price_chart_with_signals(
        result.df,
        sig,
        title=f"{item.symbol} · {chart_strategy} · 最近 120 根",
        max_bars=120,
    )
    st.plotly_chart(fig, use_container_width=True)


def _data_row_columns():
    try:
        return st.columns(_DATA_ROW_COLS, gap=None, vertical_alignment="center")
    except TypeError:
        try:
            return st.columns(_DATA_ROW_COLS, gap=None)
        except TypeError:
            return st.columns(_DATA_ROW_COLS)


def _render_row_text_grid(item: WatchlistItem) -> None:
    """Render 6 text columns in one HTML grid — same technique as the header row."""
    texts = [
        _list_name(item),
        item.market.upper(),
        _INTERVAL_LABEL.get(item.interval, item.interval),
        item.wfo_status,
        f"{item.bars_since_optimization}/{item.retrain_cycle_bars or '?'}",
        "✓" if item.notify_enabled else "—",
    ]
    grid_cols = " ".join(f"{w}fr" for w in _TEXT_COL_WEIGHTS)
    cells: list[str] = []
    for text in texts:
        cells.append(
            f'<div style="display:flex;align-items:center;box-sizing:border-box;'
            f"padding:0 0.55rem;min-height:2.75rem;width:100%;"
            f'color:#3d4451;font-size:0.92rem;">'
            f"{text}</div>"
        )
    html = (
        f'<div class="wl-row-text-grid" style="display:grid;grid-template-columns:{grid_cols};'
        f'width:100%;min-height:2.75rem;align-items:center;">'
        f'{"".join(cells)}</div>'
    )
    if hasattr(st, "html"):
        st.html(html)
    else:
        st.markdown(html, unsafe_allow_html=True)


def _render_watchlist_header() -> None:
    """Single HTML grid row — inline styles only, no reliance on :has() CSS."""
    grid_cols = " ".join(f"{w}fr" for w in _ROW_COLS)
    cells: list[str] = []
    for i, label in enumerate(_ROW_LABELS):
        divider = "" if i == len(_ROW_LABELS) - 1 else "border-right:1px solid #d0d5de;"
        content = f"<strong>{label}</strong>" if label else ""
        cells.append(
            f'<div style="display:flex;align-items:center;box-sizing:border-box;'
            f"padding:0 0.55rem;min-height:2.75rem;{divider}\">{content}</div>"
        )
    st.markdown(
        '<div class="wl-header-wrap" style="border:1px solid rgba(49,51,63,0.2);'
        "border-radius:0.45rem;overflow:hidden;margin-bottom:0.55rem;background:#eef1f6;\">"
        f'<div style="display:grid;grid-template-columns:{grid_cols};'
        "background:#eef1f6;width:100%;min-height:2.75rem;"
        'color:#2f3540;font-size:0.88rem;">'
        f'{"".join(cells)}'
        "</div></div>",
        unsafe_allow_html=True,
    )


def _render_watchlist_rows(items: list[WatchlistItem]) -> None:
    _render_watchlist_header()
    for it in items:
        expanded = st.session_state.expanded_id == it.id
        row_icon = "▼" if expanded else "▶"

        with st.container(border=True):
            cols = _data_row_columns()
            with cols[0]:
                if _row_icon_button(row_icon, f"expand_{it.id}", help_text="展开/收起详情"):
                    _toggle_expand(it.id)
                    st.rerun()
            with cols[1]:
                if _row_text_button(it.symbol, f"sym_{it.id}"):
                    _toggle_expand(it.id)
                    st.rerun()
            with cols[2]:
                _render_row_text_grid(it)
            with cols[3]:
                b1, b2, b3 = st.columns(3)
                with b1:
                    if st.button("配置", key=f"cfg_{it.id}", use_container_width=True):
                        _open_config_dialog(it.id)
                with b2:
                    if st.button(
                        "同步行情并刷新",
                        key=f"sync_{it.id}",
                        use_container_width=True,
                    ):
                        repo = _repo()
                        fresh = repo.get_watchlist_by_id(it.id)
                        if fresh:
                            with st.spinner("同步中..."):
                                Updater(repo).update_watchlist_item(fresh)
                            st.session_state.pop(f"detail_result_{it.id}", None)
                            if st.session_state.expanded_id == it.id:
                                st.session_state[f"loaded_{it.id}"] = True
                        st.rerun()
                with b3:
                    if st.button(
                        "立即重新训练",
                        key=f"train_{it.id}",
                        use_container_width=True,
                    ):
                        repo = _repo()
                        fresh = repo.get_watchlist_by_id(it.id)
                        if fresh:
                            with st.spinner("Walk-forward 训练中..."):
                                trained = Trainer(repo).run_walk_forward(fresh, force=True)
                                Updater(repo).update_watchlist_item(trained)
                            st.session_state.pop(f"detail_result_{it.id}", None)
                            if st.session_state.expanded_id == it.id:
                                st.session_state[f"loaded_{it.id}"] = True
                        st.rerun()

            if expanded and st.session_state.get(f"loaded_{it.id}"):
                fresh = _repo().get_watchlist_by_id(it.id)
                if fresh:
                    st.divider()
                    st.markdown(f"**{fresh.symbol} · {_resolve_name(fresh)}** 详情")
                    _render_detail(fresh)


st.title("自选管理")

st.markdown(
    """
    <style>
    div[data-testid="stForm"] [data-testid="stHorizontalBlock"],
    form[data-testid="stForm"] [data-testid="stHorizontalBlock"] {
        align-items: flex-end !important;
    }
    div[data-testid="stForm"] [data-testid="stHorizontalBlock"] [data-testid="column"]:nth-child(3) [data-testid="stCheckbox"],
    form[data-testid="stForm"] [data-testid="stHorizontalBlock"] [data-testid="column"]:nth-child(3) [data-testid="stCheckbox"] {
        margin-bottom: 0.25rem;
    }
    /* 自选列表：行间边框容器间距 */
    div[data-testid="stVerticalBlock"] > div[data-testid="stVerticalBlockBorderWrapper"] {
        margin-bottom: 0.55rem;
        border-radius: 0.45rem;
    }
    /* 表头 HTML 块：去掉 Streamlit markdown 容器默认留白 */
    [data-testid="stElementContainer"]:has(.wl-header-wrap) {
        margin-bottom: 0 !important;
        padding: 0 !important;
    }
    [data-testid="stMarkdownContainer"]:has(.wl-header-wrap) {
        margin: 0 !important;
        padding: 0 !important;
    }
    [data-testid="stElementContainer"]:has(.wl-row-text-grid),
    [data-testid="stMarkdownContainer"]:has(.wl-row-text-grid),
    div[data-testid="stVerticalBlockBorderWrapper"] [data-testid="stHtml"] {
        margin: 0 !important;
        padding: 0 !important;
        width: 100%;
    }
    /* 数据行：相对 block 垂直居中 */
    div[data-testid="stVerticalBlockBorderWrapper"] > div {
        padding: 0.35rem 0 !important;
    }
    div[data-testid="stVerticalBlockBorderWrapper"] > div > [data-testid="stVerticalBlock"] {
        padding: 0 !important;
        gap: 0 !important;
    }
    div[data-testid="stVerticalBlockBorderWrapper"] > div > [data-testid="stVerticalBlock"]
    > [data-testid="stElementContainer"]:first-child {
        margin: 0 !important;
        padding: 0 !important;
    }
    div[data-testid="stVerticalBlockBorderWrapper"] > div > [data-testid="stVerticalBlock"]
    > [data-testid="stElementContainer"]:first-child [data-testid="stHorizontalBlock"] {
        align-items: stretch !important;
        gap: 0 !important;
        margin: 0 !important;
    }
    div[data-testid="stVerticalBlockBorderWrapper"] > div > [data-testid="stVerticalBlock"]
    > [data-testid="stElementContainer"]:first-child [data-testid="stHorizontalBlock"]
    > [data-testid="column"] {
        display: flex !important;
        align-items: center !important;
        align-self: stretch !important;
        padding: 0 0.55rem !important;
        box-sizing: border-box;
    }
    div[data-testid="stVerticalBlockBorderWrapper"] > div > [data-testid="stVerticalBlock"]
    > [data-testid="stElementContainer"]:first-child [data-testid="stHorizontalBlock"]
    > [data-testid="column"] > div {
        width: 100%;
        height: 100%;
        display: flex !important;
        align-items: center !important;
        justify-content: flex-start;
        margin: 0 !important;
        padding: 0 !important;
    }
    /* 行首箭头 / 代码：无边框文字按钮 */
    div[data-testid="stVerticalBlockBorderWrapper"] > div > [data-testid="stVerticalBlock"]
    > [data-testid="stElementContainer"]:first-child
    [data-testid="column"]:nth-child(1) .stButton > button,
    div[data-testid="stVerticalBlockBorderWrapper"] > div > [data-testid="stVerticalBlock"]
    > [data-testid="stElementContainer"]:first-child
    [data-testid="column"]:nth-child(2) .stButton > button {
        border: none !important;
        background: transparent !important;
        box-shadow: none !important;
        padding: 0 !important;
        min-height: 1.75rem !important;
        font-weight: 500;
    }
    div[data-testid="stVerticalBlockBorderWrapper"] > div > [data-testid="stVerticalBlock"]
    > [data-testid="stElementContainer"]:first-child
    [data-testid="column"]:nth-child(1) .stButton > button {
        font-size: 0.85rem;
        color: #5f6368 !important;
    }
    div[data-testid="stVerticalBlockBorderWrapper"] > div > [data-testid="stVerticalBlock"]
    > [data-testid="stElementContainer"]:first-child
    [data-testid="column"]:nth-child(2) .stButton > button {
        font-size: 0.95rem;
        color: #1a1a1a !important;
        justify-content: flex-start !important;
        text-align: left !important;
    }
    div[data-testid="stVerticalBlockBorderWrapper"] > div > [data-testid="stVerticalBlock"]
    > [data-testid="stElementContainer"]:first-child
    [data-testid="column"]:nth-child(1) .stButton > button:hover,
    div[data-testid="stVerticalBlockBorderWrapper"] > div > [data-testid="stVerticalBlock"]
    > [data-testid="stElementContainer"]:first-child
    [data-testid="column"]:nth-child(2) .stButton > button:hover {
        background: rgba(49, 51, 63, 0.06) !important;
        color: #1565c0 !important;
    }
    /* 操作列内按钮垂直居中 */
    div[data-testid="stVerticalBlockBorderWrapper"] > div > [data-testid="stVerticalBlock"]
    > [data-testid="stElementContainer"]:first-child
    [data-testid="column"]:nth-child(4) [data-testid="stHorizontalBlock"] {
        align-items: center !important;
    }
    </style>
    """,
    unsafe_allow_html=True,
)

repo = _repo()

with st.form("add_watch"):
    try:
        c1, c2, c3, c4 = st.columns([2, 3, 1, 1], vertical_alignment="bottom")
    except TypeError:
        c1, c2, c3, c4 = st.columns([2, 3, 1, 1])
    with c1:
        symbol_in = st.text_input("股票代码", value="600519")
    with c2:
        interval_in = st.radio(
            "K线周期",
            options=["1d", "1h", "1m"],
            format_func=lambda x: _INTERVAL_LABEL[x],
            horizontal=True,
            index=0,
            help="选择加入自选后拉取与训练的 K 线频率",
        )
    with c3:
        notify = st.checkbox("开启提醒")
    with c4:
        submitted = st.form_submit_button("加入自选", type="primary")

if submitted and symbol_in:
    try:
        from quant_picker.market.detector import Market

        m = detect_market(symbol_in)
        sym = normalize_symbol(symbol_in, m)
        name = validate_symbol(sym, m)
        existing = repo.get_watchlist(sym, m.value, interval_in)
        interval_label = _INTERVAL_LABEL[interval_in]
        if existing:
            st.warning(f"{sym}（{name}）已在自选中，周期 {interval_label}")
        else:
            with st.spinner(f"校验并训练 {sym}（{name}）· {interval_label}..."):
                item = repo.add_watchlist(
                    sym, m.value, interval_in, notify, display_name=name
                )
                item = Trainer(repo).run_walk_forward(item, force=True)
                if item.wfo_status == "done":
                    Updater(repo).update_watchlist_item(item)
            st.success(f"已加入 {sym}（{name}）· {interval_label}，训练状态: {item.wfo_status}")
    except SymbolNotFoundError as e:
        st.error(str(e))
    except Exception as e:
        try:
            repo.session.rollback()
        except Exception:
            pass
        st.error(f"加入失败: {e}")

items = repo.list_watchlist()
if not items:
    st.info("暂无自选，请在上方添加。")
else:
    st.caption(f"共 {len(items)} 只自选 · 列表仅读数据库 · 点击行首 ▶ 或代码展开详情")
    _render_watchlist_rows(items)
