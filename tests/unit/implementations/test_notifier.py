"""Tests for SMTP notifier."""
import pytest
from argus.interfaces.notifier import Notification
from argus.implementations.notifiers.smtp_notifier import SMTPNotifier


class TestSMTPNotifier:
    @pytest.fixture
    def notifier(self, tmp_path):
        return SMTPNotifier(
            host="localhost",
            port=1025,
            from_addr="argus@test.com",
            template_dir="web/templates",
        )

    def test_channel_name(self, notifier):
        assert notifier.channel_name == "smtp"

    def test_build_message_contains_subject(self, notifier):
        notif = Notification(
            subject="[Argus][P0] ValueError in app.py:42",
            body_html="<h1>Root Cause</h1><p>ValueError in process()</p>",
            body_text="Root Cause: ValueError in process()",
            recipients=["dev@test.com"],
            priority="P0",
        )
        msg = notifier._build_message(notif)
        assert "ValueError" in msg["Subject"]
        assert "dev@test.com" in msg["To"]
