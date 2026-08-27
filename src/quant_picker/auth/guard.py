"""Login gate shared by every Streamlit page."""

from __future__ import annotations

import hashlib
import os
from dataclasses import dataclass

import streamlit as st
import streamlit_authenticator as stauth

from quant_picker.auth import service
from quant_picker.config import load_env
from quant_picker.storage.models import get_session_factory, init_db

COOKIE_NAME = "quant_picker_auth"
COOKIE_EXPIRY_DAYS = 30.0


@dataclass(frozen=True)
class CurrentUser:
    id: int
    username: str
    display_name: str
    is_admin: bool


def _cookie_key() -> str:
    load_env()
    raw = os.getenv("QUANT_PICKER_SECRET_KEY", "").strip() or "quant-picker-dev"
    return hashlib.sha256(f"cookie:{raw}".encode()).hexdigest()


@st.cache_resource
def _bootstrap() -> bool:
    init_db()
    return True


def _session():
    return get_session_factory()()


def _build_authenticator() -> stauth.Authenticate:
    with _session() as session:
        credentials = service.build_credentials(session)
    return stauth.Authenticate(
        credentials,
        COOKIE_NAME,
        _cookie_key(),
        COOKIE_EXPIRY_DAYS,
        auto_hash=False,
    )


def require_login() -> CurrentUser:
    """Render the login form and halt the page until a valid user is present."""
    from quant_picker.web.db_session import release_web_session

    _bootstrap()
    # Every page calls this first, which makes it the one reliable place to drop
    # the connection the previous rerun left checked out.
    release_web_session()
    authenticator = _build_authenticator()
    st.session_state["_authenticator"] = authenticator

    authenticator.login(
        location="main",
        fields={
            "Form name": "登录",
            "Username": "用户名",
            "Password": "密码",
            "Login": "登录",
        },
    )

    status = st.session_state.get("authentication_status")
    if status is False:
        st.error("用户名或密码错误")
        st.stop()
    if status is None:
        st.info("请先登录后使用")
        st.stop()

    username = st.session_state.get("username") or ""
    with _session() as session:
        user = service.get_user(session, username)
        if user is None or not user.is_active:
            authenticator.logout(location="unrendered")
            st.error("账号不存在或已被停用，请联系管理员")
            st.stop()
        current = CurrentUser(
            id=user.id,
            username=user.username,
            display_name=user.display_name or user.username,
            is_admin=bool(user.is_admin),
        )
        # Only on the first page load of a session; every widget interaction
        # reruns this gate and would otherwise write on each click.
        if st.session_state.get("current_user_id") != current.id:
            service.touch_login(session, current.id)

    st.session_state["current_user_id"] = current.id
    return current


def render_sidebar_account(user: CurrentUser) -> None:
    authenticator = st.session_state.get("_authenticator")
    with st.sidebar:
        st.caption(f"👤 {user.display_name}" + ("（管理员）" if user.is_admin else ""))
        if authenticator is not None:
            authenticator.logout("退出登录", "sidebar", key="sidebar_logout")


def current_user_id() -> int | None:
    return st.session_state.get("current_user_id")
