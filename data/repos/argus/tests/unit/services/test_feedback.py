"""Tests for feedback service."""
import pytest
from argus.services.feedback import FeedbackService, Feedback


class FakePool:
    def __init__(self):
        self.executed: list[str] = []
        self.rows: list[dict] = []

    async def execute(self, sql, *args):
        self.executed.append(sql)

    async def fetch(self, sql, *args):
        return self.rows


class TestFeedback:
    def test_valid_feedback_type(self):
        fb = Feedback(event_id="evt-1", feedback_type="accurate")
        assert fb.feedback_type == "accurate"

    def test_invalid_feedback_type_raises(self):
        with pytest.raises(ValueError, match="Invalid feedback_type"):
            Feedback(event_id="evt-1", feedback_type="bad_type")


class TestFeedbackService:
    @pytest.fixture
    def svc(self):
        return FeedbackService(FakePool())

    @pytest.mark.asyncio
    async def test_record_feedback_writes_to_db(self, svc):
        fb = Feedback(
            event_id="evt-1",
            feedback_type="accurate",
            comment="root cause was correct",
        )
        await svc.record(fb)
        assert len(svc.db.executed) > 0

    @pytest.mark.asyncio
    async def test_get_for_event_returns_list(self, svc):
        svc.db.rows = [
            {"event_id": "evt-1", "feedback_type": "accurate", "comment": "good", "submitted_by": ""},
        ]
        result = await svc.get_for_event("evt-1")
        assert len(result) == 1
        assert result[0].feedback_type == "accurate"
