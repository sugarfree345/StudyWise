"""OpenAI 风格适配器。

覆盖面最广：OpenAI 本体，以及 DeepSeek、通义千问（DashScope 兼容模式）、
Kimi/Moonshot、智谱 GLM，还有本地 Ollama / vLLM / LM Studio —— 它们都暴露
OpenAI 兼容端点，只需换 base_url。

工具调用：流式增量里累积 tool_calls，本轮结束后执行工具，把结果作为 role=tool
消息回给模型；图片无法塞进 tool 消息，改用随后的一条 user 消息（image_url）承载。
"""

import json
from collections.abc import AsyncIterator
from urllib.parse import urlparse

from openai import AsyncOpenAI

from app.services.llm.base import MAX_TOOL_ROUNDS, ChatMessage, ToolRunner, Usage
from app.services.llm.profiles import ModelProfile
from app.services.llm.tools import ToolResult, ToolSpec, openai_tools


# OpenAI 的 GPT-5 / o 系列（推理模型）弃用 max_tokens，改用 max_completion_tokens；
# DeepSeek、Qwen、Ollama、gpt-4.x 等仍用 max_tokens。按模型名前缀区分。
_COMPLETION_TOKEN_PREFIXES = ("gpt-5", "o1", "o3", "o4")


def _token_limit_kwarg(model_id: str, max_tokens: int) -> dict:
    if model_id.lower().startswith(_COMPLETION_TOKEN_PREFIXES):
        return {"max_completion_tokens": max_tokens}
    return {"max_tokens": max_tokens}


def _is_official_openai_endpoint(base_url: str | None) -> bool:
    """只对 OpenAI 官方端点发送其专有缓存参数。

    DeepSeek、Ollama 等同样使用 Chat Completions 的请求外形，但未必接受
    ``prompt_cache_key``，因此不能仅按 provider 风格判断。
    """
    endpoint = base_url or "https://api.openai.com/v1"
    return urlparse(endpoint).hostname == "api.openai.com"


def _image_followup(tool_call_id: str, result: ToolResult) -> dict | None:
    """OpenAI 的 tool 消息只能是纯文本，图片改用随后的一条 user 消息回传。"""
    if result.image is None:
        return None
    data_url = f"data:{result.image.mime_type};base64,{result.image.as_base64()}"
    return {
        "role": "user",
        "content": [
            {"type": "text", "text": f"（上一步工具返回的图片，tool_call_id={tool_call_id}）"},
            {"type": "image_url", "image_url": {"url": data_url}},
        ],
    }


class OpenAIProvider:
    def __init__(self, profile: ModelProfile):
        self._profile = profile
        self._client = AsyncOpenAI(
            api_key=profile.api_key or "not-needed",  # 本地模型常常不校验 key
            base_url=profile.base_url,
        )

    async def stream_chat(
        self,
        *,
        system: str,
        messages: list[ChatMessage],
        tools: list[ToolSpec] | None = None,
        tool_runner: ToolRunner | None = None,
        usage: Usage | None = None,
        prompt_cache_key: str | None = None,
    ) -> AsyncIterator[str]:
        # OpenAI 风格：system 是消息数组里的第一条
        conversation: list[dict] = [{"role": "system", "content": system}, *messages]
        tool_defs = openai_tools(tools) if tools else None

        for _ in range(MAX_TOOL_ROUNDS):
            kwargs: dict = {
                "model": self._profile.model_id,
                "messages": conversation,
                "stream": True,
                **_token_limit_kwarg(self._profile.model_id, self._profile.max_tokens),
            }
            if tool_defs:
                kwargs["tools"] = tool_defs
            if usage is not None:
                # 流式默认不返回用量，需显式开启；末尾会多一个带 usage 的 chunk。
                kwargs["stream_options"] = {"include_usage": True}
            # 同一个文档会话复用同一个稳定键，帮助 OpenAI 路由到持有相同
            # 提示前缀缓存的机器。兼容端点不一定识别这些字段，故严格限于
            # api.openai.com。gpt-5.5 只支持 24h 的扩展缓存保留策略。
            if prompt_cache_key and _is_official_openai_endpoint(self._profile.base_url):
                kwargs["prompt_cache_key"] = prompt_cache_key
                if self._profile.model_id.lower().startswith("gpt-5.5"):
                    kwargs["prompt_cache_retention"] = "24h"
            stream = await self._client.chat.completions.create(**kwargs)

            content_parts: list[str] = []
            calls: dict[int, dict] = {}
            async for chunk in stream:
                chunk_usage = getattr(chunk, "usage", None)
                if usage is not None and chunk_usage is not None:
                    details = getattr(chunk_usage, "prompt_tokens_details", None)
                    cached = getattr(details, "cached_tokens", 0) or 0
                    usage.add(
                        chunk_usage.prompt_tokens,
                        chunk_usage.completion_tokens,
                        cached,
                    )
                if not chunk.choices:
                    continue
                delta = chunk.choices[0].delta
                if delta.content:
                    content_parts.append(delta.content)
                    yield delta.content
                for call in delta.tool_calls or []:
                    slot = calls.setdefault(
                        call.index, {"id": "", "name": "", "arguments": ""}
                    )
                    if call.id:
                        slot["id"] = call.id
                    if call.function and call.function.name:
                        slot["name"] = call.function.name
                    if call.function and call.function.arguments:
                        slot["arguments"] += call.function.arguments

            if not calls or tool_runner is None:
                return

            ordered = [calls[index] for index in sorted(calls)]
            conversation.append(
                {
                    "role": "assistant",
                    "content": "".join(content_parts) or None,
                    "tool_calls": [
                        {
                            "id": call["id"],
                            "type": "function",
                            "function": {
                                "name": call["name"],
                                "arguments": call["arguments"] or "{}",
                            },
                        }
                        for call in ordered
                    ],
                }
            )

            followups: list[dict] = []
            for call in ordered:
                try:
                    arguments = json.loads(call["arguments"] or "{}")
                except json.JSONDecodeError:
                    arguments = {}
                result = tool_runner(call["name"], arguments)
                conversation.append(
                    {
                        "role": "tool",
                        "tool_call_id": call["id"],
                        "content": result.text or "(no output)",
                    }
                )
                followup = _image_followup(call["id"], result)
                if followup is not None:
                    followups.append(followup)
            conversation.extend(followups)

        yield "\n\n（工具调用轮次过多，已停止。）"
