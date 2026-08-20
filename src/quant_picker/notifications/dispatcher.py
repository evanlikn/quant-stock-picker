from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

from quant_picker.config import load_env, load_settings
from quant_picker.notifications.config_status import SendResult
from quant_picker.notifications.email_notifier import EmailNotifier
from quant_picker.notifications.formatter import (
    detect_changes,
    format_change_message,
    format_daily_summary_message,
    format_wechat_message,
    format_wechat_title,
)
from quant_picker.notifications.wpush_notifier import WPushNotifier
from quant_picker.storage.models import Recommendation, WatchlistItem
from quant_picker.storage.repository import Repository


class NotificationDispatcher:
    DAILY_LOG_TAG = "daily"
    BUY_SELL_LOG_TAG = "buy_sell"
    INTRADAY_INTERVALS = ("1h", "1m")

    def __init__(self, repo: Repository):
        load_env()
        self.repo = repo
        self._reload_settings()
        self.email = EmailNotifier()
        self.wpush = WPushNotifier()

    def _reload_settings(self) -> None:
        self.settings = load_settings().get("notifications", {})

    def _local_today(self) -> datetime.date:
        tz_name = load_settings().get("scheduler", {}).get("timezone", "Asia/Shanghai")
        return datetime.now(ZoneInfo(tz_name)).date()

    def _send_channel(
        self,
        channel: str,
        watchlist_id: int,
        bar_time: datetime,
        send_fn,
        *,
        log_tag: str = "*",
        dedupe_by_date: bool = False,
    ) -> SendResult:
        if dedupe_by_date:
            if self.repo.notification_sent_on_date(
                watchlist_id, channel, self._local_today(), strategy_name=log_tag
            ):
                return SendResult(True, "今日已发送，跳过")
        elif self.repo.notification_exists(watchlist_id, log_tag, bar_time, channel):
            return SendResult(True, "已发送过，跳过")

        try:
            result = send_fn()
        except Exception as exc:
            result = SendResult(False, str(exc))
        self.repo.log_notification(
            watchlist_id,
            log_tag,
            bar_time,
            channel,
            "success" if result.ok else "failed",
            error_message=result.error,
        )
        return result

    def _effective_trigger(self, item: WatchlistItem) -> str:
        """Pick the trigger for this item's K-line interval.

        日线一天只出一根 K 线，每日汇总正好一条。时/分线套用同一套逻辑会被
        `dedupe_by_date` 压成每天一条（后续信号全部丢失），若改成逐根推送又会
        刷屏，所以日内周期默认只在 buy/hold/sell 发生变化时推送。
        """
        if item.interval in self.INTRADAY_INTERVALS:
            return str(self.settings.get("intraday_trigger", "signal_change"))
        return str(self.settings.get("trigger", "daily_summary"))

    def notify_after_update(
        self,
        item: WatchlistItem,
        recommendations: list[Recommendation],
        previous: list[Recommendation],
        bar_time: datetime,
        reference_price: float | None,
    ) -> None:
        if not item.notify_enabled or not recommendations:
            return

        self._reload_settings()
        trigger = self._effective_trigger(item)
        if trigger == "buy_sell":
            self._notify_buy_sell(item, recommendations, bar_time, reference_price)
        elif trigger == "daily_summary":
            self._notify_daily_summary(item, recommendations, bar_time, reference_price)
        elif trigger == "signal_change":
            self._notify_signal_change(
                item, recommendations, previous, bar_time, reference_price
            )

    def _notify_buy_sell(
        self,
        item: WatchlistItem,
        recommendations: list[Recommendation],
        bar_time: datetime,
        reference_price: float | None,
    ) -> None:
        """Legacy trigger name; sends all strategies (buy/hold/sell)."""
        self._notify_daily_summary(item, recommendations, bar_time, reference_price)

    def _notify_daily_summary(
        self,
        item: WatchlistItem,
        recommendations: list[Recommendation],
        bar_time: datetime,
        reference_price: float | None,
    ) -> None:
        email_title = f"量化选股 {item.symbol} 每日建议"
        email_body = format_daily_summary_message(
            item, recommendations, bar_time, reference_price
        )
        wechat_title = format_wechat_title(item)
        wechat_body = format_wechat_message(
            item, recommendations, bar_time, reference_price
        )

        if self.settings.get("email_enabled", True):
            self._send_channel(
                "email",
                item.id,
                bar_time,
                lambda: self.email.send(email_title, email_body),
                log_tag=self.DAILY_LOG_TAG,
                dedupe_by_date=True,
            )

        if self.settings.get("wechat_enabled", True):
            self._send_channel(
                "wpush",
                item.id,
                bar_time,
                lambda: self.wpush.send(wechat_title, wechat_body),
                log_tag=self.DAILY_LOG_TAG,
                dedupe_by_date=True,
            )

    def _notify_signal_change(
        self,
        item: WatchlistItem,
        new_recommendations: list[Recommendation],
        previous: list[Recommendation],
        bar_time: datetime,
        reference_price: float | None,
    ) -> None:
        changes = detect_changes(new_recommendations, previous)
        if not changes:
            return

        title = f"量化选股 {item.symbol} 建议变化"
        body = format_change_message(
            item, changes, reference_price=reference_price, bar_time=bar_time
        )
        change_bar_time = changes[0][0].bar_time

        if self.settings.get("email_enabled", True):
            self._send_channel(
                "email",
                item.id,
                change_bar_time,
                lambda: self.email.send(title, body),
            )

        if self.settings.get("wechat_enabled", True):
            self._send_channel(
                "wpush",
                item.id,
                change_bar_time,
                lambda: self.wpush.send(title, body),
            )

    def send_test_email(self) -> SendResult:
        title = "量化选股邮件测试"
        body = (
            "这是一条邮件测试消息。\n\n"
            "参考执行价（示例）: ¥100.00\n"
            "说明: 正式推送会附带信号 K 线收盘价作为参考执行价。\n\n"
            "⚠ 仅供参考，不构成投资建议"
        )
        return self.email.send(title, body)

    def send_test_wpush(self) -> SendResult:
        title = "600519 贵州茅台"
        body = (
            "2026-07-14  收盘 ¥1688.00\n"
            "\n"
            "ma_cross\n"
            "历史表现：胜率62% 收益+8.1% 回撤12.3%\n"
            "建议：买入\n"
            "理由：均线金叉向上\n"
            "\n"
            "macd\n"
            "历史表现：胜率55% 收益+5.2% 回撤15.0%\n"
            "建议：观望\n"
            "理由：DIF 与 DEA 粘合"
        )
        return self.wpush.send(title, body)
