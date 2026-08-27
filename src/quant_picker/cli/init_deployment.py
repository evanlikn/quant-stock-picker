"""One-shot setup for a fresh deployment: create the schema, key and admin.

Both services call init_db() themselves, so this is not strictly required.
Running it once before enabling them gives the operator the generated admin
password and secret key on screen instead of buried in a service log.
"""

from __future__ import annotations

import logging

from quant_picker.config import database_url, log_level, project_root
from quant_picker.storage.db import get_session_factory, init_db


def main() -> None:
    logging.basicConfig(
        level=getattr(logging, log_level(), logging.INFO),
        format="%(levelname)s: %(message)s",
    )

    url = database_url()
    printable = url.split("@")[-1] if "@" in url else url
    print(f"项目目录: {project_root()}")
    print(f"数据库  : {printable}")

    init_db()

    from quant_picker.auth.service import list_users

    with get_session_factory()() as session:
        users = list_users(session)
    print(f"账号数  : {len(users)}（{'、'.join(u.username for u in users)}）")

    password_file = project_root() / "data" / "bootstrap_admin_password.txt"
    if password_file.exists():
        print(f"\n初始管理员密码见 {password_file}")
        print("登录后请在「账号管理」修改密码，并删除该文件。")

    print("\n初始化完成，可以启动 Web 与 scheduler 了。")


if __name__ == "__main__":
    main()
