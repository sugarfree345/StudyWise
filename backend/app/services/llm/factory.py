from urllib.parse import urlparse

from app.services.llm.anthropic_provider import AnthropicProvider
from app.services.llm.base import LLMProvider
from app.services.llm.openai_provider import OpenAIProvider
from app.services.llm.openai_responses_provider import OpenAIResponsesProvider
from app.services.llm.profiles import ModelProfile


def _is_official_openai_endpoint(base_url: str | None) -> bool:
    endpoint = base_url or "https://api.openai.com/v1"
    return urlparse(endpoint).hostname == "api.openai.com"


def get_provider(profile: ModelProfile) -> LLMProvider:
    """按档案的 style 挑选对应的 Provider 实现。"""
    if profile.style == "openai":
        if _is_official_openai_endpoint(profile.base_url):
            return OpenAIResponsesProvider(profile)
        return OpenAIProvider(profile)
    if profile.style == "anthropic":
        return AnthropicProvider(profile)
    raise ValueError(f"不支持的模型 API 风格：{profile.style}")
