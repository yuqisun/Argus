"""Redis Streams event bus implementation."""
from __future__ import annotations
import json
from collections.abc import AsyncIterator
import structlog
from redis.asyncio import Redis
from argus.models.event import AnomalyEvent, RawEvent

logger = structlog.get_logger(__name__)


class RedisEventBus:
    """EventBus backed by Redis Streams.

    Stream keys: argus:events:{priority} (p0, p1, p2).
    Dead letter queue: argus:dlq.
    """

    STREAM_PREFIX = "argus:events"
    DLQ_KEY = "argus:dlq"

    def __init__(self, redis_client: Redis):
        self._redis = redis_client

    def _stream_key(self, priority: str) -> str:
        return f"{self.STREAM_PREFIX}:{priority.lower()}"

    async def publish(self, event: AnomalyEvent, priority: str) -> str:
        raw = event.raw_sample
        fields = {
            "event_id": event.event_id,
            "fingerprint": event.fingerprint,
            "priority": event.priority,
            "count": str(event.count),
            "first_seen": event.first_seen,
            "last_seen": event.last_seen,
            "raw_json": json.dumps({
                "source": raw.source,
                "timestamp": raw.timestamp,
                "raw_message": raw.raw_message,
                "service_name": raw.service_name,
                "host": raw.host,
                "environment": raw.environment,
                "stack_trace": raw.stack_trace,
                "metadata": raw.metadata,
            }),
        }
        stream = self._stream_key(priority)
        msg_id = await self._redis.xadd(stream, fields)
        logger.debug("Published to stream", stream=stream, msg_id=msg_id)
        return msg_id

    async def consume(self, priority: str, block_ms: int = 5000) -> AsyncIterator[AnomalyEvent]:
        stream = self._stream_key(priority)
        last_id = "0"
        while True:
            results = await self._redis.xread({stream: last_id}, count=1, block=block_ms)
            if not results:
                continue
            for _stream_name, messages in results:
                for msg_id, fields in messages:
                    last_id = msg_id
                    raw_data = json.loads(fields[b"raw_json"])
                    yield AnomalyEvent(
                        event_id=fields.get(b"event_id", b"").decode(),
                        fingerprint=fields.get(b"fingerprint", b"").decode(),
                        raw_sample=RawEvent(
                            source=raw_data.get("source", "unknown"),
                            timestamp=raw_data.get("timestamp", ""),
                            raw_message=raw_data.get("raw_message", ""),
                            service_name=raw_data.get("service_name", ""),
                            host=raw_data.get("host", ""),
                            environment=raw_data.get("environment", ""),
                            stack_trace=raw_data.get("stack_trace"),
                            metadata=raw_data.get("metadata", {}),
                        ),
                        count=int(fields.get(b"count", b"1")),
                        priority=fields.get(b"priority", b"P2").decode(),
                        first_seen=fields.get(b"first_seen", b"").decode(),
                        last_seen=fields.get(b"last_seen", b"").decode(),
                    )

    async def dead_letter(self, event: AnomalyEvent, reason: str) -> None:
        payload = {
            "event_id": event.event_id,
            "fingerprint": event.fingerprint,
            "reason": reason,
        }
        await self._redis.xadd(self.DLQ_KEY, payload)
        logger.warning("Event sent to DLQ", event_id=event.event_id, reason=reason)
