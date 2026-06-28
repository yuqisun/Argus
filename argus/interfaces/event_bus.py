"""Event queue abstraction."""
from __future__ import annotations
from collections.abc import AsyncIterator
from typing import Protocol, runtime_checkable
from argus.models.event import AnomalyEvent  # single source of truth


@runtime_checkable
class EventBus(Protocol):
    """事件队列抽象 — arq vs Kafka 对外接口一致."""

    async def publish(self, event: AnomalyEvent, priority: str) -> str: ...
    async def consume(self, priority: str) -> AsyncIterator[AnomalyEvent]: ...
    async def dead_letter(self, event: AnomalyEvent, reason: str) -> None: ...
