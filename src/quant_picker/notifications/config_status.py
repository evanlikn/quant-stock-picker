from __future__ import annotations

import os
from dataclasses import dataclass

from quant_picker.config import load_env


@dataclass
class SendResult:
    ok: bool
    error: str | None = None


def email_config_status() -> tuple[bool, str]:
    load_env()
    required = {
        "SMTP_HOST": os.getenv("SMTP_HOST"),
        "SMTP_USER": os.getenv("SMTP_USER"),
        "SMTP_PASSWORD": os.getenv("SMTP_PASSWORD"),
        "EMAIL_TO": os.getenv("EMAIL_TO"),
    }
    missing = [k for k, v in required.items() if not v]
    if missing:
        return False, f"缺少配置: {', '.join(missing)}"
    return True, f"已配置 → {required['EMAIL_TO']}"


def wpush_config_status() -> tuple[bool, str]:
    load_env()
    apikey = os.getenv("WPUSH_APIKEY")
    if not apikey or apikey == "your_wpush_apikey":
        return False, "缺少配置: WPUSH_APIKEY"
    channel = os.getenv("WPUSH_CHANNEL", "wechat")
    masked = f"{apikey[:6]}...{apikey[-4:]}" if len(apikey) > 12 else "已设置"
    return True, f"已配置 ({masked})，通道 {channel}"
