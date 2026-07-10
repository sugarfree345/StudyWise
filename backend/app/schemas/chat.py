from typing import Literal

from pydantic import BaseModel


class ChatMessageIn(BaseModel):
    role: Literal["user", "assistant"]
    content: str


class ChatRequest(BaseModel):
    profile: str                       # 用哪个模型档案（ModelProfile.name）
    messages: list[ChatMessageIn]      # 对话历史（后端无状态，前端每次带全量）
