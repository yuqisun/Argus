"""Fingerprint algorithm abstraction."""
from __future__ import annotations
from dataclasses import dataclass
from typing import Protocol, runtime_checkable
from argus.models.event import RawEvent  # single source of truth


@dataclass
class Fingerprint:
    hash: str
    exception_type: str
    template_message: str
    top_frames: list[str]


@runtime_checkable
class Fingerprinter(Protocol):
    """指纹聚合抽象 — 算法可插拔、可调参."""

    def fingerprint(self, event: RawEvent) -> Fingerprint: ...
    def is_same_group(self, fp1: Fingerprint, fp2: Fingerprint) -> bool: ...
