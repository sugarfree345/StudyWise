"""Anthropic 风格适配器（Claude）。

与 OpenAI 风格的关键差异，在这里抹平：
- system 是顶层参数，不放进 messages 数组
- 流式是 messages.stream 的结构化事件，用 text_stream 取纯文本增量
"""

from collections.abc import AsyncIterator

from anthropic import AsyncAnthropic

from app.services.llm.base import ChatMessage
from app.services.llm.profiles import ModelProfile


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
    ) -> AsyncIterator[str]:
        async with self._client.messages.stream(
            model=self._profile.model_id,
            max_tokens=self._profile.max_tokens,
            system=system,  # 顶层参数，不进 messages
            messages=messages,  # type: ignore[arg-type]
        ) as stream:
            async for text in stream.text_stream:
                yield text
