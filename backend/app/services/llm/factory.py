from app.services.llm.anthropic_provider import AnthropicProvider
from app.services.llm.base import LLMProvider
from app.services.llm.openai_provider import OpenAIProvider
from app.services.llm.profiles import ModelProfile


def get_provider(profile: ModelProfile) -> LLMProvider:
    """按档案的 style 挑选对应的 Provider 实现。"""
    if profile.style == "openai":
        return OpenAIProvider(profile)
    if profile.style == "anthropic":
        return AnthropicProvider(profile)
    raise ValueError(f"不支持的模型 API 风格：{profile.style}")
