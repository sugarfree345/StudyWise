"""OpenAI 官方 Responses API 适配器。

仅用于 ``api.openai.com``：使用 typed streaming events、Responses function
items 与多模态 input items。对话历史仍由 StudyWise 管理，因此请求显式设置
``store=False``；推理模型同时取回 encrypted reasoning items，供一次用户提问中
的后续工具轮次继续使用。
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from typing import Any

from openai import AsyncOpenAI

from app.services.llm.base import MAX_TOOL_ROUNDS, ChatMessage, ToolRunner, Usage
from app.services.llm.profiles import ModelProfile
from app.services.llm.tools import ToolResult, ToolSpec


def _responses_tools(specs: list[ToolSpec] | None) -> list[dict] | None:
    if not specs:
        return None
    return [
        {
            "type": "function",
            "name": spec.name,
            "description": spec.description,
            "parameters": spec.parameters,
            "strict": False,
        }
        for spec in specs
    ]


def _item_value(item: Any, name: str, default: Any = None) -> Any:
    return item.get(name, default) if isinstance(item, dict) else getattr(item, name, default)


def _dump_item(item: Any) -> dict:
    if isinstance(item, dict):
        return dict(item)
    return item.model_dump(mode="json", exclude_none=True)


def _image_input(call_id: str, result: ToolResult) -> dict | None:
    if result.image is None:
        return None
    data_url = f"data:{result.image.mime_type};base64,{result.image.as_base64()}"
    return {
        "role": "user",
        "content": [
            {
                "type": "input_text",
                "text": f"（上一步函数工具返回的图片，call_id={call_id}）",
            },
            {
                "type": "input_image",
                "image_url": data_url,
                "detail": "auto",
            },
        ],
    }


class OpenAIResponsesProvider:
    def __init__(self, profile: ModelProfile):
        self._profile = profile
        self._client = AsyncOpenAI(
            api_key=profile.api_key,
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
        conversation: list[dict] = [dict(message) for message in messages]
        tool_defs = _responses_tools(tools)
        model_id = self._profile.model_id.lower()

        for _ in range(MAX_TOOL_ROUNDS):
            kwargs: dict = {
                "model": self._profile.model_id,
                "instructions": system,
                "input": conversation,
                "max_output_tokens": self._profile.max_tokens,
                "stream": True,
                # StudyWise 自己保存对话；不在 OpenAI 侧创建持久会话链。
                "store": False,
            }
            if tool_defs:
                kwargs["tools"] = tool_defs
            if prompt_cache_key:
                kwargs["prompt_cache_key"] = prompt_cache_key
                if model_id.startswith("gpt-5.5"):
                    kwargs["prompt_cache_retention"] = "24h"
            if model_id.startswith("gpt-5.6"):
                # 官方建议为 GPT-5.6 显式选择 effort；medium 是均衡起点。
                kwargs["reasoning"] = {"effort": "medium"}
            if model_id.startswith("gpt-5"):
                # store=False 时，工具轮次需回放加密推理 item 才能延续本轮推理。
                kwargs["include"] = ["reasoning.encrypted_content"]

            stream = await self._client.responses.create(**kwargs)
            completed = None
            async for event in stream:
                event_type = _item_value(event, "type", "")
                if event_type == "response.output_text.delta":
                    delta = _item_value(event, "delta", "")
                    if delta:
                        yield delta
                elif event_type == "response.completed":
                    completed = _item_value(event, "response")
                elif event_type in {"response.failed", "error"}:
                    response = _item_value(event, "response")
                    error = _item_value(event, "error") or _item_value(response, "error")
                    message = _item_value(error, "message", str(error))
                    raise RuntimeError(f"OpenAI Responses API 失败：{message}")

            if completed is None:
                raise RuntimeError("OpenAI Responses API 流已结束，但未收到 response.completed")

            response_usage = _item_value(completed, "usage")
            if usage is not None and response_usage is not None:
                details = _item_value(response_usage, "input_tokens_details")
                cached = _item_value(details, "cached_tokens", 0) or 0
                usage.add(
                    _item_value(response_usage, "input_tokens", 0) or 0,
                    _item_value(response_usage, "output_tokens", 0) or 0,
                    cached,
                )

            output = _item_value(completed, "output", []) or []
            calls = [item for item in output if _item_value(item, "type") == "function_call"]
            if not calls or tool_runner is None:
                return

            # Reasoning、消息与 function_call 都是后续请求所需的 typed Items。
            conversation.extend(_dump_item(item) for item in output)
            image_inputs: list[dict] = []
            for call in calls:
                call_id = _item_value(call, "call_id", "")
                try:
                    arguments = json.loads(_item_value(call, "arguments", "{}") or "{}")
                except json.JSONDecodeError:
                    arguments = {}
                result = tool_runner(_item_value(call, "name", ""), arguments)
                conversation.append(
                    {
                        "type": "function_call_output",
                        "call_id": call_id,
                        "output": result.text or "(no output)",
                    }
                )
                image_input = _image_input(call_id, result)
                if image_input is not None:
                    image_inputs.append(image_input)
            conversation.extend(image_inputs)

        yield "\n\n（工具调用轮次过多，已停止。）"
