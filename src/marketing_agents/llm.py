from __future__ import annotations

import json
import os
from abc import ABC, abstractmethod
from collections import deque
from dataclasses import dataclass, field
from datetime import UTC, datetime
from time import perf_counter
from typing import Any, Generic, TypeVar

from anthropic import AsyncAnthropic
from pydantic import BaseModel, ValidationError


ResponseT = TypeVar("ResponseT", bound=BaseModel)


class LLMConfigurationError(RuntimeError):
    """Raised when an LLM provider is missing required configuration."""


class LLMProviderError(RuntimeError):
    """Raised when an LLM provider call fails."""


class LLMResponseValidationError(LLMProviderError):
    """Raised when a structured provider response fails schema validation."""


@dataclass(frozen=True)
class LLMUsage:
    input_tokens: int = 0
    output_tokens: int = 0
    cache_creation_input_tokens: int = 0
    cache_read_input_tokens: int = 0
    cost_usd: float | None = None


@dataclass(frozen=True)
class LLMResult(Generic[ResponseT]):
    text: str
    parsed: ResponseT | None
    model: str
    request_id: str
    stop_reason: str
    prompt_version: str
    started_at: datetime
    completed_at: datetime
    latency_ms: int
    usage: LLMUsage


@dataclass(frozen=True)
class LLMRequest:
    system_prompt: str
    user_prompt: str
    response_schema: type[BaseModel] | None
    temperature: float | None
    max_tokens: int | None
    prompt_version: str


class LLMProvider(ABC):
    @abstractmethod
    async def generate(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
        response_schema: type[ResponseT] | None = None,
        temperature: float | None = None,
        max_tokens: int | None = None,
        prompt_version: str = "unversioned",
    ) -> LLMResult[ResponseT]:
        raise NotImplementedError


@dataclass(frozen=True)
class ClaudeSettings:
    api_key: str
    model: str
    max_tokens: int = 4096
    timeout_seconds: float = 60.0
    max_retries: int = 2
    temperature: float = 0.2

    @classmethod
    def from_env(cls) -> ClaudeSettings:
        settings = cls(
            api_key=os.getenv("ANTHROPIC_API_KEY", "").strip(),
            model=os.getenv("ANTHROPIC_MODEL", "").strip(),
            max_tokens=_positive_int("LLM_MAX_TOKENS", 4096),
            timeout_seconds=_positive_float("LLM_TIMEOUT_SECONDS", 60.0),
            max_retries=_nonnegative_int("LLM_MAX_RETRIES", 2),
            temperature=_temperature("LLM_TEMPERATURE", 0.2),
        )
        if not settings.api_key:
            raise LLMConfigurationError("ANTHROPIC_API_KEY is required for ClaudeProvider.")
        if not settings.model:
            raise LLMConfigurationError("ANTHROPIC_MODEL is required for ClaudeProvider.")
        return settings


class ClaudeProvider(LLMProvider):
    def __init__(
        self,
        settings: ClaudeSettings | None = None,
        *,
        client: Any | None = None,
    ) -> None:
        self.settings = settings or ClaudeSettings.from_env()
        if client is None:
            if not self.settings.api_key:
                raise LLMConfigurationError("ANTHROPIC_API_KEY is required for ClaudeProvider.")
            client = AsyncAnthropic(
                api_key=self.settings.api_key,
                timeout=self.settings.timeout_seconds,
                max_retries=self.settings.max_retries,
            )
        self.client = client

    async def generate(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
        response_schema: type[ResponseT] | None = None,
        temperature: float | None = None,
        max_tokens: int | None = None,
        prompt_version: str = "unversioned",
    ) -> LLMResult[ResponseT]:
        started_at = datetime.now(UTC)
        started = perf_counter()
        parameters: dict[str, Any] = {
            "model": self.settings.model,
            "max_tokens": max_tokens or self.settings.max_tokens,
            "temperature": self.settings.temperature if temperature is None else temperature,
            "system": system_prompt,
            "messages": [{"role": "user", "content": user_prompt}],
        }
        if response_schema is not None:
            parameters["output_config"] = {
                "format": {
                    "type": "json_schema",
                    "schema": response_schema.model_json_schema(),
                }
            }

        try:
            response = await self.client.messages.create(**parameters)
        except Exception as exc:
            raise LLMProviderError(
                f"Claude generation failed with {type(exc).__name__}: {exc}"
            ) from exc

        completed_at = datetime.now(UTC)
        text = "".join(
            block.text for block in response.content if getattr(block, "type", "") == "text"
        )
        parsed: ResponseT | None = None
        if response_schema is not None:
            try:
                parsed = response_schema.model_validate_json(text)
            except (ValidationError, ValueError, json.JSONDecodeError) as exc:
                raise LLMResponseValidationError(
                    f"Claude returned invalid {response_schema.__name__} output."
                ) from exc

        usage = response.usage
        return LLMResult(
            text=text,
            parsed=parsed,
            model=str(response.model),
            request_id=str(response.id),
            stop_reason=str(response.stop_reason or ""),
            prompt_version=prompt_version,
            started_at=started_at,
            completed_at=completed_at,
            latency_ms=round((perf_counter() - started) * 1000),
            usage=LLMUsage(
                input_tokens=int(getattr(usage, "input_tokens", 0) or 0),
                output_tokens=int(getattr(usage, "output_tokens", 0) or 0),
                cache_creation_input_tokens=int(
                    getattr(usage, "cache_creation_input_tokens", 0) or 0
                ),
                cache_read_input_tokens=int(
                    getattr(usage, "cache_read_input_tokens", 0) or 0
                ),
            ),
        )


class FakeLLMProvider(LLMProvider):
    """Deterministic provider for unit tests and offline development."""

    def __init__(self, responses: list[str | dict[str, Any] | BaseModel]) -> None:
        self.responses = deque(responses)
        self.requests: list[LLMRequest] = []

    async def generate(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
        response_schema: type[ResponseT] | None = None,
        temperature: float | None = None,
        max_tokens: int | None = None,
        prompt_version: str = "unversioned",
    ) -> LLMResult[ResponseT]:
        if not self.responses:
            raise LLMProviderError("FakeLLMProvider has no queued responses.")
        started_at = datetime.now(UTC)
        self.requests.append(
            LLMRequest(
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                response_schema=response_schema,
                temperature=temperature,
                max_tokens=max_tokens,
                prompt_version=prompt_version,
            )
        )
        value = self.responses.popleft()
        parsed: ResponseT | None = None
        if isinstance(value, BaseModel):
            text = value.model_dump_json()
        elif isinstance(value, dict):
            text = json.dumps(value)
        else:
            text = value
        if response_schema is not None:
            try:
                parsed = response_schema.model_validate_json(text)
            except (ValidationError, ValueError, json.JSONDecodeError) as exc:
                raise LLMResponseValidationError(
                    f"Fake response is invalid for {response_schema.__name__}."
                ) from exc
        completed_at = datetime.now(UTC)
        return LLMResult(
            text=text,
            parsed=parsed,
            model="fake",
            request_id=f"fake-{len(self.requests)}",
            stop_reason="end_turn",
            prompt_version=prompt_version,
            started_at=started_at,
            completed_at=completed_at,
            latency_ms=0,
            usage=LLMUsage(),
        )


def create_llm_provider(provider: str | None = None) -> LLMProvider:
    selected = (provider or os.getenv("LLM_PROVIDER", "claude")).strip().lower()
    if selected == "claude":
        return ClaudeProvider()
    raise LLMConfigurationError(f"Unsupported LLM provider: {selected}")


def _positive_int(name: str, default: int) -> int:
    value = int(os.getenv(name, str(default)))
    if value <= 0:
        raise LLMConfigurationError(f"{name} must be greater than zero.")
    return value


def _nonnegative_int(name: str, default: int) -> int:
    value = int(os.getenv(name, str(default)))
    if value < 0:
        raise LLMConfigurationError(f"{name} cannot be negative.")
    return value


def _positive_float(name: str, default: float) -> float:
    value = float(os.getenv(name, str(default)))
    if value <= 0:
        raise LLMConfigurationError(f"{name} must be greater than zero.")
    return value


def _temperature(name: str, default: float) -> float:
    value = float(os.getenv(name, str(default)))
    if not 0 <= value <= 1:
        raise LLMConfigurationError(f"{name} must be between 0 and 1.")
    return value
