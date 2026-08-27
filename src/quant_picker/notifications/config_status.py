from __future__ import annotations

from dataclasses import dataclass

from quant_picker.notifications.credentials import EmailCredentials, WPushCredentials


@dataclass
class SendResult:
    ok: bool
    error: str | None = None


def email_config_status(creds: EmailCredentials) -> tuple[bool, str]:
    required = {
        "SMTP 服务器": creds.host,
        "发件账号": creds.user,
        "发件密码": creds.password,
        "收件邮箱": creds.to_addr,
    }
    missing = [k for k, v in required.items() if not v]
    if missing:
        return False, f"缺少配置: {', '.join(missing)}"
    return True, f"已配置 → {creds.to_addr}"


def wpush_config_status(creds: WPushCredentials) -> tuple[bool, str]:
    if not creds.configured:
        return False, "缺少配置: WPUSH APIKEY"
    apikey = creds.apikey or ""
    masked = f"{apikey[:6]}...{apikey[-4:]}" if len(apikey) > 12 else "已设置"
    return True, f"已配置 ({masked})，通道 {creds.channel}"
