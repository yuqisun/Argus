"""Vector store abstraction (optional for MVP)."""
from __future__ import annotations
from dataclasses import dataclass, field
from typing import Protocol


@dataclass
class VectorDoc:
    id: str
    text: str
    metadata: dict[str, object] = field(default_factory=dict)
    embedding: list[float] | None = None


class VectorStore(Protocol):
    """向量库抽象 — pgvector vs Milvus 对外一致."""

    async def store(self, docs: list[VectorDoc]) -> list[str]: ...
    async def search(self, query: str, *, top_k: int = 5) -> list[tuple[VectorDoc, float]]: ...
    async def delete(self, doc_id: str) -> None: ...
