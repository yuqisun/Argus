"""YAML config loading with env var interpolation."""
import os
import re
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, Field


class LLMConfig(BaseModel):
    base_url: str = "https://api.deepseek.com"
    api_key: str = ""
    models: dict[str, str] = Field(
        default_factory=lambda: {"cheap": "deepseek-chat", "strong": "deepseek-chat"}
    )
    limits: dict = Field(
        default_factory=lambda: {"daily_token_budget": 10_000_000, "max_concurrency": 5}
    )


class AppConfig(BaseModel):
    name: str = "argus"
    environment: str = "dev"


class RedisConfig(BaseModel):
    url: str = "redis://localhost:6379/0"


class DatabaseConfig(BaseModel):
    url: str = "postgresql+asyncpg://argus:argus_dev@localhost:5432/argus"


class Config(BaseModel):
    app: AppConfig = AppConfig()
    llm: LLMConfig = LLMConfig()
    database: DatabaseConfig = DatabaseConfig()
    redis: RedisConfig = RedisConfig()
    event_bus: dict[str, Any] = Field(default_factory=dict)
    code_search: dict[str, Any] = Field(default_factory=dict)
    notifiers: list[dict[str, Any]] = Field(default_factory=list)
    log_sources: list[dict[str, Any]] = Field(default_factory=list)
    owner_resolver: dict[str, Any] = Field(default_factory=dict)
    fingerprinter: dict[str, Any] = Field(default_factory=dict)

    @classmethod
    def from_yaml(cls, path: str | None = None) -> "Config":
        if path is None:
            path = os.getenv("ARGUS_CONFIG", "config/config.yaml")
        raw = Path(path).read_text(encoding="utf-8")
        raw = cls._interpolate_env(raw)
        data = yaml.safe_load(raw)
        return cls(**data)

    @staticmethod
    def _interpolate_env(text: str) -> str:
        pattern = re.compile(r'\$\{(\w+)(?::-(.*?))?\}')

        def _replacer(m: re.Match) -> str:
            var = m.group(1)
            default = m.group(2)
            return os.getenv(var, default if default is not None else "")

        return pattern.sub(_replacer, text)
