"""SMTP email notifier with Jinja2 templates."""
from __future__ import annotations
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
import structlog
import aiosmtplib
from jinja2 import Environment, FileSystemLoader
from argus.interfaces.notifier import Notification

logger = structlog.get_logger(__name__)


class SMTPNotifier:
    """Send notifications via SMTP with Jinja2-rendered HTML emails."""

    channel_name = "smtp"

    def __init__(
        self,
        host: str,
        port: int = 587,
        username: str = "",
        password: str = "",
        from_addr: str = "argus@company.com",
        template_dir: str = "web/templates",
        use_tls: bool = True,
    ):
        self.host = host
        self.port = port
        self.username = username
        self.password = password
        self.from_addr = from_addr
        self.use_tls = use_tls
        self._jinja = Environment(
            loader=FileSystemLoader(template_dir),
            autoescape=True,
        )

    def _build_message(self, notification: Notification) -> MIMEMultipart:
        msg = MIMEMultipart("alternative")
        msg["Subject"] = notification.subject
        msg["From"] = self.from_addr
        msg["To"] = ", ".join(notification.recipients)
        msg.attach(MIMEText(notification.body_text, "plain", "utf-8"))
        msg.attach(MIMEText(notification.body_html, "html", "utf-8"))
        return msg

    async def send(self, notification: Notification) -> bool:
        try:
            msg = self._build_message(notification)
            await aiosmtplib.send(
                msg,
                hostname=self.host,
                port=self.port,
                username=self.username or None,
                password=self.password or None,
                use_tls=self.use_tls,
            )
            logger.info("Notification sent", channel="smtp", recipients=notification.recipients)
            return True
        except Exception:
            logger.exception("SMTP send failed", recipients=notification.recipients)
            return False
