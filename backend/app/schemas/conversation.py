from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


class ConversationMessageIn(BaseModel):
    role: Literal["user", "assistant"]
    content: str
    request_content: str | None = None
    input_tokens: int | None = None
    output_tokens: int | None = None
    cached_tokens: int | None = None
    total_tokens: int | None = None
    activity_trace: list[dict] | None = None
    duration_ms: int | None = None


class ConversationCreate(BaseModel):
    profile: str
    title: str = Field(default="新对话", max_length=100)


class ConversationUpdate(BaseModel):
    profile: str
    title: str | None = Field(default=None, max_length=100)
    messages: list[ConversationMessageIn]


class ConversationSummary(BaseModel):
    id: int
    document_id: int
    title: str
    profile: str
    message_count: int
    created_at: datetime
    updated_at: datetime


class ConversationDetail(ConversationSummary):
    messages: list[ConversationMessageIn]
