from __future__ import annotations

import os
import smtplib
import ssl
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

from quant_picker.notifications.config_status import SendResult, email_config_status


class EmailNotifier:
    def send(self, title: str, content: str) -> SendResult:
        ok, msg = email_config_status()
        if not ok:
            return SendResult(False, msg)

        host = os.getenv("SMTP_HOST")
        port = int(os.getenv("SMTP_PORT", "465"))
        user = os.getenv("SMTP_USER")
        password = os.getenv("SMTP_PASSWORD")
        to_addr = os.getenv("EMAIL_TO")
        try:
            mime = MIMEMultipart()
            mime["From"] = user
            mime["To"] = to_addr
            mime["Subject"] = title
            mime.attach(MIMEText(content, "plain", "utf-8"))
            context = ssl.create_default_context()
            with smtplib.SMTP_SSL(host, port, context=context) as server:
                server.login(user, password)
                server.sendmail(user, to_addr, mime.as_string())
            return SendResult(True)
        except Exception as exc:
            return SendResult(False, str(exc))
