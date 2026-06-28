"""Notification channel abstraction."""
from __future__ import annotations
from dataclasses import dataclass
from typing import Protocol, runtime_checkable


@dataclass
class Notification:
    subject: str
    body_html: str
    body_text: str
    recipients: list[str]
    priority: str  # P0/P1/P2/P3


@runtime_checkable
class Notifier(Protocol):
    """通知渠道抽象 — 可同时注入多个实现（邮件+IM）."""

    @property
    def channel_name(self) -> str: ...

    async def send(self, notification: Notification) -> bool: ...
