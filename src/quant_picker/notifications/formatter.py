from __future__ import annotations

import json
from datetime import datetime

from quant_picker.config import load_settings
from quant_picker.storage.models import Recommendation, WatchlistItem

_ACTION_LABEL = {"buy": "买入", "hold": "观望", "sell": "卖出"}


def _format_price(price: float | None, market: str = "cn") -> str:
    if price is None or price <= 0:
        return "—"
    m = (market or "cn").lower()
    if m == "us":
        return f"${price:,.2f}"
    if m == "hk":
        return f"HK${price:,.2f}"
    return f"¥{price:,.2f}"


def format_wechat_title(item: WatchlistItem) -> str:
    name = (item.display_name or "").strip()
    if name and name != "—":
        return f"{item.symbol} {name}"
    return item.symbol


def _format_oos_summary(rec: Recommendation) -> str:
    try:
        oos = json.loads(rec.oos_metrics_snapshot)
        if not oos:
            return "历史表现：—"
        return (
            f"历史表现：胜率{oos.get('win_rate', 0) * 100:.0f}% "
            f"收益{oos.get('total_return', 0) * 100:+.1f}% "
            f"回撤{oos.get('max_drawdown', 0) * 100:.1f}%"
        )
    except (json.JSONDecodeError, TypeError):
        return "历史表现：—"


def _format_advice_summary(rec: Recommendation, market: str) -> str:
    action = _ACTION_LABEL.get(rec.action, rec.action)
    if rec.action == "buy" and rec.amount > 0:
        text = f"建议：{action} {_format_price(rec.amount, market)}"
        if rec.shares:
            text += f"（{rec.shares}股）"
        return text
    if rec.action == "sell" and rec.amount > 0:
        text = f"建议：{action} {_format_price(rec.amount, market)}"
        if rec.shares:
            text += f"（{rec.shares}股）"
        return text
    return f"建议：{action}"


def format_wechat_message(
    item: WatchlistItem,
    recommendations: list[Recommendation],
    bar_time: datetime,
    reference_price: float | None,
) -> str:
    """Simplified WeChat body: date + close, then one block per strategy."""
    market = item.market.lower()
    lines = [f"{bar_time:%Y-%m-%d}  收盘 {_format_price(reference_price, market)}"]

    blocks: list[str] = []
    for rec in recommendations:
        block = "\n".join(
            [
                rec.strategy_name,
                _format_oos_summary(rec),
                _format_advice_summary(rec, market),
                f"理由：{rec.reason}",
            ]
        )
        blocks.append(block)

    if blocks:
        lines.append("")
        lines.append("\n\n".join(blocks))

    return "\n".join(lines)


def filter_buy_sell(recommendations: list[Recommendation]) -> list[Recommendation]:
    """Keep recommendations whose latest action is buy or sell."""
    return [r for r in recommendations if r.action in ("buy", "sell")]


def format_buy_sell_message(
    item: WatchlistItem,
    recommendations: list[Recommendation],
    bar_time: datetime,
    reference_price: float | None,
) -> str:
    """Alert body when at least one strategy signals buy or sell."""
    lines = [
        f"【量化选股】{item.symbol} 买入/卖出提醒 | {item.interval} | {datetime.now():%Y-%m-%d %H:%M}",
        "",
        f"信号 K 线: {bar_time:%Y-%m-%d %H:%M}",
        f"参考执行价（该 K 线收盘）: {_format_price(reference_price, item.market)}",
        "说明: 回测按下一根 K 线开盘价成交；收盘后收到提示时，请对比次日开盘价，避免偏离过大再跟进。",
        "",
    ]
    settings = load_settings()
    include_oos = settings.get("notifications", {}).get("include_backtest_summary", True)

    for rec in recommendations:
        action = _ACTION_LABEL.get(rec.action, rec.action)
        line = f"• {rec.strategy_name}: {action}"
        if reference_price and reference_price > 0:
            line += f" @ {_format_price(reference_price, item.market)}"
        if rec.action == "buy" and rec.amount > 0:
            line += f" | 建议 {_format_price(rec.amount, item.market)}"
            if rec.shares:
                line += f"（{rec.shares}股）"
        elif rec.action == "sell" and rec.amount > 0:
            line += f" | 建议卖出 {_format_price(rec.amount, item.market)}"
            if rec.shares:
                line += f"（{rec.shares}股）"
        lines.append(line)
        lines.append(f"  理由: {rec.reason}")
        if include_oos:
            try:
                oos = json.loads(rec.oos_metrics_snapshot)
                if oos:
                    lines.append(
                        f"  OOS: 胜率 {oos.get('win_rate', 0)*100:.0f}% | "
                        f"收益 {oos.get('total_return', 0)*100:.1f}% | "
                        f"回撤 {oos.get('max_drawdown', 0)*100:.1f}%"
                    )
            except json.JSONDecodeError:
                pass

    lines.append("")
    lines.append("⚠ 仅供参考，不构成投资建议")
    return "\n".join(lines)


def format_daily_summary_message(
    item: WatchlistItem,
    recommendations: list[Recommendation],
    bar_time: datetime,
    reference_price: float | None,
) -> str:
    lines = [
        f"【量化选股】{item.symbol} 每日建议 | {item.interval} | {datetime.now():%Y-%m-%d %H:%M}",
        "",
        f"信号 K 线: {bar_time:%Y-%m-%d %H:%M}",
        f"参考执行价（该 K 线收盘）: {_format_price(reference_price, item.market)}",
        "说明: 回测按下一根 K 线开盘价成交；收盘后收到提示时，请对比次日开盘价，避免偏离过大再跟进。",
        "",
    ]
    settings = load_settings()
    include_oos = settings.get("notifications", {}).get("include_backtest_summary", True)

    for rec in recommendations:
        action = _ACTION_LABEL.get(rec.action, rec.action)
        line = f"• {rec.strategy_name}: {action}"
        if reference_price and reference_price > 0:
            line += f" @ {_format_price(reference_price, item.market)}"
        if rec.action == "buy" and rec.amount > 0:
            line += f" | 建议 {_format_price(rec.amount, item.market)}"
            if rec.shares:
                line += f"（{rec.shares}股）"
        elif rec.action == "sell" and rec.amount > 0:
            line += f" | 建议卖出 {_format_price(rec.amount, item.market)}"
            if rec.shares:
                line += f"（{rec.shares}股）"
        lines.append(line)
        lines.append(f"  理由: {rec.reason}")
        if include_oos:
            try:
                oos = json.loads(rec.oos_metrics_snapshot)
                if oos:
                    lines.append(
                        f"  OOS: 胜率 {oos.get('win_rate', 0)*100:.0f}% | "
                        f"收益 {oos.get('total_return', 0)*100:+.1f}% | "
                        f"回撤 {oos.get('max_drawdown', 0)*100:.1f}%"
                    )
            except json.JSONDecodeError:
                pass

    lines.append("")
    lines.append("⚠ 仅供参考，不构成投资建议")
    return "\n".join(lines)


def format_change_message(
    item: WatchlistItem,
    changes: list[tuple[Recommendation, str | None]],
    reference_price: float | None = None,
    bar_time: datetime | None = None,
) -> str:
    lines = [
        f"【量化选股】{item.symbol} 建议变化 | {item.interval} | {datetime.now():%Y-%m-%d %H:%M}",
        "",
    ]
    if bar_time is not None:
        lines.append(f"信号 K 线: {bar_time:%Y-%m-%d %H:%M}")
    if reference_price and reference_price > 0:
        lines.append(f"参考执行价（该 K 线收盘）: {_format_price(reference_price, item.market)}")
        lines.append(
            "说明: 回测按下一根 K 线开盘价成交；请以参考价对比实际成交价。"
        )
        lines.append("")

    settings = load_settings()
    include_oos = settings.get("notifications", {}).get("include_backtest_summary", True)

    for rec, prev_action in changes:
        prev = _ACTION_LABEL.get(prev_action or "?", prev_action or "?")
        cur = _ACTION_LABEL.get(rec.action, rec.action)
        arrow = f"{prev} → {cur}"
        line = f"• {rec.strategy_name}: {arrow}"
        if reference_price and reference_price > 0:
            line += f" @ {_format_price(reference_price, item.market)}"
        if rec.amount > 0:
            line += f" | 建议 {_format_price(rec.amount, item.market)}"
        if rec.shares:
            line += f"（{rec.shares}股）"
        lines.append(line)
        lines.append(f"  理由: {rec.reason}")
        if include_oos:
            try:
                oos = json.loads(rec.oos_metrics_snapshot)
                if oos:
                    lines.append(
                        f"  OOS: 胜率 {oos.get('win_rate', 0)*100:.0f}% | "
                        f"收益 {oos.get('total_return', 0)*100:+.1f}% | "
                        f"回撤 {oos.get('max_drawdown', 0)*100:.1f}%"
                    )
            except json.JSONDecodeError:
                pass
        try:
            params = json.loads(rec.params_snapshot)
            if params:
                lines.append(f"  参数: {params}")
        except json.JSONDecodeError:
            pass

    lines.append("")
    lines.append("⚠ 仅供参考，不构成投资建议")
    return "\n".join(lines)


def detect_changes(
    new_recs: list[Recommendation],
    previous: list[Recommendation],
) -> list[tuple[Recommendation, str | None]]:
    prev_map = {r.strategy_name: r.action for r in previous}
    changes = []
    for rec in new_recs:
        prev = prev_map.get(rec.strategy_name)
        if prev != rec.action:
            changes.append((rec, prev))
    return changes
