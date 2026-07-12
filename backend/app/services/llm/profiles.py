"""模型配置档案（ModelProfile）。

每个档案描述一个可用模型：走哪种风格、连哪个地址、模型名是什么。
密钥统一从 Settings/.env 注入，不存入模型档案。
"""

import json
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field, TypeAdapter

from app.core.config import settings


class ModelProfile(BaseModel):
    name: str = Field(min_length=1)             # 唯一标识，前端下拉展示用
    style: Literal["openai", "anthropic"]       # 决定用哪个 Provider
    credential: Literal["openai", "deepseek", "anthropic", "none"] | None = None
    model_id: str = Field(min_length=1)         # 传给上游的真实模型名
    api_key: str = ""
    base_url: str | None = None                 # OpenAI 兼容端点在这里覆盖
    max_tokens: int = Field(default=2048, gt=0)
    # 上下文窗口上限。可按具体部署模型在 models.json 覆盖；默认 128K。
    context_window: int = Field(default=128_000, gt=0)


class PublicProfile(BaseModel):
    """暴露给前端的档案信息，不含 api_key。"""

    name: str
    style: Literal["openai", "anthropic"]
    model_id: str
    context_window: int


def profiles_path() -> Path:
    """返回本机模型档案路径。"""
    return settings.data_dir / "models.json"


def load_profiles() -> dict[str, ModelProfile]:
    path = profiles_path()
    if not path.exists():
        return {}
    raw = json.loads(path.read_text(encoding="utf-8"))
    profiles = TypeAdapter(list[ModelProfile]).validate_python(raw)
    profiles = [
        profile.model_copy(
            update={
                "api_key": _api_key_for(profile)
            }
        )
        for profile in profiles
    ]
    result = {profile.name: profile for profile in profiles}
    if len(result) != len(profiles):
        raise ValueError(f"模型档案名称不能重复：{path}")
    return result


def get_profile(name: str) -> ModelProfile | None:
    return load_profiles().get(name)


def _api_key_for(profile: ModelProfile) -> str:
    credential = profile.credential
    if credential is None:
        base_url = (profile.base_url or "").lower()
        if profile.style == "anthropic":
            credential = "anthropic"
        elif "deepseek.com" in base_url:
            credential = "deepseek"
        elif "localhost" in base_url or "127.0.0.1" in base_url:
            credential = "none"
        else:
            credential = "openai"
    return {
        "openai": settings.openai_api_key,
        "deepseek": settings.deepseek_api_key,
        "anthropic": settings.anthropic_api_key,
        "none": "",
    }[credential]
