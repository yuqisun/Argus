"""Tests for RedisEventBus using fakeredis."""
import pytest
from argus.models.event import RawEvent, AnomalyEvent
from argus.implementations.event_bus.redis_bus import RedisEventBus


def make_anomaly(event_id="evt-1", fp="fp-1"):
    raw = RawEvent(
        source="test", timestamp="2026-06-28T10:00:00Z",
        raw_message="error", service_name="api", host="h1",
        environment="test",
    )
    return AnomalyEvent(
        event_id=event_id, fingerprint=fp, raw_sample=raw,
        count=1, priority="P1", first_seen="t1", last_seen="t1",
    )


@pytest.fixture
def bus():
    import fakeredis.aioredis
    redis = fakeredis.aioredis.FakeRedis()
    return RedisEventBus(redis_client=redis)


class TestRedisEventBus:
    @pytest.mark.asyncio
    async def test_publish_and_consume(self, bus):
        event = make_anomaly()
        msg_id = await bus.publish(event, "P1")
        assert msg_id

        consumed = []
        async for e in bus.consume("P1", block_ms=100):
            consumed.append(e)
            break

        assert len(consumed) == 1
        assert consumed[0].event_id == "evt-1"

    @pytest.mark.asyncio
    async def test_dead_letter_does_not_raise(self, bus):
        event = make_anomaly()
        await bus.dead_letter(event, "test failure")
