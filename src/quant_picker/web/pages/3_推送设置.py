from __future__ import annotations

import os
import sys

_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "..", ".."))
if _ROOT not in sys.path:
    sys.path.insert(0, os.path.join(_ROOT, "src"))
os.environ.setdefault("QUANT_PICKER_ROOT", _ROOT)

import streamlit as st

from quant_picker.config import load_settings, save_notification_flags
from quant_picker.notifications.dispatcher import NotificationDispatcher
from quant_picker.notifications.config_status import email_config_status, wpush_config_status
from quant_picker.storage.db import get_session_factory, init_db
from quant_picker.storage.repository import Repository

st.set_page_config(page_title="推送设置", page_icon="🔔", layout="wide")
init_db()
repo = Repository(get_session_factory()())
dispatcher = NotificationDispatcher(repo)
notif_cfg = load_settings().get("notifications", {})

_TRIGGER_LABELS = {
    "daily_summary": "每日建议汇总（收盘更新后推送，买入/卖出/观望均提醒）",
    "buy_sell": "每日建议汇总（与 daily_summary 相同，兼容旧配置）",
    "signal_change": "建议变化（仅当 buy/hold/sell 相对上次发生变化时推送）",
}

st.title("推送设置")
trigger = notif_cfg.get("trigger", "daily_summary")
st.caption(
    f"邮件与微信（WPUSH）独立配置、独立发送；单渠道失败不影响另一渠道。"
    f" 当前推送策略：`{trigger}` — {_TRIGGER_LABELS.get(trigger, trigger)}"
    "（在 `config/settings.yaml` 的 `notifications.trigger` 修改）"
)

col_email, col_wpush = st.columns(2)

with col_email:
    st.subheader("📧 邮件推送")
    email_ok, email_msg = email_config_status()
    st.markdown(f"**配置状态**: {'✅' if email_ok else '⚠️'} {email_msg}")
    st.markdown(
        "在 `config/.env` 中配置：`SMTP_HOST`、`SMTP_PORT`、`SMTP_USER`、"
        "`SMTP_PASSWORD`、`EMAIL_TO`"
    )
    email_enabled = st.toggle(
        "启用邮件推送",
        value=bool(notif_cfg.get("email_enabled", True)),
        key="email_enabled_toggle",
    )
    if st.button("发送邮件测试", type="primary", key="test_email"):
        result = dispatcher.send_test_email()
        if result.ok:
            st.success("邮件发送成功")
        else:
            st.error(f"邮件发送失败: {result.error or '未知错误'}")

with col_wpush:
    st.subheader("💬 微信推送 (WPUSH)")
    wpush_ok, wpush_msg = wpush_config_status()
    st.markdown(f"**配置状态**: {'✅' if wpush_ok else '⚠️'} {wpush_msg}")
    st.markdown(
        "在 `config/.env` 中配置：`WPUSH_APIKEY`、可选 `WPUSH_CHANNEL`（默认 wechat）"
    )
    wpush_enabled = st.toggle(
        "启用微信推送",
        value=bool(notif_cfg.get("wechat_enabled", True)),
        key="wpush_enabled_toggle",
    )
    if st.button("发送微信测试", type="primary", key="test_wpush"):
        result = dispatcher.send_test_wpush()
        if result.ok:
            st.success("微信推送成功")
        else:
            st.error(f"微信推送失败: {result.error or '未知错误'}")

if st.button("保存推送开关"):
    save_notification_flags(email_enabled=email_enabled, wpush_enabled=wpush_enabled)
    dispatcher._reload_settings()
    st.success("已保存到 config/settings.yaml")
    st.rerun()

st.divider()
log_filter = st.radio("推送日志筛选", ["全部", "邮件", "微信"], horizontal=True)
channel_map = {"邮件": "email", "微信": "wpush"}
logs = repo.list_notification_logs(50)
if log_filter != "全部":
    logs = [l for l in logs if l.channel == channel_map[log_filter]]

st.subheader("最近推送日志")
if logs:
    st.dataframe(
        [
            {
                "时间": l.sent_at,
                "渠道": {"email": "邮件", "wpush": "微信"}.get(l.channel, l.channel),
                "状态": l.status,
                "策略": l.strategy_name,
                "错误": l.error_message or "",
            }
            for l in logs
        ],
        use_container_width=True,
    )
else:
    st.info("暂无推送记录")
