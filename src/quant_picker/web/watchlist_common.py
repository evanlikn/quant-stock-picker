from __future__ import annotations

import os
import sys

_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
if _ROOT not in sys.path:
    sys.path.insert(0, os.path.join(_ROOT, "src"))
os.environ.setdefault("QUANT_PICKER_ROOT", _ROOT)

import pandas as pd
import streamlit as st
import streamlit.components.v1 as components

from quant_picker.auth.guard import current_user_id
from quant_picker.backtest.oos_quality import oos_sample_warning
from quant_picker.data.bars_util import initial_history_days
from quant_picker.data.symbol_validate import SymbolNotFoundError, validate_symbol
from quant_picker.engine.analyzer import Analyzer
from quant_picker.engine.position_tracker import (
    atr_at_bar,
    effective_stop_price,
    resolve_position,
    watchlist_manual_snapshot,
)
from quant_picker.portfolio.position_sizer import atr_stop_price, get_position_sizing_config
from quant_picker.storage.models import WatchlistItem
from quant_picker.storage.repository import Repository
from quant_picker.strategies.indicators import atr as calc_atr
from quant_picker.strategies.registry import build_strategy
from quant_picker.web.charts import PAN_CHART_CONFIG, price_chart_with_signals
from quant_picker.web.db_session import web_session

INTERVAL_LABEL = {"1d": "日K", "1h": "时K", "1m": "分K"}
MARKET_FILTER_LABELS = {"all": "全部", "cn": "A股", "hk": "港股", "us": "美股"}
WATCHLIST_PAGE = "pages/1_自选管理.py"
_DETAIL_ID_SESSION_KEY = "watchlist_detail_id"
_SCROLL_VIEW_KEY = "watchlist_scroll_view"


def mark_scroll_view(view: str) -> None:
    """Record the view currently on screen without moving the scroll position."""
    st.session_state[_SCROLL_VIEW_KEY] = view


def scroll_to_top(view: str) -> None:
    """Jump back to the top when entering a different view.

    列表页和详情页共用同一个 Streamlit 页面，切换时只改 query param，浏览器不会重置
    滚动位置，从长列表点进详情会停在半空中。Streamlit 没有原生的置顶 API，只能借
    components iframe 里的脚本去操作父文档。仅在视图真正切换时注入，避免详情页内部
    的按钮 rerun 也把页面弹回顶部。
    """
    if st.session_state.get(_SCROLL_VIEW_KEY) == view:
        return
    st.session_state[_SCROLL_VIEW_KEY] = view
    components.html(
        f"""<script>
(function () {{
    const doc = window.parent && window.parent.document;
    if (!doc) return;
    const scrollTop = () => {{
        const targets = [
            doc.scrollingElement,
            doc.querySelector('section[data-testid="stMain"]'),
            doc.querySelector('[data-testid="stAppViewContainer"]'),
            doc.querySelector('[data-testid="stMainBlockContainer"]'),
        ];
        for (const t of targets) {{
            if (!t) continue;
            if (typeof t.scrollTo === 'function') t.scrollTo(0, 0);
            if ('scrollTop' in t) t.scrollTop = 0;
        }}
        try {{ window.parent.scrollTo(0, 0); }} catch (e) {{}}
    }};
    scrollTop();
    requestAnimationFrame(scrollTop);
    // 详情页的图表/表格是异步撑开的，高度变化后需要再压一次
    [60, 200, 500].forEach((d) => setTimeout(scrollTop, d));
}})();
</script><!-- {view} -->""",
        height=0,
    )
    st.markdown(
        """
        <style>
        [data-testid="stElementContainer"]:has(> [data-testid="stIFrame"]),
        [data-testid="stElementContainer"]:has(> iframe[title="st.iframe"]) {
            display: none !important;
        }
        </style>
        """,
        unsafe_allow_html=True,
    )


def _restore_detail_query_param() -> None:
    """Streamlit widget rerun may drop query params; restore from session."""
    saved = st.session_state.get(_DETAIL_ID_SESSION_KEY)
    if saved is not None and not st.query_params.get("watchlist_id"):
        st.query_params["watchlist_id"] = str(saved)


def detail_page_url(item_id: int) -> str:
    return f"/自选管理?watchlist_id={item_id}"


def back_to_watchlist_list() -> None:
    st.session_state.pop(_DETAIL_ID_SESSION_KEY, None)
    st.query_params.clear()
    st.rerun()


def go_detail(item_id: int) -> None:
    st.session_state[_DETAIL_ID_SESSION_KEY] = item_id
    st.query_params["watchlist_id"] = str(item_id)
    st.rerun()


def rerun_watchlist_detail(item_id: int) -> None:
    st.session_state[_DETAIL_ID_SESSION_KEY] = item_id
    st.query_params["watchlist_id"] = str(item_id)
    st.rerun()


def parse_watchlist_id() -> int | None:
    raw = st.query_params.get("watchlist_id")
    if raw is not None:
        value = raw[0] if isinstance(raw, list) else raw
        try:
            item_id = int(value)
            st.session_state[_DETAIL_ID_SESSION_KEY] = item_id
            return item_id
        except (TypeError, ValueError):
            pass
    saved = st.session_state.get(_DETAIL_ID_SESSION_KEY)
    if saved is not None:
        try:
            return int(saved)
        except (TypeError, ValueError):
            st.session_state.pop(_DETAIL_ID_SESSION_KEY, None)
    return None


def repo() -> Repository:
    """Repository scoped to the logged-in user; pages must call require_login first.

    Shares one session across the whole run: a page calls this a dozen times,
    and a fresh session per call would check out a connection per call.
    """
    user_id = current_user_id()
    if user_id is None:
        st.error("会话已失效，请重新登录")
        st.stop()
    return Repository(web_session(), user_id)


def list_name(item: WatchlistItem) -> str:
    return item.display_name or "—"


def resolve_name(item: WatchlistItem) -> str:
    if item.display_name:
        return item.display_name
    try:
        from quant_picker.market.detector import Market

        name = validate_symbol(item.symbol, Market(item.market))
        item.display_name = name
        repo().update_watchlist(item)
        return name
    except SymbolNotFoundError:
        return "—"


def config_form(item_id: int, *, after_delete=None) -> None:
    r = repo()
    item = r.get_watchlist_by_id(item_id)
    if item is None:
        return

    st.caption(
        f"{item.symbol} · {resolve_name(item)} · "
        f"{INTERVAL_LABEL.get(item.interval, item.interval)}"
    )
    new_cycle = st.number_input(
        "再训练周期(bars)",
        min_value=1,
        value=int(item.retrain_cycle_bars or 20),
        key=f"dlg_cycle_{item.id}",
    )
    new_history_days = st.number_input(
        "历史窗口（天）",
        min_value=1,
        value=int(item.history_days or initial_history_days(item.interval)),
        step=1,
        key=f"dlg_history_{item.id}",
        help=(
            "拉取最近 N 个自然日内的 K 线，与加入自选时的「历史窗口」一致。"
            "改大后保存会立即重新拉取，因为增量同步只会往后追加。"
        ),
    )
    notify_on = st.checkbox("提醒", value=item.notify_enabled, key=f"dlg_notify_{item.id}")
    enabled_on = st.checkbox("定时更新", value=item.enabled, key=f"dlg_enabled_{item.id}")

    c1, c2, c3 = st.columns(3)
    with c1:
        if st.button("保存", type="primary", key=f"dlg_save_{item.id}"):
            previous_days = int(item.history_days or initial_history_days(item.interval))
            item.retrain_cycle_bars = int(new_cycle)
            item.retrain_cycle_source = "manual"
            item.history_days = int(new_history_days)
            item.notify_enabled = notify_on
            item.enabled = enabled_on
            r.update_watchlist(item)
            if int(new_history_days) > previous_days:
                from quant_picker.data.bar_sync import BarSyncService

                with st.spinner(f"重新拉取最近 {int(new_history_days)} 天 K 线..."):
                    _, inserted = BarSyncService(r).sync(
                        item.symbol,
                        item.market,
                        item.interval,
                        force_full=True,
                        item=item,
                    )
                st.success(f"已保存，补拉 {inserted} 根 K 线")
            else:
                st.success("已保存")
            rerun_watchlist_detail(item.id)
    with c2:
        if st.button("取消", key=f"dlg_cancel_{item.id}"):
            rerun_watchlist_detail(item.id)
    with c3:
        if st.button("删除自选", type="secondary", key=f"dlg_del_{item.id}"):
            r.delete_watchlist(item.id)
            st.session_state.pop(f"detail_result_{item.id}", None)
            if after_delete:
                after_delete()
            else:
                rerun_watchlist_detail(item.id)


if hasattr(st, "dialog"):

    def _on_detail_dialog_dismiss() -> None:
        item_id = st.session_state.get(_DETAIL_ID_SESSION_KEY)
        if item_id is not None:
            rerun_watchlist_detail(int(item_id))

    @st.dialog("配置自选", on_dismiss=_on_detail_dialog_dismiss)
    def open_config_dialog(item_id: int, *, after_delete=None) -> None:
        st.session_state[_DETAIL_ID_SESSION_KEY] = item_id
        config_form(item_id, after_delete=after_delete)

else:

    def open_config_dialog(item_id: int, *, after_delete=None) -> None:
        with st.container(border=True):
            st.subheader("配置自选")
            config_form(item_id, after_delete=after_delete)


def _position_defaults(item: WatchlistItem, r: Repository) -> tuple[float, int]:
    manual = watchlist_manual_snapshot(item)
    if manual is not None:
        return manual.entry_price, manual.entry_shares

    for pos in r.list_strategy_positions(item.id):
        if pos.entry_shares > 0 and pos.entry_price > 0:
            return float(pos.entry_price), int(pos.entry_shares)
    return 0.0, 0


def position_form(item_id: int) -> None:
    r = repo()
    item = r.get_watchlist_by_id(item_id)
    if item is None:
        return

    cfg = get_position_sizing_config()
    lot_step = 100 if item.market.lower() in ("cn", "hk") else 1
    manual = watchlist_manual_snapshot(item)

    st.caption(
        f"{item.symbol} · {resolve_name(item)} · "
        f"{INTERVAL_LABEL.get(item.interval, item.interval)}"
    )
    st.caption(
        "保存后，该股票所有策略共用此持仓；买入价和股数都设为 0 表示已清仓，"
        "将恢复为各策略独立记录建议持仓。"
        f" 移动止损 = max(历史止损, 收盘 − {cfg['stop_atr_mult']:.0f}×最新ATR)，只升不降。"
    )

    default_price, default_shares = _position_defaults(item, r)
    if manual:
        stop = effective_stop_price(manual)
        stop_note = f"，移动止损 {stop:.2f}" if stop else ""
        st.caption(
            f"当前手动持仓：{manual.entry_price:.2f} × {manual.entry_shares} 股{stop_note}"
        )

    price_in = st.number_input(
        "买入价",
        min_value=0.0,
        value=float(default_price),
        format="%.4f",
        key=f"pos_price_{item.id}",
    )
    shares_in = st.number_input(
        "买入股数",
        min_value=0,
        value=int(default_shares),
        step=lot_step,
        key=f"pos_shares_{item.id}",
    )

    c1, c2, c3 = st.columns(3)
    with c1:
        if st.button("保存", type="primary", key=f"pos_save_{item.id}"):
            if price_in <= 0 and shares_in <= 0:
                r.clear_watchlist_manual_position(item.id)
                st.session_state.pop(f"detail_result_{item.id}", None)
                st.success("已标记清仓，各策略恢复独立记录")
                rerun_watchlist_detail(item.id)
            elif price_in <= 0 or shares_in <= 0:
                st.error("买入价和股数须同时大于 0，或都设为 0 表示清仓")
            else:
                df = r.load_bars(item.symbol, item.market, item.interval)
                bar_time = (
                    pd.Timestamp(df.index.max()).to_pydatetime()
                    if not df.empty
                    else item.position_entry_bar_time
                )
                entry_atr = item.position_entry_atr
                if entry_atr is None and not df.empty and bar_time:
                    entry_atr = atr_at_bar(df, bar_time, cfg["atr_period"])
                initial_stop = (
                    atr_stop_price(price_in, entry_atr)
                    if entry_atr and entry_atr > 0
                    else None
                )
                r.set_watchlist_manual_position(
                    item.id,
                    entry_price=price_in,
                    entry_shares=int(shares_in),
                    entry_atr=entry_atr,
                    entry_bar_time=bar_time,
                    trailing_stop=initial_stop,
                )
                st.session_state.pop(f"detail_result_{item.id}", None)
                st.success("已保存，所有策略已同步为该持仓")
                rerun_watchlist_detail(item.id)
    with c2:
        if st.button("取消", key=f"pos_cancel_{item.id}"):
            rerun_watchlist_detail(item.id)
    with c3:
        if st.button("恢复默认值", key=f"pos_auto_{item.id}"):
            r.clear_watchlist_manual_position(item.id)
            st.session_state.pop(f"detail_result_{item.id}", None)
            st.success("已恢复各策略独立记录")
            rerun_watchlist_detail(item.id)


if hasattr(st, "dialog"):

    @st.dialog("编辑持仓", on_dismiss=_on_detail_dialog_dismiss)
    def open_position_dialog(item_id: int) -> None:
        st.session_state[_DETAIL_ID_SESSION_KEY] = item_id
        position_form(item_id)

else:

    def open_position_dialog(item_id: int) -> None:
        with st.container(border=True):
            st.subheader("编辑持仓")
            position_form(item_id)


def render_detail(item: WatchlistItem) -> None:
    cache_key = f"detail_result_{item.id}"
    if cache_key not in st.session_state:
        with st.spinner("加载分析..."):
            analyzer = Analyzer(repo())
            st.session_state[cache_key] = analyzer.analyze_watchlist_item(
                item, sync_remote=False
            )

    result = st.session_state[cache_key]
    if result.df is None or result.df.empty:
        st.warning("本地无 K 线数据，请点击「同步行情」。")
        return

    for adv in result.advices:
        warn = oos_sample_warning(adv.oos_backtest)
        if warn:
            st.warning(f"{adv.strategy_name}: {warn}")

    manual = watchlist_manual_snapshot(item)
    if manual:
        stop = effective_stop_price(manual)
        stop_note = f"，移动止损 {stop:.2f}" if stop else ""
        st.info(
            f"手动持仓（全策略共用）：{manual.entry_price:.2f} × {manual.entry_shares} 股"
            f"{stop_note} · 可在「编辑持仓」修改"
        )

    rows = []
    r = repo()
    atr_txt = "—"
    atr_period = get_position_sizing_config()["atr_period"]
    if len(result.df) >= atr_period + 1:
        atr_series = calc_atr(
            result.df["high"], result.df["low"], result.df["close"], atr_period
        )
        val = atr_series.iloc[-1]
        if val is not None and not pd.isna(val):
            atr_txt = f"{float(val):.4f}"

    for adv in result.advices:
        oos = adv.oos_backtest
        pos = resolve_position(r, item.id, adv.strategy_name)
        stop_txt = "—"
        stop_val = effective_stop_price(pos)
        if stop_val is not None:
            stop_txt = f"{stop_val:.2f}"
        hold_txt = "—"
        if pos and pos.entry_shares > 0:
            hold_txt = f"{pos.entry_price:.2f} × {pos.entry_shares}"
            if pos.manual_override:
                hold_txt += " 手动"
            elif not manual:
                hold_txt += " 自动"
        rows.append(
            {
                "策略": adv.strategy_name,
                "建议": adv.signal.action,
                "参数": adv.params_display,
                "OOS胜率": f"{oos.win_rate*100:.0f}%" if oos else "-",
                "OOS收益": f"{oos.total_return*100:+.1f}%" if oos else "-",
                "OOS回撤": f"{oos.max_drawdown*100:.1f}%" if oos else "-",
                "可信度": adv.confidence,
                "ATR": atr_txt,
                "持仓": hold_txt,
                "止损价": stop_txt,
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
        interval=item.interval,
        title=(
            f"{item.symbol} · {chart_strategy} · "
            f"{INTERVAL_LABEL.get(item.interval, item.interval)}"
        ),
        max_bars=500,
        window_bars=120,
    )
    st.plotly_chart(fig, use_container_width=True, config=PAN_CHART_CONFIG)


def render_watchlist_detail_page(item_id: int) -> None:
    from quant_picker.engine.updater import Updater
    from quant_picker.optimization.trainer import Trainer

    st.session_state[_DETAIL_ID_SESSION_KEY] = item_id
    st.query_params["watchlist_id"] = str(item_id)
    scroll_to_top(f"detail:{item_id}")

    item = repo().get_watchlist_by_id(item_id)
    if item is None:
        st.error("自选记录不存在或已被删除。")
        if st.button("返回自选列表"):
            back_to_watchlist_list()
        return

    name = resolve_name(item)
    interval_label = INTERVAL_LABEL.get(item.interval, item.interval)

    top_left, top_right = st.columns([4, 1])
    with top_left:
        if st.button("← 返回自选列表"):
            back_to_watchlist_list()
    with top_right:
        st.link_button(
            "新窗口打开",
            url=detail_page_url(item.id),
            help="在新标签页打开当前详情",
        )

    st.title(f"{item.symbol} · {name}")
    st.caption(
        f"{item.market.upper()} · {interval_label} · WFO {item.wfo_status} · "
        f"再训练 {item.bars_since_optimization}/{item.retrain_cycle_bars or '?'}"
    )

    b1, b2, b3, b4 = st.columns(4)
    with b1:
        if st.button("配置", use_container_width=True, key="detail_cfg"):
            open_config_dialog(item.id, after_delete=back_to_watchlist_list)
    with b2:
        if st.button("编辑持仓", use_container_width=True, key="detail_pos"):
            open_position_dialog(item.id)
    with b3:
        if st.button("同步行情", use_container_width=True, key="detail_sync"):
            fresh = repo().get_watchlist_by_id(item.id)
            if fresh:
                with st.spinner("同步中..."):
                    Updater(repo()).update_watchlist_item(fresh)
                st.session_state.pop(f"detail_result_{item.id}", None)
            rerun_watchlist_detail(item.id)
    with b4:
        if st.button("重新训练", use_container_width=True, key="detail_train"):
            fresh = repo().get_watchlist_by_id(item.id)
            if fresh:
                with st.spinner("Walk-forward 训练中..."):
                    trained = Trainer(repo()).run_walk_forward(fresh, force=True)
                    Updater(repo()).update_watchlist_item(trained)
                st.session_state.pop(f"detail_result_{item.id}", None)
            rerun_watchlist_detail(item.id)

    st.divider()
    fresh = repo().get_watchlist_by_id(item.id)
    if fresh:
        render_detail(fresh)
