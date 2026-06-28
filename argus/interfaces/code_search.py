"""Code search abstraction."""
from __future__ import annotations
from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable


@dataclass
class CodeHit:
    file_path: str
    line_number: int
    content: str
    context: list[str] = field(default_factory=list)


@dataclass
class CallGraphNode:
    function_name: str
    file_path: str
    line_number: int
    callers: list[str] = field(default_factory=list)
    callees: list[str] = field(default_factory=list)


@runtime_checkable
class CodeSearcher(Protocol):
    """代码检索抽象 — grep + AST 统一接口."""

    async def grep(
        self, repo: str, pattern: str, *, commit: str, glob: str | None = None,
    ) -> list[CodeHit]: ...

    async def find_definition(
        self, repo: str, symbol: str, *, commit: str,
    ) -> CodeHit | None: ...

    async def get_call_graph(
        self, repo: str, function: str, *, commit: str, depth: int = 2,
    ) -> CallGraphNode | None: ...

    async def blame(
        self, repo: str, file_path: str, line_number: int, *, commit: str,
    ) -> tuple[str, str]: ...
