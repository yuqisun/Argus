"""LLM Root Cause Analysis Agent — two-stage (candidate → verify)."""
from __future__ import annotations
import json
import re
from dataclasses import dataclass, field
import structlog
from argus.interfaces.llm import LLMClient
from argus.interfaces.code_search import CodeSearcher, CodeHit
from argus.models.event import RawEvent

logger = structlog.get_logger(__name__)


@dataclass
class RCAResult:
    event_id: str
    root_cause_type: str
    root_cause_summary: str
    file_path: str | None = None
    line_number: int | None = None
    diff_suggestion: str | None = None
    fix_suggestion: str | None = None
    confidence: str = "medium"
    evidence: list[str] = field(default_factory=list)


CLASSIFY_PROMPT = """Classify this error into exactly one category. Respond with ONLY the category name.

Categories:
- code_bug: exception in application code (ValueError, NullPointer, IndexError, etc.)
- data: bad upstream data (schema mismatch, null in unexpected field, value out of range)
- config: configuration or environment variable issue
- dependency: downstream service or database failure
- missing_file: required file or resource not found
- capacity: OOM, timeout, rate limit, connection pool exhausted

Error message: {message}
Stack trace: {stack}

Category:"""


STAGE1_PROMPT = """You are a root cause analysis agent. Analyze this error and propose 2-3 candidate root causes.

Error: {message}
Stack trace:
{stack}

Related code (from grep search):
{code_context}

For each candidate, provide:
1. What the root cause might be
2. Which file and line supports this hypothesis
3. Why this is the most likely explanation

Output in JSON format:
{{"candidates": [{{"description": "...", "file_path": "...", "line_number": N, "confidence_reason": "..."}}]}}
"""


STAGE2_PROMPT = """Verify each candidate root cause by checking against the actual code.

Candidate root causes:
{candidates}

Actual code context (verified):
{code_context}

For each candidate, state VERIFIED or REFUTED with reasoning. If all are refuted, say ALL_REFUTED.

Respond in JSON format:
{{"verification_results": [{{"candidate_index": 0, "verdict": "VERIFIED", "reason": "..."}}]}}
"""


DIFF_PROMPT = """Generate a unified diff patch to fix this bug.

File: {file_path}:{line_number}
Root cause: {root_cause}
Current code:
{code_snippet}

Provide ONLY the unified diff (```diff ... ```), no explanations.
"""


class RCAAgent:
    """Two-stage LLM root cause analysis agent."""

    def __init__(self, llm: LLMClient, searcher: CodeSearcher):
        self.llm = llm
        self.searcher = searcher

    async def classify(self, event: RawEvent) -> str:
        prompt = CLASSIFY_PROMPT.format(
            message=event.raw_message,
            stack=event.stack_trace or "no stack trace",
        )
        response = await self.llm.chat(
            [{"role": "user", "content": prompt}],
            max_tokens=50, temperature=0.0,
        )
        category = response.strip().lower()
        valid = {"code_bug", "data", "config", "dependency", "missing_file", "capacity"}
        return category if category in valid else "code_bug"

    async def analyze(self, event: RawEvent, *, repo: str, commit: str) -> RCAResult:
        category = await self.classify(event)
        logger.info("Root cause classified", category=category)

        if category == "code_bug":
            return await self._analyze_code_bug(event, repo, commit)
        else:
            return await self._analyze_non_code(event, category, repo, commit)

    async def _analyze_code_bug(self, event: RawEvent, repo: str, commit: str) -> RCAResult:
        file_hints = self._extract_file_hints(event.stack_trace)
        code_hits: list[CodeHit] = []
        if file_hints:
            exc_type = event.raw_message.split(':')[0] if ':' in event.raw_message else event.raw_message[:30]
            hits = await self.searcher.grep(repo, exc_type, commit=commit)
            code_hits.extend(hits[:5])

        code_context = "\n".join(
            f"{h.file_path}:{h.line_number}: {h.content}" for h in code_hits
        ) or "no code found"

        # Stage 1: Generate candidates
        stage1_response = await self.llm.chat(
            [{"role": "user", "content": STAGE1_PROMPT.format(
                message=event.raw_message,
                stack=event.stack_trace or "no stack",
                code_context=code_context,
            )}],
            max_tokens=1024, temperature=0.2,
        )

        # Stage 2: Verify
        stage2_response = await self.llm.chat(
            [{"role": "user", "content": STAGE2_PROMPT.format(
                candidates=stage1_response,
                code_context=code_context,
            )}],
            max_tokens=1024, temperature=0.1,
        )

        verified = "ALL_REFUTED" not in stage2_response
        confidence = "high" if verified and code_hits else "medium" if verified else "low"

        diff = None
        target_file = file_hints[0] if file_hints else (code_hits[0] if code_hits else None)
        if verified and target_file:
            diff = await self._generate_diff(stage2_response, target_file[0], target_file[1], repo, commit)

        return RCAResult(
            event_id="",
            root_cause_type="code_bug",
            root_cause_summary=stage2_response[:500],
            file_path=target_file[0] if target_file else None,
            line_number=target_file[1] if target_file else None,
            diff_suggestion=diff,
            confidence=confidence,
            evidence=[stage1_response[:200], stage2_response[:200]],
        )

    async def _analyze_non_code(self, event: RawEvent, category: str, repo: str, commit: str) -> RCAResult:
        prompt = f"Analyze this {category} error and suggest a fix action.\n\nError: {event.raw_message}\nStack: {event.stack_trace or 'N/A'}\n"
        response = await self.llm.chat(
            [{"role": "user", "content": prompt}],
            max_tokens=512, temperature=0.2,
        )
        return RCAResult(
            event_id="",
            root_cause_type=category,
            root_cause_summary=response[:500],
            fix_suggestion=response[:500],
            confidence="medium",
        )

    async def _generate_diff(self, root_cause: str, file_path: str, line_number: int, repo: str, commit: str) -> str:
        hits = await self.searcher.grep(repo, file_path, commit=commit)
        code_snippet = "\n".join(f"{h.file_path}:{h.line_number}: {h.content}" for h in hits[:20]) or "unavailable"
        response = await self.llm.chat(
            [{"role": "user", "content": DIFF_PROMPT.format(
                file_path=file_path, line_number=line_number,
                root_cause=root_cause[:300], code_snippet=code_snippet,
            )}],
            max_tokens=1024, temperature=0.1,
        )
        match = re.search(r'```diff\n(.*?)\n```', response, re.DOTALL)
        return match.group(1) if match else response[:500]

    def _extract_file_hints(self, stack_trace: str | None) -> list[tuple[str, int]]:
        if not stack_trace:
            return []
        hints = []
        for line in stack_trace.split('\n'):
            match = re.search(r'File\s+"([^"]+)",\s*line\s+(\d+)', line)
            if match:
                hints.append((match.group(1), int(match.group(2))))
        return hints
