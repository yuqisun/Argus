"""Tests for LLM client implementations."""
import pytest
from unittest.mock import MagicMock, AsyncMock, patch
from argus.interfaces.llm import LLMClient
from argus.implementations.llm.openai_client import OpenAILLMClient


class TestOpenAILLMClient:
    @pytest.fixture
    def client(self):
        return OpenAILLMClient(
            base_url="https://api.deepseek.com",
            api_key="test-key",
            default_model="deepseek-chat",
        )

    def test_implements_protocol(self, client):
        assert isinstance(client, LLMClient)

    @pytest.mark.asyncio
    async def test_chat_returns_response(self, client):
        mock_msg = MagicMock(content="root cause found")
        mock_choice = MagicMock(message=mock_msg)
        mock_resp = MagicMock(choices=[mock_choice])

        with patch.object(
            client._client.chat.completions, "create",
            new_callable=AsyncMock, return_value=mock_resp,
        ):
            result = await client.chat([
                {"role": "user", "content": "analyze this error"}
            ])
            assert "root cause found" in result

    @pytest.mark.asyncio
    async def test_chat_stream_yields_chunks(self, client):
        mock_delta1 = MagicMock(content="chunk1")
        mock_delta2 = MagicMock(content="chunk2")
        mock_choice1 = MagicMock(delta=mock_delta1)
        mock_choice2 = MagicMock(delta=mock_delta2)
        mock_chunk1 = MagicMock(choices=[mock_choice1])
        mock_chunk2 = MagicMock(choices=[mock_choice2])

        async def mock_stream(**kwargs):
            yield mock_chunk1
            yield mock_chunk2

        # For streaming, create() returns an async generator — no await needed
        with patch.object(
            client._client.chat.completions, "create",
            new_callable=AsyncMock, return_value=mock_stream(),
        ):
            chunks = []
            async for chunk in client.chat_stream([{"role": "user", "content": "hi"}]):
                chunks.append(chunk)

            assert len(chunks) == 2
