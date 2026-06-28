"""Core event data models — single source of truth for Argus."""
from __future__ import annotations
from dataclasses import dataclass, field
from datetime import datetime, timezone
import uuid


@dataclass
class RawEvent:
    """Unified event from any log source."""
    source: str
    timestamp: str
    raw_message: str
    service_name: str
    host: str
    environment: str
    stack_trace: str | None = None
    metadata: dict[str, object] = field(default_factory=dict)


@dataclass
class AnomalyEvent:
    """Fingerprinted anomaly ready for analysis."""
    event_id: str
    fingerprint: str
    raw_sample: RawEvent
    count: int
    priority: str
    first_seen: str
    last_seen: str

    @classmethod
    def create(cls, raw: RawEvent, fingerprint: str) -> "AnomalyEvent":
        now = datetime.now(timezone.utc).isoformat()
        return cls(
            event_id=str(uuid.uuid4())[:8],
            fingerprint=fingerprint,
            raw_sample=raw,
            count=1,
            priority="P2",
            first_seen=now,
            last_seen=now,
        )
