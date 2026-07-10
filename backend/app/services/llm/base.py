"""LLM 适配器的统一接口。

上层（chat 接口、右侧学习面板）只依赖这个 Protocol，永远不知道底下是
OpenAI 风格还是 Anthropic 风格。两种风格在协议层面的差异（system 的位置、
流式事件格式、以后的多模态/工具调用）都由各自的 Provider 实现抹平。
"""

from collections.abc import AsyncIterator
from typing import Protocol, TypedDict


class ChatMessage(TypedDict):
    role: str  # "user" | "assistant"
    content: str


class LLMProvider(Protocol):
    async def stream_chat(
        self,
        *,
        system: str,
        messages: list[ChatMessage],
    ) -> AsyncIterator[str]:
        """流式返回纯文本增量。system 单独传入，由各 Provider 决定如何塞进请求。"""
        ...
