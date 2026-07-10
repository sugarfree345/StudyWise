import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from app.core.config import settings
from app.services.llm.anthropic_provider import AnthropicProvider
from app.services.llm.factory import get_provider
from app.services.llm.openai_provider import OpenAIProvider
from app.services.llm.profiles import ModelProfile, load_profiles


def profile(style: str = "openai") -> ModelProfile:
    return ModelProfile.model_construct(
        name="test",
        style=style,
        model_id="test-model",
        api_key="test-key",
        base_url=None,
        max_tokens=123,
    )


async def async_values(*values):
    for value in values:
        yield value


class FactoryTests(unittest.TestCase):
    def test_selects_openai_provider(self):
        with patch("app.services.llm.factory.OpenAIProvider") as provider:
            self.assertIs(get_provider(profile("openai")), provider.return_value)

    def test_selects_anthropic_provider(self):
        with patch("app.services.llm.factory.AnthropicProvider") as provider:
            self.assertIs(get_provider(profile("anthropic")), provider.return_value)

    def test_rejects_unknown_style(self):
        with self.assertRaisesRegex(ValueError, "不支持"):
            get_provider(profile("unknown"))


class ProfileTests(unittest.TestCase):
    def test_loads_profiles_and_rejects_duplicate_names(self):
        entries = [
            {
                "name": "same-name",
                "style": "openai",
                "model_id": "model-a",
            },
            {
                "name": "same-name",
                "style": "anthropic",
                "model_id": "model-b",
            },
        ]
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)
            (path / "models.json").write_text(json.dumps(entries), encoding="utf-8")
            with patch.object(settings, "data_dir", path):
                with self.assertRaisesRegex(ValueError, "名称不能重复"):
                    load_profiles()


class ProviderTests(unittest.IsolatedAsyncioTestCase):
    async def test_openai_request_uses_system_message(self):
        stream = async_values(
            SimpleNamespace(choices=[SimpleNamespace(delta=SimpleNamespace(content="A"))]),
            SimpleNamespace(choices=[SimpleNamespace(delta=SimpleNamespace(content=None))]),
        )
        create = AsyncMock(return_value=stream)
        provider = OpenAIProvider.__new__(OpenAIProvider)
        provider._profile = profile("openai")
        provider._client = SimpleNamespace(
            chat=SimpleNamespace(completions=SimpleNamespace(create=create))
        )

        result = [
            text
            async for text in provider.stream_chat(
                system="system text",
                messages=[{"role": "user", "content": "question"}],
            )
        ]

        self.assertEqual(result, ["A"])
        self.assertEqual(
            create.await_args.kwargs["messages"][0],
            {"role": "system", "content": "system text"},
        )

    async def test_anthropic_request_uses_top_level_system(self):
        stream = MagicMock()
        stream.__aenter__ = AsyncMock(return_value=stream)
        stream.__aexit__ = AsyncMock(return_value=None)
        stream.text_stream = async_values("A", "B")
        create_stream = MagicMock(return_value=stream)
        provider = AnthropicProvider.__new__(AnthropicProvider)
        provider._profile = profile("anthropic")
        provider._client = SimpleNamespace(
            messages=SimpleNamespace(stream=create_stream)
        )

        result = [
            text
            async for text in provider.stream_chat(
                system="system text",
                messages=[{"role": "user", "content": "question"}],
            )
        ]

        self.assertEqual(result, ["A", "B"])
        self.assertEqual(create_stream.call_args.kwargs["system"], "system text")
        self.assertEqual(
            create_stream.call_args.kwargs["messages"],
            [{"role": "user", "content": "question"}],
        )


if __name__ == "__main__":
    unittest.main()
