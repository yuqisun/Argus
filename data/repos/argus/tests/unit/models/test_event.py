import pytest
from argus.models.event import RawEvent, AnomalyEvent


class TestRawEvent:
    def test_parses_minimal_sentry_payload(self):
        data = {
            "source": "sentry",
            "timestamp": "2026-06-28T10:30:00Z",
            "raw_message": "ValueError: something broke",
            "stack_trace": 'File "app.py", line 42, in handle\n    raise ValueError("something broke")',
            "service_name": "api",
            "host": "prod-1",
            "environment": "prod",
            "metadata": {"sentry_event_id": "abc123"},
        }
        event = RawEvent(**data)
        assert event.source == "sentry"
        assert event.stack_trace is not None

    def test_stack_trace_is_optional(self):
        event = RawEvent(
            source="elk",
            timestamp="2026-06-28T10:30:00Z",
            raw_message="disk full",
            service_name="worker",
            host="prod-2",
            environment="prod",
        )
        assert event.stack_trace is None


class TestAnomalyEvent:
    def test_creates_from_raw_and_fingerprint(self):
        raw = RawEvent(
            source="sentry",
            timestamp="2026-06-28T10:30:00Z",
            raw_message="ValueError: x",
            stack_trace="File a.py, line 1",
            service_name="api",
            host="h1",
            environment="prod",
        )
        ae = AnomalyEvent(
            event_id="evt-001",
            fingerprint="fp-abc",
            raw_sample=raw,
            count=1,
            priority="P1",
            first_seen="2026-06-28T10:30:00Z",
            last_seen="2026-06-28T10:30:00Z",
        )
        assert ae.priority == "P1"
        assert ae.raw_sample.service_name == "api"
