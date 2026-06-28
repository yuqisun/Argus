"""Dependency injection container and bootstrap."""
from __future__ import annotations
from typing import Any, TypeVar
import structlog

logger = structlog.get_logger(__name__)

T = TypeVar("T")


class Container:
    """Minimal DI container — protocol → implementation mapping."""

    def __init__(self):
        self._registry: dict[type, Any] = {}

    def register(self, protocol: type, implementation: Any) -> None:
        self._registry[protocol] = implementation
        logger.debug("Registered", protocol=protocol.__name__)

    def get(self, protocol: type[T]) -> T:
        if protocol not in self._registry:
            raise KeyError(f"No implementation registered for {protocol.__name__}")
        return self._registry[protocol]


_container = Container()


def bootstrap(config: dict) -> Container:
    """Wire up all implementations from config. Returns the populated container."""
    from argus.implementations.llm.openai_client import OpenAILLMClient
    from argus.implementations.fingerprint.stack_message_fp import StackMessageFingerprinter
    from argus.interfaces.llm import LLMClient
    from argus.interfaces.fingerprinter import Fingerprinter

    llm_cfg = config.get("llm", {})
    llm = OpenAILLMClient(
        base_url=llm_cfg.get("base_url", "https://api.deepseek.com"),
        api_key=llm_cfg.get("api_key", ""),
        default_model=llm_cfg.get("models", {}).get("strong", "deepseek-chat"),
    )
    _container.register(LLMClient, llm)

    fp_cfg = config.get("fingerprinter", {})
    fingerprinter = StackMessageFingerprinter(
        stack_top_n=fp_cfg.get("stack_top_n", 5),
    )
    _container.register(Fingerprinter, fingerprinter)

    logger.info("Bootstrap complete", modules=list(_container._registry.keys()))
    return _container
