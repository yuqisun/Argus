"""Tests for fingerprint implementations."""
import pytest
from argus.models.event import RawEvent
from argus.interfaces.fingerprinter import Fingerprinter
from argus.implementations.fingerprint.stack_message_fp import StackMessageFingerprinter


def make_event(message: str, stack: str | None = None) -> RawEvent:
    return RawEvent(
        source="sentry",
        timestamp="2026-06-28T10:00:00Z",
        raw_message=message,
        service_name="api",
        host="prod-1",
        environment="prod",
        stack_trace=stack,
    )


class TestStackMessageFingerprinter:
    @pytest.fixture
    def fp(self):
        return StackMessageFingerprinter(stack_top_n=5)

    def test_implements_protocol(self, fp):
        assert isinstance(fp, Fingerprinter)

    def test_same_stack_same_fingerprint(self, fp):
        stack = 'File "app.py", line 10, in foo\n  raise ValueError("bad value")'
        f1 = fp.fingerprint(make_event("ValueError: bad value", stack))
        f2 = fp.fingerprint(make_event("ValueError: bad value", stack))
        assert f1.hash == f2.hash
        assert fp.is_same_group(f1, f2)

    def test_different_exception_different_fingerprint(self, fp):
        f1 = fp.fingerprint(make_event("ValueError: bad", "File a.py, line 1"))
        f2 = fp.fingerprint(make_event("KeyError: missing", "File b.py, line 5"))
        assert f1.hash != f2.hash
        assert not fp.is_same_group(f1, f2)

    def test_normalizes_numbers(self, fp):
        f1 = fp.fingerprint(make_event("Timeout on host 10.0.0.5", "File a.py"))
        f2 = fp.fingerprint(make_event("Timeout on host 10.0.0.99", "File a.py"))
        assert f1.hash == f2.hash

    def test_normalizes_uuids(self, fp):
        f1 = fp.fingerprint(make_event(
            "Error 550e8400-e29b-41d4-a716-446655440000",
            "File a.py, line 1"
        ))
        f2 = fp.fingerprint(make_event(
            "Error 12345678-1234-1234-1234-123456789abc",
            "File a.py, line 1"
        ))
        assert f1.hash == f2.hash

    def test_no_stack_uses_message(self, fp):
        f1 = fp.fingerprint(make_event("Disk full on /dev/sda1"))
        f2 = fp.fingerprint(make_event("Disk full on /dev/sda1"))
        assert f1.hash == f2.hash
