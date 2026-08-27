"""Push channel credentials. Every user supplies their own via the settings page."""

from __future__ import annotations

from dataclasses import dataclass

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
