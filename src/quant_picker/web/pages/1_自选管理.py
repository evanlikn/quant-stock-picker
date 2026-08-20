from __future__ import annotations

import os
import sys

_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "..", ".."))
if _ROOT not in sys.path:
    sys.path.insert(0, os.path.join(_ROOT, "src"))
os.environ.setdefault("QUANT_PICKER_ROOT", _ROOT)

import streamlit as st

from quant_picker.data.bars_util import initial_history_days
from quant_picker.data.symbol_validate import SymbolNotFoundError, validate_symbol
from quant_picker.engine.updater import Updater
from quant_picker.market.detector import detect_market, normalize_symbol
from quant_picker.optimization.trainer import Trainer
from quant_picker.storage.models import WatchlistItem
from quant_picker.web.watchlist_common import (
    INTERVAL_LABEL,
    MARKET_FILTER_LABELS,
    WATCHLIST_PAGE,
    _restore_detail_query_param,
    list_name,
    mark_scroll_view,
    parse_watchlist_id,
    render_watchlist_detail_page,
    repo as get_repo,
)

st.set_page_config(page_title="自选管理", page_icon="⭐", layout="wide")

_restore_detail_query_param()
_detail_id = parse_watchlist_id()
if _detail_id is not None:
    render_watchlist_detail_page(_detail_id)
    st.stop()

# 记录当前停留在列表视图，这样再次点进同一只股票仍会触发置顶
mark_scroll_view("list")

_ROW_COLS = [1.0, 1.15, 0.55, 0.55, 0.65, 0.75, 0.45]
_TEXT_COL_WEIGHTS = _ROW_COLS[1:]
_DATA_ROW_COLS = [_ROW_COLS[0], sum(_TEXT_COL_WEIGHTS)]
_ROW_LABELS = ["代码", "股票名称", "市场", "周期", "WFO", "再训练周期", "提醒"]

_MARKET_KEYS = ["cn", "hk", "us"]
_MARKET_STATE_KEY = "wl_market_{}"

for _mk in _MARKET_KEYS:
    st.session_state.setdefault(_MARKET_STATE_KEY.format(_mk), True)


def _selected_markets() -> list[str]:
    return [m for m in _MARKET_KEYS if st.session_state.get(_MARKET_STATE_KEY.format(m), True)]


def _data_row_columns():
    try:
        return st.columns(_DATA_ROW_COLS, gap=None, vertical_alignment="center")
    except TypeError:
        try:
            return st.columns(_DATA_ROW_COLS, gap=None)
        except TypeError:
            return st.columns(_DATA_ROW_COLS)


def _render_row_text_grid(item: WatchlistItem) -> None:
    texts = [
        list_name(item),
        item.market.upper(),
        INTERVAL_LABEL.get(item.interval, item.interval),
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


def _filter_watchlist_by_market(
    items: list[WatchlistItem], selected: list[str]
) -> list[WatchlistItem]:
    markets = {m.lower() for m in selected if m in _MARKET_KEYS}
    if markets >= set(_MARKET_KEYS):
        return items
    return [i for i in items if i.market.lower() in markets]


def _market_filter_summary(selected: list[str]) -> str:
    if set(selected) >= set(_MARKET_KEYS):
        return ""
    if not selected:
        return "未选择市场"
    return "、".join(MARKET_FILTER_LABELS.get(m, m.upper()) for m in selected)


_HEADER_CELL_CSS = (
    "display:flex;align-items:center;width:100%;height:100%;min-height:2.75rem;"
    "box-sizing:border-box;padding:0 0.55rem;"
    "font-size:0.88rem;font-weight:700;color:#2f3540;"
)


def _header_cell(label: str, *, last: bool = False, anchor: bool = False) -> None:
    divider = "" if last else "border-right:1px solid #d0d5de;"
    marker = '<span id="wl-header-marker"></span>' if anchor else ""
    st.markdown(
        f'<div class="wl-h-cell" style="{_HEADER_CELL_CSS}{divider}">{marker}{label}</div>',
        unsafe_allow_html=True,
    )


def _market_header_cell() -> None:
    if len(_selected_markets()) < len(_MARKET_KEYS):
        st.markdown('<span id="wl-market-filtered"></span>', unsafe_allow_html=True)
    # 触发器箭头由 Streamlit popover 自带，标签里不要再写一个。
    with st.popover("市场", width="stretch", key="wl_market_filter"):
        st.caption("按市场筛选")
        for market in _MARKET_KEYS:
            st.checkbox(
                MARKET_FILTER_LABELS.get(market, market),
                key=_MARKET_STATE_KEY.format(market),
            )


def _render_watchlist_header() -> None:
    # 表头拍平成与数据行等比例的单层列，避免嵌套列带来的宽度/间距偏差。
    try:
        cols = st.columns(_ROW_COLS, gap=None, vertical_alignment="center")
    except TypeError:
        cols = st.columns(_ROW_COLS)
    last_idx = len(_ROW_LABELS) - 1
    for i, (col, label) in enumerate(zip(cols, _ROW_LABELS)):
        with col:
            if label == "市场":
                _market_header_cell()
            else:
                _header_cell(label, last=i == last_idx, anchor=i == 0)


def _render_watchlist_rows(items: list[WatchlistItem]) -> None:
    _render_watchlist_header()
    for it in items:
        with st.container(border=True):
            cols = _data_row_columns()
            link_kwargs = {
                "page": WATCHLIST_PAGE,
                "query_params": {"watchlist_id": str(it.id)},
                "help": "查看详情（Ctrl/Cmd+点击可在新标签页打开）",
            }
            with cols[0]:
                st.page_link(label=it.symbol, **link_kwargs)
            with cols[1]:
                _render_row_text_grid(it)


st.title("自选管理")

st.markdown(
    """
    <style>
    div[data-testid="stForm"] [data-testid="stHorizontalBlock"],
    form[data-testid="stForm"] [data-testid="stHorizontalBlock"] {
        align-items: flex-end !important;
    }
    div[data-testid="stVerticalBlock"]:has(#add-watch-form) form[data-testid="stForm"]
    [data-testid="stHorizontalBlock"] {
        align-items: flex-end !important;
    }
    div[data-testid="stVerticalBlock"]:has(#add-watch-form) form[data-testid="stForm"]
    [data-testid="stHorizontalBlock"] > [data-testid="stColumn"]:nth-child(4)
    [data-testid="stCheckbox"],
    div[data-testid="stVerticalBlock"]:has(#add-watch-form) form[data-testid="stForm"]
    [data-testid="stHorizontalBlock"] > [data-testid="column"]:nth-child(4)
    [data-testid="stCheckbox"] {
        margin-bottom: 0.35rem !important;
    }
    /* 行卡片：1.58 起 st.container(border=True) 就是带边框的 stVerticalBlock，
       去掉它默认的左右内边距，行内容才能和表头落在同一组列边界上 */
    [data-testid="stVerticalBlock"]:has(> * > [data-testid="stHorizontalBlock"] .wl-row-text-grid) {
        margin-bottom: 0.55rem !important;
        border-radius: 0.45rem !important;
        padding: 0.35rem 0 !important;
        gap: 0 !important;
    }
    /* 表头行：整行一体化灰底，列之间用细分隔线 */
    [data-testid="stHorizontalBlock"]:has(#wl-header-marker) {
        background: #eef1f6;
        border: 1px solid rgba(49, 51, 63, 0.2);
        border-radius: 0.45rem;
        overflow: hidden;
        margin-bottom: 0.55rem;
        gap: 0 !important;
        align-items: stretch !important;
    }
    [data-testid="stHorizontalBlock"]:has(#wl-header-marker) [data-testid="stColumn"],
    [data-testid="stHorizontalBlock"]:has(#wl-header-marker) [data-testid="column"],
    [data-testid="stHorizontalBlock"]:has(#wl-header-marker) [data-testid="stVerticalBlock"],
    [data-testid="stHorizontalBlock"]:has(#wl-header-marker) [data-testid="stElementContainer"],
    [data-testid="stHorizontalBlock"]:has(#wl-header-marker) [data-testid="stMarkdownContainer"],
    [data-testid="stHorizontalBlock"]:has(#wl-header-marker) [data-testid="stPopover"] {
        display: flex !important;
        flex-direction: column !important;
        align-items: stretch !important;
        justify-content: center !important;
        align-self: stretch !important;
        width: 100% !important;
        min-width: 0 !important;
        margin: 0 !important;
        padding: 0 !important;
        gap: 0 !important;
    }
    /* 「市场」列的筛选入口只是个表头单元格，抹掉按钮自带的外观 */
    [data-testid="stElementContainer"]:has(#wl-market-filtered) {
        display: none !important;
    }
    [data-testid="stHorizontalBlock"]:has(#wl-header-marker) [data-testid="stPopoverButton"] {
        width: 100% !important;
        height: 100% !important;
        min-height: 2.75rem !important;
        justify-content: flex-start !important;
        padding: 0 0.55rem !important;
        border: none !important;
        border-right: 1px solid #d0d5de !important;
        border-radius: 0 !important;
        background: transparent !important;
        box-shadow: none !important;
        color: #2f3540 !important;
        line-height: 1.2 !important;
    }
    [data-testid="stHorizontalBlock"]:has(#wl-header-marker) [data-testid="stPopoverButton"],
    [data-testid="stHorizontalBlock"]:has(#wl-header-marker) [data-testid="stPopoverButton"] * {
        font-size: 0.88rem !important;
        font-weight: 700 !important;
    }
    [data-testid="stHorizontalBlock"]:has(#wl-header-marker)
    [data-testid="stPopoverButton"]:hover {
        background: rgba(49, 51, 63, 0.06) !important;
        color: #1565c0 !important;
    }
    /* 有筛选生效时高亮该列 */
    [data-testid="stColumn"]:has(#wl-market-filtered) [data-testid="stPopoverButton"],
    [data-testid="column"]:has(#wl-market-filtered) [data-testid="stPopoverButton"] {
        color: #1565c0 !important;
    }
    [data-testid="stPopoverBody"] [data-testid="stCheckbox"] {
        margin-bottom: 0.1rem !important;
    }
    [data-testid="stElementContainer"]:has(.wl-row-text-grid),
    [data-testid="stMarkdownContainer"]:has(.wl-row-text-grid),
    [data-testid="stHtml"]:has(.wl-row-text-grid) {
        margin: 0 !important;
        padding: 0 !important;
        width: 100%;
    }
    /* 数据行：列比例与表头一致，代码列的内边距对齐表头单元格 */
    [data-testid="stHorizontalBlock"]:has(.wl-row-text-grid) {
        align-items: stretch !important;
        gap: 0 !important;
        margin: 0 !important;
    }
    /* 这些是纵向 flex 容器：align-items 管的是横向，必须 stretch 才不会把内容居中 */
    [data-testid="stHorizontalBlock"]:has(.wl-row-text-grid) > [data-testid="stColumn"],
    [data-testid="stHorizontalBlock"]:has(.wl-row-text-grid) > [data-testid="column"],
    [data-testid="stHorizontalBlock"]:has(.wl-row-text-grid) > [data-testid="stColumn"]
    > [data-testid="stVerticalBlock"],
    [data-testid="stHorizontalBlock"]:has(.wl-row-text-grid) > [data-testid="column"] > div {
        display: flex !important;
        flex-direction: column !important;
        align-items: stretch !important;
        justify-content: center !important;
        align-self: stretch !important;
        width: 100%;
        min-width: 0 !important;
        margin: 0 !important;
        padding: 0 !important;
        gap: 0 !important;
        box-sizing: border-box;
    }
    [data-testid="stHorizontalBlock"]:has(.wl-row-text-grid) [data-testid="stPageLink"],
    [data-testid="stHorizontalBlock"]:has(.wl-row-text-grid) [data-testid="stTooltipHoverTarget"] {
        width: 100% !important;
    }
    /* 代码列做成纯文本链接：去掉 page_link 自带的底色（含 isCurrentPage 常亮态），
       只用下划线表示可点击 */
    [data-testid="stHorizontalBlock"]:has(.wl-row-text-grid)
    [data-testid="stPageLink-NavLink"],
    [data-testid="stHorizontalBlock"]:has(.wl-row-text-grid)
    [data-testid="stPageLink-NavLink"]:hover,
    [data-testid="stHorizontalBlock"]:has(.wl-row-text-grid)
    [data-testid="stPageLink-NavLink"]:focus,
    [data-testid="stHorizontalBlock"]:has(.wl-row-text-grid)
    [data-testid="stPageLink-NavLink"]:focus-visible,
    [data-testid="stHorizontalBlock"]:has(.wl-row-text-grid)
    [data-testid="stPageLink-NavLink"]:active {
        width: 100% !important;
        justify-content: flex-start !important;
        margin: 0 !important;
        padding: 0 0.55rem !important;
        background: transparent !important;
        border-radius: 0 !important;
        box-shadow: none !important;
        outline: none !important;
        font-size: 0.95rem;
        font-weight: 500;
        color: #1a1a1a !important;
    }
    [data-testid="stHorizontalBlock"]:has(.wl-row-text-grid)
    [data-testid="stPageLink-NavLink"] span,
    [data-testid="stHorizontalBlock"]:has(.wl-row-text-grid)
    [data-testid="stPageLink-NavLink"] span * {
        text-decoration-line: underline !important;
        text-decoration-style: solid !important;
        text-decoration-thickness: 1px !important;
        text-decoration-color: rgba(26, 26, 26, 0.45) !important;
        text-underline-offset: 0.18em;
    }
    [data-testid="stHorizontalBlock"]:has(.wl-row-text-grid)
    [data-testid="stPageLink-NavLink"]:hover {
        color: #1565c0 !important;
    }
    [data-testid="stHorizontalBlock"]:has(.wl-row-text-grid)
    [data-testid="stPageLink-NavLink"]:hover span,
    [data-testid="stHorizontalBlock"]:has(.wl-row-text-grid)
    [data-testid="stPageLink-NavLink"]:hover span * {
        color: #1565c0 !important;
        text-decoration-color: #1565c0 !important;
    }
    </style>
    """,
    unsafe_allow_html=True,
)

watchlist_repo = get_repo()

st.markdown('<div id="add-watch-form"></div>', unsafe_allow_html=True)

_ADD_WATCH_COLS = [1.2, 1, 1, 1, 1]

with st.form("add_watch"):
    try:
        c1, c2, c3, c4, c5 = st.columns(_ADD_WATCH_COLS, vertical_alignment="bottom")
    except TypeError:
        c1, c2, c3, c4, c5 = st.columns(_ADD_WATCH_COLS)
    with c1:
        symbol_in = st.text_input("股票代码", value="600519", width=173)
    with c2:
        interval_in = st.radio(
            "K线周期",
            options=["1d", "1h", "1m"],
            format_func=lambda x: INTERVAL_LABEL[x],
            horizontal=True,
            index=0,
            width="content",
            help="选择加入自选后拉取与训练的 K 线频率",
        )
    with c3:
        history_days_in = st.number_input(
            "历史窗口（天）",
            min_value=1,
            value=initial_history_days(interval_in),
            step=1,
            width=140,
            key=f"add_history_days_{interval_in}",
            help=(
                "固定以自然日计：日K 拉取最近 N 根日K；"
                "时K/分K 拉取最近 N 个自然日内的全部时K/分K"
            ),
        )
    with c4:
        notify = st.checkbox("开启提醒")
    with c5:
        submitted = st.form_submit_button("加入自选", type="primary")

if submitted and symbol_in:
    try:
        from quant_picker.market.detector import Market

        m = detect_market(symbol_in)
        sym = normalize_symbol(symbol_in, m)
        name = validate_symbol(sym, m)
        existing = watchlist_repo.get_watchlist(sym, m.value, interval_in)
        interval_label = INTERVAL_LABEL[interval_in]
        if existing:
            st.warning(f"{sym}（{name}）已在自选中，周期 {interval_label}")
        else:
            with st.spinner(f"校验并训练 {sym}（{name}）· {interval_label}..."):
                item = watchlist_repo.add_watchlist(
                    sym,
                    m.value,
                    interval_in,
                    notify,
                    display_name=name,
                    history_days=int(history_days_in),
                )
                item = Trainer(watchlist_repo).run_walk_forward(item, force=True)
                if item.wfo_status == "done":
                    Updater(watchlist_repo).update_watchlist_item(item)
            st.success(f"已加入 {sym}（{name}）· {interval_label}，训练状态: {item.wfo_status}")
    except SymbolNotFoundError as e:
        st.error(str(e))
    except Exception as e:
        try:
            watchlist_repo.session.rollback()
        except Exception:
            pass
        st.error(f"加入失败: {e}")

items = watchlist_repo.list_watchlist()
if not items:
    st.info("暂无自选，请在上方添加。")
else:
    selected_markets = _selected_markets()
    filtered = _filter_watchlist_by_market(items, selected_markets)
    filter_note = _market_filter_summary(selected_markets)

    parts = [f"共 {len(filtered)} 只自选"]
    if filter_note:
        parts[0] += f"（全部 {len(items)} 只）"
        parts.append(filter_note)
    parts.append("当前筛选无结果" if not filtered else "列表仅读数据库 · 点击代码进入详情")
    st.caption(" · ".join(parts))

    _render_watchlist_rows(filtered)
