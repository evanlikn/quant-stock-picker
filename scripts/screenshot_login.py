"""Capture the login screen to confirm the web app renders after startup."""

from __future__ import annotations

import sys

from playwright.sync_api import sync_playwright

from quant_picker.config import web_host, web_port

host = web_host()
# 0.0.0.0 is a bind address, not a browser destination.
browser_host = "127.0.0.1" if host in {"0.0.0.0", "::"} else host
BASE = f"http://{browser_host}:{web_port()}"
OUT = sys.argv[1] if len(sys.argv) > 1 else "/tmp/qp_login.png"

with sync_playwright() as p:
    browser = p.chromium.launch()
    page = browser.new_context(viewport={"width": 1440, "height": 900}).new_page()
    page.goto(BASE, wait_until="networkidle")
    page.wait_for_timeout(3000)
    body = page.inner_text("body")
    print("login form rendered:", "登录" in body)
    print("business UI hidden:", "量化选股分析" not in body)
    page.screenshot(path=OUT, full_page=True)
    print("screenshot:", OUT)
    browser.close()
