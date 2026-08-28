from __future__ import annotations

import os
import sys

_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "..", ".."))
if _ROOT not in sys.path:
    sys.path.insert(0, os.path.join(_ROOT, "src"))
os.environ.setdefault("QUANT_PICKER_ROOT", _ROOT)

import streamlit as st

from quant_picker.auth import service
from quant_picker.auth.guard import render_sidebar_account, require_login
from quant_picker.config import load_settings
from quant_picker.notifications.config_status import email_config_status, wpush_config_status
from quant_picker.notifications.credentials import WPUSH_CHANNEL
from quant_picker.notifications.dispatcher import NotificationDispatcher
from quant_picker.security.crypto import SecretUndecryptable, decrypt_secret, mask_secret
from quant_picker.web.db_session import web_session
from quant_picker.storage.repository import Repository

st.set_page_config(page_title="推送设置", page_icon="🔔", layout="wide")
user = require_login()
render_sidebar_account(user)

session = web_session()
repo = Repository(session, user.id)
dispatcher = NotificationDispatcher(repo)
defaults = load_settings().get("notifications", {})

_TRIGGER_OPTIONS = ["daily_summary", "signal_change"]
_TRIGGER_LABELS = {
    "daily_summary": "每日汇总（收盘更新后推送，买入/卖出/观望均提醒）",
    "buy_sell": "每日汇总（等同 daily_summary，兼容旧配置）",
    "signal_change": "仅建议变化（buy/hold/sell 相对上次变化时才推送）",
}

def _stored_secret(ciphertext: str | None) -> str | None:
    """Decrypted value, or None when nothing is stored or the key changed."""
    try:
        return decrypt_secret(ciphertext)
    except SecretUndecryptable:
        return None


setting = service.get_or_create_notification_setting(session, user.id)
config = service.resolve_notify_config(session, user.id, defaults)

st.title("推送设置")
st.caption(
    f"当前账号：**{user.display_name}**。以下配置只对你自己生效，"
    "邮件与微信（WPUSH）独立发送，单渠道失败不影响另一渠道。"
)

if config.needs_recredential:
    lost = [
        name
        for name, broken in (("邮件密码", config.email_unreadable), ("WPUSH APIKEY", config.wpush_unreadable))
        if broken
    ]
    st.error(
        f"**{'、'.join(lost)} 无法解密**，相关推送已自动停用。"
        "服务器上的 `QUANT_PICKER_SECRET_KEY` 与保存这些凭据时用的密钥不一致"
        "（通常是恢复数据库时没有一并恢复 `config/.env`）。"
        "已保存的密文无法找回，请在下方重新填写并保存。",
        icon="🔑",
    )

email_ok, email_msg = email_config_status(config.email)
wpush_ok, wpush_msg = wpush_config_status(config.wpush)

with st.form("notify_form"):
    col_email, col_wpush = st.columns(2)

    with col_email:
        st.subheader("📧 邮件推送")
        st.markdown(f"**当前状态**: {'✅' if email_ok else '⚠️'} {email_msg}")
        email_enabled = st.toggle("启用邮件推送", value=bool(setting.email_enabled))
        smtp_host = st.text_input(
            "SMTP 服务器", value=setting.smtp_host or "", placeholder="smtp.qq.com"
        )
        smtp_port = st.number_input(
            "SMTP 端口（SSL）", min_value=1, max_value=65535, value=int(setting.smtp_port or 465)
        )
        smtp_user = st.text_input(
            "发件邮箱", value=setting.smtp_user or "", placeholder="you@example.com"
        )
        stored_pwd = _stored_secret(setting.smtp_password_enc)
        smtp_password = st.text_input(
            "发件密码 / 授权码",
            value="",
            type="password",
            placeholder="留空则沿用已保存的密码" if stored_pwd else "多数邮箱需填授权码而非登录密码",
        )
        st.caption(
            f"已保存：`{mask_secret(stored_pwd)}`，需要更换时才填写"
            if stored_pwd
            else "尚未保存密码"
        )
        email_to = st.text_input("收件邮箱", value=setting.email_to or "")

    with col_wpush:
        st.subheader("💬 微信推送 (WPUSH)")
        st.markdown(f"**当前状态**: {'✅' if wpush_ok else '⚠️'} {wpush_msg}")
        wechat_enabled = st.toggle("启用微信推送", value=bool(setting.wechat_enabled))
        stored_key = _stored_secret(setting.wpush_apikey_enc)
        wpush_apikey = st.text_input(
            "WPUSH APIKEY",
            value="",
            type="password",
            placeholder="留空则沿用已保存的 APIKEY" if stored_key else "在 wpush.cn 个人消息页获取",
        )
        st.caption(
            f"已保存：`{mask_secret(stored_key)}`，需要更换时才填写"
            if stored_key
            else "尚未保存 APIKEY"
        )
        st.caption(
            f"推送通道：`{WPUSH_CHANNEL}`（微信公众号模板消息，由 WPUSH 定义，不可修改）"
        )

        st.markdown("**推送策略**")
        trigger = st.selectbox(
            "日K 推送策略",
            _TRIGGER_OPTIONS,
            index=_TRIGGER_OPTIONS.index(
                setting.trigger if setting.trigger in _TRIGGER_OPTIONS else "daily_summary"
            ),
            format_func=lambda x: _TRIGGER_LABELS.get(x, x),
        )
        intraday_trigger = st.selectbox(
            "时K/分K 推送策略",
            _TRIGGER_OPTIONS,
            index=_TRIGGER_OPTIONS.index(
                setting.intraday_trigger
                if setting.intraday_trigger in _TRIGGER_OPTIONS
                else "signal_change"
            ),
            format_func=lambda x: _TRIGGER_LABELS.get(x, x),
            help="日内周期出线频繁，选「每日汇总」会被每日去重压成一条，建议保留「仅建议变化」",
        )

    if st.form_submit_button("保存配置", type="primary"):
        service.save_notification_setting(
            session,
            user.id,
            email_enabled=email_enabled,
            wechat_enabled=wechat_enabled,
            trigger=trigger,
            intraday_trigger=intraday_trigger,
            smtp_host=smtp_host,
            smtp_port=int(smtp_port),
            smtp_user=smtp_user,
            smtp_password=smtp_password.strip() or None,
            email_to=email_to,
            wpush_apikey=wpush_apikey.strip() or None,
        )
        st.success("已保存")
        st.rerun()

st.caption("测试发送使用**已保存**的配置。刚改过输入框的话，请先点「保存配置」再测试。")
test_email_col, test_wpush_col = st.columns(2)
with test_email_col:
    if st.button("发送邮件测试", use_container_width=True):
        result = dispatcher.send_test_email(user.id)
        if result.ok:
            st.success("邮件发送成功")
        else:
            st.error(f"邮件发送失败: {result.error or '未知错误'}")
with test_wpush_col:
    if st.button("发送微信测试", use_container_width=True):
        result = dispatcher.send_test_wpush(user.id)
        if result.ok:
            st.success("微信推送成功")
        else:
            st.error(f"微信推送失败: {result.error or '未知错误'}")

st.divider()
st.subheader("最近推送日志")
st.caption("只显示你自己自选股产生的推送记录。")
log_filter = st.radio("筛选渠道", ["全部", "邮件", "微信"], horizontal=True)
channel_map = {"邮件": "email", "微信": "wpush"}
logs = repo.list_notification_logs(50)
if log_filter != "全部":
    logs = [entry for entry in logs if entry.channel == channel_map[log_filter]]

if logs:
    st.dataframe(
        [
            {
                "时间": entry.sent_at,
                "渠道": {"email": "邮件", "wpush": "微信"}.get(entry.channel, entry.channel),
                "状态": entry.status,
                "策略": entry.strategy_name,
                "错误": entry.error_message or "",
            }
            for entry in logs
        ],
        use_container_width=True,
    )
else:
    st.info("暂无推送记录")
