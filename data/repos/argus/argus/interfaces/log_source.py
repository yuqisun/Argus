"""Log source abstraction."""
from __future__ import annotations
from collections.abc import AsyncIterator
from typing import Protocol, runtime_checkable
from argus.models.event import RawEvent  # single source of truth


@runtime_checkable
class LogSource(Protocol):
    """日志源抽象 — 新增来源实现此接口即可."""

    @property
    def source_name(self) -> str: ...

    async def listen(self) -> AsyncIterator[RawEvent]: ...
    async def ack(self, event_id: str) -> None: ...
