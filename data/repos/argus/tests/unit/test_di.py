"""Tests for dependency injection container."""
import pytest
from argus.di import Container
from argus.interfaces.llm import LLMClient
from argus.interfaces.fingerprinter import Fingerprinter


class FakeLLM:
    async def chat(self, messages, *, model=None, max_tokens=4096, temperature=0.1):
        return "fake"
    async def chat_stream(self, messages, *, model=None, max_tokens=4096):
        yield "fake"


class TestContainer:
    def test_register_and_get(self):
        c = Container()
        c.register(LLMClient, FakeLLM())
        result = c.get(LLMClient)
        assert isinstance(result, FakeLLM)

    def test_get_unregistered_raises(self):
        c = Container()
        with pytest.raises(KeyError):
            c.get(LLMClient)

    def test_register_overwrites(self):
        c = Container()
        c.register(LLMClient, FakeLLM())
        c.register(LLMClient, FakeLLM())
        assert c.get(LLMClient) is not None

    def test_bootstrap_registers_llm_and_fingerprinter(self):
        from argus.di import bootstrap
        config = {
            "llm": {
                "base_url": "https://api.deepseek.com",
                "api_key": "test",
                "models": {"strong": "deepseek-chat"},
            },
            "fingerprinter": {"stack_top_n": 5},
        }
        container = bootstrap(config)
        llm = container.get(LLMClient)
        fp = container.get(Fingerprinter)
        assert llm is not None
        assert fp is not None
