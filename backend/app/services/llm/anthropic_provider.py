"""Anthropic 风格适配器（Claude）。

与 OpenAI 风格的关键差异，在这里抹平：
- system 是顶层参数，不放进 messages 数组
- 流式是 messages.stream 的结构化事件，用 text_stream 取纯文本增量
- 工具调用：stop_reason=="tool_use" 时执行工具，把 tool_result（含图片）
  作为一条 user 消息回给模型，再进入下一轮，直到模型给出最终文本
"""

from collections.abc import AsyncIterator

from anthropic import AsyncAnthropic

from app.services.llm.base import MAX_TOOL_ROUNDS, ChatMessage, ToolRunner
from app.services.llm.profiles import ModelProfile
from app.services.llm.tools import ToolResult, ToolSpec, anthropic_tools


def _tool_result_block(tool_use_id: str, result: ToolResult) -> dict:
    content: list[dict] = []
    if result.text:
        content.append({"type": "text", "text": result.text})
    if result.image is not None:
        content.append(
            {
                "type": "image",
                "source": {
                    "type": "base64",
                    "media_type": result.image.mime_type,
                    "data": result.image.as_base64(),
                },
            }
        )
    if not content:
        content.append({"type": "text", "text": "(no output)"})
    return {
        "type": "tool_result",
        "tool_use_id": tool_use_id,
        "content": content,
        "is_error": result.is_error,
    }


class AnthropicProvider:
    def __init__(self, profile: ModelProfile):
        self._profile = profile
        kwargs = {"api_key": profile.api_key}
        if profile.base_url:
            kwargs["base_url"] = profile.base_url
        self._client = AsyncAnthropic(**kwargs)

    async def stream_chat(
        self,
        *,
        system: str,
        messages: list[ChatMessage],
        tools: list[ToolSpec] | None = None,
        tool_runner: ToolRunner | None = None,
    ) -> AsyncIterator[str]:
        conversation: list[dict] = [dict(m) for m in messages]
        tool_defs = anthropic_tools(tools) if tools else None

        for _ in range(MAX_TOOL_ROUNDS):
            kwargs: dict = {
                "model": self._profile.model_id,
                "max_tokens": self._profile.max_tokens,
                "system": system,  # 顶层参数，不进 messages
                "messages": conversation,
            }
            if tool_defs:
                kwargs["tools"] = tool_defs

            async with self._client.messages.stream(**kwargs) as stream:
                async for text in stream.text_stream:
                    yield text
                final = await stream.get_final_message()

            tool_uses = [block for block in final.content if block.type == "tool_use"]
            if not tool_uses or tool_runner is None:
                return

            # 记录助手这一轮（含 tool_use 块），维持后续上下文
            conversation.append(
                {"role": "assistant", "content": [b.model_dump() for b in final.content]}
            )
            results = [
                _tool_result_block(block.id, tool_runner(block.name, dict(block.input)))
                for block in tool_uses
            ]
            conversation.append({"role": "user", "content": results})

        yield "\n\n（工具调用轮次过多，已停止。）"
