"""Capture the login screen to confirm the web app renders after startup."""

from __future__ import annotations

import sys

from playwright.sync_api import sync_playwright

BASE = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8599"
OUT = sys.argv[2] if len(sys.argv) > 2 else "/tmp/qp_login.png"

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
