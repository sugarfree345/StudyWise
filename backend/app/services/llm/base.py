"""LLM 适配器的统一接口。

上层（chat 接口、右侧学习面板）只依赖这个 Protocol，永远不知道底下是
OpenAI 风格还是 Anthropic 风格。两种风格在协议层面的差异（system 的位置、
流式事件格式、工具调用/多模态 tool_result）都由各自的 Provider 实现抹平。
"""

from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass
from typing import Protocol, TypedDict

from app.services.llm.tools import ToolResult, ToolSpec

# 工具执行回调：provider 拿到模型要调的工具名和参数，交给它执行并拿回结果。
ToolRunner = Callable[[str, dict], ToolResult]

# 单轮对话里最多允许的工具调用往返次数，防止模型陷入无限工具循环。
MAX_TOOL_ROUNDS = 8


@dataclass
class Usage:
    """一次用户提问的 token 用量累加器。

    因为一次提问可能触发多轮工具调用（多次 API 请求），Provider 会把每轮的
    input/output tokens 累加到同一个实例上，得到这次提问的真实总量。

    ``cached_tokens`` 是 ``input_tokens`` 里命中提示缓存的部分（子集，非额外量），
    计费更便宜；先采集存下，供以后换算价格时按缓存折扣计算。
    """

    input_tokens: int = 0
    output_tokens: int = 0
    cached_tokens: int = 0

    def add(
        self, input_tokens: int, output_tokens: int, cached_tokens: int = 0
    ) -> None:
        self.input_tokens += input_tokens
        self.output_tokens += output_tokens
        self.cached_tokens += cached_tokens

    @property
    def total_tokens(self) -> int:
        return self.input_tokens + self.output_tokens


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
        usage: Usage | None = None,
        prompt_cache_key: str | None = None,
    ) -> AsyncIterator[str]:
        """流式返回纯文本增量。

        传入 ``tools`` 与 ``tool_runner`` 时，Provider 在内部跑「模型→工具→模型」的
        多轮循环：把工具结果（含图片）按各自 API 的格式回给模型，最终只向上层
        吐出面向用户的文本增量，因此 SSE 层无需改动。

        传入 ``usage`` 时，Provider 把每轮的 token 用量累加进去；调用方在流式
        结束后读取它即可拿到本次提问的总用量。

        ``prompt_cache_key`` 是同一稳定提示前缀的路由键。支持该参数的
        Provider 会用它提高提示缓存命中率；不支持的 Provider 忽略它。
        """
        ...
