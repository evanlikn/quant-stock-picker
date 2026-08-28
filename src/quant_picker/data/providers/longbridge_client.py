from __future__ import annotations

from quant_picker.config import (
    load_env,
    longbridge_access_token,
    longbridge_app_key,
    longbridge_app_secret,
    longbridge_configured,
)

_ctx = None


class LongbridgeNotConfigured(RuntimeError):
    """港股/美股分钟 K 线需要长桥 OpenAPI 三项凭证。"""


def get_quote_context():
    """Reuse one QuoteContext; the SDK holds a websocket for the process lifetime."""
    global _ctx
    if _ctx is None:
        load_env()
        if not longbridge_configured():
            raise LongbridgeNotConfigured(
                "港股/美股的 1小时/1分钟 K 线走长桥 OpenAPI。"
                "请在 config/.env 配置 LONGBRIDGE_APP_KEY、"
                "LONGBRIDGE_APP_SECRET、LONGBRIDGE_ACCESS_TOKEN。"
                "三项都要填：开发者中心同时发放 App Key、App Secret 和 Access Token。"
            )
        from longbridge.openapi import Config, QuoteContext

        config = Config.from_apikey(
            longbridge_app_key(),
            longbridge_app_secret(),
            longbridge_access_token(),
            enable_print_quote_packages=False,
        )
        _ctx = QuoteContext(config)
    return _ctx


def clear_quote_context() -> None:
    global _ctx
    _ctx = None
