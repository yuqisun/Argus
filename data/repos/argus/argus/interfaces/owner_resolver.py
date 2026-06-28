"""Owner resolution abstraction."""
from __future__ import annotations
from dataclasses import dataclass
from typing import Protocol, runtime_checkable


@dataclass
class OwnerResult:
    name: str
    email: str
    im_id: str | None = None
    source: str = "unknown"
    confidence: float = 0.0


@runtime_checkable
class OwnerResolver(Protocol):
    """定责抽象 — 四级 fallback 统一接口."""

    async def resolve(
        self, repo: str, file_path: str, line_number: int, *, commit: str,
    ) -> list[OwnerResult]: ...
