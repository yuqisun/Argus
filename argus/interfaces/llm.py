"""LLM client abstraction."""
from __future__ import annotations
from collections.abc import AsyncIterator
from typing import Protocol, runtime_checkable


@runtime_checkable
class LLMClient(Protocol):
    """LLM调用抽象 — 换模型只改配置不改代码."""

    async def chat(
        self,
        messages: list[dict[str, str]],
        *,
        model: str | None = None,
        max_tokens: int = 4096,
        temperature: float = 0.1,
    ) -> str: ...

    async def chat_stream(
        self,
        messages: list[dict[str, str]],
        *,
        model: str | None = None,
        max_tokens: int = 4096,
    ) -> AsyncIterator[str]: ...
