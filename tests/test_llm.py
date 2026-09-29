from __future__ import annotations

import os
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

from pydantic import BaseModel

from src.marketing_agents.llm import (
    ClaudeProvider,
    ClaudeSettings,
    FakeLLMProvider,
    LLMConfigurationError,
    LLMProviderError,
    LLMResponseValidationError,
)
from src.marketing_agents.prompts import PromptRenderError, PromptTemplate



class ArticlePlan(BaseModel):
    title: str
    sections: list[str]


def response(text: str):
    return SimpleNamespace(
        id="msg_test",
        model="claude-test-model",
        stop_reason="end_turn",
        content=[SimpleNamespace(type="text", text=text)],
        usage=SimpleNamespace(
            input_tokens=12,
            output_tokens=8,
            cache_creation_input_tokens=3,
            cache_read_input_tokens=2,
        ),
    )


class ClaudeSettingsTests(unittest.TestCase):
    def test_requires_api_key_and_model(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            with self.assertRaisesRegex(LLMConfigurationError, "ANTHROPIC_API_KEY"):
                ClaudeSettings.from_env()

    def test_reads_and_validates_environment(self) -> None:
        environment = {
            "ANTHROPIC_API_KEY": "test-key",
            "ANTHROPIC_MODEL": "claude-test-model",
            "LLM_MAX_TOKENS": "2048",
            "LLM_TIMEOUT_SECONDS": "30",
            "LLM_MAX_RETRIES": "4",
            "LLM_TEMPERATURE": "0.4",
        }
        with patch.dict(os.environ, environment, clear=True):
            settings = ClaudeSettings.from_env()

        self.assertEqual(settings.max_tokens, 2048)
        self.assertEqual(settings.timeout_seconds, 30)
        self.assertEqual(settings.max_retries, 4)
        self.assertEqual(settings.temperature, 0.4)


class ClaudeProviderTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.client = Mock()
        self.client.messages.create = AsyncMock()
        self.settings = ClaudeSettings(
            api_key="test-key",
            model="claude-test-model",
            max_tokens=1024,
            timeout_seconds=12,
            max_retries=2,
            temperature=0.2,
        )

    async def test_structured_output_is_validated_and_usage_is_returned(self) -> None:
        self.client.messages.create.return_value = response(
            '{"title":"AOSP boundaries","sections":["System","Vendor"]}'
        )
        provider = ClaudeProvider(self.settings, client=self.client)

        result = await provider.generate(
            system_prompt="You are a strategist.",
            user_prompt="Create a plan.",
            response_schema=ArticlePlan,
            prompt_version="strategist-v1",
        )

        self.assertEqual(result.parsed.title, "AOSP boundaries")
        self.assertEqual(result.usage.input_tokens, 12)
        self.assertEqual(result.usage.cache_read_input_tokens, 2)
        self.assertEqual(result.prompt_version, "strategist-v1")
        parameters = self.client.messages.create.await_args.kwargs
        self.assertEqual(parameters["model"], "claude-test-model")
        self.assertEqual(parameters["output_config"]["format"]["type"], "json_schema")
        self.assertEqual(parameters["messages"][0]["role"], "user")

    async def test_invalid_structured_output_has_explicit_error(self) -> None:
        self.client.messages.create.return_value = response('{"title": 42}')
        provider = ClaudeProvider(self.settings, client=self.client)

        with self.assertRaises(LLMResponseValidationError):
            await provider.generate(
                system_prompt="System",
                user_prompt="User",
                response_schema=ArticlePlan,
            )

    async def test_provider_errors_are_wrapped(self) -> None:
        self.client.messages.create.side_effect = TimeoutError("timed out")
        provider = ClaudeProvider(self.settings, client=self.client)

        with self.assertRaisesRegex(LLMProviderError, "TimeoutError"):
            await provider.generate(system_prompt="System", user_prompt="User")

    async def test_sdk_receives_timeout_and_retry_configuration(self) -> None:
        sdk_client = Mock()
        sdk_client.messages.create = AsyncMock(return_value=response("Text"))
        with patch("src.marketing_agents.llm.AsyncAnthropic", return_value=sdk_client) as sdk:
            provider = ClaudeProvider(self.settings)
            await provider.generate(system_prompt="System", user_prompt="User")

        sdk.assert_called_once_with(api_key="test-key", timeout=12, max_retries=2)


class FakeProviderTests(unittest.IsolatedAsyncioTestCase):
    async def test_fake_provider_is_deterministic_and_records_request(self) -> None:
        provider = FakeLLMProvider(
            [{"title": "Offline plan", "sections": ["One", "Two"]}]
        )

        result = await provider.generate(
            system_prompt="System",
            user_prompt="User",
            response_schema=ArticlePlan,
            temperature=0.1,
            prompt_version="test-v1",
        )

        self.assertEqual(result.parsed.title, "Offline plan")
        self.assertEqual(provider.requests[0].temperature, 0.1)
        self.assertEqual(provider.requests[0].prompt_version, "test-v1")

    async def test_fake_provider_fails_when_queue_is_empty(self) -> None:
        provider = FakeLLMProvider([])
        with self.assertRaisesRegex(LLMProviderError, "no queued responses"):
            await provider.generate(system_prompt="System", user_prompt="User")


class PromptTemplateTests(unittest.TestCase):
    def test_prompt_has_stable_versioned_identifier(self) -> None:
        prompt = PromptTemplate(
            name="writer",
            version="v1",
            system="Write grounded content.",
            user_template="Write about {topic}.",
        )

        self.assertEqual(prompt.identifier, "writer:v1")
        self.assertEqual(prompt.render_user(topic="AOSP"), "Write about AOSP.")

    def test_missing_context_has_explicit_error(self) -> None:
        prompt = PromptTemplate(
            name="writer", version="v1", system="System", user_template="{topic}"
        )
        with self.assertRaisesRegex(PromptRenderError, "topic"):
            prompt.render_user()



if __name__ == "__main__":
    unittest.main()
