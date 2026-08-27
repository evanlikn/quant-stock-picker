from __future__ import annotations

import httpx

from quant_picker.notifications.config_status import SendResult, wpush_config_status
from quant_picker.notifications.credentials import WPushCredentials

WPUSH_SEND_URL = "https://api.wpush.cn/api/v1/send"


class WPushNotifier:
    """WeChat push via WPUSH (https://docs.wpush.cn/docs/api/message.html)."""

    def send(self, creds: WPushCredentials, title: str, content: str) -> SendResult:
        ok, msg = wpush_config_status(creds)
        if not ok:
            return SendResult(False, msg)

        try:
            resp = httpx.post(
                WPUSH_SEND_URL,
                data={
                    "apikey": creds.apikey,
                    "title": title,
                    "content": content,
                    "channel": creds.channel,
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
