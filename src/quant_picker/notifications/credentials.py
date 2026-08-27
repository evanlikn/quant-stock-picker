"""Push channel credentials, resolved per user with a shared .env fallback."""

from __future__ import annotations

import os
from dataclasses import dataclass

from quant_picker.config import load_env

# WPUSH 的 channel 枚举里只有 wechat 表示微信公众号模板消息，其余取值是飞书/钉钉/
# 短信等别的渠道。本项目只做微信推送，所以固定死，不开放给用户填。
# https://docs.wpush.cn/docs/api/message.html
WPUSH_CHANNEL = "wechat"


@dataclass(frozen=True)
class EmailCredentials:
    host: str | None = None
    port: int = 465
    user: str | None = None
    password: str | None = None
    to_addr: str | None = None

    @property
    def configured(self) -> bool:
        return all([self.host, self.user, self.password, self.to_addr])


@dataclass(frozen=True)
class WPushCredentials:
    apikey: str | None = None
    channel: str = WPUSH_CHANNEL

    @property
    def configured(self) -> bool:
        return bool(self.apikey) and self.apikey != "your_wpush_apikey"


def email_credentials_from_env() -> EmailCredentials:
    load_env()
    return EmailCredentials(
        host=os.getenv("SMTP_HOST") or None,
        port=int(os.getenv("SMTP_PORT", "465") or 465),
        user=os.getenv("SMTP_USER") or None,
        password=os.getenv("SMTP_PASSWORD") or None,
        to_addr=os.getenv("EMAIL_TO") or None,
    )


def wpush_credentials_from_env() -> WPushCredentials:
    load_env()
    return WPushCredentials(apikey=os.getenv("WPUSH_APIKEY") or None)
