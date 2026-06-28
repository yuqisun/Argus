"""OpenAI-compatible LLM client (DeepSeek, GPT, Claude API, vLLM, Ollama)."""
from __future__ import annotations
from collections.abc import AsyncIterator
import structlog
from openai import AsyncOpenAI

logger = structlog.get_logger(__name__)


class OpenAILLMClient:
    """OpenAI SDK client — works with any OpenAI-compatible API.

    Default: DeepSeek. Switch to Claude/GPT/vLLM by changing base_url + api_key.
    """

    def __init__(
        self,
        base_url: str,
        api_key: str,
        default_model: str = "deepseek-chat",
        max_concurrency: int = 5,
    ):
        self.default_model = default_model
        self._client = AsyncOpenAI(base_url=base_url, api_key=api_key)

    async def chat(
        self,
        messages: list[dict[str, str]],
        *,
        model: str | None = None,
        max_tokens: int = 4096,
        temperature: float = 0.1,
    ) -> str:
        logger.debug("LLM chat", model=model or self.default_model, msg_count=len(messages))
        response = await self._client.chat.completions.create(
            model=model or self.default_model,
            messages=messages,
            max_tokens=max_tokens,
            temperature=temperature,
        )
        return response.choices[0].message.content or ""

    async def chat_stream(
        self,
        messages: list[dict[str, str]],
        *,
        model: str | None = None,
        max_tokens: int = 4096,
    ) -> AsyncIterator[str]:
        stream = await self._client.chat.completions.create(
            model=model or self.default_model,
            messages=messages,
            max_tokens=max_tokens,
            stream=True,
        )
        async for chunk in stream:
            content = chunk.choices[0].delta.content
            if content:
                yield content
