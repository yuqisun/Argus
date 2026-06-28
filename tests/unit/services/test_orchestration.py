"""Tests for orchestration service."""
import pytest
from argus.models.event import RawEvent
from argus.services.orchestration import PriorityScorer, Orchestrator


class TestPriorityScorer:
    @pytest.fixture
    def scorer(self):
        return PriorityScorer()

    def test_fatal_scores_higher_than_error(self, scorer):
        e1 = RawEvent(
            source="test", timestamp="t", raw_message="FATAL: system crash",
            service_name="api", host="h1", environment="prod",
        )
        e2 = RawEvent(
            source="test", timestamp="t", raw_message="ERROR: minor issue",
            service_name="api", host="h1", environment="prod",
        )
        assert scorer.score(e1) > scorer.score(e2)

    def test_returns_p0_to_p3(self, scorer):
        event = RawEvent(
            source="test", timestamp="t", raw_message="ERROR: test",
            service_name="api", host="h1", environment="prod",
        )
        priority = scorer.evaluate(event)
        assert priority in ("P0", "P1", "P2", "P3")

    def test_more_hosts_scores_higher(self, scorer):
        e1 = RawEvent(
            source="test", timestamp="t", raw_message="ERROR: x",
            service_name="api", host="h1", environment="prod",
        )
        e2 = RawEvent(
            source="test", timestamp="t", raw_message="ERROR: x",
            service_name="api", host="h1", environment="prod",
            metadata={"host_count": 10},
        )
        assert scorer.score(e2) > scorer.score(e1)

    def test_prod_scores_higher_than_dev(self, scorer):
        e1 = RawEvent(
            source="test", timestamp="t", raw_message="ERROR: x",
            service_name="api", host="h1", environment="prod",
        )
        e2 = RawEvent(
            source="test", timestamp="t", raw_message="ERROR: x",
            service_name="api", host="h1", environment="dev",
        )
        assert scorer.score(e1) > scorer.score(e2)
