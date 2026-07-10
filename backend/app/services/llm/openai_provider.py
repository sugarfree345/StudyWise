"""OpenAI 风格适配器。

覆盖面最广：OpenAI 本体，以及 DeepSeek、通义千问（DashScope 兼容模式）、
Kimi/Moonshot、智谱 GLM，还有本地 Ollama / vLLM / LM Studio —— 它们都暴露
OpenAI 兼容端点，只需换 base_url。
"""

from collections.abc import AsyncIterator

from openai import AsyncOpenAI

from app.services.llm.base import ChatMessage
from app.services.llm.profiles import ModelProfile


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
    ) -> AsyncIterator[str]:
        # OpenAI 风格：system 是消息数组里的第一条
        payload = [{"role": "system", "content": system}, *messages]
        stream = await self._client.chat.completions.create(
            model=self._profile.model_id,
            messages=payload,  # type: ignore[arg-type]
            max_tokens=self._profile.max_tokens,
            stream=True,
        )
        async for chunk in stream:
            if not chunk.choices:
                continue
            delta = chunk.choices[0].delta.content
            if delta:
                yield delta
