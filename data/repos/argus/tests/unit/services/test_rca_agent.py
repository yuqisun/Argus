"""Tests for the RCA two-stage agent."""
import pytest
from unittest.mock import AsyncMock
from argus.models.event import RawEvent
from argus.services.rca_agent import RCAAgent, RCAResult


class FakeLLM:
    def __init__(self, responses=None):
        self.responses = responses or ["code_bug"]
        self.call_count = 0

    async def chat(self, messages, *, model=None, max_tokens=4096, temperature=0.1):
        resp = self.responses[self.call_count % len(self.responses)]
        self.call_count += 1
        return resp

    async def chat_stream(self, messages, *, model=None, max_tokens=4096):
        yield "streamed"


class FakeSearcher:
    def __init__(self, grep_results=None):
        self.grep_results = grep_results or []
        self.blame_results = {}

    async def grep(self, repo, pattern, *, commit, glob=None):
        from argus.interfaces.code_search import CodeHit
        return self.grep_results

    async def find_definition(self, repo, symbol, *, commit):
        return None

    async def get_call_graph(self, repo, function, *, commit, depth=2):
        return None

    async def blame(self, repo, file_path, line_number, *, commit):
        return self.blame_results.get(file_path, ("dev@test.com", commit))


def make_raw_event(message="ValueError: bad input", stack=None):
    return RawEvent(
        source="sentry", timestamp="2026-06-28T10:00:00Z",
        raw_message=message, service_name="api", host="h1",
        environment="prod",
        stack_trace=stack or 'File "app.py", line 42, in handle\n    raise ValueError("bad input")',
    )


class TestRCAAgent:
    @pytest.mark.asyncio
    async def test_classify_code_bug(self):
        llm = FakeLLM(["code_bug"])
        agent = RCAAgent(llm=llm, searcher=FakeSearcher())
        category = await agent.classify(make_raw_event())
        assert category == "code_bug"

    @pytest.mark.asyncio
    async def test_two_stage_analysis_returns_result(self):
        llm = FakeLLM([
            "code_bug",
            '{"candidates": [{"description": "null check", "file_path": "app.py", "line_number": 42}]}',
            '{"verification_results": [{"candidate_index": 0, "verdict": "VERIFIED", "reason": "confirmed"}]}',
        ])
        searcher = FakeSearcher(grep_results=[
            type("Hit", (), {"file_path": "app.py", "line_number": 42, "content": "result = process()", "context": []})()
        ])
        agent = RCAAgent(llm=llm, searcher=searcher)

        event = make_raw_event()
        result = await agent.analyze(event, repo="myproject", commit="abc123")

        assert isinstance(result, RCAResult)
        assert result.root_cause_type == "code_bug"
        assert result.confidence in ("high", "medium", "low")

    @pytest.mark.asyncio
    async def test_generate_diff_returns_patch(self):
        agent = RCAAgent(llm=FakeLLM(["```diff\n-old\n+new\n```"]), searcher=FakeSearcher())
        diff = await agent._generate_diff(
            root_cause="Null check missing",
            file_path="app.py", line_number=42,
            repo="myproject", commit="abc123",
        )
        assert "-old" in diff or "```diff" in diff
