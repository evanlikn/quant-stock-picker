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


class LongbridgeNotInstalled(RuntimeError):
    """长桥 SDK 未安装。它只发 manylinux_2_39 wheel，老系统装不上。"""


def sdk_available() -> bool:
    try:
        import longbridge  # noqa: F401
    except ImportError:
        return False
    return True


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
        try:
            from longbridge.openapi import Config, QuoteContext
        except ImportError as exc:
            raise LongbridgeNotInstalled(
                "已配置长桥凭证，但未安装 longbridge SDK。"
                "执行 pip install -r requirements-longbridge.txt；"
                "若报 No matching distribution found，说明系统 glibc < 2.39"
                "（ldd --version 查看），长桥 SDK 不支持该系统，"
                "港股/美股分钟线将不可用，日 K 不受影响。"
            ) from exc

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
