"""模型配置档案（ModelProfile）。

每个档案描述一个可用模型：走哪种风格、连哪个地址、用哪个 key、模型名是什么。
本地单用户，档案存放在 data/models.json（已 gitignore），示例见
backend/models.example.json。
"""

import json
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field, TypeAdapter

from app.core.config import settings


class ModelProfile(BaseModel):
    name: str = Field(min_length=1)             # 唯一标识，前端下拉展示用
    style: Literal["openai", "anthropic"]       # 决定用哪个 Provider
    model_id: str = Field(min_length=1)         # 传给上游的真实模型名
    api_key: str = ""
    base_url: str | None = None                 # OpenAI 兼容端点在这里覆盖
    max_tokens: int = Field(default=2048, gt=0)


class PublicProfile(BaseModel):
    """暴露给前端的档案信息，不含 api_key。"""

    name: str
    style: Literal["openai", "anthropic"]
    model_id: str


def profiles_path() -> Path:
    """返回本机模型档案路径。该文件含密钥，不应提交到版本库。"""
    return settings.data_dir / "models.json"


def load_profiles() -> dict[str, ModelProfile]:
    path = profiles_path()
    if not path.exists():
        return {}
    raw = json.loads(path.read_text(encoding="utf-8"))
    profiles = TypeAdapter(list[ModelProfile]).validate_python(raw)
    result = {profile.name: profile for profile in profiles}
    if len(result) != len(profiles):
        raise ValueError(f"模型档案名称不能重复：{path}")
    return result


def get_profile(name: str) -> ModelProfile | None:
    return load_profiles().get(name)
