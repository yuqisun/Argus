"""Tests for the ingest pipeline."""
import pytest
from argus.models.event import RawEvent
from argus.interfaces.event_bus import AnomalyEvent
from argus.interfaces.fingerprinter import Fingerprint
from argus.services.ingest import IngestService, DedupState


def make_raw(message="ValueError: test", stack=None):
    return RawEvent(
        source="sentry", timestamp="2026-06-28T10:00:00Z",
        raw_message=message, service_name="api", host="h1",
        environment="prod", stack_trace=stack,
    )


class FakeFingerprinter:
    def fingerprint(self, event):
        return Fingerprint(
            hash=f"fp-{hash(event.raw_message) & 0xFFFF:04x}",
            exception_type="ValueError", template_message=event.raw_message,
            top_frames=[],
        )
    def is_same_group(self, fp1, fp2):
        return fp1.hash == fp2.hash


class FakeEventBus:
    def __init__(self):
        self.published: list[tuple] = []

    async def publish(self, event, priority):
        self.published.append((event, priority))
        return event.event_id

    async def consume(self, priority):
        if False: yield  # pragma: no cover

    async def dead_letter(self, event, reason):
        pass


class TestDedupState:
    @pytest.mark.asyncio
    async def test_first_event_should_publish(self):
        state = DedupState(dedup_window=300, cooldown=3600)
        assert await state.should_publish("fp-1")

    @pytest.mark.asyncio
    async def test_duplicate_within_window_is_blocked(self):
        state = DedupState(dedup_window=300, cooldown=3600)
        await state.record("fp-1")
        assert not await state.should_publish("fp-1")

    @pytest.mark.asyncio
    async def test_counts_increment(self):
        state = DedupState(dedup_window=300, cooldown=3600)
        await state.record("fp-1")
        await state.record("fp-1")
        assert await state.get_count("fp-1") == 2


class TestIngestService:
    @pytest.fixture
    def svc_and_bus(self):
        bus = FakeEventBus()
        fp = FakeFingerprinter()
        svc = IngestService(fingerprinter=fp, event_bus=bus)
        return svc, bus

    @pytest.mark.asyncio
    async def test_first_event_publishes(self, svc_and_bus):
        svc, bus = svc_and_bus
        event = make_raw()
        result = await svc.process(event)
        assert result is not None
        assert len(bus.published) == 1

    @pytest.mark.asyncio
    async def test_duplicate_within_window_is_deduped(self, svc_and_bus):
        svc, bus = svc_and_bus
        e1 = make_raw(message="ValueError: test")
        e2 = make_raw(message="ValueError: test")

        await svc.process(e1)
        result = await svc.process(e2)

        assert result is None  # deduped
        assert len(bus.published) == 1

    @pytest.mark.asyncio
    async def test_different_message_publishes_separately(self, svc_and_bus):
        svc, bus = svc_and_bus
        await svc.process(make_raw(message="ValueError: A"))
        await svc.process(make_raw(message="ValueError: B"))
        assert len(bus.published) == 2
