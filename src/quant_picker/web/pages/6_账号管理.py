from __future__ import annotations

import os
import sys

_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "..", ".."))
if _ROOT not in sys.path:
    sys.path.insert(0, os.path.join(_ROOT, "src"))
os.environ.setdefault("QUANT_PICKER_ROOT", _ROOT)

import streamlit as st

from quant_picker.auth import service
from quant_picker.auth.guard import render_sidebar_account, require_login
from quant_picker.web.db_session import web_session
from quant_picker.storage.repository import Repository

st.set_page_config(page_title="账号管理", page_icon="👤", layout="wide")
user = require_login()
render_sidebar_account(user)

session = web_session()

st.title("账号管理")

st.subheader("修改密码")
with st.form("change_password"):
    current_pwd = st.text_input("当前密码", type="password")
    new_pwd = st.text_input("新密码", type="password")
    confirm_pwd = st.text_input("确认新密码", type="password")
    if st.form_submit_button("更新密码", type="primary"):
        if new_pwd != confirm_pwd:
            st.error("两次输入的新密码不一致")
        else:
            try:
                service.change_password(session, user.id, current_pwd, new_pwd)
                st.success("密码已更新，下次登录请使用新密码")
            except ValueError as exc:
                st.error(str(exc))

if not user.is_admin:
    st.stop()

st.divider()
st.subheader("用户列表（管理员）")

users = service.list_users(session)
repo = Repository(session)
counts: dict[int, int] = {}
for item in repo.list_all_watchlist():
    counts[item.user_id] = counts.get(item.user_id, 0) + 1

st.dataframe(
    [
        {
            "ID": u.id,
            "用户名": u.username,
            "显示名": u.display_name,
            "邮箱": u.email or "",
            "管理员": "是" if u.is_admin else "",
            "状态": "启用" if u.is_active else "停用",
            "自选数": counts.get(u.id, 0),
            "最近登录": u.last_login_at,
        }
        for u in users
    ],
    use_container_width=True,
    hide_index=True,
)

st.subheader("新建用户")
with st.form("create_user"):
    c1, c2 = st.columns(2)
    with c1:
        new_username = st.text_input("用户名", placeholder="登录名，建议英文")
        new_display = st.text_input("显示名", placeholder="留空则同用户名")
    with c2:
        new_email = st.text_input("邮箱（可选）")
        new_password = st.text_input("初始密码", type="password")
    new_is_admin = st.checkbox("授予管理员权限")
    if st.form_submit_button("创建用户", type="primary"):
        try:
            created = service.create_user(
                session,
                username=new_username,
                password=new_password,
                display_name=new_display,
                email=new_email,
                is_admin=new_is_admin,
            )
            st.success(f"已创建用户 {created.username}")
            st.rerun()
        except ValueError as exc:
            st.error(str(exc))

st.subheader("维护用户")
others = {f"{u.username}（{u.display_name}）": u for u in users}
target_label = st.selectbox("选择用户", list(others.keys()))
target = others[target_label]

c1, c2 = st.columns(2)
with c1:
    reset_pwd = st.text_input("重置密码为", type="password", key="reset_pwd")
    if st.button("重置密码", disabled=not reset_pwd):
        service.set_password(session, target.id, reset_pwd)
        st.success(f"已重置 {target.username} 的密码")
with c2:
    if target.id == user.id:
        st.caption("不能停用自己的账号")
    else:
        label = "停用账号" if target.is_active else "启用账号"
        if st.button(label):
            service.set_active(session, target.id, not target.is_active)
            st.success(f"已{label[:2]} {target.username}")
            st.rerun()
