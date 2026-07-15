from __future__ import annotations

import os

import httpx

from quant_picker.notifications.config_status import SendResult, wpush_config_status

WPUSH_SEND_URL = "https://api.wpush.cn/api/v1/send"


class WPushNotifier:
    """WeChat push via WPUSH (https://docs.wpush.cn/docs/api/message.html)."""

    def send(self, title: str, content: str) -> SendResult:
        ok, msg = wpush_config_status()
        if not ok:
            return SendResult(False, msg)

        apikey = os.getenv("WPUSH_APIKEY")
        channel = os.getenv("WPUSH_CHANNEL", "wechat")
        try:
            resp = httpx.post(
                WPUSH_SEND_URL,
                data={
                    "apikey": apikey,
                    "title": title,
                    "content": content,
                    "channel": channel,
                },
                timeout=15,
            )
            resp.raise_for_status()
            payload = resp.json()
        except httpx.HTTPError as exc:
            return SendResult(False, str(exc))
        except ValueError:
            return SendResult(False, "WPUSH 响应解析失败")

        if payload.get("code") == 0:
            return SendResult(True)
        return SendResult(False, payload.get("message") or f"code={payload.get('code')}")
