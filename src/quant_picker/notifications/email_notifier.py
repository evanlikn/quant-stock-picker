from __future__ import annotations

import smtplib
import ssl
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

from quant_picker.notifications.config_status import SendResult, email_config_status
from quant_picker.notifications.credentials import EmailCredentials


class EmailNotifier:
    def send(self, creds: EmailCredentials, title: str, content: str) -> SendResult:
        ok, msg = email_config_status(creds)
        if not ok:
            return SendResult(False, msg)

        try:
            mime = MIMEMultipart()
            mime["From"] = creds.user
            mime["To"] = creds.to_addr
            mime["Subject"] = title
            mime.attach(MIMEText(content, "plain", "utf-8"))
            context = ssl.create_default_context()
            with smtplib.SMTP_SSL(creds.host, creds.port, context=context) as server:
                server.login(creds.user, creds.password)
                server.sendmail(creds.user, creds.to_addr, mime.as_string())
            return SendResult(True)
        except Exception as exc:
            return SendResult(False, str(exc))
