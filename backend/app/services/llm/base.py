"""LLM 适配器的统一接口。

上层（chat 接口、右侧学习面板）只依赖这个 Protocol，永远不知道底下是
OpenAI 风格还是 Anthropic 风格。两种风格在协议层面的差异（system 的位置、
流式事件格式、工具调用/多模态 tool_result）都由各自的 Provider 实现抹平。
"""

from collections.abc import AsyncIterator, Callable
from typing import Protocol, TypedDict

from app.services.llm.tools import ToolResult, ToolSpec

# 工具执行回调：provider 拿到模型要调的工具名和参数，交给它执行并拿回结果。
ToolRunner = Callable[[str, dict], ToolResult]

# 单轮对话里最多允许的工具调用往返次数，防止模型陷入无限工具循环。
MAX_TOOL_ROUNDS = 8


class ChatMessage(TypedDict):
    role: str  # "user" | "assistant"
    content: str


class LLMProvider(Protocol):
    async def stream_chat(
        self,
        *,
        system: str,
        messages: list[ChatMessage],
        tools: list[ToolSpec] | None = None,
        tool_runner: ToolRunner | None = None,
    ) -> AsyncIterator[str]:
        """流式返回纯文本增量。

        传入 ``tools`` 与 ``tool_runner`` 时，Provider 在内部跑「模型→工具→模型」的
        多轮循环：把工具结果（含图片）按各自 API 的格式回给模型，最终只向上层
        吐出面向用户的文本增量，因此 SSE 层无需改动。
        """
        ...
