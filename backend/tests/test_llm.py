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
            SimpleNamespace(
                choices=[SimpleNamespace(delta=SimpleNamespace(content="A", tool_calls=None))]
            ),
            SimpleNamespace(
                choices=[SimpleNamespace(delta=SimpleNamespace(content=None, tool_calls=None))]
            ),
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

    async def test_openai_sends_cache_controls_only_to_official_endpoint(self):
        stream = async_values(
            SimpleNamespace(
                choices=[SimpleNamespace(delta=SimpleNamespace(content="A", tool_calls=None))]
            )
        )
        create = AsyncMock(return_value=stream)
        provider = OpenAIProvider.__new__(OpenAIProvider)
        provider._profile = ModelProfile.model_construct(
            name="openai", style="openai", model_id="gpt-5.5", api_key="key",
            base_url="https://api.openai.com/v1", max_tokens=123,
        )
        provider._client = SimpleNamespace(
            chat=SimpleNamespace(completions=SimpleNamespace(create=create))
        )

        _ = [
            text async for text in provider.stream_chat(
                system="s", messages=[{"role": "user", "content": "q"}],
                prompt_cache_key="studywise:test",
            )
        ]

        self.assertEqual(create.await_args.kwargs["prompt_cache_key"], "studywise:test")
        self.assertEqual(create.await_args.kwargs["prompt_cache_retention"], "24h")

    async def test_compatible_endpoint_does_not_receive_openai_cache_controls(self):
        stream = async_values(
            SimpleNamespace(
                choices=[SimpleNamespace(delta=SimpleNamespace(content="A", tool_calls=None))]
            )
        )
        create = AsyncMock(return_value=stream)
        provider = OpenAIProvider.__new__(OpenAIProvider)
        provider._profile = ModelProfile.model_construct(
            name="local", style="openai", model_id="gpt-5.5", api_key="key",
            base_url="http://localhost:11434/v1", max_tokens=123,
        )
        provider._client = SimpleNamespace(
            chat=SimpleNamespace(completions=SimpleNamespace(create=create))
        )

        _ = [
            text async for text in provider.stream_chat(
                system="s", messages=[{"role": "user", "content": "q"}],
                prompt_cache_key="studywise:test",
            )
        ]

        self.assertNotIn("prompt_cache_key", create.await_args.kwargs)
        self.assertNotIn("prompt_cache_retention", create.await_args.kwargs)

    async def test_luna_uses_none_reasoning_effort_when_tools_are_enabled(self):
        from app.services.llm.tools import ToolSpec

        stream = async_values(
            SimpleNamespace(
                choices=[SimpleNamespace(delta=SimpleNamespace(content="A", tool_calls=None))]
            )
        )
        create = AsyncMock(return_value=stream)
        provider = OpenAIProvider.__new__(OpenAIProvider)
        provider._profile = ModelProfile.model_construct(
            name="luna", style="openai", model_id="gpt-5.6-luna", api_key="key",
            base_url="https://api.openai.com/v1", max_tokens=123,
        )
        provider._client = SimpleNamespace(
            chat=SimpleNamespace(completions=SimpleNamespace(create=create))
        )

        _ = [
            text
            async for text in provider.stream_chat(
                system="s",
                messages=[{"role": "user", "content": "q"}],
                tools=[ToolSpec(name="get_text", description="d", parameters={})],
            )
        ]

        self.assertEqual(create.await_args.kwargs["reasoning_effort"], "none")

    async def test_anthropic_request_uses_top_level_system(self):
        stream = MagicMock()
        stream.__aenter__ = AsyncMock(return_value=stream)
        stream.__aexit__ = AsyncMock(return_value=None)
        stream.text_stream = async_values("A", "B")
        # 无工具：最终消息不含 tool_use，循环一轮即收尾
        stream.get_final_message = AsyncMock(
            return_value=SimpleNamespace(content=[], stop_reason="end_turn")
        )
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


class ToolLoopTests(unittest.IsolatedAsyncioTestCase):
    """验证「模型→工具→模型」的多轮闭环：工具结果被回喂后，模型再产出最终文本。"""

    async def test_openai_runs_tool_then_finishes(self):
        from app.services.llm.base import Usage
        from app.services.llm.tools import ToolResult, ToolSpec

        # 每轮末尾带一个 usage chunk（choices 为空），provider 应累加两轮用量；
        # prompt_tokens_details.cached_tokens 是缓存命中的子集，也应累加
        usage_chunk = lambda p, c, cached=0: SimpleNamespace(  # noqa: E731
            choices=[],
            usage=SimpleNamespace(
                prompt_tokens=p,
                completion_tokens=c,
                prompt_tokens_details=SimpleNamespace(cached_tokens=cached),
            ),
        )
        # 第一轮：模型要求调用工具；第二轮：拿到结果后输出文本
        round1 = async_values(
            SimpleNamespace(choices=[SimpleNamespace(delta=SimpleNamespace(
                content=None,
                tool_calls=[SimpleNamespace(
                    index=0, id="call_1",
                    function=SimpleNamespace(
                        name="get_page_content", arguments='{"page_number": 2}'
                    ),
                )],
            ))]),
            usage_chunk(10, 5, cached=4),
        )
        round2 = async_values(
            SimpleNamespace(choices=[SimpleNamespace(
                delta=SimpleNamespace(content="第2页讲的是X。", tool_calls=None)
            )]),
            usage_chunk(20, 8, cached=6),
        )
        create = AsyncMock(side_effect=[round1, round2])
        provider = OpenAIProvider.__new__(OpenAIProvider)
        provider._profile = profile("openai")
        provider._client = SimpleNamespace(
            chat=SimpleNamespace(completions=SimpleNamespace(create=create))
        )

        seen = []

        def runner(name, args):
            seen.append((name, args))
            return ToolResult.json({"markdown": "内容X"})

        spec = ToolSpec(name="get_page_content", description="d", parameters={})
        usage = Usage()
        result = [
            text
            async for text in provider.stream_chat(
                system="s",
                messages=[{"role": "user", "content": "第2页讲什么"}],
                tools=[spec],
                tool_runner=runner,
                usage=usage,
            )
        ]

        self.assertEqual(result, ["第2页讲的是X。"])
        self.assertEqual(seen, [("get_page_content", {"page_number": 2})])
        self.assertEqual(create.await_count, 2)
        # 两轮 token 累加：input 10+20，output 5+8，cached 4+6
        self.assertEqual((usage.input_tokens, usage.output_tokens), (30, 13))
        self.assertEqual(usage.total_tokens, 43)
        self.assertEqual(usage.cached_tokens, 10)
        self.assertEqual(create.await_args_list[0].kwargs["stream_options"],
                         {"include_usage": True})
        # 第二轮请求里应包含 assistant(tool_calls) 和 tool 结果两条消息
        second_messages = create.await_args_list[1].kwargs["messages"]
        roles = [m["role"] for m in second_messages]
        self.assertIn("tool", roles)
        tool_msg = next(m for m in second_messages if m["role"] == "tool")
        self.assertEqual(tool_msg["tool_call_id"], "call_1")

    async def test_anthropic_runs_tool_then_finishes(self):
        from app.services.llm.base import Usage
        from app.services.llm.tools import ToolResult, ToolSpec

        def make_stream(texts, final_content, usage_tokens):
            stream = MagicMock()
            stream.__aenter__ = AsyncMock(return_value=stream)
            stream.__aexit__ = AsyncMock(return_value=None)
            stream.text_stream = async_values(*texts)
            stream.get_final_message = AsyncMock(
                return_value=SimpleNamespace(
                    content=final_content,
                    stop_reason="end_turn",
                    usage=SimpleNamespace(
                        input_tokens=usage_tokens[0], output_tokens=usage_tokens[1]
                    ),
                )
            )
            return stream

        tool_use = SimpleNamespace(
            type="tool_use", id="tu_1", name="get_page_content",
            input={"page_number": 2},
        )
        tool_use.model_dump = lambda: {
            "type": "tool_use", "id": "tu_1", "name": "get_page_content",
            "input": {"page_number": 2},
        }
        round1 = make_stream([], [tool_use], (100, 20))       # 只要求调用工具
        round2 = make_stream(["第2页讲的是X。"], [], (150, 30))  # 拿到结果后输出文本
        create_stream = MagicMock(side_effect=[round1, round2])
        provider = AnthropicProvider.__new__(AnthropicProvider)
        provider._profile = profile("anthropic")
        provider._client = SimpleNamespace(
            messages=SimpleNamespace(stream=create_stream)
        )

        seen = []

        def runner(name, args):
            seen.append((name, args))
            return ToolResult.json({"markdown": "内容X"})

        spec = ToolSpec(name="get_page_content", description="d", parameters={})
        usage = Usage()
        result = [
            text
            async for text in provider.stream_chat(
                system="s",
                messages=[{"role": "user", "content": "第2页讲什么"}],
                tools=[spec],
                tool_runner=runner,
                usage=usage,
            )
        ]

        self.assertEqual(result, ["第2页讲的是X。"])
        self.assertEqual(seen, [("get_page_content", {"page_number": 2})])
        self.assertEqual(create_stream.call_count, 2)
        # 两轮 token 累加：input 100+150，output 20+30
        self.assertEqual((usage.input_tokens, usage.output_tokens), (250, 50))
        # 第二轮的 messages 末尾应是带 tool_result 的 user 消息
        second_messages = create_stream.call_args_list[1].kwargs["messages"]
        last = second_messages[-1]
        self.assertEqual(last["role"], "user")
        self.assertEqual(last["content"][0]["type"], "tool_result")
        self.assertEqual(last["content"][0]["tool_use_id"], "tu_1")


if __name__ == "__main__":
    unittest.main()
